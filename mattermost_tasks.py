"""Validated, replay-safe task changes shared by Mattermost discovery and Paco DMs."""
import hashlib
import json
import time
from datetime import datetime

import company_sync
import workflows
import workspace
from task_contract import clean_task

FIELDS = {'title','description','priority','urgent','deadline','remind_at','estimate_minutes','assignee','tags','status','project','responsibility'}


def initialize(db):
    db.executescript('''
    CREATE TABLE IF NOT EXISTS mattermost_action(key TEXT PRIMARY KEY,task INTEGER,result TEXT);
    CREATE TABLE IF NOT EXISTS mattermost_proposal(id INTEGER PRIMARY KEY,source_key TEXT UNIQUE,
      task INTEGER,changes TEXT,snapshot TEXT,quote TEXT,status TEXT DEFAULT 'pending');
    ''')


def task(db, ident):
    import attention
    alias=attention.info(db,ident).get('duplicate_of')
    if alias:ident=alias
    value = company_sync.local_data(db,'task',ident)
    if value is None: return None
    row = db.execute('SELECT project FROM task_project WHERE task=?',(ident,)).fetchone()
    return dict(value,id=ident,project=row[0] if row else None)


def snapshot(value):
    # Reminder nudges can change due independently. A user's explicit snooze is
    # included when an action actually edits remind_at (checked separately below).
    return json.dumps({k:v for k,v in value.items() if k not in ('remind_at','source_url')},sort_keys=True)


def changes(value):
    if not isinstance(value,dict) or not value or set(value)-FIELDS:
        raise ValueError('Unsupported Mattermost task changes')
    parsed=dict(value)
    for key in ('deadline','remind_at'):
        if isinstance(parsed.get(key),str):
            if key == 'deadline':
                from task_dates import timestamp
                parsed[key] = timestamp(parsed[key])
                continue
            date=datetime.fromisoformat(parsed[key].replace('Z','+00:00'))
            if date.tzinfo is None:raise ValueError('Task dates need a timezone')
            parsed[key]=date.timestamp()
    clean=clean_task({k:v for k,v in parsed.items() if k!='project'},partial=True)
    if 'project' in parsed:
        if parsed['project'] is not None and type(parsed['project']) is not int:raise ValueError('Unknown project')
        clean['project']=parsed['project']
    if 'remind_at' in clean and clean['remind_at'] is None:raise ValueError('Specify a reminder time')
    return clean


def prepare(db, action, context, messages, account, direct=False, current_message=None):
    if not isinstance(action,dict):raise ValueError('Invalid Mattermost action')
    kind=action.get('kind','add')
    if kind not in ('add','update','approve'):raise ValueError('Unsupported Mattermost action')
    msg=next((m for m in messages if m['id']==action.get('message')),None)
    quote=action.get('quote')
    if not msg or not isinstance(quote,str) or not quote.strip() or quote not in msg['text']:
        raise ValueError('Task change lacks supporting message evidence')
    if direct and (not msg.get('mine') or msg['id']!=current_message):
        raise ValueError('Only your current direct message can request a change')
    if workflows.forgotten(db,'mattermost',account+'/'+msg['id']):return None
    if kind=='approve':
        if not direct or type(action.get('proposal')) is not int:raise ValueError('Only you can approve a proposal')
        proposal=db.execute("SELECT * FROM mattermost_proposal WHERE id=? AND status='pending'",(action['proposal'],)).fetchone()
        if not proposal:raise ValueError('That proposal is no longer pending')
        current=task(db,proposal['task'])
        if not current or snapshot(current)!=proposal['snapshot']:raise ValueError('Task changed since that proposal; ask Paco to review it again')
        fields=json.loads(proposal['changes']);ident=proposal['task'];expected=current
    else:
        fields=changes(action.get('changes') or ({'title':action.get('title'),**({'responsibility':action['responsibility']} if 'responsibility' in action else {})} if kind=='add' else {}))
        ident=None if kind=='add' else action.get('task')
        expected=None if ident is None else next((t for t in context if t['id']==ident),None)
        if kind=='update' and (type(ident) is not int or expected is None):raise ValueError('Task was not in this conversation context')
        if kind=='add' and not fields.get('title'):raise ValueError('A new task needs a title')
    if fields.get('project') is not None and not db.execute('SELECT 1 FROM project WHERE id=?',(fields['project'],)).fetchone():raise ValueError('Unknown project')
    if expected:
        current=task(db,ident)
        if not current or snapshot(current)!=snapshot(expected) or ('remind_at' in fields and current['remind_at']!=expected['remind_at']):
            raise ValueError('Task changed while Paco was reading; please try again')
    # Add identity deliberately matches the original connector's message+quote identity.
    digest=hashlib.sha256((msg['id']+'\0'+quote+((':'+json.dumps(fields,sort_keys=True)) if kind!='add' else '')).encode()).hexdigest()
    return dict(key=account+'/'+digest,kind=kind,task=ident,fields=fields,expected=expected,msg=msg,quote=quote,
                direct=direct,proposal=action.get('proposal'),suggest=kind=='update' and not direct and not msg.get('mine'))


