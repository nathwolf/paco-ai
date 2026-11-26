#import <Cocoa/Cocoa.h>
#import <WebKit/WebKit.h>
#import <Carbon/Carbon.h>
#import "MeetingCapture.h"
#import "MeetingSpeakers.h"
int appleSources(NSArray *args);
int captureContext(NSArray *args);

@interface PacoPanel : NSPanel
@end
@implementation PacoPanel
- (BOOL)canBecomeKeyWindow { return YES; }
@end

@interface PacoApp : NSObject <NSApplicationDelegate,WKNavigationDelegate,WKScriptMessageHandler>
@property PacoMeetingCapture *meetingCapture;
@property NSMenuItem *meetingStart;
@property NSMenuItem *meetingPause;
@property NSMenuItem *meetingStop;
@property NSURLSession *audioSession;
@property NSWindow *window;
@property WKWebView *web;
@property NSStatusItem *statusItem;
@property NSMenu *menu;
@property NSPanel *banner;
@property NSURL *url;
@property NSString *token;
@property NSString *base;
@property NSString *assets;
@property NSDictionary *expressions;
@property NSNumber *task;
@property NSMutableSet *seen;
@property BOOL polling;
@property BOOL checkedSetup;
@property NSUInteger ticks;
@property NSTimer *timer;
@property EventHotKeyRef hotKey;
@property NSDictionary *currentAlert;
@property NSSound *screech;
@property NSMutableDictionary *modeItems;
@property NSMenuItem *focusDay;
@property BOOL resting;
@property BOOL quietFocus;
@property BOOL composing;
@property BOOL replying;
@property NSTextField *replyField;
@property NSTextView *replyStatus;
@property NSButton *sendButton;
@property NSButton *applyButton;
@property NSButton *cancelButton;
@property NSNumber *pendingReply;
@property NSString *replyRequest;
@property NSString *replyText;
@end
static NSColor *color(unsigned rgb) { return [NSColor colorWithSRGBRed:((rgb>>16)&255)/255.0 green:((rgb>>8)&255)/255.0 blue:(rgb&255)/255.0 alpha:1]; }
static NSFont *rounded(CGFloat size,NSFontWeight weight) {
    NSFont *font=[NSFont systemFontOfSize:size weight:weight];
    NSFontDescriptor *descriptor=[font.fontDescriptor fontDescriptorWithDesign:NSFontDescriptorSystemDesignRounded];
    NSFont *result=descriptor?[NSFont fontWithDescriptor:descriptor size:size]:nil;
    return result?:font;
}
// Banner tones. Fills carry white text at 4.5:1 or better; toneText is for coloured text on white.
static unsigned paletteValue(NSDictionary *table,NSString *name,unsigned fallback) { NSNumber *value=table[name?:@""];return value?value.unsignedIntValue:fallback; }
static unsigned toneFill(NSString *name) { return paletteValue(@{@"red":@(0xDE3324),@"orange":@(0xB35F00),@"green":@(0x2D8511),@"blue":@(0x0E7CC0),@"gray":@(0x5E6B62)},name,0x2D8511); }
static unsigned toneEdge(NSString *name) { return paletteValue(@{@"red":@(0xA82217),@"orange":@(0x7F4300),@"green":@(0x1F5F0B),@"blue":@(0x0A5C8F),@"gray":@(0x46524A)},name,0x1F5F0B); }
static unsigned toneText(NSString *name) { return paletteValue(@{@"red":@(0xC3301F),@"orange":@(0xA85800),@"green":@(0x2B7F10),@"blue":@(0x1278AE),@"gray":@(0x5E6B62)},name,0x5E6B62); }
OSStatus hotKeyHandler(EventHandlerCallRef next,EventRef event,void *ref) { [(__bridge PacoApp *)ref performSelector:@selector(companionMenu)];return noErr; }
@implementation PacoApp
- (NSImage *)menuIcon {
    // A round head, hooked beak and one eye: readable at 20 points, without a hat.
    // Template transparency lets macOS supply the light/dark menu-bar tint.
    NSImage *icon=[NSImage imageWithSize:NSMakeSize(20,20) flipped:NO drawingHandler:^BOOL(NSRect rect){
        [NSColor.blackColor setFill];
        NSBezierPath *parrot=[NSBezierPath bezierPath];
        [parrot moveToPoint:NSMakePoint(3.5,3)];
        [parrot curveToPoint:NSMakePoint(3,11) controlPoint1:NSMakePoint(4.5,5) controlPoint2:NSMakePoint(2.5,7)];
        [parrot curveToPoint:NSMakePoint(9,17) controlPoint1:NSMakePoint(3,14.5) controlPoint2:NSMakePoint(5.5,17)];
        [parrot curveToPoint:NSMakePoint(14,14) controlPoint1:NSMakePoint(11.5,17) controlPoint2:NSMakePoint(13,16)];
        [parrot curveToPoint:NSMakePoint(18.5,10.5) controlPoint1:NSMakePoint(16.5,14) controlPoint2:NSMakePoint(18.5,12.8)];
        [parrot curveToPoint:NSMakePoint(15.5,6.5) controlPoint1:NSMakePoint(18.5,8.5) controlPoint2:NSMakePoint(17,7)];
        [parrot curveToPoint:NSMakePoint(15,9.5) controlPoint1:NSMakePoint(16,8) controlPoint2:NSMakePoint(16,9)];
        [parrot lineToPoint:NSMakePoint(12.5,10)];
        [parrot curveToPoint:NSMakePoint(11.5,3) controlPoint1:NSMakePoint(12.5,7) controlPoint2:NSMakePoint(13,4.5)];
        [parrot closePath];[parrot fill];
        [NSGraphicsContext saveGraphicsState];
        NSGraphicsContext.currentContext.compositingOperation=NSCompositingOperationDestinationOut;
        [[NSBezierPath bezierPathWithOvalInRect:NSMakeRect(9.2,12.5,2,2)] fill];
        NSBezierPath *beak=[NSBezierPath bezierPath];beak.lineWidth=1;beak.lineCapStyle=NSLineCapStyleRound;
        [beak moveToPoint:NSMakePoint(14,13.8)];
        [beak curveToPoint:NSMakePoint(12.5,10) controlPoint1:NSMakePoint(12.9,13) controlPoint2:NSMakePoint(12.5,11.7)];
        [beak stroke];
        [NSGraphicsContext restoreGraphicsState];
        return YES;
    }];icon.template=YES;icon.accessibilityDescription=@"Paco parrot";return icon;
}

