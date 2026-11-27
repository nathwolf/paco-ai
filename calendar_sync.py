"""Discover every readable Google calendar; reconcile event identity before disappearance."""
import json,time
from datetime import datetime,timezone
from urllib.parse import quote
import attention,calendar_tasks,discovery

class CalendarAccessError(ValueError):pass


def calendars(session):
    result=[];token=None;seen=set()
    while True:
        params={'maxResults':250,'showHidden':'true'}
        if token:params['pageToken']=token
        response=session.get('https://www.googleapis.com/calendar/v3/users/me/calendarList',params=params,timeout=20)
        if response.status_code==403:raise CalendarAccessError('Reconnect Google to allow read-only calendar-list access; previous calendar data was retained')
        response.raise_for_status();data=response.json()
        for item in data.get('items',[]):
            if item.get('deleted') or item.get('id') in seen:continue
            seen.add(item['id']);result.append(dict(id=item['id'],key='primary' if item.get('primary') else item['id'],
                name=item.get('summaryOverride') or item.get('summary') or item['id'],role=item.get('accessRole',''),
                primary=bool(item.get('primary')),hidden=bool(item.get('hidden'))))
        token=data.get('nextPageToken')
        if not token:break
    if not any(c['primary'] for c in result):raise CalendarAccessError('Google returned an incomplete calendar list; previous calendar data was retained')
    return result


def initialize(db):
    db.execute('CREATE TABLE IF NOT EXISTS google_calendar_inventory(id TEXT PRIMARY KEY,payload TEXT,checked REAL)')
    db.execute('CREATE TABLE IF NOT EXISTS google_event_identity(key TEXT PRIMARY KEY,payload TEXT)')
    db.execute('CREATE TABLE IF NOT EXISTS google_event_alias(old_key TEXT PRIMARY KEY,new_key TEXT,reason TEXT,at REAL)')


def identity(event):
    uid=event.get('iCalUID')
    if not uid:return None
    original=event.get('originalStartTime') or {}
    occurrence=original.get('dateTime') or original.get('date') or ''
    if original.get('dateTime'):
        occurrence=datetime.fromisoformat(occurrence.replace('Z','+00:00')).astimezone(timezone.utc).isoformat()
    # A recurring master without an occurrence must not absorb an instance.
    if event.get('recurringEventId') and not occurrence:return None
    return (uid,occurrence)


def canonical(raw,previous):
    groups={}
    for key,event in raw.items():
        if event.get('status')=='cancelled':continue
        if any(a.get('self') and a.get('responseStatus')=='declined' for a in event.get('attendees',[])):continue
        groups.setdefault(identity(event) or ('key',key),[]).append(key)
    result={};aliases={}
    for keys in groups.values():
        # Prefer a previously tracked live copy; a move selects the remaining live copy.
        selected=min(keys,key=lambda k:(k not in previous,not k.startswith('primary:'),k))
        result[selected]=raw[selected]
        for key in keys:
            if key!=selected:aliases[key]=selected
    byidentity={identity(e):k for k,e in result.items() if identity(e)}
    combined={**previous,**{k:{**previous.get(k,{}),**e} for k,e in raw.items()}}
    for key,old in combined.items():
        if key in result:continue
        target=byidentity.get(identity(old)) if identity(old) else None
        # Older Paco versions did not store iCalUID. Google's moved tombstone can
        # still identify the destination organizer and preserve the same event ID.
        if target is None and old.get('id'):
            matches=[k for k,e in result.items() if e.get('id')==old['id'] and
                     (not old.get('iCalUID') or old.get('iCalUID')==e.get('iCalUID')) and
                     old.get('organizer',{}).get('email')==k.rsplit(':',1)[0]]
            if len(matches)==1:target=matches[0]
        if target and target!=key:aliases[key]=target
    return result,aliases


