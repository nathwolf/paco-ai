"""Task-only synchronization. Private tables are never serialized or uploaded."""
from contextlib import closing
import json
import hashlib
import threading
import time
import urllib.request
import urllib.error
import uuid
from urllib.parse import urlsplit
from task_contract import clean_task,clean_project

LOCK=threading.Lock()


def initialize(db):
    db.executescript('''
    CREATE TABLE IF NOT EXISTS company_link(kind TEXT NOT NULL,local INTEGER NOT NULL,remote TEXT NOT NULL UNIQUE,revision INTEGER NOT NULL DEFAULT 0,base TEXT,PRIMARY KEY(kind,local));
    CREATE TABLE IF NOT EXISTS company_outbox(id TEXT PRIMARY KEY,payload TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS company_task_fields(task INTEGER PRIMARY KEY,source_url TEXT NOT NULL DEFAULT '');
    CREATE TABLE IF NOT EXISTS company_conflict(remote TEXT PRIMARY KEY,kind TEXT NOT NULL,payload TEXT NOT NULL,fields TEXT NOT NULL);
    ''')
    with db:
        for row in db.execute("SELECT local,base FROM company_link WHERE kind='task' AND base IS NOT NULL").fetchall():
            db.execute("UPDATE company_link SET base=? WHERE kind='task' AND local=?",(json.dumps(clean_task(json.loads(row['base']))),row['local']))


def setting(db,key,default=None):
    row=db.execute('SELECT value FROM preference WHERE key=?',('company_'+key,)).fetchone()
    return json.loads(row[0]) if row else default


def save(db,key,value):db.execute('INSERT OR REPLACE INTO preference VALUES(?,?)',('company_'+key,json.dumps(value)))


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None


def request(base,path,data=None,token=None):
    u=urlsplit(base)
    if u.scheme!='https' or not u.hostname or u.username or u.password or u.query or u.fragment:raise ValueError('Use the HTTPS Paco company address')
    headers={'Content-Type':'application/json'}
    if token:headers['Authorization']='Bearer '+token
    req=urllib.request.Request(base.rstrip('/')+path,None if data is None else json.dumps(data).encode(),headers)
    try:
        with urllib.request.build_opener(NoRedirect).open(req,timeout=20) as response:return json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code==409:raise Conflict('Remote record changed') from None
        if exc.code==401:raise ValueError('Company sign-in expired; reconnect in Settings') from None
        raise ValueError('Company service rejected the request (HTTP '+str(exc.code)+')') from None


class Conflict(ValueError):pass


def connect(db,base,username,password):
    import keyring
    value=request(base,'/api/login',{'username':username,'password':password})
    account={'url':base.rstrip('/'),'user':value['user']['id'],'username':value['user']['username'],'expires':time.time()+value['expires_in']}
    prior=setting(db,'binding')
    if prior and prior['user']!=account['user']:raise ValueError('This Mac is linked to another task account. Use a separate macOS account/database to avoid mixing company data.')
    if prior and prior['url']!=account['url']:
        # An explicit sign-in to the same account after a tunnel/domain migration.
        try:keyring.delete_password('paco.company',prior['url']+'|'+prior['user'])
        except keyring.errors.PasswordDeleteError:pass
    keyring.set_password('paco.company',account['url']+'|'+account['user'],value['token'])
    with db:save(db,'account',account);save(db,'binding',{'url':account['url'],'user':account['user']});save(db,'error',None)
    return {'username':account['username'],'url':account['url']}


def disconnect(db):
    import keyring
    account=setting(db,'account')
    if account:
        token=keyring.get_password('paco.company',account['url']+'|'+account['user'])
        if token:
            try:request(account['url'],'/api/logout',{},token)
            except (ValueError,OSError):pass  # Offline disconnect still removes this Mac's credential.
        try:keyring.delete_password('paco.company',account['url']+'|'+account['user'])
        except keyring.errors.PasswordDeleteError:pass
    with db:save(db,'account',None)


