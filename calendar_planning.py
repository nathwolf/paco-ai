"""Conflict previews, with ETag-checked Google moves and explicit attendee notice."""
from datetime import datetime
import json
import uuid
from urllib.parse import quote


def initialize(db):
    db.executescript('''CREATE TABLE IF NOT EXISTS calendar_event(id TEXT PRIMARY KEY,calendar TEXT,title TEXT,start REAL,end REAL,url TEXT,etag TEXT,attendees TEXT);
    CREATE TABLE IF NOT EXISTS calendar_proposal(id TEXT PRIMARY KEY,event TEXT,etag TEXT,start TEXT,end TEXT,status TEXT,receipt TEXT);''')


def conflicts(db):
    return [dict(r) for r in db.execute('''SELECT a.id AS first_id,a.title AS first,b.id AS second_id,b.title AS second,
        MAX(a.start,b.start) AS start,MIN(a.end,b.end) AS end FROM calendar_event a JOIN calendar_event b
        ON a.id<b.id AND a.start<b.end AND b.start<a.end ORDER BY start''')]


def preview(db,event,start,end):
    row=db.execute('SELECT * FROM calendar_event WHERE id=?',(event,)).fetchone()
    if not row:
        raise ValueError('Unknown event')
    if row['id'].startswith('apple:'):
        raise ValueError('Apple events are read-only; move this event in Calendar')
    begin,finish=[datetime.fromisoformat(v.replace('Z','+00:00')) for v in (start,end)]
    if begin.tzinfo is None or finish.tzinfo is None or finish<=begin:
        raise ValueError('Choose timezone-aware start and end times')
    if db.execute('SELECT 1 FROM calendar_event WHERE id!=? AND start<? AND end>?',(event,finish.timestamp(),begin.timestamp())).fetchone():
        raise ValueError('Proposed time overlaps another selected calendar event')
    ident=uuid.uuid4().hex
    with db:
        db.execute("INSERT INTO calendar_proposal VALUES(?,?,?,?,?,'draft',NULL)",(ident,event,row['etag'],start,end))
    return {'id':ident,'event':row['title'],'calendar':row['calendar'],'start':start,'end':end,
            'notify_attendees':json.loads(row['attendees']),'send_updates':'all'}


def apply(db,session,ident):
    row=db.execute('SELECT p.*,e.calendar FROM calendar_proposal p JOIN calendar_event e ON e.id=p.event WHERE p.id=?',(ident,)).fetchone()
    if not row:
        raise ValueError('Unknown proposal')
    if row['status']=='sent':
        return row['receipt']
    if row['status']!='draft':
        raise ValueError('Delivery uncertain; inspect the calendar before retrying')
    event=row['event'].split(':',1)[1]
    url='https://www.googleapis.com/calendar/v3/calendars/'+quote(row['calendar'],safe='')+'/events/'+quote(event,safe='')
    response=session.get(url,timeout=20);response.raise_for_status();current=response.json()
    if current['etag']!=row['etag']:
        raise ValueError('Event changed; create a new preview')
    with db:
        if db.execute("UPDATE calendar_proposal SET status='pending' WHERE id=? AND status='draft'",(ident,)).rowcount!=1:
            raise ValueError('Move already in progress')
    response=session.patch(url,params={'sendUpdates':'all'},headers={'If-Match':row['etag']},
                           json={'start':{'dateTime':row['start']},'end':{'dateTime':row['end']}},timeout=20)
    response.raise_for_status()
    result=response.json();receipt=result.get('htmlLink',url)
    with db:db.execute("UPDATE calendar_proposal SET status='sent',receipt=? WHERE id=?",(receipt,ident))
    return receipt