def rekey(db,old,new,now,new_url=None):
    """Preserve meaningful task identities and explicit decisions across calendar copies."""
    if old==new:return
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='calendar_alert'").fetchone():
        db.execute('UPDATE OR IGNORE calendar_alert SET event=? WHERE event=?',(new,old))
    tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    prior=db.execute("SELECT task_id FROM discovered WHERE source='calendar' AND key=?",(old,)).fetchone() if 'discovered' in tables else None
    destination=db.execute("SELECT task_id FROM discovered WHERE source='calendar' AND key=?",(new,)).fetchone() if 'discovered' in tables else None
    if prior:
        if not destination:
            db.execute("UPDATE discovered SET key=? WHERE source='calendar' AND key=?",(new,old))
            db.execute("UPDATE source_state SET key=? WHERE source='calendar' AND key=?",(new,old))
        else:
            db.execute("DELETE FROM discovered WHERE source='calendar' AND key=?",(old,))
            state=attention.info(db,prior[0])
            if state['status']=='reference':
                db.execute("UPDATE task SET state='archived' WHERE id=? AND state IN ('open','unavailable')",(prior[0],))
                attention.record(db,prior[0],'duplicate','Same calendar occurrence on another calendar','calendar',state['kind'],destination[0])
            else:
                db.execute('INSERT OR IGNORE INTO calendar_task_link VALUES(?,?,?)',(new,'moved-reference-'+str(prior[0]),prior[0]))
            db.execute("DELETE FROM source_state WHERE source='calendar' AND key=?",(old,))
        db.execute("INSERT INTO source_event(source,key,task,outcome,at) VALUES('calendar',?,?,'moved',?)",(old,prior[0],now))
    links=list(db.execute('SELECT action,task FROM calendar_task_link WHERE event=?',(old,)))
    for link in links:
        action=link['action'];existing=db.execute('SELECT task FROM calendar_task_link WHERE event=? AND action=?',(new,action)).fetchone()
        if existing and existing[0]!=link['task']:action+=':task:'+str(link['task'])
        db.execute('INSERT OR IGNORE INTO calendar_task_link VALUES(?,?,?)',(new,action,link['task']))
    db.execute('DELETE FROM calendar_task_link WHERE event=?',(old,))
    old_revision=db.execute('SELECT fingerprint FROM calendar_task_revision WHERE event=?',(old,)).fetchone()
    # Re-analyze changed context; existing_task/link matching prevents recreating the action.
    if old_revision:db.execute('DELETE FROM calendar_task_revision WHERE event=?',(old,))
    for table,column in [('meeting_calendar_choice','event')]:
        if table in tables and column in {r[1] for r in db.execute('PRAGMA table_info('+table+')')}:
            db.execute('UPDATE OR IGNORE '+table+' SET '+column+'=? WHERE '+column+'=?',(new,old))
    if new_url:
        db.execute("UPDATE evidence SET url=? WHERE source='calendar' AND (source_key=? OR substr(source_key,1,?)=?)",(new_url,old,len(old)+1,old+'/'))
    db.execute('INSERT OR REPLACE INTO google_event_alias VALUES(?,?,?,?)',(old,new,'Same Google event occurrence',now))


def refresh_schedule(db,old,new):
    if not old or old.get('start')==new.get('start'):return
    for row in db.execute('''SELECT DISTINCT t.id,t.state,t.due,d.deadline FROM calendar_task_link l
        JOIN task t ON t.id=l.task JOIN details d ON d.task=t.id WHERE l.event=?''',(new['id'],)).fetchall():
        if row['state'] not in ('open','focus','blocked'):continue
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='task_recurrence'").fetchone() and db.execute('SELECT 1 FROM task_recurrence WHERE task=? AND enabled=1',(row['id'],)).fetchone():continue
        # Only move deadlines actually anchored to this occurrence; keep unrelated dates.
        if row['deadline']==old.get('start'):deadline=new['start']
        elif old.get('all_day') and row['deadline']==old.get('end',0)-1:deadline=new['end']-1
        else:continue
        db.execute('UPDATE details SET deadline=? WHERE task=?',(deadline,row['id']))
        lead=old['start']-row['due']
        if 0<=lead<=86400:db.execute('UPDATE task SET due=? WHERE id=?',(new['start']-lead,row['id']))