def apply(db, item, base, account, now=None):
    """Caller holds a transaction; no commits or network calls in this function."""
    if item is None:return None
    if workflows.forgotten(db,'mattermost',account+'/'+item['msg']['id']):raise ValueError('That message has been forgotten')
    previous=db.execute('SELECT result FROM mattermost_action WHERE key=?',(item['key'],)).fetchone()
    if previous:return json.loads(previous[0])
    now=now or time.time();ident=item['task'];fields=item['fields'];expected=item['expected']
    if expected:
        current=task(db,ident)
        if not current or snapshot(current)!=snapshot(expected) or ('remind_at' in fields and current['remind_at']!=expected['remind_at']):
            raise ValueError('Task changed while Paco was reading; please try again')
    citation=account+'/'+item['msg']['id']+'/'+item['key'].rsplit('/',1)[-1]
    if item['suggest']:
        pid=db.execute('INSERT INTO mattermost_proposal(source_key,task,changes,snapshot,quote) VALUES(?,?,?,?,?)',
                       (citation,ident,json.dumps(fields),snapshot(expected),item['quote'])).lastrowid
        result=dict(kind='suggested',proposal=pid,task=ident,title=expected['title'],changes=fields)
    else:
        editable={k:v for k,v in fields.items() if k not in ('status','remind_at')}
        ident=workspace.edit_task(db,dict(id=ident,changes=editable),commit=False)['id']
        if 'status' in fields:
            db.execute('UPDATE task SET state=?,nudges=0 WHERE id=?',(fields['status'],ident))
            db.execute('INSERT INTO task_override(task,state) VALUES(?,?) ON CONFLICT(task) DO UPDATE SET state=excluded.state',(ident,fields['status']))
        if 'remind_at' in fields:
            db.execute('UPDATE task SET due=?,nudges=0 WHERE id=?',(fields['remind_at'],ident))
        if item['kind']=='approve':db.execute("UPDATE mattermost_proposal SET status='accepted' WHERE id=?",(item['proposal'],))
        import attention
        if item['kind']=='add' and not item.get('direct'):
            attention.candidate(db,ident,'mattermost',kind=fields.get('responsibility','execute'))
        elif item.get('direct') and item['kind']=='add':
            attention.record(db,ident,'accepted','Explicit request in your private DM','direct',fields.get('responsibility','execute'))
        result=dict(kind='created' if item['kind']=='add' else 'updated',task=ident,title=task(db,ident)['title'],changes=fields)
        workflows.changed(db,'task.'+result['kind'],{'id':ident,'source':'mattermost'})
    citation=account+'/'+item['msg']['id']+'/'+item['key'].rsplit('/',1)[-1]
    workflows.remember(db,'mattermost',citation,item['quote'],base+'/_redirect/pl/'+item['msg']['id'],item['msg']['sender'],at=item['msg']['at'],task=ident)
    db.execute('INSERT INTO mattermost_action VALUES(?,?,?)',(item['key'],ident,json.dumps(result)))
    return result


def describe(result):
    label='Suggested change' if result['kind']=='suggested' else 'Created' if result['kind']=='created' else 'Updated'
    values=[]
    for key,value in result['changes'].items():
        if key=='title':continue
        if key in ('deadline','remind_at') and value is not None:value=datetime.fromtimestamp(value).astimezone().isoformat(timespec='minutes')
        values.append(key.replace('_',' ')+': '+str(value))
    return f"{label} #{result['task']}: {result['title']}"+(' — '+', '.join(values) if values else '')
