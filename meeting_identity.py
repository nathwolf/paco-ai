"""Calendar context and time-aligned speaker evidence. No voiceprints or audio storage.

Invitations describe expected attendance; only call signals or user corrections
can strengthen speaker attribution. Unsupported/stale signals fail unnamed.
"""
import json
import math
import re
import time
import unicodedata
from urllib.parse import urlsplit


def initialize(db):
    db.executescript('''
    CREATE TABLE IF NOT EXISTS calendar_people(event TEXT PRIMARY KEY,people TEXT NOT NULL,synced REAL NOT NULL);
    CREATE TABLE IF NOT EXISTS meeting_calendar_choice(event TEXT PRIMARY KEY,visible INTEGER NOT NULL CHECK(visible IN (0,1)),updated REAL NOT NULL);
    CREATE TABLE IF NOT EXISTS meeting_context(meeting TEXT PRIMARY KEY,event TEXT,context TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS meeting_speaker_sample(meeting TEXT,seconds REAL,source TEXT,snapshot TEXT NOT NULL,
      PRIMARY KEY(meeting,seconds,source));
    CREATE TABLE IF NOT EXISTS meeting_segment_identity(segment TEXT PRIMARY KEY,meeting TEXT,channel TEXT,
      finish REAL,source TEXT,confidence TEXT,participant TEXT,explanation TEXT);
    CREATE INDEX IF NOT EXISTS meeting_speaker_time ON meeting_speaker_sample(meeting,seconds);
    ''')


def normalize_people(raw):
    if not isinstance(raw,list):return []
    people=[];seen=set()
    for p in raw[:200]:
        if isinstance(p,str):p={'email':p}
        if not isinstance(p,dict):continue
        email=str(p.get('email','')).removeprefix('mailto:').strip().casefold()[:254]
        name=str(p.get('name') or p.get('displayName') or email).strip()[:120]
        status=str(p.get('status') or p.get('responseStatus') or 'unknown')
        if status=='declined' or p.get('resource') or not name:continue
        key=email or name.casefold()
        if key in seen:continue
        seen.add(key)
        people.append({'id':key,'name':name,'email':email,'self':p.get('self') is True,
                       'status':status,'organizer':p.get('organizer') is True})
    return people


def non_meeting_reason(event,people):
    """Exclude clear personal blocks; ambiguous entries remain available.

    This is deterministic and local. Invitation/meeting signals take priority over
    task-like wording, except the user's explicit placeholder convention (x).
    """
    title=' '.join(''.join(c for c in unicodedata.normalize('NFKD',event['title']).casefold()
                          if not unicodedata.combining(c)).split()).strip(' ._-')
    if not title or re.fullmatch(r'x+',title):return 'Calendar block'
    try:host=(urlsplit(event['url'] or '').hostname or '').lower()
    except ValueError:host=''
    call=host=='meet.google.com' or host in ('teams.microsoft.com','teams.live.com','teams.cloud.microsoft') or host=='zoom.us' or host.endswith('.zoom.us')
    if call or any(not p['self'] for p in people):return None
    if re.match(r'^(print|imprimir|buy|comprar|pick up|recoger)\b',title) or (re.match(r'^(get|take|sacar)\b',title) and re.search(r'\b(photos|photo|fotos|foto)\b',title)):
        return 'Personal task'
    if re.search(r'\b(meeting|reunion|reu|call|llamada|standup|stand-up|retro|workshop|taller|interview|entrevista|rendez-vous|focus group)\b',title):return None
    if re.fullmatch(r'(busy|blocked|block|hold|ocupad[oa]|bloquead[oa]|bloqueo|indisponible|focus|lunch|almuerzo|dejeuner|break|pausa|descanso|ooo|out of office|vacation|vacaciones|holiday|conges)',title):return 'Personal time'
    if re.match(r'^(focus time|deep work|focus session|tiempo de concentracion|trabajo profundo|calendar block|bloqueo de calendario|personal time|admin time|out of office|vacaciones)\b',title):return 'Calendar block'
    return None