def sync(db,now=None):
    initialize(db);now=time.time() if now is None else now
    # Entire provider snapshot is fetched before any live task/calendar mutations.
    with discovery.google_session() as session:inventory=calendars(session)
    readable=[c for c in inventory if c['role'] in ('reader','writer','owner','writerWithoutPrivateAccess')]
    if not readable:raise CalendarAccessError('No calendars with event-reading access; previous calendar data was retained')
    intervals,absences,events,people,contexts,raw=[],[],[],[],[],[]
    account=next(c['id'] for c in inventory if c['primary'])
    rows=list(discovery.google_rows('calendar',now,intervals,absences,[c['key'] for c in readable],events,people,contexts,raw_events_out=raw,account_email=account))
    raw={cal+':'+e['id']:e for cal,e in raw}
    previous={r['key']:json.loads(r['payload']) for r in db.execute('SELECT * FROM google_event_identity')}
    old_contexts={r['event']:json.loads(r['payload']) for r in db.execute('SELECT * FROM calendar_task_context')}
    for key,context in old_contexts.items():
        previous.setdefault(key,dict(context,id=key.rsplit(':',1)[-1]))
    chosen,aliases=canonical(raw,previous)
    ids=set(chosen);rows=[r for r in rows if r[0] in ids];events=[r for r in events if r[0] in ids];people=[r for r in people if r[0] in ids]
    contexts=[c for c in contexts if c['id'] in ids]
    metadata={c['key']:c for c in readable};account=next(c['id'] for c in inventory if c['primary'])
    for context in contexts:
        meta=metadata[context['id'].rsplit(':',1)[0]]
        context.update(calendar_name=meta['name'],calendar_primary=meta['primary'],account_email=account)
    with db:
        db.execute('BEGIN IMMEDIATE')
        for key in ids:db.execute('DELETE FROM google_event_alias WHERE old_key=?',(key,))
        for old,new in aliases.items():rekey(db,old,new,now,chosen[new].get('htmlLink'))
        # discovery.reconcile uses the same transaction, so mutations roll back together.
        discovery.reconcile(db,'calendar',rows,now,commit=False)
        for context in contexts:
            prior=old_contexts.get(context['id'])
            if not prior:prior=next((old_contexts[k] for k,v in aliases.items() if v==context['id'] and k in old_contexts),None)
            refresh_schedule(db,prior,context)
        calendar_tasks.replace_context(db,contexts)
        db.execute("DELETE FROM calendar_event WHERE id NOT LIKE 'apple:%' AND id NOT LIKE 'outlook:%'")
        db.executemany('INSERT OR REPLACE INTO calendar_event VALUES(?,?,?,?,?,?,?,?)',events)
        db.execute("DELETE FROM calendar_people WHERE event NOT LIKE 'apple:%' AND event NOT LIKE 'outlook:%'")
        db.executemany('INSERT OR REPLACE INTO calendar_people VALUES(?,?,?)',people)
        db.execute("DELETE FROM calendar_busy WHERE provider='google'")
        db.executemany("INSERT INTO calendar_busy VALUES('google',?,?)",sorted(set(intervals)))
        db.execute('DELETE FROM busy');db.execute('INSERT INTO busy SELECT start,end FROM calendar_busy')
        db.execute("DELETE FROM absence WHERE source='calendar'")
        db.executemany('INSERT OR REPLACE INTO absence VALUES(?,?,?,?,?)',absences)
        db.execute('DELETE FROM google_calendar_inventory')
        db.executemany('INSERT INTO google_calendar_inventory VALUES(?,?,?)',[(c['id'],json.dumps(c),now) for c in inventory])
        db.executemany('INSERT OR REPLACE INTO google_event_identity VALUES(?,?)',[(k,json.dumps(e)) for k,e in raw.items()])
    return {'calendars':len(readable),'events':len(events),'moves':len(aliases),'limited':len(inventory)-len(readable)}


def scope(db):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='google_calendar_inventory'").fetchone():return 'Calendar discovery pending'
    items=[json.loads(r[0]) for r in db.execute('SELECT payload FROM google_calendar_inventory')]
    readable=sum(c['role'] in ('reader','writer','owner','writerWithoutPrivateAccess') for c in items)
    return str(readable)+' calendars automatically discovered, next 30 days'+(' · '+str(len(items)-readable)+' with limited access' if len(items)>readable else '')
