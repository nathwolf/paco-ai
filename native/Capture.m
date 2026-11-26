#import <Cocoa/Cocoa.h>
#import <ApplicationServices/ApplicationServices.h>
#import <AVFoundation/AVFoundation.h>
static id attr(AXUIElementRef item, CFStringRef name) { CFTypeRef value=NULL; if(AXUIElementCopyAttributeValue(item,name,&value)!=kAXErrorSuccess)return nil; return CFBridgingRelease(value); }
static void collect(AXUIElementRef item, NSMutableArray *parts, int depth, int *visited) {
    if(depth>8 || ++(*visited)>2000)return;
    NSString *role=attr(item,kAXRoleAttribute);
    NSString *subrole=attr(item,kAXSubroleAttribute);
    if([subrole isEqualToString:@"AXSecureTextField"])return;
    if([@[@"AXStaticText",@"AXTextArea",@"AXTextField"] containsObject:role]) {
        id value=attr(item,kAXValueAttribute); if([value isKindOfClass:NSString.class] && [value length]>0)[parts addObject:value];
    }
    NSArray *children=attr(item,kAXChildrenAttribute);
    for(id child in children)collect((__bridge AXUIElementRef)child,parts,depth+1,visited);
}
int captureContext(NSArray *args) {
    @autoreleasepool {
        if([args[2] isEqualToString:@"permissions"]) {
            NSDictionary *value=@{@"microphone":@([AVCaptureDevice authorizationStatusForMediaType:AVMediaTypeAudio]),
                                  @"screen_audio":@(CGPreflightScreenCaptureAccess()),@"accessibility":@(AXIsProcessTrusted())};
            NSData *data=[NSJSONSerialization dataWithJSONObject:value options:0 error:nil];
            fwrite(data.bytes,1,data.length,stdout);return 0;
        }
        if([args[2] isEqualToString:@"request"]) { NSDictionary *options=@{(__bridge NSString *)kAXTrustedCheckOptionPrompt:@YES}; return AXIsProcessTrustedWithOptions((__bridge CFDictionaryRef)options)?0:3; }
        if([args[2] isEqualToString:@"activity"]) {
            // No Accessibility tree, window titles, screenshots or keystroke values.
            NSDictionary *session=CFBridgingRelease(CGSessionCopyCurrentDictionary());
            BOOL locked=[session[@"CGSSessionScreenIsLocked"] boolValue];
            NSRunningApplication *front=locked?nil:NSWorkspace.sharedWorkspace.frontmostApplication;
            double idle=CGEventSourceSecondsSinceLastEventType(kCGEventSourceStateCombinedSessionState,kCGAnyInputEventType);
            NSMutableDictionary *result=[@{@"app":front.localizedName?:@"",@"bundle":front.bundleIdentifier?:@"",@"idle":@(idle),@"locked":@(locked)} mutableCopy];
            // Session presence: Paco rests when another user has the console or no display is awake
            // (lid closed without an external monitor, or displays asleep).
            result[@"on_console"]=@([session[(__bridge NSString *)kCGSessionOnConsoleKey] boolValue]);
            CGDirectDisplayID displays[16];uint32_t count=0;
            if(CGGetOnlineDisplayList(16,displays,&count)==kCGErrorSuccess){
                uint32_t awake=0;for(uint32_t i=0;i<count;i++)if(CGDisplayIsActive(displays[i])&&!CGDisplayIsAsleep(displays[i]))awake++;
                result[@"displays"]=@(awake);
            }
            // The app's declared App Store category lets Paco recognise games without a list.
            id category=front.bundleURL?[NSBundle bundleWithURL:front.bundleURL].infoDictionary[@"LSApplicationCategoryType"]:nil;
            if([category isKindOfClass:NSString.class])result[@"category"]=category;
            // Call-outs only: the front window title of a browser, so a site like Instagram can be matched.
            // Requires Accessibility permission; never requested here, and Paco discards it after matching.
            NSArray *browsers=@[@"com.apple.Safari",@"com.google.Chrome",@"company.thebrowser.Browser",@"org.mozilla.firefox",@"com.microsoft.edgemac",@"com.brave.Browser",@"com.operasoftware.Opera",@"com.vivaldi.Vivaldi"];
            if(args.count>3&&[args[3] isEqualToString:@"titles"]&&front&&AXIsProcessTrusted()&&[browsers containsObject:front.bundleIdentifier?:@""]) {
                AXUIElementRef app=AXUIElementCreateApplication(front.processIdentifier);
                id focused=attr(app,kAXFocusedWindowAttribute);id title=focused?attr((__bridge AXUIElementRef)focused,kAXTitleAttribute):nil;
                if([title isKindOfClass:NSString.class])result[@"title"]=title;
                CFRelease(app);
            }
            NSData *data=[NSJSONSerialization dataWithJSONObject:result options:0 error:nil];
            if(!data)return 3;fwrite(data.bytes,1,data.length,stdout);return 0;
        }
        NSRunningApplication *front=NSWorkspace.sharedWorkspace.frontmostApplication;
        if(!AXIsProcessTrusted()){fprintf(stderr,"Accessibility permission is off.\n");return 3;}
        AXUIElementRef app=AXUIElementCreateApplication(front.processIdentifier);
        id focused=attr(app,kAXFocusedWindowAttribute); NSString *title=focused?attr((__bridge AXUIElementRef)focused,kAXTitleAttribute):nil;
        NSMutableDictionary *result=[@{@"app":front.localizedName?:@"",@"bundle":front.bundleIdentifier?:@"",@"title":title?:@""} mutableCopy];
        if([args[2] isEqualToString:@"text"] && focused && args.count>3 && [front.bundleIdentifier isEqualToString:args[3]]) {
            NSMutableArray *parts=[NSMutableArray array];int visited=0;collect((__bridge AXUIElementRef)focused,parts,0,&visited);
            result[@"text"]=[parts componentsJoinedByString:@"\n"];
        }
        CFRelease(app);
        NSData *data=[NSJSONSerialization dataWithJSONObject:result options:0 error:nil];fwrite(data.bytes,1,data.length,stdout);return 0;
    }
}