def calendar_rows(db,where,args):
    return db.execute('''SELECT e.*,p.people,p.synced,c.visible FROM calendar_event e
        LEFT JOIN calendar_people p ON p.event=e.id
        LEFT JOIN meeting_calendar_choice c ON c.event=e.id WHERE '''+where+' ORDER BY e.start,e.id',args)


def event_people(row):
    try:return normalize_people(json.loads(row['people'] or row['attendees'] or '[]'))
    except (ValueError,TypeError):return []


def hidden_reason(row,people):
    if row['visible'] is not None:return None if row['visible'] else 'Removed by you'
    return non_meeting_reason(row,people)


def calendar_visibility(db,event,visible):
    if not isinstance(event,str) or type(visible) is not bool:raise ValueError('Choose a calendar event')
    if not db.execute('SELECT 1 FROM calendar_event WHERE id=?',(event,)).fetchone():raise ValueError('Calendar event no longer available')
    with db:db.execute('INSERT OR REPLACE INTO meeting_calendar_choice VALUES(?,?,?)',(event,int(visible),time.time()))
    return {'ok':True}


def candidates(db,now=None):
    now=time.time() if now is None else now
    result=[]
    for r in calendar_rows(db,'e.start<=? AND e.end>=?',(now+15*60,now-15*60)):
        people=event_people(r)
        if hidden_reason(r,people):continue
        result.append({'id':r['id'],'title':r['title'],'start':r['start'],'end':r['end'],'url':r['url'],
                       'people':people,'fresh':bool(r['synced'] and now-r['synced']<=1800)})
    return result


def upcoming(db,now=None,hidden=False):
    now=time.time() if now is None else now
    result=[]
    import calendar_series
    series=calendar_series.info(db)
    for r in calendar_rows(db,'e.end>? AND e.start<?',(now,now+7*86400)):
        reason=hidden_reason(r,event_people(r))
        if bool(reason)!=hidden:continue
        item={k:r[k] for k in ('id','title','start','end','url')}
        item['recurrence']=series.get(r['id'])
        if reason:item['reason']=reason
        result.append(item)
    return result if hidden else result[:12]


def suggested_event(events,now=None):
    now=time.time() if now is None else now
    current=[e for e in events if e['start']<=now<e['end']]
    if current:return current[0]['id'] if len(current)==1 else None
    upcoming=[e for e in events if now<e['start']<=now+15*60]
    return upcoming[0]['id'] if len(upcoming)==1 else None


def bind(db,ident,event_id=None,microphone_only=False,now=None):
    events=candidates(db,now);event=next((e for e in events if e['id']==event_id),None)
    if event_id and not event:raise ValueError('That calendar event is no longer near this meeting. Choose it again or start without a calendar event.')
    context={'event':event,'microphone_only':bool(microphone_only),'attendance':'expected, not verified'}
    with db:
        db.execute('INSERT OR REPLACE INTO meeting_context VALUES(?,?,?)',(ident,event_id,json.dumps(context)))
        if event:
            me=next((p['name'] for p in event['people'] if p['self']),None)
            if me:db.execute("UPDATE meeting_note SET me=CASE WHEN me='' THEN ? ELSE me END WHERE id=?",(me,ident))
        db.execute('UPDATE meeting_note SET revision=revision+1 WHERE id=?',(ident,))
    return context


def context(db,ident):
    r=db.execute('SELECT context FROM meeting_context WHERE meeting=?',(ident,)).fetchone()
    return json.loads(r[0]) if r else {'event':None,'microphone_only':False}