def status(db):
    account=setting(db,'account')
    return {'account':account,'last_sync':setting(db,'last_sync'),'error':setting(db,'error'),
            'pending':db.execute('SELECT count(*) FROM company_outbox').fetchone()[0],
            'conflicts':[{'id':r['remote'],'kind':r['kind'],'fields':json.loads(r['fields'])} for r in db.execute('SELECT * FROM company_conflict')]}


def ensure_links(db):
    with db:
        for kind,table in (('project','project'),('task','task')):
            for row in db.execute('SELECT id FROM '+table).fetchall():
                db.execute('INSERT OR IGNORE INTO company_link(kind,local,remote) VALUES(?,?,?)',(kind,row[0],str(uuid.uuid4())))


def remote_id(db,kind,local):
    if local is None:return None
    row=db.execute('SELECT remote FROM company_link WHERE kind=? AND local=?',(kind,local)).fetchone()
    return row[0] if row else None


def local_data(db,kind,local):
    if kind=='project':
        r=db.execute('SELECT name,area,hints FROM project WHERE id=?',(local,)).fetchone()
        return dict(r) if r else None
    r=db.execute('SELECT * FROM task WHERE id=?',(local,)).fetchone()
    if not r:return None
    detail=db.execute('SELECT * FROM details WHERE task=?',(local,)).fetchone()
    extra=db.execute('SELECT * FROM task_extra WHERE task=?',(local,)).fetchone()
    project=db.execute('SELECT project FROM task_project WHERE task=?',(local,)).fetchone()
    owner=db.execute('SELECT owner FROM ownership WHERE task=?',(local,)).fetchone()
    urgent=db.execute('SELECT critical FROM urgency WHERE task=?',(local,)).fetchone()
    import links
    link=links.for_task(db,local)
    source=db.execute('SELECT source_url FROM company_task_fields WHERE task=?',(local,)).fetchone()
    # Explicit allowlist: no evidence, transcript, reply text, summary, activity or config.
    import attention
    admission=attention.info(db,local)
    return clean_task(dict(intake_status=admission['status'],responsibility=admission['kind'],duplicate_of=remote_id(db,'task',admission['duplicate_of']),title=r['title'],description=extra['description'] if extra else '',
        status=r['state'] if r['state'] in ('open','done','blocked','archived','cancelled') else 'open' if r['state']=='focus' else 'archived',
        priority=r['priority'],urgent=bool(urgent and urgent[0]),project_id=remote_id(db,'project',project[0]) if project else None,
        assignee=owner[0] if owner else '',deadline=detail['deadline'] if detail else None,remind_at=r['due'],
        estimate_minutes=(detail['minutes'] or 30) if detail else 30,goal=(detail['goal'] or '') if detail else '',
        parent_id=remote_id(db,'task',extra['parent']) if extra else None,
        dependencies=[remote_id(db,'task',x[0]) for x in db.execute('SELECT prerequisite FROM dependency WHERE task=?',(local,)) if remote_id(db,'task',x[0])],
        tags=json.loads(extra['tags']) if extra else [],source_url=link['url'] if link and link['url'].startswith(('https://','http://')) else source[0] if source else ''))


def merge(base,local,remote):
    if base is None:return remote,[]
    value={};conflicts=[]
    for key in set(base)|set(local)|set(remote):
        before=base.get(key);ours=local.get(key);theirs=remote.get(key)
        if ours==before:value[key]=theirs
        elif theirs==before or ours==theirs:value[key]=ours
        else:conflicts.append(key);value[key]=ours
    return value,conflicts