- (NSImage *)imageFor:(NSString *)mood {
    NSString *file=self.expressions[mood][@"file"]?:self.expressions[@"friendly"][@"file"];
    return [[NSImage alloc] initWithContentsOfFile:[self.assets stringByAppendingPathComponent:file]];
}
- (NSPanel *)panel:(NSRect)rect {
    NSPanel *panel=[[PacoPanel alloc] initWithContentRect:rect styleMask:NSWindowStyleMaskBorderless|NSWindowStyleMaskNonactivatingPanel backing:NSBackingStoreBuffered defer:NO];
    panel.level=NSFloatingWindowLevel; panel.collectionBehavior=NSWindowCollectionBehaviorCanJoinAllSpaces|NSWindowCollectionBehaviorFullScreenAuxiliary;
    panel.opaque=NO;panel.backgroundColor=NSColor.clearColor;panel.hidesOnDeactivate=NO;panel.hasShadow=YES;
    return panel;
}
- (void)applicationDidFinishLaunching:(NSNotification *)note {
    [NSApp setActivationPolicy:NSApplicationActivationPolicyAccessory];
    self.seen=[NSMutableSet set];NSArray *args=NSProcessInfo.processInfo.arguments;
    self.url=[NSURL URLWithString:args[1]];self.assets=args[2];
    self.expressions=[NSJSONSerialization JSONObjectWithData:[NSData dataWithContentsOfFile:[self.assets stringByAppendingPathComponent:@"expressions.json"]] options:0 error:nil];
    self.token=[NSURLComponents componentsWithURL:self.url resolvingAgainstBaseURL:NO].queryItems.firstObject.value;
    self.base=[NSString stringWithFormat:@"http://127.0.0.1:%@",self.url.port];
    self.statusItem=[NSStatusBar.systemStatusBar statusItemWithLength:28];
    self.statusItem.button.image=[self menuIcon];self.statusItem.button.toolTip=@"Paco — settings and replies";
    [self.statusItem.button setAccessibilityLabel:@"Paco"];
    self.menu=[NSMenu new];
    NSArray *titles=@[@"Open Paco…",@"Controls…",@"Talk to Paco…",@"Holiday — urgent only",@"Back to work",@"Pause reminders"];
    NSArray *selectors=@[@"show",@"showControls",@"show",@"holiday",@"work",@"pause"];
    self.modeItems=[NSMutableDictionary dictionary];
    for(NSUInteger i=0;i<titles.count;i++) {
        NSMenuItem *item=[[NSMenuItem alloc] initWithTitle:titles[i] action:NSSelectorFromString(selectors[i]) keyEquivalent:@""];item.target=self;[self.menu addItem:item];
        NSDictionary *modes=@{@"holiday":@"holiday",@"work":@"work",@"pause":@"paused"};
        if(modes[selectors[i]])self.modeItems[modes[selectors[i]]]=item;   // ticked by refreshStatus
    }
    // Focus day: one project for the rest of today; only urgent work from other projects interrupts.
    self.focusDay=[[NSMenuItem alloc] initWithTitle:@"Focus day" action:nil keyEquivalent:@""];self.focusDay.submenu=[NSMenu new];self.focusDay.hidden=YES;[self.menu addItem:self.focusDay];
    [self.menu addItem:NSMenuItem.separatorItem];
    NSMenuItem *intake=[[NSMenuItem alloc] initWithTitle:@"Add tasks from text…" action:@selector(showIntake) keyEquivalent:@""];intake.target=self;[self.menu addItem:intake];
    NSMenuItem *previews=[[NSMenuItem alloc] initWithTitle:@"Preview expression" action:nil keyEquivalent:@""];
    NSMenu *previewMenu=[NSMenu new];
    for(NSString *mood in @[@"friendly",@"impatient",@"angry",@"furious",@"rage"]) {
        NSMenuItem *item=[[NSMenuItem alloc] initWithTitle:self.expressions[mood][@"label"] action:@selector(preview:) keyEquivalent:@""];
        item.target=self;item.representedObject=mood;NSImage *icon=[self imageFor:mood];icon.size=NSMakeSize(28,28);item.image=icon;[previewMenu addItem:item];
    }
    previews.submenu=previewMenu;[self.menu addItem:previews];[self.menu addItem:NSMenuItem.separatorItem];
    NSMenuItem *quit=[[NSMenuItem alloc] initWithTitle:@"Quit Paco" action:@selector(quit) keyEquivalent:@"q"];quit.target=self;[self.menu addItem:quit];
    self.meetingStart=[[NSMenuItem alloc] initWithTitle:@"Start meeting notes…" action:@selector(startMeeting) keyEquivalent:@""];self.meetingStart.target=self;[self.menu insertItem:self.meetingStart atIndex:3];
    self.meetingPause=[[NSMenuItem alloc] initWithTitle:@"Pause meeting capture" action:@selector(pauseMeeting) keyEquivalent:@""];self.meetingPause.target=self;self.meetingPause.hidden=YES;[self.menu insertItem:self.meetingPause atIndex:4];
    self.meetingStop=[[NSMenuItem alloc] initWithTitle:@"Finish meeting" action:@selector(stopMeeting) keyEquivalent:@""];self.meetingStop.target=self;self.meetingStop.hidden=YES;[self.menu insertItem:self.meetingStop atIndex:5];
    NSMenuItem *notes=[[NSMenuItem alloc] initWithTitle:@"Meeting notes…" action:@selector(showMeetings) keyEquivalent:@""];notes.target=self;[self.menu insertItem:notes atIndex:6];
    NSURLSessionConfiguration *audioConfig=NSURLSessionConfiguration.ephemeralSessionConfiguration;audioConfig.URLCache=nil;audioConfig.requestCachePolicy=NSURLRequestReloadIgnoringLocalCacheData;self.audioSession=[NSURLSession sessionWithConfiguration:audioConfig];
    [NSWorkspace.sharedWorkspace.notificationCenter addObserver:self selector:@selector(meetingWillSleep:) name:NSWorkspaceWillSleepNotification object:nil];
    // Paco rests while the session is not in use: displays asleep (including a closed lid) or another user on the console.
    NSNotificationCenter *workspace=NSWorkspace.sharedWorkspace.notificationCenter;
    for(NSString *name in @[NSWorkspaceScreensDidSleepNotification,NSWorkspaceSessionDidResignActiveNotification,NSWorkspaceWillSleepNotification])
        [workspace addObserver:self selector:@selector(rest:) name:name object:nil];
    for(NSString *name in @[NSWorkspaceScreensDidWakeNotification,NSWorkspaceSessionDidBecomeActiveNotification,NSWorkspaceDidWakeNotification])
        [workspace addObserver:self selector:@selector(wake:) name:name object:nil];
    self.statusItem.menu=self.menu;
    EventTypeSpec event={kEventClassKeyboard,kEventHotKeyPressed};InstallEventHandler(GetApplicationEventTarget(),hotKeyHandler,1,&event,(__bridge void *)self,NULL);
    EventHotKeyID ident={'PACO',1};EventHotKeyRef key;RegisterEventHotKey(kVK_ANSI_P,controlKey|optionKey,ident,GetApplicationEventTarget(),0,&key);self.hotKey=key;
    self.timer=[NSTimer scheduledTimerWithTimeInterval:2 target:self selector:@selector(poll) userInfo:nil repeats:YES];
    [self refreshStatus];
}
- (void)companionMenu { [self.statusItem.button performClick:nil]; }
- (void)preview:(NSMenuItem *)item { [self dismiss];[self post:@{@"action":@"demo",@"mood":item.representedObject}]; }
- (BOOL)applicationShouldHandleReopen:(NSApplication *)app hasVisibleWindows:(BOOL)visible { [self show];return YES; }
- (void)show { [self open:@"/" title:@"Paco — Tasks"]; }
- (void)showControls { [self open:@"/#controls" title:@"Paco — Controls"]; }
- (void)showWorkspace { [self open:@"/advanced" title:@"Paco — Workspace"]; }
- (void)showIntake { [self open:@"/#intake" title:@"Paco — Tasks"]; }
- (void)open:(NSString *)path title:(NSString *)title {
    if(!self.window) {
        WKWebViewConfiguration *config=[WKWebViewConfiguration new];[config.userContentController addScriptMessageHandler:self name:@"paco"];
        self.web=[[WKWebView alloc] initWithFrame:NSZeroRect configuration:config];self.web.navigationDelegate=self;self.web.underPageBackgroundColor=NSColor.windowBackgroundColor;
        self.window=[[NSWindow alloc] initWithContentRect:NSMakeRect(0,0,960,740) styleMask:NSWindowStyleMaskTitled|NSWindowStyleMaskClosable|NSWindowStyleMaskMiniaturizable|NSWindowStyleMaskResizable backing:NSBackingStoreBuffered defer:NO];
        self.window.contentMinSize=NSMakeSize(640,480);self.window.releasedWhenClosed=NO;self.window.contentView=self.web;[self.window center];
    }
    self.window.title=title;
    if([path isEqual:@"/advanced"])[self widenForWorkspace];
    // One request: the token sets the session cookie, then the server redirects to the page. A second
    // loadRequest here could cancel the first before the cookie exists.
    NSMutableCharacterSet *queryChars=[NSCharacterSet.URLQueryAllowedCharacterSet mutableCopy];[queryChars removeCharactersInString:@"&=#?+"];
    NSURL *target=[NSURL URLWithString:[NSString stringWithFormat:@"%@&next=%@",self.url.absoluteString,[path stringByAddingPercentEncodingWithAllowedCharacters:queryChars]]];
    [self.web loadRequest:[NSURLRequest requestWithURL:target cachePolicy:NSURLRequestReloadIgnoringLocalCacheData timeoutInterval:30]];
    [self.window makeKeyAndOrderFront:nil];[NSApp activateIgnoringOtherApps:YES];
}
- (void)widenForWorkspace {
    if(NSWidth(self.window.frame)>=1000)return;
    NSRect screen=(self.window.screen?:NSScreen.mainScreen).visibleFrame;
    CGFloat width=MIN(1180,NSWidth(screen)-40),height=MIN(820,NSHeight(screen)-40);
    [self.window setFrame:NSMakeRect(NSMidX(screen)-width/2,NSMidY(screen)-height/2,width,height) display:YES];
}
- (void)userContentController:(WKUserContentController *)controller didReceiveScriptMessage:(WKScriptMessage *)message {
    NSURL *origin=message.frameInfo.request.URL;
    if([origin.host isEqualToString:@"127.0.0.1"]&&[origin.port isEqual:self.url.port]&&[message.body isKindOfClass:NSString.class]&&[@[@"theme:light",@"theme:dark",@"theme:system"] containsObject:message.body]) {
        NSString *theme=message.body;
        self.window.appearance=[theme isEqual:@"theme:system"]?nil:[NSAppearance appearanceNamed:[theme isEqual:@"theme:dark"]?NSAppearanceNameDarkAqua:NSAppearanceNameAqua];
        return;
    }
    if([origin.host isEqualToString:@"127.0.0.1"]&&[origin.port isEqual:self.url.port]&&[message.body isEqual:@"focus-changed"]){[self refreshStatus];return;}
    if([origin.host isEqualToString:@"127.0.0.1"]&&[origin.port isEqual:self.url.port]&&[message.body isEqual:@"meeting-start"]){[self startMeeting];return;}
    if([origin.host isEqualToString:@"127.0.0.1"]&&[origin.port isEqual:self.url.port]&&[message.body isEqual:@"meeting-stop"]){[self stopMeeting];return;}
    if([origin.host isEqualToString:@"127.0.0.1"]&&[origin.port isEqual:self.url.port]&&[message.body isEqual:@"speaker-permission"]){PacoRequestSpeakerPermission();return;}
    if([origin.host isEqualToString:@"127.0.0.1"]&&[origin.port isEqual:self.url.port]&&[message.body isEqual:@"setup-complete"]) {
        [self.window orderOut:nil];
    }
}
- (void)webView:(WKWebView *)web decidePolicyForNavigationAction:(WKNavigationAction *)action decisionHandler:(void (^)(WKNavigationActionPolicy))decision {
    NSURL *target=action.request.URL;
    if([target.host isEqualToString:@"127.0.0.1"]&&[target.port isEqual:self.url.port]) {
        // In-page links between Settings, Meeting notes and the workspace keep the title and size sensible.
        if([target.path isEqual:@"/advanced"]){self.window.title=@"Paco — Workspace";[self widenForWorkspace];}
        else if([target.path isEqual:@"/meetings"])self.window.title=@"Paco — Meeting notes";
        else if([target.path isEqual:@"/"]&&!target.query)self.window.title=@"Paco";
        decision(WKNavigationActionPolicyAllow);
    }
    else {if([@[@"http",@"https"] containsObject:target.scheme])[NSWorkspace.sharedWorkspace openURL:target];decision(WKNavigationActionPolicyCancel);}
}
- (void)quit { if(self.meetingCapture){[self stopMeeting];dispatch_after(dispatch_time(DISPATCH_TIME_NOW,13*NSEC_PER_SEC),dispatch_get_main_queue(),^{[NSApp terminate:nil];});}else [NSApp terminate:nil]; }
- (void)showMeetings { [self open:@"/#meetings" title:@"Paco — Meetings"]; }
- (void)meetingRequest:(NSDictionary *)value completion:(void (^)(NSDictionary *,NSString *))completion {
    NSMutableURLRequest *request=[self request:@"/api/action"];request.timeoutInterval=60;request.HTTPMethod=@"POST";[request setValue:@"1" forHTTPHeaderField:@"X-Paco"];[request setValue:@"application/json" forHTTPHeaderField:@"Content-Type"];request.HTTPBody=[NSJSONSerialization dataWithJSONObject:value options:0 error:nil];
    [[self.audioSession dataTaskWithRequest:request completionHandler:^(NSData *data,NSURLResponse *response,NSError *error){
        NSDictionary *result=data?[NSJSONSerialization JSONObjectWithData:data options:0 error:nil]:nil;
        completion(result,error?@"The local meeting service is unavailable.":[(NSHTTPURLResponse *)response statusCode]!=200?result[@"error"]?:@"Meeting request failed.":nil);
    }] resume];
}
- (void)meetingButtons {
    BOOL active=self.meetingCapture!=nil;self.meetingStart.hidden=active;self.meetingPause.hidden=!active;self.meetingStop.hidden=!active;
    self.meetingPause.title=self.meetingCapture.paused?@"Resume meeting capture":@"Pause meeting capture";
    self.statusItem.button.title=active?(self.meetingCapture.paused?@"Ⅱ":@"●"):@"";self.statusItem.length=active?44:28;
    self.statusItem.button.toolTip=active?@"Paco — meeting capture active; click to pause or finish":@"Paco";
}
- (void)startMeeting {
    if(self.meetingCapture)return;
    [[self.audioSession dataTaskWithRequest:[self request:@"/api/meetings"] completionHandler:^(NSData *data,NSURLResponse *response,NSError *error){
        NSDictionary *state=data?[NSJSONSerialization JSONObjectWithData:data options:0 error:nil]:nil;
        dispatch_async(dispatch_get_main_queue(),^{[self startMeetingWithCalendar:state?:@{}];});
    }] resume];
}
- (void)startMeetingWithCalendar:(NSDictionary *)state {
    if(self.meetingCapture)return;
    NSAlert *alert=[NSAlert new];alert.messageText=@"Start meeting notes";alert.informativeText=@"Audio is transcribed locally and never saved. Transcripts expire after 14 days by default. Make sure participants know you’re taking notes. Choose Zoom-only audio or all system audio below. Headphones help avoid echo.";
    [alert addButtonWithTitle:@"Microphone + call audio"];[alert addButtonWithTitle:@"Microphone only"];[alert addButtonWithTitle:@"Cancel"];
    NSView *fields=[[NSView alloc] initWithFrame:NSMakeRect(0,0,360,110)];
    NSTextField *title=[[NSTextField alloc] initWithFrame:NSMakeRect(0,80,360,26)];title.placeholderString=@"Meeting title";[fields addSubview:title];
    NSPopUpButton *events=[[NSPopUpButton alloc] initWithFrame:NSMakeRect(0,40,360,30)];[events addItemWithTitle:@"No calendar event"];events.lastItem.representedObject=@"";
    for(NSDictionary *event in state[@"calendar_candidates"]){[events addItemWithTitle:event[@"title"]];events.lastItem.representedObject=event[@"id"];if([event[@"id"] isEqual:state[@"suggested_event"]]){[events selectItem:events.lastItem];title.stringValue=event[@"title"];}}
    [events setAccessibilityLabel:@"Linked calendar event"];[fields addSubview:events];
    NSPopUpButton *audioSource=[[NSPopUpButton alloc] initWithFrame:NSMakeRect(0,0,360,30)];[audioSource addItemsWithTitles:@[@"All system audio / Google Meet",@"Zoom audio only"]];
    for(NSDictionary *event in state[@"calendar_candidates"])if([event[@"id"] isEqual:events.selectedItem.representedObject]){NSString *host=[NSURL URLWithString:event[@"url"]].host.lowercaseString;if([host isEqual:@"zoom.us"]||[host hasSuffix:@".zoom.us"])[audioSource selectItemAtIndex:1];}
    [audioSource setAccessibilityLabel:@"Call audio source"];[fields addSubview:audioSource];alert.accessoryView=fields;
    [NSApp activateIgnoringOtherApps:YES];NSModalResponse choice=[alert runModal];if(choice==NSAlertThirdButtonReturn)return;
    self.meetingStart.enabled=NO;
    [self meetingRequest:@{@"action":@"meeting_start",@"title":title.stringValue.length?title.stringValue:@"Meeting",@"microphone_only":@(choice==NSAlertSecondButtonReturn),@"calendar_event":events.selectedItem.representedObject?:@"",@"speaker_source":audioSource.indexOfSelectedItem==1?@"zoom":@"none"} completion:^(NSDictionary *result,NSString *error){dispatch_async(dispatch_get_main_queue(),^{
        self.meetingStart.enabled=YES;if(error){[self showMeetings];NSAlert *a=[NSAlert new];a.messageText=error;[a runModal];return;}
        PacoMeetingCapture *capture=[PacoMeetingCapture new];capture.ident=result[@"id"];capture.zoomSpeakers=[result[@"zoom_speakers"] boolValue];capture.zoomAudio=audioSource.indexOfSelectedItem==1;self.meetingCapture=capture;
        __weak PacoApp *weakSelf=self;
        capture.send=^(NSDictionary *body,void (^done)(BOOL)){[weakSelf meetingRequest:body completion:^(NSDictionary *r,NSString *e){done(e==nil);}];};
        capture.failed=^(NSString *message){dispatch_async(dispatch_get_main_queue(),^{[weakSelf.meetingCapture reportGap:message];[weakSelf stopMeeting];[weakSelf present:@{@"message":message,@"mood":@"friendly",@"reason":@"Meeting interrupted"}];});};
        [self meetingButtons];
        [capture startWithSystemAudio:choice==NSAlertFirstButtonReturn completion:^(NSString *error){if(error)dispatch_async(dispatch_get_main_queue(),^{[capture reportGap:error];[self stopMeeting];NSAlert *a=[NSAlert new];a.messageText=error;[a runModal];});}];
    });}];
}
- (void)pauseMeeting {
    PacoMeetingCapture *capture=self.meetingCapture;if(!capture)return;
    BOOL resume=capture.paused;
    if(!resume)[capture pauseCapture];
    // Let already submitted chunks finish before changing the backend state.
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW,1*NSEC_PER_SEC),dispatch_get_main_queue(),^{
        [self meetingRequest:@{@"action":@"meeting_control",@"id":capture.ident,@"command":resume?@"resume":@"pause"} completion:^(NSDictionary *r,NSString *error){dispatch_async(dispatch_get_main_queue(),^{if(!error&&resume)[capture resumeCapture];[self meetingButtons];});}];
    });
}
- (void)stopMeeting {
    PacoMeetingCapture *capture=self.meetingCapture;if(!capture)return;
    self.meetingStop.enabled=NO;self.meetingPause.enabled=NO;
    [capture stop:^{[self meetingRequest:@{@"action":@"meeting_control",@"id":capture.ident,@"command":@"stop"} completion:^(NSDictionary *r,NSString *error){dispatch_async(dispatch_get_main_queue(),^{self.meetingCapture=nil;self.meetingStop.enabled=YES;self.meetingPause.enabled=YES;[self meetingButtons];});}];}];
}
- (void)meetingWillSleep:(NSNotification *)note { if(self.meetingCapture){[self.meetingCapture reportGap:@"The Mac went to sleep; meeting capture ended."];[self stopMeeting];} }