def samples(db,ident,values):
    if not isinstance(values,list) or len(values)>30:raise ValueError('Invalid speaker samples')
    note=db.execute('SELECT transcript_deleted,expires FROM meeting_note WHERE id=?',(ident,)).fetchone()
    if not note or note['transcript_deleted'] or (note['expires'] and note['expires']<=time.time()):raise ValueError('Speaker evidence has expired')
    rows=[]
    for value in values:
        if not isinstance(value,dict):raise ValueError('Invalid speaker sample')
        at=float(value.get('seconds',-1));source=value.get('source');status=value.get('status')
        if not math.isfinite(at) or not 0<=at<=86400 or source not in ('zoom','google_meet'):raise ValueError('Invalid speaker timestamp or source')
        if status not in ('ok','unavailable','permission_missing','not_running','paused'):raise ValueError('Invalid speaker status')
        raw=value.get('participants',[]);active=value.get('active',[])
        if not isinstance(raw,list) or len(raw)>200 or not isinstance(active,list) or len(active)>20:raise ValueError('Invalid participant list')
        participants=[];ids=set()
        for p in raw:
            if not isinstance(p,dict) or not isinstance(p.get('id'),str) or not isinstance(p.get('name'),str) or not 0<len(p['id'])<=200 or not 0<len(p['name'].strip())<=120:raise ValueError('Invalid participant')
            if p['id'] in ids:raise ValueError('Duplicate participant id')
            ids.add(p['id']);participants.append({'id':p['id'],'name':p['name'].strip(),'self':p.get('self') is True})
        if any(not isinstance(k,str) or k not in ids for k in active):raise ValueError('Unknown active speaker')
        clean={'source':source,'status':status,'participants':participants,'active':list(dict.fromkeys(active))}
        rows.append((ident,at,source,json.dumps(clean)))
    with db:
        db.executemany('INSERT OR REPLACE INTO meeting_speaker_sample VALUES(?,?,?,?)',rows)
        if any(json.loads(r[3])['participants'] for r in rows):
            ctx=context(db,ident);ctx['call_observed']=True
            db.execute('UPDATE meeting_context SET context=? WHERE meeting=?',(json.dumps(ctx),ident))


def key(name):
    return ' '.join(unicodedata.normalize('NFKC',name).casefold().split())


def resolve(db,ident,channel,start,finish):
    ctx=context(db,ident);note=db.execute('SELECT me FROM meeting_note WHERE id=?',(ident,)).fetchone()
    if channel=='microphone':
        if ctx['microphone_only']:return {'speaker':'In-room participants','source':'unknown','confidence':'unknown','participant':'','explanation':'A shared microphone does not identify an individual.'}
        return {'speaker':note['me'] or 'You','source':'microphone','confidence':'channel','participant':'self','explanation':'Local microphone channel; assumes this microphone is yours.'}
    unknown={'speaker':'Remote participants','source':'unknown','confidence':'unknown','participant':'','explanation':'No reliable speaker signal covered this turn.'}
    finish=max(start+.01,finish)
    rows=[(r['seconds'],json.loads(r['snapshot'])) for r in db.execute('SELECT seconds,snapshot FROM meeting_speaker_sample WHERE meeting=? AND seconds>=? AND seconds<=? ORDER BY seconds',(ident,max(0,start-1.5),finish))]
    # An observed ambiguity overrides calendar inference, even if only one invitee
    # is listed. A speaking highlight must cover the turn, not just its last frame.
    if len({snap['source'] for _,snap in rows if snap['status']=='ok'})>1:
        unknown['explanation']='More than one call app supplied speaker signals; choose a single call source.'
        return unknown
    labels=[];coverage=0;ambiguous=False;observed=False
    for index,(at,snap) in enumerate(rows):
        stop=min(finish,at+1.5,rows[index+1][0] if index+1<len(rows) else finish)
        duration=max(0,stop-max(start,at))
        if not duration:continue
        if snap['status']!='ok':continue
        observed=True
        people={p['id']:p for p in snap['participants']}
        remote=[people[k] for k in snap['active'] if not people[k]['self']]
        if len(remote)!=1 or len({key(p['name']) for p in people.values()})!=len(people):
            ambiguous=True;continue
        p=remote[0];labels.append((snap['source'],p['id'],p['name']));coverage+=duration
    unique=set(labels)
    if not ambiguous and len(unique)==1 and coverage/(finish-start)>=.8:
        source,pid,name=next(iter(unique))
        # Calendar names enrich only exact unambiguous matches; never fuzzy-match Juan/John.
        expected=(ctx.get('event') or {}).get('people',[])
        matches=[p for p in expected if not p['self'] and key(p['name'])==key(name)]
        return {'speaker':name,'source':source,'confidence':'observed','participant':matches[0]['id'] if len(matches)==1 else source+':'+pid,
                'explanation':'Call-app speaking indicator covered this turn. Display names are not verified legal identities.'}
    if observed:
        unknown['explanation']='Overlapping speakers, a speaker change, duplicate names or incomplete timing made this turn ambiguous.'
        return unknown
    # Never apply a 1:1 guess when ANY observed roster established a larger call.
    if ctx.get('call_observed'):return unknown
    roster_seen=db.execute('SELECT snapshot FROM meeting_speaker_sample WHERE meeting=? ORDER BY seconds DESC LIMIT 1',(ident,)).fetchone()
    if roster_seen:
        snap=json.loads(roster_seen[0])
        if snap['participants']:return unknown
    event=ctx.get('event');people=(event or {}).get('people',[])
    own=[p for p in people if p['self']];other=[p for p in people if not p['self']]
    if event and event['fresh'] and len(own)==1 and len(other)==1 and not ctx['microphone_only']:
        p=other[0]
        return {'speaker':p['name'],'source':'calendar_inferred','confidence':'tentative','participant':p['id'],
                'explanation':'Expected other participant in the linked one-to-one invite. Actual attendance has not been verified.'}
    return unknown


