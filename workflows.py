"""Durable, inspectable personal context and proposed work. No implicit external writes."""
import hashlib
import json
import re
import time
import uuid
from datetime import datetime


def initialize(db):
    db.executescript('''
    CREATE TABLE IF NOT EXISTS evidence(id TEXT PRIMARY KEY,source TEXT,source_key TEXT,url TEXT,
      person TEXT,project TEXT,at REAL,text TEXT,task INTEGER,deleted INTEGER DEFAULT 0);
    CREATE TABLE IF NOT EXISTS correction(id INTEGER PRIMARY KEY,task INTEGER,before_json TEXT,after_json TEXT,at REAL);
    CREATE TABLE IF NOT EXISTS learned(key TEXT PRIMARY KEY,value TEXT,evidence TEXT,status TEXT);
    CREATE TABLE IF NOT EXISTS meeting(id TEXT PRIMARY KEY,title TEXT,at REAL,partial INTEGER,source TEXT);
    CREATE TABLE IF NOT EXISTS waiting(id TEXT PRIMARY KEY,thread TEXT,recipient TEXT,request TEXT,since REAL,due REAL,status TEXT,draft TEXT,reply TEXT);
    CREATE TABLE IF NOT EXISTS request_history(id INTEGER PRIMARY KEY,signature TEXT,request TEXT,at REAL);
    CREATE TABLE IF NOT EXISTS automation(id TEXT PRIMARY KEY,title TEXT,trigger TEXT,interval INTEGER,next_run REAL,status TEXT,action TEXT);
    CREATE TABLE IF NOT EXISTS automation_run(id INTEGER PRIMARY KEY,automation TEXT,at REAL,result TEXT,UNIQUE(automation,at));
    CREATE TABLE IF NOT EXISTS capture_rule(app TEXT PRIMARY KEY,enabled INTEGER,images INTEGER);
    CREATE TABLE IF NOT EXISTS exclusion(kind TEXT,value TEXT,PRIMARY KEY(kind,value));
    CREATE TABLE IF NOT EXISTS tombstone(source TEXT,source_key TEXT,PRIMARY KEY(source,source_key));
    CREATE TABLE IF NOT EXISTS change_log(id INTEGER PRIMARY KEY,kind TEXT,payload TEXT,at REAL);
    CREATE TABLE IF NOT EXISTS conversation(id INTEGER PRIMARY KEY,role TEXT,text TEXT,at REAL);
    CREATE TABLE IF NOT EXISTS suggestion(id TEXT PRIMARY KEY,action TEXT,status TEXT);
    CREATE TABLE IF NOT EXISTS ownership(task INTEGER PRIMARY KEY,owner TEXT,requester TEXT);
    ''')


def changed(db, kind, payload):
    db.execute("INSERT INTO change_log(kind,payload,at) VALUES(?,?,?)", (kind,json.dumps(payload),time.time()))


def remember(db, source, key, text, url='', person='', project='', at=None, task=None):
    if forgotten(db,source,key):
        return None
    ident = hashlib.sha256((source+'\0'+key).encode()).hexdigest()
    db.execute("INSERT INTO evidence(id,source,source_key,url,person,project,at,text,task) VALUES(?,?,?,?,?,?,?,?,?) "
               "ON CONFLICT(id) DO UPDATE SET text=excluded.text,url=excluded.url,task=COALESCE(excluded.task,evidence.task)",
               (ident,source,key,url,person,project,at or time.time(),text,task))
    return ident


def forgotten(db,source,key):
    return db.execute('SELECT 1 FROM tombstone WHERE source=? AND source_key=?',
                      (source,hashlib.sha256(key.encode()).hexdigest())).fetchone() is not None


def search(db, query='', person='', project='', since=0, until=None):
    # Literal substring search: '%' in the user's text is not a wildcard.
    return [dict(r) for r in db.execute('''SELECT * FROM evidence WHERE deleted=0
        AND instr(lower(text),lower(?))>0 AND (?='' OR instr(lower(person),lower(?))>0)
        AND (?='' OR project=?) AND at>=? AND at<=? ORDER BY at DESC LIMIT 100''',
        (query,person,person,project,project,since,until or time.time()))]


