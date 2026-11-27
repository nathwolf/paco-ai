"""Recognize provider calendar series without synthesizing future occurrences."""
import json
import re
from datetime import datetime


def info(db):
    result={}
    patterns={}
    for row in db.execute('SELECT event,payload FROM calendar_task_context'):
        event=json.loads(row['payload'])
        series=event.get('recurringEventId')
        title=' '.join(event.get('title','').casefold().split())
        if not series and title and not re.fullmatch(r'x+|busy|blocked|focus|lunch',title):
            patterns.setdefault((row['event'].rsplit(':',1)[0],title),[]).append(event)
        if series:
            # Calendar ID scopes provider IDs; iCalUID survives copies and moves.
            key=event.get('iCalUID') or row['event'].rsplit(':',1)[0]+':'+series
            result[row['event']]={'id':key,'label':'Repeating event',
                                'original_start':event.get('originalStartTime',{})}
    for (calendar,title),events in patterns.items():
        events=sorted(events,key=lambda e:e['start'])
        if len(events)<3:continue
        dates=[datetime.fromtimestamp(e['start']) for e in events]
        same_time=len({(d.hour,d.minute) for d in dates})==1
        weekly=all((b.date()-a.date()).days==7 for a,b in zip(dates,dates[1:]))
        monthly=len({d.day for d in dates})==1 and all((b.year-a.year)*12+b.month-a.month==1 for a,b in zip(dates,dates[1:]))
        if same_time and (weekly or monthly):
            for event in events:
                result[event['id']]={'id':calendar+':pattern:'+title,'label':'Weekly pattern' if weekly else 'Monthly pattern','inferred':True}
    return result


def events(db):
    series=info(db)
    return [dict(r,recurrence=series.get(r['id'])) for r in db.execute('SELECT * FROM calendar_event ORDER BY start')]
