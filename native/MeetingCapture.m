#import "MeetingCapture.h"
#import "MeetingSpeakers.h"
#import <AVFoundation/AVFoundation.h>
#import <ScreenCaptureKit/ScreenCaptureKit.h>
#import <CoreMedia/CoreMedia.h>

@interface PacoMeetingCapture () <SCStreamOutput,SCStreamDelegate>
@property AVAudioEngine *engine;
@property SCStream *stream;
@property dispatch_queue_t queue;
@property NSMutableDictionary *buffers;
@property NSMutableDictionary *sequences;
@property NSMutableDictionary *offsets;
@property NSDate *started;
@property double clockOrigin;
@property NSMutableArray *speakerSamples;
@property dispatch_source_t speakerTimer;
@property NSLock *lock;
@property NSInteger pending;
@property BOOL stopping;
@property BOOL tapInstalled;
@end
@implementation PacoMeetingCapture
- (instancetype)init {
    if((self=[super init])){self.queue=dispatch_queue_create("paco.meeting.audio",DISPATCH_QUEUE_SERIAL);self.buffers=[NSMutableDictionary new];self.sequences=[NSMutableDictionary new];self.offsets=[NSMutableDictionary new];self.speakerSamples=[NSMutableArray new];self.lock=[NSLock new];}
    return self;
}
- (void)reportGap:(NSString *)reason {
    self.send(@{@"action":@"meeting_control",@"id":self.ident,@"command":@"gap",@"seconds":@((NSProcessInfo.processInfo.systemUptime-self.clockOrigin)),@"reason":reason},^(BOOL ok){});
}
- (void)consume:(AVAudioPCMBuffer *)input channel:(NSString *)channel {
    [self.lock lock];
    if(self.paused||self.stopping){[self.lock unlock];return;}
    AVAudioFormat *format=[[AVAudioFormat alloc] initWithCommonFormat:AVAudioPCMFormatFloat32 sampleRate:16000 channels:1 interleaved:NO];
    AVAudioConverter *converter=[[AVAudioConverter alloc] initFromFormat:input.format toFormat:format];
    if(!converter){[self.lock unlock];[self reportGap:@"Unsupported audio device format."];return;}
    AVAudioPCMBuffer *output=[[AVAudioPCMBuffer alloc] initWithPCMFormat:format frameCapacity:(AVAudioFrameCount)(input.frameLength*16000/input.format.sampleRate+64)];
    __block BOOL used=NO;NSError *error=nil;
    [converter convertToBuffer:output error:&error withInputFromBlock:^AVAudioBuffer *(AVAudioPacketCount count,AVAudioConverterInputStatus *status){
        if(used){*status=AVAudioConverterInputStatus_NoDataNow;return nil;}used=YES;*status=AVAudioConverterInputStatus_HaveData;return input;
    }];
    if(error){[self.lock unlock];[self reportGap:@"Audio conversion failed; an interval is missing."];return;}
    NSMutableData *buffer=self.buffers[channel];
    if(!buffer){buffer=[NSMutableData new];self.buffers[channel]=buffer;}
    if(buffer.length==0)self.offsets[channel]=@(MAX(0,(NSProcessInfo.processInfo.systemUptime-self.clockOrigin)-input.frameLength/input.format.sampleRate));
    [buffer appendBytes:output.floatChannelData[0] length:output.frameLength*sizeof(float)];
    if(buffer.length>=16000*4*8)[self flush:channel];
    [self.lock unlock];
}
// Called under lock. Two in-flight chunks maximum; no on-disk NSURLSession cache.
- (void)flush:(NSString *)channel {
    NSMutableData *buffer=self.buffers[channel];if(!buffer.length)return;
    NSInteger sequence=[self.sequences[channel] integerValue];self.sequences[channel]=@(sequence+1);
    if(self.pending>=2||buffer.length>16000*4*10){[buffer setLength:0];[self reportGap:@"Audio delivery fell behind; an interval was discarded."];return;}
    NSDictionary *body=@{@"action":@"meeting_audio",@"id":self.ident,@"channel":channel,@"sequence":@(sequence),@"seconds":self.offsets[channel],@"capture_origin":@(self.started.timeIntervalSince1970),@"speakers":[self.speakerSamples copy],@"pcm":[buffer base64EncodedStringWithOptions:0]};
    [buffer setLength:0];self.pending++;
    self.send(body,^(BOOL ok){[self.lock lock];self.pending--;[self.lock unlock];if(!ok)[self reportGap:@"An audio interval could not be delivered to local transcription."];});
}
- (void)startWithSystemAudio:(BOOL)system completion:(void (^)(NSString *))completion {
    self.started=[NSDate date];self.clockOrigin=NSProcessInfo.processInfo.systemUptime;
    if(self.zoomSpeakers&&system){
        self.speakerTimer=dispatch_source_create(DISPATCH_SOURCE_TYPE_TIMER,0,0,dispatch_queue_create("paco.meeting.speakers",DISPATCH_QUEUE_SERIAL));
        dispatch_source_set_timer(self.speakerTimer,DISPATCH_TIME_NOW,NSEC_PER_SEC/2,NSEC_PER_SEC/10);
        __weak PacoMeetingCapture *weakSelf=self;
        dispatch_source_set_event_handler(self.speakerTimer,^{
            PacoMeetingCapture *capture=weakSelf;if(!capture)return;
            [capture.lock lock];BOOL skip=capture.paused||capture.stopping;[capture.lock unlock];if(skip)return;
            double at=NSProcessInfo.processInfo.systemUptime-capture.clockOrigin;
            NSMutableDictionary *sample=[PacoZoomSpeakerSnapshot() mutableCopy];sample[@"seconds"]=@(at);
            [capture.lock lock];[capture.speakerSamples addObject:sample];while(capture.speakerSamples.count>24)[capture.speakerSamples removeObjectAtIndex:0];[capture.lock unlock];
        });dispatch_resume(self.speakerTimer);
    }
    [AVCaptureDevice requestAccessForMediaType:AVMediaTypeAudio completionHandler:^(BOOL granted){dispatch_async(dispatch_get_main_queue(),^{
        if(self.stopping){completion(@"Meeting capture was cancelled.");return;}
        if(!granted){completion(@"Enable Paco’s microphone permission in System Settings, then try again.");return;}
        self.engine=[AVAudioEngine new];[NSNotificationCenter.defaultCenter addObserver:self selector:@selector(audioDeviceChanged:) name:AVAudioEngineConfigurationChangeNotification object:self.engine];AVAudioInputNode *input=self.engine.inputNode;
        AVAudioFormat *format=[input outputFormatForBus:0];
        if(!format.channelCount||!format.sampleRate){completion(@"No microphone is available.");return;}
        [input installTapOnBus:0 bufferSize:4096 format:format block:^(AVAudioPCMBuffer *buffer,AVAudioTime *time){[self consume:buffer channel:@"microphone"];}];self.tapInstalled=YES;
        NSError *error=nil;if(![self.engine startAndReturnError:&error]){completion(@"Could not start the microphone. Check your input device.");return;}
        if(!system){completion(nil);return;}
        if(@available(macOS 13.0,*)){
            [SCShareableContent getShareableContentExcludingDesktopWindows:YES onScreenWindowsOnly:YES completionHandler:^(SCShareableContent *content,NSError *error){
                if(error||content.displays.count==0){completion(@"Enable Paco’s Screen & System Audio Recording permission, then restart capture. No screen images are stored.");return;}
                NSMutableArray *excluded=[NSMutableArray new];for(SCRunningApplication *app in content.applications)if(app.processID==NSProcessInfo.processInfo.processIdentifier)[excluded addObject:app];
                SCContentFilter *filter;
                if(self.zoomAudio){
                    NSMutableArray *zoom=[NSMutableArray new];for(SCRunningApplication *app in content.applications)if([app.bundleIdentifier isEqual:@"us.zoom.xos"])[zoom addObject:app];
                    if(!zoom.count){completion(@"Open your Zoom call first, or choose All system audio when starting notes.");return;}
                    filter=[[SCContentFilter alloc] initWithDisplay:content.displays.firstObject includingApplications:zoom exceptingWindows:@[]];
                }else filter=[[SCContentFilter alloc] initWithDisplay:content.displays.firstObject excludingApplications:excluded exceptingWindows:@[]];
                SCStreamConfiguration *config=[SCStreamConfiguration new];config.capturesAudio=YES;config.excludesCurrentProcessAudio=YES;config.sampleRate=16000;config.channelCount=1;config.width=2;config.height=2;config.minimumFrameInterval=CMTimeMake(1,1);config.showsCursor=NO;
                self.stream=[[SCStream alloc] initWithFilter:filter configuration:config delegate:self];NSError *addError=nil;
                // Only audio output is registered. No image callback, encoder or file writer.
                if(![self.stream addStreamOutput:self type:SCStreamOutputTypeAudio sampleHandlerQueue:self.queue error:&addError]){completion(@"Could not connect system audio capture.");return;}
                [self.stream startCaptureWithCompletionHandler:^(NSError *error){completion(error?@"Could not start system audio capture. Check the macOS recording permission.":nil);}];
            }];
        }else completion(@"System audio requires macOS 13 or later. Use microphone-only mode.");
    });}];
}
- (void)stream:(SCStream *)stream didOutputSampleBuffer:(CMSampleBufferRef)sample ofType:(SCStreamOutputType)type {
    if(type!=SCStreamOutputTypeAudio||!CMSampleBufferDataIsReady(sample))return;
    const AudioStreamBasicDescription *asbd=CMAudioFormatDescriptionGetStreamBasicDescription(CMSampleBufferGetFormatDescription(sample));if(!asbd)return;
    AVAudioFormat *format=[[AVAudioFormat alloc] initWithStreamDescription:asbd];
    AVAudioPCMBuffer *buffer=[[AVAudioPCMBuffer alloc] initWithPCMFormat:format frameCapacity:(AVAudioFrameCount)CMSampleBufferGetNumSamples(sample)];buffer.frameLength=buffer.frameCapacity;
    OSStatus status=CMSampleBufferCopyPCMDataIntoAudioBufferList(sample,0,(int32_t)buffer.frameLength,buffer.mutableAudioBufferList);
    if(status==noErr)[self consume:buffer channel:@"system"];else [self reportGap:@"System audio could not be decoded."];
}
- (void)stream:(SCStream *)stream didStopWithError:(NSError *)error {if(!self.stopping)self.failed(@"System audio capture stopped. The meeting is incomplete.");}
- (void)audioDeviceChanged:(NSNotification *)note {if(!self.stopping)self.failed(@"The microphone configuration changed. Capture ended so missing audio is not mistaken for a complete meeting.");}
- (void)pauseCapture {[self.lock lock];for(NSString *channel in self.buffers.allKeys)[self flush:channel];self.paused=YES;[self.lock unlock];}
- (void)resumeCapture {[self.lock lock];self.paused=NO;[self.lock unlock];}
- (void)stop:(void (^)(void))completion {
    [self.lock lock];self.stopping=YES;for(NSString *channel in self.buffers.allKeys)[self flush:channel];[self.lock unlock];
    if(self.speakerTimer){dispatch_source_cancel(self.speakerTimer);self.speakerTimer=nil;}
    [NSNotificationCenter.defaultCenter removeObserver:self];
    if(self.tapInstalled){[self.engine.inputNode removeTapOnBus:0];self.tapInstalled=NO;}[self.engine stop];
    if(self.stream)[self.stream stopCaptureWithCompletionHandler:^(NSError *error){[self.stream removeStreamOutput:self type:SCStreamOutputTypeAudio error:nil];self.stream=nil;}];
    dispatch_async(dispatch_get_global_queue(QOS_CLASS_UTILITY,0),^{
        NSDate *deadline=[NSDate dateWithTimeIntervalSinceNow:12];
        while(deadline.timeIntervalSinceNow>0){[self.lock lock];BOOL pending=self.pending>0;[self.lock unlock];if(!pending)break;[NSThread sleepForTimeInterval:.05];}
        completion();
    });
}
@end
