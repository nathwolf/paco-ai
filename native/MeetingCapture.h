#import <Cocoa/Cocoa.h>
@interface PacoMeetingCapture : NSObject
@property (copy) void (^send)(NSDictionary *, void (^)(BOOL));
@property (copy) void (^failed)(NSString *);
@property (copy) NSString *ident;
@property BOOL paused;
@property BOOL zoomSpeakers;
@property BOOL zoomAudio;
- (void)startWithSystemAudio:(BOOL)system completion:(void (^)(NSString *))completion;
- (void)reportGap:(NSString *)reason;
- (void)pauseCapture;
- (void)resumeCapture;
- (void)stop:(void (^)(void))completion;
@end