- (void)focusMenu:(NSDictionary *)value {
    NSArray *projects=[value[@"projects"] isKindOfClass:NSArray.class]?value[@"projects"]:@[];
    NSDictionary *focus=[value[@"focus"] isKindOfClass:NSDictionary.class]?value[@"focus"]:nil;
    self.focusDay.hidden=projects.count==0;
    self.focusDay.title=focus&&[focus[@"name"] isKindOfClass:NSString.class]?[NSString stringWithFormat:@"Focus day: %@",focus[@"name"]]:@"Focus day";
    NSMenu *menu=self.focusDay.submenu;[menu removeAllItems];
    NSMenuItem *none=[[NSMenuItem alloc] initWithTitle:@"All projects" action:@selector(chooseFocus:) keyEquivalent:@""];none.target=self;none.representedObject=NSNull.null;none.state=focus?NSControlStateValueOff:NSControlStateValueOn;[menu addItem:none];
    [menu addItem:NSMenuItem.separatorItem];
    for(NSDictionary *project in projects){
        if(![project isKindOfClass:NSDictionary.class]||![project[@"name"] isKindOfClass:NSString.class])continue;
        NSMenuItem *item=[[NSMenuItem alloc] initWithTitle:project[@"name"] action:@selector(chooseFocus:) keyEquivalent:@""];item.target=self;item.representedObject=project[@"id"];
        item.state=[focus[@"id"] isEqual:project[@"id"]]?NSControlStateValueOn:NSControlStateValueOff;[menu addItem:item];
    }
}
- (void)chooseFocus:(NSMenuItem *)item { [self post:@{@"action":@"focus_project",@"project":item.representedObject?:NSNull.null}]; }
- (void)holiday { [self post:@{@"action":@"preference",@"key":@"mode",@"value":@"holiday"}]; }
- (void)work { [self post:@{@"action":@"preference",@"key":@"mode",@"value":@"work"}]; }
- (void)pause { [self post:@{@"action":@"preference",@"key":@"mode",@"value":@"paused"}]; }
- (NSMutableURLRequest *)request:(NSString *)path { NSMutableURLRequest *r=[NSMutableURLRequest requestWithURL:[NSURL URLWithString:[self.base stringByAppendingString:path]]];[r setValue:[@"Bearer " stringByAppendingString:self.token] forHTTPHeaderField:@"Authorization"];r.timeoutInterval=8;return r; }
- (void)post:(NSDictionary *)value {
    NSMutableURLRequest *request=[self request:@"/api/action"];request.HTTPMethod=@"POST";[request setValue:@"1" forHTTPHeaderField:@"X-Paco"];[request setValue:@"application/json" forHTTPHeaderField:@"Content-Type"];request.HTTPBody=[NSJSONSerialization dataWithJSONObject:value options:0 error:nil];
    [[NSURLSession.sharedSession dataTaskWithRequest:request completionHandler:^(NSData *data,NSURLResponse *response,NSError *error){
        dispatch_async(dispatch_get_main_queue(),^{
            if(error||[(NSHTTPURLResponse *)response statusCode]!=200) {
                if([value[@"action"] isEqual:@"ack"])return;
                NSDictionary *reply=data?[NSJSONSerialization JSONObjectWithData:data options:0 error:nil]:nil;
                [self present:@{@"message":reply[@"error"]?:@"I couldn’t save that. Please try again.",@"reason":@"Couldn’t update",@"mood":@"friendly"}];
            } else [self refreshStatus];
        });
    }] resume];
}
- (void)refreshStatus {
    [[NSURLSession.sharedSession dataTaskWithRequest:[self request:@"/api/companion"] completionHandler:^(NSData *data,NSURLResponse *response,NSError *error){
        if(error||!data)return;id value=[NSJSONSerialization JSONObjectWithData:data options:0 error:nil];if(![value isKindOfClass:NSDictionary.class])return;
        dispatch_async(dispatch_get_main_queue(),^{
            self.quietFocus=[value[@"quiet_focus"] boolValue];
            if(self.quietFocus){[self.screech stop];[self.banner orderOut:nil];}
            if(self.meetingCapture){[self meetingButtons];[self meetingRequest:@{@"action":@"meeting_control",@"id":self.meetingCapture.ident,@"command":@"heartbeat"} completion:^(NSDictionary *r,NSString *error){}];}
            else self.statusItem.button.toolTip=[value[@"mode"] isEqual:@"paused"]?@"Paco — reminders paused":@"Paco — settings and replies";
            for(NSString *mode in self.modeItems)[self.modeItems[mode] setState:[value[@"mode"] isEqual:mode]?NSControlStateValueOn:NSControlStateValueOff];
            [self focusMenu:value];
            if(!self.checkedSetup){self.checkedSetup=YES;if(![value[@"setup_complete"] boolValue])[self showControls];else if([NSProcessInfo.processInfo.arguments containsObject:@"--show-settings"])[self show];}
        });
    }] resume];
}
- (void)rest:(NSNotification *)note { self.resting=YES;[self.screech stop];if(!self.replying){[self.banner orderOut:nil];self.banner=nil;self.composing=NO;} }
- (void)wake:(NSNotification *)note { self.resting=NO; }
- (void)poll {
    NSDictionary *session=CFBridgingRelease(CGSessionCopyCurrentDictionary());
    if(self.resting||[session[@"CGSSessionScreenIsLocked"] boolValue]||(session[(__bridge NSString *)kCGSessionOnConsoleKey]&&![session[(__bridge NSString *)kCGSessionOnConsoleKey] boolValue])){[self.banner orderOut:nil];return;}
    if(++self.ticks%5==0)[self refreshStatus];
    if(self.quietFocus){[self.banner orderOut:nil];return;}
    if(self.banner)[self.banner orderFrontRegardless];
    if(self.polling||self.banner)return;self.polling=YES;
    [[NSURLSession.sharedSession dataTaskWithRequest:[self request:@"/api/banner"] completionHandler:^(NSData *data,NSURLResponse *response,NSError *error){
        dispatch_async(dispatch_get_main_queue(),^{self.polling=NO;id value=data?[NSJSONSerialization JSONObjectWithData:data options:NSJSONReadingFragmentsAllowed error:nil]:nil;
            if(![value isKindOfClass:NSDictionary.class]||!value[@"id"]||[self.seen containsObject:value[@"id"]])return;
            [self present:value];[self.seen addObject:value[@"id"]];[self post:@{@"action":@"ack",@"id":value[@"id"]}];
        });
    }] resume];
}
- (void)present:(NSDictionary *)value {
    if(self.replying)return;
    self.currentAlert=value;self.composing=NO;self.pendingReply=nil;self.replyRequest=nil;self.replyText=nil;
    [self renderAlert];
    if([value[@"scream"] isKindOfClass:NSNumber.class]&&[value[@"scream"] boolValue])[self scream];
}
// Caught slacking: Paco screeches at full volume (1.7 s, follows your Mac's volume) and the banner shakes.
- (void)scream {
    NSString *path=[[self.assets stringByDeletingLastPathComponent] stringByAppendingPathComponent:@"sounds/paco-screech.wav"];
    [self.screech stop];self.screech=[[NSSound alloc] initWithContentsOfFile:path byReference:YES];self.screech.volume=1.0;[self.screech play];
    if(NSWorkspace.sharedWorkspace.accessibilityDisplayShouldReduceMotion)return;
    NSPanel *panel=self.banner;NSPoint origin=panel.frame.origin;
    NSArray *offsets=@[@14,@-12,@10,@-8,@6,@-4,@2,@0];
    for(NSUInteger i=0;i<offsets.count;i++){
        dispatch_after(dispatch_time(DISPATCH_TIME_NOW,(int64_t)((i+1)*45*NSEC_PER_MSEC)),dispatch_get_main_queue(),^{
            if(self.banner==panel)[panel setFrameOrigin:NSMakePoint(origin.x+[offsets[i] doubleValue],origin.y)];
        });
    }
}
- (NSString *)word:(NSString *)key fallback:(NSString *)fallback {
    // Wording comes from the backend in the user's language; English is the fallback for every key.
    NSDictionary *words=[self.currentAlert[@"labels"] isKindOfClass:NSDictionary.class]?self.currentAlert[@"labels"]:nil;
    id text=words[key];return [text isKindOfClass:NSString.class]?text:fallback;
}
// A pressable button: a coloured face sitting on a darker 4pt edge. The edge and face share one container so hiding works.
- (NSButton *)chunky:(NSString *)title kind:(NSString *)kind frame:(NSRect)frame action:(SEL)action in:(NSView *)content {
    BOOL filled=![kind hasPrefix:@"white"];
    unsigned face=filled?toneFill(kind):0xFFFFFF,edge=filled?toneEdge(kind):0xDDE5D6;
    unsigned text=filled?0xFFFFFF:[kind isEqual:@"white-blue"]?0x1278AE:0x4A5A50;
    NSView *box=[[NSView alloc] initWithFrame:NSMakeRect(frame.origin.x,frame.origin.y-4,frame.size.width,frame.size.height+4)];
    NSView *shade=[[NSView alloc] initWithFrame:NSMakeRect(0,0,frame.size.width,frame.size.height)];shade.wantsLayer=YES;shade.layer.backgroundColor=color(edge).CGColor;shade.layer.cornerRadius=12;[box addSubview:shade];
    NSButton *button=[NSButton buttonWithTitle:@"" target:self action:action];button.bordered=NO;button.frame=NSMakeRect(0,4,frame.size.width,frame.size.height);
    button.wantsLayer=YES;button.layer.backgroundColor=color(face).CGColor;button.layer.cornerRadius=12;
    if(!filled){button.layer.borderWidth=2;button.layer.borderColor=color(edge).CGColor;}
    NSMutableParagraphStyle *center=[NSMutableParagraphStyle new];center.alignment=NSTextAlignmentCenter;
    button.attributedTitle=[[NSAttributedString alloc] initWithString:title.uppercaseString attributes:@{NSFontAttributeName:rounded(title.length>8?11:12,NSFontWeightHeavy),NSForegroundColorAttributeName:color(text),NSParagraphStyleAttributeName:center}];
    [button setAccessibilityLabel:title];[box addSubview:button];[content addSubview:box];
    return button;
}
- (void)renderAlert {
    NSDictionary *value=self.currentAlert;
    [self.banner orderOut:nil];
    // Layout in points from the top-left; AppKit's origin is bottom-left, so y = height - top - itemHeight.
    CGFloat height=self.composing?256:150;
    NSRect screen=NSScreen.mainScreen.visibleFrame;
    NSPanel *panel=[self panel:NSMakeRect(NSMaxX(screen)-382,NSMaxY(screen)-height-18,364,height)];panel.title=@"Paco notification";panel.appearance=[NSAppearance appearanceNamed:NSAppearanceNameAqua];
    NSView *content=[[NSView alloc] initWithFrame:NSMakeRect(0,0,364,height)];content.wantsLayer=YES;panel.contentView=content;
    NSString *mood=value[@"mood"]?:@"friendly";
    NSArray *badges=[value[@"badges"] isKindOfClass:NSArray.class]&&[value[@"badges"] count]?value[@"badges"]:@[@{@"text":value[@"reason"]?:@"Paco",@"tone":@"green"}];
    NSDictionary *firstBadge=[badges.firstObject isKindOfClass:NSDictionary.class]?badges.firstObject:@{};
    NSString *tone=[firstBadge[@"tone"] isKindOfClass:NSString.class]?firstBadge[@"tone"]:@"green";
    BOOL alarm=[tone isEqual:@"red"]||[tone isEqual:@"orange"];
    content.layer.backgroundColor=NSColor.whiteColor.CGColor;content.layer.cornerRadius=20;content.layer.borderWidth=2;
    content.layer.borderColor=color(alarm?([tone isEqual:@"red"]?toneFill(@"red"):0xFFB020):0xDDE5D6).CGColor;

    NSImageView *image=[[NSImageView alloc] initWithFrame:NSMakeRect(12,height-14-84,84,84)];image.image=[self imageFor:mood];image.imageScaling=NSImageScaleProportionallyUpOrDown;[image setAccessibilityLabel:self.expressions[mood][@"label"]?:@"Paco"];[content addSubview:image];

    // Status chips: the first is filled, the rest are bold coloured text. Chips that do not fit are left out.
    NSDictionary *source=[value[@"source"] isKindOfClass:NSDictionary.class]?value[@"source"]:@{};
    NSString *sourceID=source[@"id"];
    NSArray *sourceIDs=@[@"github",@"mattermost",@"chatgpt",@"calendar",@"gmail",@"drive",@"tasks",@"slack",@"meeting",@"mail",@"paco",@"cloud"];
    if(![sourceIDs containsObject:sourceID?:@""])sourceID=@"paco";
    NSString *sourcePath=[[[self.assets stringByDeletingLastPathComponent] stringByAppendingPathComponent:@"sources"] stringByAppendingPathComponent:[sourceID stringByAppendingPathExtension:@"png"]];
    NSImage *sourceImage=[[NSImage alloc] initWithContentsOfFile:sourcePath];sourceImage.template=YES;
    NSImageView *sourceView=[[NSImageView alloc] initWithFrame:NSMakeRect(108,height-16-16,16,16)];
    sourceView.image=sourceImage;sourceView.contentTintColor=color(0x667069);sourceView.imageScaling=NSImageScaleProportionallyUpOrDown;
    sourceView.toolTip=[source[@"label"] isKindOfClass:NSString.class]?source[@"label"]:@"Paco";[sourceView setAccessibilityLabel:sourceView.toolTip];[content addSubview:sourceView];
    CGFloat x=132;
    for(NSUInteger i=0;i<badges.count&&i<2;i++){
        NSDictionary *badge=badges[i];if(![badge isKindOfClass:NSDictionary.class]||![badge[@"text"] isKindOfClass:NSString.class])continue;
        NSString *chipTone=[badge[@"tone"] isKindOfClass:NSString.class]?badge[@"tone"]:@"gray";
        NSTextField *label=[NSTextField labelWithString:badge[@"text"]];label.font=rounded(10,NSFontWeightSemibold);[label sizeToFit];
        CGFloat width=i==0?NSWidth(label.frame)+18:NSWidth(label.frame);
        if(x+width>322)break;
        if(i==0){
            NSView *chip=[[NSView alloc] initWithFrame:NSMakeRect(x,height-14-20,width,20)];chip.wantsLayer=YES;chip.layer.cornerRadius=10;
            BOOL orange=[chipTone isEqual:@"orange"];
            chip.layer.backgroundColor=color(orange?0xFFB020:toneFill(chipTone)).CGColor;label.textColor=color(orange?0x3D2400:0xFFFFFF);
            label.frame=NSMakeRect(9,(20-NSHeight(label.frame))/2,NSWidth(label.frame),NSHeight(label.frame));[chip addSubview:label];[content addSubview:chip];
        } else {
            label.textColor=color(toneText(chipTone));label.frame=NSMakeRect(x,height-14-20+(20-NSHeight(label.frame))/2,width,NSHeight(label.frame));[content addSubview:label];
        }
        x+=width+8;
    }
    NSButton *close=[NSButton buttonWithTitle:@"×" target:self action:@selector(dismiss)];close.bordered=NO;close.frame=NSMakeRect(330,height-10-22,22,22);close.font=rounded(20,NSFontWeightBold);close.contentTintColor=color(0x8A968D);[close setAccessibilityLabel:[self word:@"dismiss" fallback:@"Dismiss notification"]];[content addSubview:close];

    // Smaller task text gets four lines; keep contextual nudges on non-task notices.
    NSString *titleText=[value[@"title"] isKindOfClass:NSString.class]?value[@"title"]:(value[@"message"]?:@"");
    NSTextField *title=[NSTextField wrappingLabelWithString:titleText];title.font=rounded(12.5,NSFontWeightSemibold);title.textColor=color(0x1F3326);title.maximumNumberOfLines=value[@"task"]!=nil&&value[@"task"]!=NSNull.null?4:3;title.lineBreakMode=NSLineBreakByWordWrapping;title.cell.truncatesLastVisibleLine=YES;title.toolTip=titleText;
    CGFloat titleHeight=MIN(value[@"task"]!=nil&&value[@"task"]!=NSNull.null?62:46,ceil([title.cell cellSizeForBounds:NSMakeRect(0,0,242,1000)].height));
    title.frame=NSMakeRect(108,height-38-titleHeight,242,titleHeight);[content addSubview:title];
    NSString *nudgeText=[value[@"nudge"] isKindOfClass:NSString.class]?value[@"nudge"]:@"";
    if(nudgeText.length&&(!value[@"task"]||value[@"task"]==NSNull.null)){
        NSTextField *nudge=[NSTextField labelWithString:nudgeText];nudge.font=rounded(10.5,NSFontWeightMedium);nudge.textColor=color(toneText(tone));nudge.lineBreakMode=NSLineBreakByTruncatingTail;
        nudge.frame=NSMakeRect(108,height-(38+titleHeight+3)-16,242,16);[content addSubview:nudge];
    }

    self.task=[value[@"task"] isKindOfClass:NSNumber.class]?value[@"task"]:nil;
    BOOL opensPlan=[value[@"open"] isKindOfClass:NSString.class];
    NSDictionary *link=[value[@"link"] isKindOfClass:NSDictionary.class]&&[value[@"link"][@"url"] isKindOfClass:NSString.class]?value[@"link"]:nil;
    if(!self.composing){
        NSButton *reply=[self chunky:[self word:@"reply" fallback:@"Reply"] kind:@"white-blue" frame:NSMakeRect(12,height-106-30,84,30) action:@selector(beginReply) in:content];reply.toolTip=[self word:@"reply" fallback:@"Reply"];
        // With somewhere to go, OPEN takes the middle slot: it opens the source and starts a 25-minute focus.
        NSString *openWord=opensPlan?[self word:@"show_plan" fallback:@"Show plan"]:[self word:@"open" fallback:@"Open"];
        NSArray *labels=self.task?@[[self word:@"done" fallback:@"Done"],link?openWord:[self word:@"focus" fallback:@"Focus"],[self word:@"later" fallback:@"Later"]]:link?@[openWord,[self word:@"ok" fallback:@"Got it"]]:@[[self word:@"ok" fallback:@"Got it"]];
        NSArray *selectors=self.task?@[@"doneTask",link?@"openFromAlert":@"focusTask",@"snoozeTask"]:link?@[@"openFromAlert",@"dismiss"]:@[@"dismiss"];
        NSArray *kinds=self.task?@[@"green",link?@"blue":@"white-blue",@"white"]:link?@[@"blue",@"white"]:@[@"white"];
        CGFloat width=labels.count==3?76:118;
        for(NSUInteger i=0;i<labels.count;i++){
            NSButton *button=[self chunky:labels[i] kind:kinds[i] frame:NSMakeRect(108+i*(width+8),height-106-30,width,30) action:NSSelectorFromString(selectors[i]) in:content];
            NSString *linkTip=[link[@"label"] isKindOfClass:NSString.class]?link[@"label"]:labels[i];
            button.toolTip=self.task&&i==1?(link?[NSString stringWithFormat:@"%@ · %@",linkTip,[self word:@"open_tip" fallback:@"Open it and focus for 25 minutes"]]:[self word:@"focus_tip" fallback:@"Focus for 25 minutes"]):self.task&&i==2?[self word:@"later_tip" fallback:@"Snooze for 15 minutes"]:(!self.task&&link&&i==0?linkTip:labels[i]);
        }
    } else {
        NSScrollView *replyScroll=[[NSScrollView alloc] initWithFrame:NSMakeRect(14,height-108-56,336,56)];replyScroll.drawsBackground=NO;replyScroll.hasVerticalScroller=YES;replyScroll.wantsLayer=YES;replyScroll.layer.backgroundColor=color(0xF2F6EE).CGColor;replyScroll.layer.cornerRadius=12;
        self.replyStatus=[[NSTextView alloc] initWithFrame:NSMakeRect(0,0,320,56)];self.replyStatus.editable=NO;self.replyStatus.selectable=YES;self.replyStatus.drawsBackground=NO;self.replyStatus.verticallyResizable=YES;self.replyStatus.autoresizingMask=NSViewWidthSizable;self.replyStatus.textContainer.widthTracksTextView=YES;self.replyStatus.textContainerInset=NSMakeSize(8,6);self.replyStatus.font=rounded(13,NSFontWeightSemibold);self.replyStatus.textColor=color(0x24452E);
        self.replyStatus.string=value[@"reply_answer"]?:[self word:@"prompt" fallback:@"Tell me what changed, ask for help, or say when to check back."];[self.replyStatus setAccessibilityLabel:@"Paco’s answer"];replyScroll.documentView=self.replyStatus;[content addSubview:replyScroll];
        self.replyField=[[NSTextField alloc] initWithFrame:NSMakeRect(14,height-172-30,252,30)];self.replyField.font=rounded(13,NSFontWeightMedium);self.replyField.placeholderString=[self word:@"placeholder" fallback:@"Reply to Paco…"];self.replyField.target=self;self.replyField.action=@selector(sendReply);self.replyField.bezelStyle=NSTextFieldRoundedBezel;[self.replyField setAccessibilityLabel:@"Reply to Paco"];[content addSubview:self.replyField];
        self.sendButton=[self chunky:[self word:@"send" fallback:@"Send"] kind:@"green" frame:NSMakeRect(274,height-172-30,76,30) action:@selector(sendReply) in:content];
        self.applyButton=[self chunky:[self word:@"apply" fallback:@"Apply"] kind:@"green" frame:NSMakeRect(14,height-212-30,110,30) action:@selector(applyReply) in:content];
        self.cancelButton=[self chunky:[self word:@"cancel" fallback:@"Cancel"] kind:@"white" frame:NSMakeRect(132,height-212-30,110,30) action:@selector(cancelReply) in:content];
        self.pendingReply=value[@"pending_reply"];self.applyButton.superview.hidden=!self.pendingReply;self.cancelButton.superview.hidden=!self.pendingReply;
    }
    self.banner=panel;[panel orderFrontRegardless];
    if(self.composing){[panel makeKeyAndOrderFront:nil];[panel makeFirstResponder:self.replyField];}
    else dispatch_after(dispatch_time(DISPATCH_TIME_NOW,18*NSEC_PER_SEC),dispatch_get_main_queue(),^{if(self.banner==panel&&!self.composing)[self dismiss];});
}
// Only web pages, Mac apps by bundle ID, and Paco's own pages; anything else is ignored.
- (void)openLink:(NSString *)url {
    if(![url isKindOfClass:NSString.class])return;
    if([url isEqual:@"/meetings"]){[self showMeetings];return;}
    if([url isEqual:@"/advanced"]){[self showWorkspace];return;}
    if([url hasPrefix:@"paco-app:"]){
        NSURL *app=[NSWorkspace.sharedWorkspace URLForApplicationWithBundleIdentifier:[url substringFromIndex:9]];
        if(app)[NSWorkspace.sharedWorkspace openApplicationAtURL:app configuration:[NSWorkspaceOpenConfiguration configuration] completionHandler:nil];
        return;
    }
    NSURL *target=[NSURL URLWithString:url];
    if([@[@"http",@"https"] containsObject:target.scheme.lowercaseString?:@""])[NSWorkspace.sharedWorkspace openURL:target];
}
- (void)openFromAlert {
    NSDictionary *link=[self.currentAlert[@"link"] isKindOfClass:NSDictionary.class]?self.currentAlert[@"link"]:nil;
    NSString *url=[link[@"url"] isKindOfClass:NSString.class]?link[@"url"]:self.currentAlert[@"open"];
    NSNumber *task=self.task;[self dismiss];[self openLink:url];
    if(task)[self post:@{@"action":@"start",@"id":task}];   // going to deal with it counts as focusing on it
}
- (void)dismiss { if(self.replying)return;[self.banner orderOut:nil];self.banner=nil;self.task=nil;self.composing=NO; }
- (void)beginReply { self.composing=YES;[self renderAlert]; }
- (void)talk {
    if(self.replying)return;
    NSMutableURLRequest *request=[self request:@"/api/action"];request.HTTPMethod=@"POST";[request setValue:@"1" forHTTPHeaderField:@"X-Paco"];[request setValue:@"application/json" forHTTPHeaderField:@"Content-Type"];request.HTTPBody=[NSJSONSerialization dataWithJSONObject:@{@"action":@"reply_context"} options:0 error:nil];
    [[NSURLSession.sharedSession dataTaskWithRequest:request completionHandler:^(NSData *data,NSURLResponse *response,NSError *error){dispatch_async(dispatch_get_main_queue(),^{
        NSDictionary *value=data?[NSJSONSerialization JSONObjectWithData:data options:0 error:nil]:nil;
        if(error||[(NSHTTPURLResponse *)response statusCode]!=200||!value){[self present:@{@"message":@"I couldn’t open the conversation. Please try again.",@"mood":@"friendly"}];return;}
        [self present:value];[self beginReply];
    });}] resume];
}
- (void)sendReply {
    NSString *text=[self.replyField.stringValue stringByTrimmingCharactersInSet:NSCharacterSet.whitespaceAndNewlineCharacterSet];
    if(self.replying||text.length==0)return;
    if(![text isEqual:self.replyText]){self.replyRequest=NSUUID.UUID.UUIDString;self.replyText=text;}
    [self submitReply:@{@"action":@"notification_reply",@"notification":self.currentAlert[@"id"]?:NSNull.null,@"text":text,@"request":self.replyRequest}];
}
- (void)applyReply { if(self.pendingReply)[self submitReply:@{@"action":@"confirm_reply",@"id":self.pendingReply,@"accept":@YES}]; }
- (void)cancelReply { if(self.pendingReply)[self submitReply:@{@"action":@"confirm_reply",@"id":self.pendingReply,@"accept":@NO}]; }
- (void)submitReply:(NSDictionary *)value {
    if(self.replying)return;self.replying=YES;self.sendButton.enabled=NO;self.replyField.editable=NO;self.applyButton.enabled=NO;self.cancelButton.enabled=NO;
    self.replyStatus.string=[self word:@"thinking" fallback:@"Thinking…"];
    NSMutableURLRequest *request=[self request:@"/api/action"];request.timeoutInterval=75;request.HTTPMethod=@"POST";[request setValue:@"1" forHTTPHeaderField:@"X-Paco"];[request setValue:@"application/json" forHTTPHeaderField:@"Content-Type"];request.HTTPBody=[NSJSONSerialization dataWithJSONObject:value options:0 error:nil];
    [[NSURLSession.sharedSession dataTaskWithRequest:request completionHandler:^(NSData *data,NSURLResponse *response,NSError *error){dispatch_async(dispatch_get_main_queue(),^{
        self.replying=NO;self.sendButton.enabled=YES;self.replyField.editable=YES;self.applyButton.enabled=YES;self.cancelButton.enabled=YES;
        NSDictionary *answer=data?[NSJSONSerialization JSONObjectWithData:data options:0 error:nil]:nil;
        if(error||[(NSHTTPURLResponse *)response statusCode]!=200){self.replyStatus.string=answer[@"error"]?:@"I couldn’t reach Paco. Your reply is still here; try Send again.";self.replyStatus.toolTip=self.replyStatus.string;return;}
        self.replyStatus.string=answer[@"answer"]?:@"Please try again.";self.replyStatus.toolTip=self.replyStatus.string;
        self.pendingReply=[answer[@"pending"] boolValue]?answer[@"reply"]:nil;self.applyButton.superview.hidden=!self.pendingReply;self.cancelButton.superview.hidden=!self.pendingReply;
        [self.replyStatus scrollRangeToVisible:NSMakeRange(0,0)];self.replyField.stringValue=@"";self.replyRequest=nil;self.replyText=nil;[self refreshStatus];[self.banner makeFirstResponder:self.replyField];
    });}] resume];
}
- (void)focusTask { NSNumber *task=self.task;[self dismiss];if(task)[self post:@{@"action":@"start",@"id":task}]; }
- (void)snoozeTask { NSNumber *task=self.task;[self dismiss];if(task)[self post:@{@"action":@"snooze",@"id":task}]; }
- (void)doneTask { NSNumber *task=self.task;[self dismiss];if(task)[self post:@{@"action":@"done",@"id":task}]; }
@end
int main(int argc,const char *argv[]) { @autoreleasepool { if(argc<3){
        NSDictionary *info=NSBundle.mainBundle.infoDictionary;
        NSString *python=info[@"PacoPython"], *script=info[@"PacoScript"];
        if(!python || !script)return 2;
        NSTask *launcher=[NSTask new];launcher.executableURL=[NSURL fileURLWithPath:python];launcher.arguments=@[script,@"desktop",@"--show-settings"];
        NSError *error=nil;if(![launcher launchAndReturnError:&error]){NSAlert *alert=[NSAlert new];alert.messageText=@"Paco could not start";alert.informativeText=error.localizedDescription;[alert runModal];return 2;}return 0;
    } if([NSProcessInfo.processInfo.arguments[1] isEqualToString:@"--capture"]) return captureContext(NSProcessInfo.processInfo.arguments); if([NSProcessInfo.processInfo.arguments[1] isEqualToString:@"--apple"]) return appleSources(NSProcessInfo.processInfo.arguments); NSApplication *app=NSApplication.sharedApplication; PacoApp *delegate=[PacoApp new]; app.delegate=delegate; [app run]; } return 0; }