def save_attribution(db,segment,ident,channel,finish,value):
    with db:db.execute('INSERT OR REPLACE INTO meeting_segment_identity VALUES(?,?,?,?,?,?,?,?)',
        (segment,ident,channel,finish,value['source'],value['confidence'],value['participant'],value['explanation']))


def attach(db,ident,segments):
    attrs={r['segment']:dict(r) for r in db.execute('SELECT * FROM meeting_segment_identity WHERE meeting=?',(ident,))}
    for s in segments:s['identity']=attrs.get(s['id'],{'source':'imported','confidence':'provided','explanation':'Speaker label supplied with the imported transcript.'})
    return segments


def status(db,ident):
    row=db.execute('SELECT seconds,snapshot FROM meeting_speaker_sample WHERE meeting=? ORDER BY seconds DESC LIMIT 1',(ident,)).fetchone()
    return {'seconds':row['seconds'],**json.loads(row['snapshot'])} if row else {'status':'unavailable','source':None,'participants':[],'active':[]}


def forget_transcript(db,ident):
    db.execute('DELETE FROM meeting_speaker_sample WHERE meeting=?',(ident,))
    db.execute('DELETE FROM meeting_segment_identity WHERE meeting=?',(ident,))


def attributed_parts(db,ident,channel,offset,segment):
    """Split a transcription at observed speaker changes using local word timing.

Boundary words need a stable signal around them; uncertain words remain unnamed.
This is alignment with app indicators, not voiceprint recognition.
"""
    words=getattr(segment,'words',None)
    if not words or channel=='microphone':
        return [{'text':segment.text,'start':offset+segment.start,'end':offset+segment.end,
                 'identity':resolve(db,ident,channel,offset+segment.start,offset+segment.end)}]
    parts=[]
    for word in words:
        start=offset+word.start;end=offset+word.end
        attr=resolve(db,ident,channel,max(0,start-.3),end+.3)
        if parts and parts[-1]['identity']==attr and start-parts[-1]['end']<1.2:
            parts[-1]['text']+=word.word;parts[-1]['end']=end
        else:parts.append({'text':word.word,'start':start,'end':end,'identity':attr})
    return parts
