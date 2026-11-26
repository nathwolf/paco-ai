"""Shared briefs use workspace membership, not ownership of personal task records."""
import hashlib
import json
import time
import uuid
from project_brain_contract import clean_brain

COMPANY='internal-company'


def initialize(db):
    db.executescript('''CREATE TABLE IF NOT EXISTS workspace(id TEXT PRIMARY KEY,name TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS workspace_member(workspace TEXT,user TEXT,PRIMARY KEY(workspace,user));
    CREATE TABLE IF NOT EXISTS shared_brain(workspace TEXT,id TEXT PRIMARY KEY,payload TEXT NOT NULL,revision INTEGER NOT NULL,updated REAL NOT NULL,actor TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS brain_audit(id INTEGER PRIMARY KEY,workspace TEXT,brain TEXT,revision INTEGER,actor TEXT,at REAL,payload TEXT);
    CREATE TABLE IF NOT EXISTS brain_request(actor TEXT,key TEXT,digest TEXT,result TEXT,PRIMARY KEY(actor,key));''')
    created=db.execute('INSERT OR IGNORE INTO workspace VALUES(?,?)',(COMPANY,'Company')).rowcount
    # Existing and manually provisioned accounts belong to this internal deployment.
    if created:db.execute('INSERT OR IGNORE INTO workspace_member SELECT ?,id FROM users',(COMPANY,))


def authorized(db,actor,workspace):
    if not db.execute('SELECT 1 FROM workspace_member m JOIN users u ON u.id=m.user WHERE m.workspace=? AND m.user=? AND u.active=1',(workspace,actor)).fetchone():
        raise PermissionError('Workspace membership required')


def row(r):
    return dict(id=r['id'],workspace=r['workspace'],data=json.loads(r['payload']),revision=r['revision'],updated=r['updated'],actor=r['actor'])


def listing(store,actor,workspace=COMPANY):
    with store.db() as db:
        authorized(db,actor,workspace)
        return dict(workspace=workspace,items=[row(r) for r in db.execute('SELECT * FROM shared_brain WHERE workspace=? ORDER BY id',(workspace,))],
                    people=[dict(r) for r in db.execute('SELECT u.id,u.username FROM users u JOIN workspace_member m ON m.user=u.id WHERE m.workspace=? AND u.active=1 ORDER BY u.username',(workspace,))])


def save(store,actor,data,revision,request_id,ident=None,workspace=COMPANY):
    from server.store import Conflict
    if type(revision) is not int or revision<0:raise ValueError('A valid revision is required')
    if not isinstance(request_id,str) or not 8<=len(request_id)<=160:raise ValueError('A stable request ID is required')
    data=clean_brain(data)
    ident=str(uuid.UUID(ident)) if ident else str(uuid.uuid5(uuid.UUID(actor),'brain:'+request_id))
    digest=hashlib.sha256(json.dumps([workspace,ident,revision,data],sort_keys=True).encode()).hexdigest()
    with store.db() as db:
        db.execute('BEGIN IMMEDIATE');authorized(db,actor,workspace)
        prior=db.execute('SELECT digest,result FROM brain_request WHERE actor=? AND key=?',(actor,request_id)).fetchone()
        if prior:
            if prior['digest']!=digest:raise Conflict('Request ID reused for a different edit')
            return json.loads(prior['result'])
        old=db.execute('SELECT * FROM shared_brain WHERE id=?',(ident,)).fetchone()
        if old and old['workspace']!=workspace:raise PermissionError('Project belongs to another workspace')
        if (old['revision'] if old else 0)!=revision:raise Conflict('Project changed. Refresh its brief before editing again; your draft has not been applied.')
        if any(json.loads(r['payload'])['name'].casefold()==data['name'].casefold() for r in db.execute('SELECT payload FROM shared_brain WHERE workspace=? AND id!=?',(workspace,ident))):raise ValueError('A shared project with that name already exists')
        now=time.time();payload=json.dumps(data)
        db.execute('INSERT INTO shared_brain VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload,revision=excluded.revision,updated=excluded.updated,actor=excluded.actor',(workspace,ident,payload,revision+1,now,actor))
        db.execute('INSERT INTO brain_audit(workspace,brain,revision,actor,at,payload) VALUES(?,?,?,?,?,?)',(workspace,ident,revision+1,actor,now,payload))
        result=row(db.execute('SELECT * FROM shared_brain WHERE id=?',(ident,)).fetchone())
        db.execute('INSERT INTO brain_request VALUES(?,?,?,?)',(actor,request_id,digest,json.dumps(result)))
        return result
