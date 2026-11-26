#import "MeetingSpeakers.h"
#import <ApplicationServices/ApplicationServices.h>

static id speakerAttribute(AXUIElementRef node,CFStringRef key){CFTypeRef value=NULL;if(AXUIElementCopyAttributeValue(node,key,&value)!=kAXErrorSuccess)return nil;return CFBridgingRelease(value);}

NSDictionary *PacoParseZoomTile(NSString *label,NSString *identifier){
    // Deliberately narrow English participant-tile grammar. A pinned tile, window
    // title, roster selection, caption or chat message is never a speaking signal.
    if(![label isKindOfClass:NSString.class]||label.length>350)return nil;
    NSRegularExpression *pattern=[NSRegularExpression regularExpressionWithPattern:@"^(.+?),\\s*(?:Computer|Phone) audio (?:unmuted|muted),\\s*Video (?:on|off)(?:,\\s*(Active speaker|Speaking))?$" options:NSRegularExpressionCaseInsensitive error:nil];
    NSTextCheckingResult *match=[pattern firstMatchInString:label options:0 range:NSMakeRange(0,label.length)];if(!match)return nil;
    NSString *name=[label substringWithRange:[match rangeAtIndex:1]];
    NSRegularExpression *suffix=[NSRegularExpression regularExpressionWithPattern:@"\\s*\\(((?:Host|Co-host|me|you)(?:,\\s*)?)+\\)$" options:NSRegularExpressionCaseInsensitive error:nil];
    NSTextCheckingResult *meta=[suffix firstMatchInString:name options:0 range:NSMakeRange(0,name.length)];BOOL own=NO;
    if(meta){NSString *markers=[[name substringWithRange:meta.range] lowercaseString];own=[markers containsString:@"me"]||[markers containsString:@"you"];name=[name substringToIndex:meta.range.location];}
    name=[name stringByTrimmingCharactersInSet:NSCharacterSet.whitespaceAndNewlineCharacterSet];if(!name.length||name.length>120)return nil;
    BOOL speaking=[match rangeAtIndex:2].location!=NSNotFound;
    return @{@"id":identifier,@"name":name,@"self":@(own),@"speaking":@(speaking)};
}
static void scanSpeakers(AXUIElementRef node,NSString *path,NSMutableArray *people,NSMutableArray *active,NSMutableSet *seen,int depth,int *count,double deadline){
    if(depth>14||++(*count)>1000||NSProcessInfo.processInfo.systemUptime>deadline)return;
    NSString *role=speakerAttribute(node,kAXRoleAttribute);
    // Never read text fields, web content, captions or chat text values.
    if([@[@"AXTextField",@"AXTextArea",@"AXWebArea",@"AXStaticText"] containsObject:role])return;
    if([@[@"AXGroup",@"AXButton",@"AXCell",@"AXRow",@"AXImage"] containsObject:role]){
        NSString *label=speakerAttribute(node,kAXDescriptionAttribute);
        NSString *identifier=speakerAttribute(node,kAXIdentifierAttribute);
        if(![identifier isKindOfClass:NSString.class]||!identifier.length)identifier=path;
        if(identifier.length>200)identifier=[identifier substringToIndex:200];
        NSDictionary *tile=PacoParseZoomTile(label,identifier);
        if(!tile)tile=PacoParseZoomTile(speakerAttribute(node,kAXTitleAttribute),identifier);
        if(tile){
            if(![seen containsObject:identifier]){[seen addObject:identifier];[people addObject:@{@"id":identifier,@"name":tile[@"name"],@"self":tile[@"self"]}];if([tile[@"speaking"] boolValue])[active addObject:identifier];}
            return;
        }
    }
    NSArray *children=speakerAttribute(node,kAXChildrenAttribute);
    if(![children isKindOfClass:NSArray.class])return;
    NSUInteger index=0;for(id child in children){scanSpeakers((__bridge AXUIElementRef)child,[path stringByAppendingFormat:@"/%lu",(unsigned long)index++],people,active,seen,depth+1,count,deadline);if(people.count>=200||NSProcessInfo.processInfo.systemUptime>deadline)break;}
}
NSDictionary *PacoZoomSpeakerSnapshot(void){
    if(!AXIsProcessTrusted())return @{@"source":@"zoom",@"status":@"permission_missing",@"participants":@[],@"active":@[]};
    NSArray *apps=[NSRunningApplication runningApplicationsWithBundleIdentifier:@"us.zoom.xos"];
    if(apps.count!=1)return @{@"source":@"zoom",@"status":@"not_running",@"participants":@[],@"active":@[]};
    AXUIElementRef app=AXUIElementCreateApplication([apps.firstObject processIdentifier]);AXUIElementSetMessagingTimeout(app,.03);
    NSMutableArray *people=[NSMutableArray new],*active=[NSMutableArray new];NSMutableSet *seen=[NSMutableSet new];int count=0;
    scanSpeakers(app,@"zoom",people,active,seen,0,&count,NSProcessInfo.processInfo.systemUptime+.25);CFRelease(app);
    return @{@"source":@"zoom",@"status":people.count?@"ok":@"unavailable",@"participants":people,@"active":active};
}
void PacoRequestSpeakerPermission(void){NSDictionary *options=@{(__bridge NSString *)kAXTrustedCheckOptionPrompt:@YES};AXIsProcessTrustedWithOptions((__bridge CFDictionaryRef)options);}
