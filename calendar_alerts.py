"""Calendar attendance reminders, independent of inferred personal tasks."""
import html
import json
import re
import time
from urllib.parse import urlsplit
import meeting_identity

REASON='Upcoming calendar event'


def provider(url):
    try:
        u=urlsplit(str(url or ''));host=(u.hostname or '').lower()
        if u.scheme!='https' or u.username or u.password:return None
        if host=='meet.google.com' and re.fullmatch(r'/[a-z]{3}-[a-z]{4}-[a-z]{3}/?',u.path):return 'Google Meet'
        if (host=='zoom.us' or host.endswith('.zoom.us')) and re.match(r'^/(j|s|my)/[^/]+',u.path):return 'Zoom'
        if host in ('teams.microsoft.com','teams.live.com','teams.cloud.microsoft') and re.match(r'^/(l/meetup-join/|meet/)',u.path):return 'Teams'
    except ValueError:pass
    return None


def join_url(event):
    """Prefer structured conference data, then explicit links in location/notes."""
    urls=[event.get('hangoutLink'),event.get('url')]
    urls += [p.get('uri') for p in event.get('conferenceData',{}).get('entryPoints',[]) if p.get('entryPointType')=='video']
    for field in ('location','description'):
        urls += re.findall(r'https://[^\s<>"\x27]+',html.unescape(event.get(field,'') or ''))
    return next((html.unescape(u).rstrip('.,);') for u in urls if isinstance(u,str) and provider(html.unescape(u).rstrip('.,);'))),None)


def initialize(db):
    db.executescript('''CREATE TABLE IF NOT EXISTS calendar_alert(
        notification INTEGER PRIMARY KEY,event TEXT NOT NULL,start REAL NOT NULL,stage TEXT NOT NULL,
        UNIQUE(event,start,stage));''')


def allowed(db,now):
    import planning,workspace,mac_focus
    if mac_focus.active(db,now) or workspace.active(db,now):return False
    if planning.setting(db,'mode','work')=='paused' or float(planning.setting(db,'quiet_until','0'))>now:return False
    if planning.time_off(db,now) or db.execute('SELECT 1 FROM absence WHERE start<=? AND end>?',(now,now)).fetchone():return False
    if db.execute("SELECT 1 FROM task WHERE state='focus' AND due>?",(now,)).fetchone():return False
    if db.execute("SELECT 1 FROM meeting_note WHERE state IN ('recording','paused','finishing')").fetchone():return False
    return True


def eligible(db,row):
    if row['visible']==0:return False
    reason=meeting_identity.non_meeting_reason(row,meeting_identity.event_people(row))
    if reason in ('Calendar block','Personal time'):return False
    context=db.execute('SELECT payload FROM calendar_task_context WHERE event=?',(row['id'],)).fetchone()
    if context:
        e=json.loads(context[0])
        if e.get('event_type') in ('outOfOffice','focusTime','workingLocation','birthday') or e.get('all_day'):return False
        account=e.get('account_email','').casefold()
        if account and not e.get('calendar_primary'):
            people=[e.get('creator',{}),e.get('organizer',{})]+[p for p in e.get('attendees',[]) if p.get('responseStatus')!='declined']
            if not any(p.get('email','').casefold()==account for p in people):return False
    return True


def queue(db,now=None):
    now=time.time() if now is None else now
    if not allowed(db,now):return 0
    count=0
    with db:
        for r in meeting_identity.calendar_rows(db,'e.start<=? AND e.start>=? AND e.end>?',(now+600,now-300,now)):
            if not eligible(db,r):continue
            stage='soon' if r['start']>now else 'now'
            if db.execute('SELECT 1 FROM calendar_alert WHERE event=? AND start=? AND stage=?',(r['id'],r['start'],stage)).fetchone():continue
            # Replace any undelivered pre-start reminder with the current one.
            db.execute('UPDATE notification SET shown=? WHERE shown IS NULL AND id IN (SELECT notification FROM calendar_alert WHERE event=?)',(now,r['id']))
            ident=db.execute("INSERT INTO notification(task,message,mood,reason,created) VALUES(NULL,?,'friendly',?,?)",(r['title'],REASON,now)).lastrowid
            db.execute('INSERT INTO calendar_alert VALUES(?,?,?,?)',(ident,r['id'],r['start'],stage));count+=1
    return count


def event_for_alert(db,ident,now=None):
    now=time.time() if now is None else now
    a=db.execute('SELECT event,start FROM calendar_alert WHERE notification=?',(ident,)).fetchone()
    if not a:return None
    r=meeting_identity.calendar_rows(db,'e.id=?',(a['event'],)).fetchone()
    if not r or r['start']!=a['start'] or not (now-300<=r['start']<=now+600) or r['end']<=now or not eligible(db,r):return None
    return dict(r)


def payload(db,ident,now=None):
    r=event_for_alert(db,ident,now)
    if not r:return None
    call=provider(r['url']) if meeting_identity.non_meeting_reason(r,meeting_identity.event_people(r)) is None else None
    return {'id':r['id'],'title':r['title'],'start':r['start'],'end':r['end'],'provider':call,
            'join_url':r['url'] if call else None,'calendar_url':r['url'] if not call else None}