def apply_local(db,kind,local,data):
    if kind=='project':
        data=clean_project(data)
        db.execute('UPDATE project SET name=?,area=?,hints=? WHERE id=?',(data['name'],data['area'],data['hints'],local));return
    data=clean_task(data)
    def lid(remote,kind='task'):
        if not remote:return None
        row=db.execute('SELECT local FROM company_link WHERE remote=? AND kind=?',(remote,kind)).fetchone()
        if not row:raise ValueError('Related record not synchronized yet')
        return row[0]
    import attention
    old_admission=attention.info(db,local)
    attention.record(db,local,data['intake_status'],old_admission['reason'],old_admission['source'],data['responsibility'],lid(data['duplicate_of']))
    current=db.execute('SELECT state,due FROM task WHERE id=?',(local,)).fetchone()
    due=data['remind_at'] if data['remind_at'] is not None else current['due']
    # Preserve a local focus session on an unrelated edit, but rescheduling an
    # open task is a reminder change, not a multi-day extension of that session.
    state='focus' if current['state']=='focus' and data['status']=='open' and due==current['due'] else data['status']
    db.execute('UPDATE task SET title=?,priority=?,state=?,due=? WHERE id=?',(data['title'],data['priority'],state,due,local))
    db.execute('INSERT OR REPLACE INTO details VALUES(?,?,?,?)',(local,data['goal'],data['estimate_minutes'],data['deadline']))
    db.execute('INSERT OR REPLACE INTO urgency VALUES(?,?)',(local,data['urgent']))
    db.execute('INSERT INTO ownership VALUES(?,?,?) ON CONFLICT(task) DO UPDATE SET owner=excluded.owner',(local,data['assignee'],''))
    db.execute('INSERT OR REPLACE INTO task_extra VALUES(?,?,?,?)',(local,data['description'],lid(data['parent_id']),json.dumps(data['tags'])))
    project = lid(data['project_id'], 'project')
    previous = db.execute('SELECT project,how FROM task_project WHERE task=?', (local,)).fetchone()
    # A round trip or an unrelated remote edit must not freeze automatic classification.
    if (previous and previous['project'] != project) or (not previous and project is not None):
        db.execute('INSERT OR REPLACE INTO task_project VALUES(?,?,?)', (local,project,'manual'))
    db.execute('INSERT OR REPLACE INTO company_task_fields VALUES(?,?)',(local,data['source_url']))
    db.execute('DELETE FROM dependency WHERE task=?',(local,))
    db.executemany('INSERT INTO dependency VALUES(?,?)',[(local,lid(ref)) for ref in data['dependencies']])
    # Remote edits are explicit user corrections, so later tracker sync cannot undo them.
    db.execute('INSERT INTO task_override(task,title,state) VALUES(?,?,?) ON CONFLICT(task) DO UPDATE SET title=excluded.title,state=excluded.state',(local,data['title'],state))


def pull(db,call):
    cursor=setting(db,'cursor',0);items={}
    while True:
        page=call('/api/changes?after='+str(cursor));cursor=page['cursor']
        for item in page['items']:items[(item['kind'],item['id'])]=item
        if not page['more']:break
    with db:
        # Reserve every local ID before resolving forward dependencies.
        for item in sorted(items.values(),key=lambda x:x['kind']!='project'):
            if db.execute('SELECT 1 FROM company_link WHERE remote=?',(item['id'],)).fetchone():continue
            if item['kind']=='project':
                d=clean_project(item['data']);existing=db.execute('SELECT id FROM project WHERE name=?',(d['name'],)).fetchone()
                if existing:
                    linked=db.execute('SELECT revision FROM company_link WHERE kind=? AND local=?',('project',existing[0])).fetchone()
                    if linked and linked[0]>0:raise ValueError('Duplicate project names need review before sync')
                    local=existing[0];db.execute("DELETE FROM company_link WHERE kind='project' AND local=?",(local,))
                else:local=db.execute('INSERT INTO project(name,area,hints) VALUES(?,?,?)',(d['name'],d['area'],d['hints'])).lastrowid
            else:local=db.execute("INSERT INTO task(title,priority,state,due) VALUES(?,3,'open',?)",(clean_task(item['data'])['title'],time.time())).lastrowid
            db.execute('INSERT INTO company_link(kind,local,remote) VALUES(?,?,?)',(item['kind'],local,item['id']))
        for item in sorted(items.values(),key=lambda x:x['kind']!='project'):
            row=db.execute('SELECT * FROM company_link WHERE remote=?',(item['id'],)).fetchone()
            if item['revision']<=row['revision']:continue
            base=json.loads(row['base']) if row['base'] else None
            ours=local_data(db,item['kind'],row['local'])
            value,conflicts=merge(base,ours,item['data'])
            if conflicts:
                db.execute('INSERT OR REPLACE INTO company_conflict VALUES(?,?,?,?)',(item['id'],item['kind'],json.dumps(item),json.dumps(conflicts)));continue
            apply_local(db,item['kind'],row['local'],value)
            db.execute('UPDATE company_link SET revision=?,base=? WHERE remote=?',(item['revision'],json.dumps(item['data']),item['id']))
        save(db,'cursor',cursor)