def flush_deleted(db):
    """Truncate the write-ahead log after deleting personal text, so deleted pages do not linger in it."""
    import sqlite3
    try:
        db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    except sqlite3.OperationalError:
        pass  # Busy readers: SQLite checkpoints again automatically; secure_delete still zeroes the pages.


def forget(db, source, key):
    with db:
        if source == 'mattermost':
            # Forget the whole message, including any task citations derived from it.
            base = '/'.join(key.split('/')[:3])
            tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if 'mattermost_proposal' in tables:
                db.execute("DELETE FROM mattermost_proposal WHERE source_key=? OR substr(source_key,1,?)=?",(base,len(base)+1,base+'/'))
            if 'mattermost_dm' in tables and len(base.split('/'))==3:
                account,message=base.rsplit('/',1)
                db.execute("UPDATE mattermost_dm SET text='',answer='',state='forgotten' WHERE account=? AND post=?",(account,message))
            if 'mattermost_mention' in tables and len(base.split('/'))==3:
                account,message=base.rsplit('/',1)
                db.execute("UPDATE mattermost_mention SET answer='',state='forgotten' WHERE account=? AND post=?",(account,message))
            related = [r[0] for r in db.execute("SELECT source_key FROM evidence WHERE source=? AND (source_key=? OR substr(source_key,1,?)=?)", (source,base,len(base)+1,base+'/'))]
            for item in set(related+[base,key]):
                db.execute("INSERT OR IGNORE INTO tombstone VALUES(?,?)", (source,hashlib.sha256(item.encode()).hexdigest()))
                db.execute("UPDATE learned SET value='',evidence='',status='rejected' WHERE instr(evidence,?)>0", (hashlib.sha256((source+'\0'+item).encode()).hexdigest(),))
                db.execute("DELETE FROM evidence WHERE source=? AND source_key=?", (source,item))
        ids = [r[0] for r in db.execute("SELECT id FROM evidence WHERE source=? AND source_key=?",(source,key))]
        db.execute("INSERT OR IGNORE INTO tombstone VALUES(?,?)",(source,hashlib.sha256(key.encode()).hexdigest()))
        db.execute("DELETE FROM evidence WHERE source=? AND source_key=?",(source,key))
        if source=='gmail' and key.count('/')>=3:
            owner,thread,message,quote=key.split('/',3)
            tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if 'mail_task' in tables:
                db.execute('DELETE FROM mail_task WHERE thread=? AND message=? AND quote=?',(owner+'/'+thread,message,quote))
                db.execute('DELETE FROM mail_resolution WHERE message=? AND quote=?',(message,quote))
            db.execute("UPDATE source_event SET key=? WHERE source='gmail' AND key=?",(owner+'/'+thread+'/'+message+'/[forgotten]',key))
        for ident in ids:
            db.execute("UPDATE learned SET value='',evidence='',status='rejected' WHERE instr(evidence,?)>0",(ident,))
        changed(db,'source.deleted',{'source':source,'key_hash':hashlib.sha256(key.encode()).hexdigest()})
    flush_deleted(db)


def correct_task(db, task, **updates):
    allowed = {'title','priority','state'}
    if not updates or set(updates)-allowed:
        raise ValueError('Only title, priority and state can be edited')
    if 'title' in updates and (not updates['title'].strip() or len(updates['title']) > 500):
        raise ValueError('Enter a title of 1–500 characters')
    if 'priority' in updates and updates['priority'] not in range(1,6):
        raise ValueError('Priority must be 1–5')
    if 'state' in updates and updates['state'] not in ('open','done','blocked','archived','incorrect','cancelled','unavailable'):
        raise ValueError('Invalid task state')
    with db:
        old = db.execute('SELECT * FROM task WHERE id=?',(task,)).fetchone()
        if not old:
            raise ValueError('Unknown task')
        before = {k:old[k] for k in updates}
        db.execute('UPDATE task SET '+','.join(k+'=?' for k in updates)+' WHERE id=?',(*updates.values(),task))
        db.execute('INSERT INTO correction(task,before_json,after_json,at) VALUES(?,?,?,?)',
                   (task,json.dumps(before),json.dumps(updates),time.time()))
        db.execute('INSERT INTO task_override(task,title,state) VALUES(?,?,?) ON CONFLICT(task) DO UPDATE SET title=COALESCE(excluded.title,title),state=COALESCE(excluded.state,state)',
                   (task,updates.get('title'),updates.get('state')))
        changed(db,'task.updated',{'id':task,**updates})


