#import "MeetingSpeakers.h"
int main(){@autoreleasepool{
 NSDictionary *a=PacoParseZoomTile(@"Juan, Computer audio unmuted,Video off, Active speaker",@"j");
 NSCAssert([a[@"name"] isEqual:@"Juan"]&&[a[@"speaking"] boolValue]&&![a[@"self"] boolValue],@"Active remote participant");
 NSDictionary *b=PacoParseZoomTile(@"Nathalia(Host, me), Computer audio unmuted,Video on, Active speaker",@"self");
 NSCAssert([b[@"name"] isEqual:@"Nathalia"]&&[b[@"self"] boolValue],@"Host/self marker");
 NSDictionary *c=PacoParseZoomTile(@"Juan, Computer audio muted,Video off",@"j");NSCAssert(![c[@"speaking"] boolValue],@"Roster is not speaking");
 for(NSString *label in @[@"Juan",@"Active speaker",@"Juan is presenting",@"Pinned: Juan",@"Chat: Juan, Computer audio unmuted,Video off, Active speaker\nhello",@"Juan, Camera on",@"Juan, Computer audio unmuted,Video off, selected"]){NSCAssert(PacoParseZoomTile(label,@"x")==nil,@"Unsupported labels must not identify speakers");}
 printf("Zoom label parser fixtures passed (no Accessibility or microphone access requested).\n");return 0;
}}
