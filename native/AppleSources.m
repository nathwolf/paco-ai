#import <Cocoa/Cocoa.h>
#import <EventKit/EventKit.h>
int appleSources(NSArray *args) {
    @autoreleasepool {
        EKEventStore *store=[EKEventStore new];
        BOOL reminders=[args[2] isEqualToString:@"reminders"];
        __block BOOL finished=NO,allowed=NO;
        void (^completion)(BOOL,NSError *)=^(BOOL granted,NSError *error){allowed=granted;finished=YES;};
        if(@available(macOS 14.0,*)) {
            if(reminders)[store requestFullAccessToRemindersWithCompletion:completion];
            else [store requestFullAccessToEventsWithCompletion:completion];
        } else [store requestAccessToEntityType:reminders?EKEntityTypeReminder:EKEntityTypeEvent completion:completion];
        NSDate *limit=[NSDate dateWithTimeIntervalSinceNow:60];
        while(!finished && [limit timeIntervalSinceNow]>0)[NSRunLoop.currentRunLoop runUntilDate:[NSDate dateWithTimeIntervalSinceNow:.05]];
        if(!allowed){fprintf(stderr,"Apple calendar/reminder permission is unavailable.\n");return 3;}
        NSMutableArray *rows=[NSMutableArray array];
        if(reminders) {
            finished=NO;
            NSPredicate *predicate=[store predicateForIncompleteRemindersWithDueDateStarting:nil ending:nil calendars:nil];
            [store fetchRemindersMatchingPredicate:predicate completion:^(NSArray<EKReminder *> *items){
                for(EKReminder *item in items) [rows addObject:@{@"id":item.calendarItemIdentifier,@"title":item.title?:@"Reminder",@"account":item.calendar.source.sourceIdentifier,@"calendar":item.calendar.title?:@"Reminders"}];
                finished=YES;
            }];
            while(!finished && [limit timeIntervalSinceNow]>0)[NSRunLoop.currentRunLoop runUntilDate:[NSDate dateWithTimeIntervalSinceNow:.05]];
            if(!finished)return 4;
        } else {
            NSPredicate *predicate=[store predicateForEventsWithStartDate:NSDate.date endDate:[NSDate dateWithTimeIntervalSinceNow:7*86400] calendars:nil];
            for(EKEvent *item in [store eventsMatchingPredicate:predicate]) {
                BOOL declined=NO;for(EKParticipant *attendee in item.attendees)if(attendee.isCurrentUser && attendee.participantStatus==EKParticipantStatusDeclined)declined=YES;
                if(declined || item.status==EKEventStatusCanceled)continue;
                NSMutableArray *people=[NSMutableArray new];
                for(EKParticipant *person in item.attendees){
                    if(person.participantType==EKParticipantTypeRoom||person.participantType==EKParticipantTypeResource)continue;
                    NSString *email=[person.URL.scheme.lowercaseString isEqual:@"mailto"]?(person.URL.resourceSpecifier.stringByRemovingPercentEncoding?:@""):@"";
                    NSString *status=person.participantStatus==EKParticipantStatusDeclined?@"declined":person.participantStatus==EKParticipantStatusAccepted?@"accepted":person.participantStatus==EKParticipantStatusTentative?@"tentative":@"unknown";
                    [people addObject:@{@"name":person.name?:email,@"email":email,@"self":@(person.isCurrentUser),@"status":status,@"organizer":@([person.URL isEqual:item.organizer.URL])}];
                }
                [rows addObject:@{@"attendees":people,@"id":item.calendarItemIdentifier,@"calendar":item.calendar.calendarIdentifier,@"title":item.title?:@"Meeting",@"start":@(item.startDate.timeIntervalSince1970),@"end":@(item.endDate.timeIntervalSince1970),@"all_day":@(item.allDay),@"busy":@(item.availability!=EKEventAvailabilityFree),@"url":item.URL.absoluteString?:@""}];
            }
        }
        NSData *data=[NSJSONSerialization dataWithJSONObject:rows options:0 error:nil];
        fwrite(data.bytes,1,data.length,stdout);return 0;
    }
}