def undo(db, ident):
    row = db.execute('SELECT * FROM correction WHERE id=?',(ident,)).fetchone()
    if not row:
        raise ValueError('Unknown correction')
    current = db.execute('SELECT * FROM task WHERE id=?',(row['task'],)).fetchone()
    if any(current[k] != v for k,v in json.loads(row['after_json']).items()):
        raise ValueError('Task changed since this edit; review it before undoing')
    correct_task(db,row['task'],**json.loads(row['before_json']))


def merge(db, keep, other):
    import task_relationships
    return task_relationships.merge(db,keep,other)


def import_meeting(db, data):
    """Import a common transcript, keeping proposals distinct from explicit assignments."""
    title = str(data['title'])[:500]
    meeting = str(data.get('id') or uuid.uuid4().hex)
    at = float(data.get('at',time.time()))
    with db:
        db.execute('INSERT OR REPLACE INTO meeting VALUES(?,?,?,?,?)',
                   (meeting,title,at,bool(data.get('partial')),data.get('url','')))
        for index, segment in enumerate(data['segments']):
            if not isinstance(segment.get('text'),str) or not isinstance(segment.get('speaker'),str):
                raise ValueError('Each segment needs speaker and text')
            offset = float(segment.get('seconds',0))
            if offset < 0:
                raise ValueError('Negative timestamp')
            remember(db,'meeting',meeting+':'+str(index),segment['text'],data.get('url',''),
                     segment['speaker'],data.get('project',''),at+offset)
        changed(db,'meeting.imported',{'id':meeting})
    return meeting


def accept_assignment(db, evidence_id, title, owner, deadline=None):
    evidence = db.execute('SELECT * FROM evidence WHERE id=?',(evidence_id,)).fetchone()
    if not evidence or not owner.strip() or not title.strip():
        raise ValueError('Select evidence and confirm the task and owner')
    if deadline:
        parsed = datetime.fromisoformat(deadline.replace('Z','+00:00'))
        if parsed.tzinfo is None:
            raise ValueError('Deadline needs a timezone offset')
        deadline = parsed.timestamp()
    with db:
        if evidence['task']:
            return evidence['task']
        task = db.execute("INSERT INTO task(title,priority,state,due) VALUES(?,3,'open',?)",(title,time.time())).lastrowid
        db.execute('UPDATE evidence SET task=? WHERE id=?',(task,evidence_id))
        db.execute('INSERT INTO details VALUES(?,?,NULL,?)',(task,evidence['project'],deadline))
        db.execute('INSERT INTO ownership VALUES(?,?,?)',(task,owner,evidence['person']))
        changed(db,'task.created',{'id':task,'owner':owner,'evidence':evidence_id})
    return task


def attach_evidence(db, evidence_id, task):
    if not db.execute('SELECT 1 FROM task WHERE id=?',(task,)).fetchone():
        raise ValueError('Unknown task')
    with db:
        if db.execute('UPDATE evidence SET task=? WHERE id=?',(task,evidence_id)).rowcount!=1:
            raise ValueError('Unknown evidence')
        changed(db,'evidence.linked',{'task':task,'evidence':evidence_id})


def wait_for(db, thread, recipient, request, days=3):
    if not 1 <= days <= 60 or not all((thread,recipient,request)):
        raise ValueError('Supply a thread, recipient, request and 1–60 days')
    ident = hashlib.sha256((thread+'\0'+recipient+'\0'+request).encode()).hexdigest()
    with db:
        db.execute("INSERT OR IGNORE INTO waiting VALUES(?,?,?,?,?,?,'waiting','',NULL)",
                   (ident,thread,recipient,request,time.time(),time.time()+days*86400))
    return ident


