"""Local cache of shared, revisioned project briefs. Personal tasks stay account-owned."""
import json
import time
import uuid
import attention
import company_sync
import tagging
from project_brain_contract import clean_brain


def initialize(db):
    db.executescript('''CREATE TABLE IF NOT EXISTS project_brain(
        project INTEGER PRIMARY KEY,shared_id TEXT UNIQUE,revision INTEGER NOT NULL DEFAULT 0,
        payload TEXT NOT NULL,updated REAL NOT NULL,actor TEXT NOT NULL DEFAULT '');''')


def get(db,project):
    row=db.execute('SELECT * FROM project_brain WHERE project=?',(project,)).fetchone()
    if row:return dict(project=project,id=row['shared_id'],revision=row['revision'],data=json.loads(row['payload']),updated=row['updated'],actor=row['actor'])
    p=db.execute('SELECT name,area,hints FROM project WHERE id=?',(project,)).fetchone()
    if not p:raise ValueError('Project not found')
    return dict(project=project,id=None,revision=0,data=clean_brain(dict(p)),updated=None,actor='')


def all_briefs(db):
    return [get(db,p['id']) for p in tagging.projects(db) if p['user_created'] or db.execute('SELECT 1 FROM project_brain WHERE project=?',(p['id'],)).fetchone()]


def transport(db):
    import keyring
    account=company_sync.setting(db,'account')
    if not account:raise ValueError('Connect your company account to edit shared project briefs')
    token=keyring.get_password('paco.company',account['url']+'|'+account['user'])
    if not token:raise ValueError('Reconnect your company account')
    return lambda path,data=None:company_sync.request(account['url'],path,data,token)


def apply(db,item,project=None):
    data=clean_brain(item['data'])
    linked=db.execute('SELECT project FROM project_brain WHERE shared_id=?',(item['id'],)).fetchone()
    if linked:project=linked[0]
    if project is None:
        matching=db.execute('SELECT id FROM project WHERE name=?',(data['name'],)).fetchone()
        project=matching[0] if matching else None
    # A conflicting local name must never merge two existing shared projects.
    if project is not None:
        old=db.execute('SELECT shared_id FROM project_brain WHERE project=?',(project,)).fetchone()
        if old and old[0] and old[0]!=item['id']:raise ValueError('Two shared projects use the same local name; rename one before syncing')
    with db:
        if project is None:project=db.execute('INSERT INTO project(name,area,hints) VALUES(?,?,?)',(data['name'],data['area'],data['hints'])).lastrowid
        else:db.execute('UPDATE project SET name=?,area=?,hints=? WHERE id=?',(data['name'],data['area'],data['hints'],project))
        db.execute("INSERT OR REPLACE INTO catalog_area VALUES(?,'manual','Shared project brief')",(project,))
        db.execute('INSERT OR REPLACE INTO project_brain VALUES(?,?,?,?,?,?)',(project,item['id'],item['revision'],json.dumps(data),item['updated'],item['actor']))
    return project


def sync(db,call=None):
    if call is None and not company_sync.setting(db,'account'):return
    call=call or transport(db)
    value=call('/api/project-brains')
    for item in value['items']:
        previous=db.execute('SELECT revision FROM project_brain WHERE shared_id=?',(item['id'],)).fetchone()
        if not previous or previous[0]!=item['revision']:apply(db,item)
    with db:
        company_sync.save(db,'brain_people',value['people']);company_sync.save(db,'brain_sync',time.time());company_sync.save(db,'brain_error',None)


def save(db,data,project=None,revision=0,request_id=None,call=None):
    data=clean_brain(data)
    current=get(db,project) if project is not None else None
    if current and current['revision']!=revision:raise ValueError('This project changed. Reopen its brief before saving; your draft has not been applied.')
    call=call or transport(db)
    result=call('/api/project-brains',dict(id=current['id'] if current else None,revision=revision,data=data,request_id=request_id or str(uuid.uuid4())))
    return get(db,apply(db,result,project))


def context(db,project=None):
    briefs=[get(db,project)] if project else all_briefs(db)
    result=[]
    for brief in briefs:
        data=brief['data']
        mine=[r for r in data['roles'] if any(attention.mine(db,x) for x in [r['person']]+r['aliases'])]
        result.append(dict(project=brief['project'],shared_id=brief['id'],revision=brief['revision'],**data,my_roles=mine))
    return result