def sync(db,transport=None):
    account=setting(db,'account')
    if not account:return
    if not LOCK.acquire(False):return
    try:
        if transport:call=transport
        else:
            import keyring
            token=keyring.get_password('paco.company',account['url']+'|'+account['user'])
            if not token:raise ValueError('Reconnect your company account in Settings')
            call=lambda path,data=None:request(account['url'],path,data,token)
        def flush():
            for pending in db.execute('SELECT * FROM company_outbox').fetchall():
                try:result=call('/api/apply',{'operations':json.loads(pending['payload']),'request_id':pending['id']})
                except Conflict:
                    # Nothing in the atomic batch was applied. Fetch current versions before retrying.
                    with db:db.execute('DELETE FROM company_outbox WHERE id=?',(pending['id'],))
                    return False
                with db:
                    for item in result['items']:db.execute('UPDATE company_link SET revision=?,base=? WHERE remote=?',(item['revision'],json.dumps(item['data']),item['id']))
                    db.execute('DELETE FROM company_outbox WHERE id=?',(pending['id'],))
            return True
        flush();pull(db,call);ensure_links(db)
        pending=[]
        for row in db.execute('SELECT * FROM company_link ORDER BY kind DESC,local'):
            if db.execute('SELECT 1 FROM company_conflict WHERE remote=?',(row['remote'],)).fetchone():continue
            value=local_data(db,row['kind'],row['local'])
            if value is None:continue  # Project deletion is local-only until explicit shared deletion exists.
            if not row['base'] or value!=json.loads(row['base']):pending.append(dict(kind=row['kind'],id=row['remote'],revision=row['revision'],data=value))
        remaining={item['id']:item for item in pending}
        while remaining:
            batch={}
            def related(ident,found):
                if ident in found or ident not in remaining:return
                item=remaining[ident];found[ident]=item
                if item['kind']=='task':
                    data=item['data']
                    for ref in [data['project_id'],data['parent_id'],data.get('duplicate_of')]+data['dependencies']:
                        if ref:related(ref,found)
            for ident in remaining:
                group={};related(ident,group)
                if len(set(batch)|set(group))<=100:batch.update(group)
            if not batch:raise ValueError('A connected group exceeds 100 records; split this plan before syncing')
            with db:db.execute('INSERT INTO company_outbox VALUES(?,?)',(str(uuid.uuid4()),json.dumps(list(batch.values()))))
            if not flush():
                pull(db,call);break
            for ident in batch:remaining.pop(ident)
        with db:save(db,'last_sync',time.time());save(db,'error',None)
    except Exception as exc:
        with db:save(db,'error',str(exc) if isinstance(exc,ValueError) else 'Company service unavailable; local work is kept for retry')
    finally:LOCK.release()


def resolve(db,remote,choice):
    if choice not in ('local','remote'):raise ValueError('Choose local or remote')
    row=db.execute('SELECT * FROM company_conflict WHERE remote=?',(remote,)).fetchone()
    if not row:raise ValueError('Conflict not found')
    item=json.loads(row['payload']);link=db.execute('SELECT * FROM company_link WHERE remote=?',(remote,)).fetchone()
    with db:
        if choice=='remote':apply_local(db,item['kind'],link['local'],item['data'])
        db.execute('UPDATE company_link SET revision=?,base=? WHERE remote=?',(item['revision'],json.dumps(item['data']),remote))
        db.execute('DELETE FROM company_conflict WHERE remote=?',(remote,))