def observe_reply(db, thread, sender, text, automated=False):
    if automated:
        return
    with db:
        db.execute("UPDATE waiting SET status='answered',reply=?,draft='' WHERE thread=? AND lower(recipient)=lower(?) AND status='waiting'",
                   (text,thread,sender))


def followup_draft(db, ident, body=None):
    with db:
        row = db.execute('SELECT * FROM waiting WHERE id=?',(ident,)).fetchone()
        if not row or row['status'] != 'waiting':
            raise ValueError('This request is no longer waiting for a reply')
        style = db.execute("SELECT value FROM learned WHERE key='writing_style' AND status='accepted'").fetchone()
        body = body if body is not None else (row['draft'] or 'Hi, just following up on '+row['request']+'. Could you send an update?')
        db.execute('UPDATE waiting SET draft=? WHERE id=?',(body,ident))
    return {'recipient':row['recipient'],'thread':row['thread'],'body':body,'style':style[0] if style else '',
            'status':'draft — review and send in the source app'}


def record_request(db, request, now=None):
    signature = re.sub(r'\s+',' ',request.strip().lower())
    with db:
        db.execute('INSERT INTO request_history(signature,request,at) VALUES(?,?,?)',(signature,request,now or time.time()))


def recurring(db, now=None):
    now = now or time.time()
    return [dict(r) for r in db.execute('''SELECT signature,MIN(request) AS request,count(DISTINCT date(at,'unixepoch','localtime')) AS days
        FROM request_history WHERE at>=? GROUP BY signature HAVING days>=3''',(now-14*86400,))]


def propose_automation(db, title, interval=86400, trigger='schedule'):
    if trigger not in ('schedule','meeting_end','missing_reply') or not 900 <= interval <= 31*86400:
        raise ValueError('Invalid trigger or interval')
    ident = hashlib.sha256((title+trigger).encode()).hexdigest()[:24]
    with db:
        db.execute("INSERT OR IGNORE INTO automation VALUES(?,?,?,?,?,'proposed','local_digest')",
                   (ident,title,trigger,interval,time.time()))
    return {'id':ident,'trigger':trigger,'destination':'Paco local inbox','action':'Read-only task digest',
            'interval_seconds':interval,'estimated_savings':'Not measured; review trial first'}


def run_automations(db, now=None, trial=None, event='schedule'):
    now = now or time.time()
    results = []
    with db:
        for row in list(db.execute('SELECT * FROM automation')):
            if trial != row['id'] and (row['status'] != 'active' or row['next_run'] > now or row['trigger'] != event):
                continue
            text = json.dumps([dict(t) for t in db.execute("SELECT id,title,state FROM task WHERE state='open' ORDER BY priority DESC LIMIT 10")])
            results.append({'id':row['id'],'result':json.loads(text)})
            if not trial:
                db.execute('INSERT OR IGNORE INTO automation_run(automation,at,result) VALUES(?,?,?)',(row['id'],row['next_run'],text))
                db.execute('UPDATE automation SET next_run=? WHERE id=?',(now+row['interval'],row['id']))
    return results


def capture(db, app, title, text, url='', private=False):
    rule = db.execute('SELECT enabled FROM capture_rule WHERE app=?',(app,)).fetchone()
    if not rule or not rule[0] or private or not title or app.lower() in ('terminal','iterm2','claude','chatgpt','codex'):
        return None
    for kind,value in db.execute('SELECT kind,value FROM exclusion'):
        target = {'app':app,'window':title,'site':url}.get(kind,'')
        if value.lower() in target.lower():
            return None
    text = re.sub(r'(?i)(?:sk-[\w-]{12,}|gh[pousr]_[\w]{16,}|bearer\s+\S+|(?:password|secret|api[_-]?key)\s*[:=]\s*\S+)', '[redacted]',text)
    with db:
        key=hashlib.sha256((app+'\0'+title+'\0'+text).encode()).hexdigest()
        return remember(db,'desktop',key,text[:12000],url,project=title)
