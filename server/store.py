"""Small internal task store. Account isolation is enforced in every data operation."""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time
import uuid
from contextlib import contextmanager
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError,InvalidHashError
from task_contract import clean_task,clean_project,identifier

PASSWORDS=PasswordHasher(time_cost=3,memory_cost=65536,parallelism=2)
DUMMY=PASSWORDS.hash('not-a-user-password')

class Conflict(ValueError):pass

class Store:
    def __init__(self,path):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.db() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY,username TEXT UNIQUE COLLATE NOCASE,password_hash TEXT NOT NULL,active INTEGER NOT NULL DEFAULT 1);
            CREATE TABLE IF NOT EXISTS entities(owner TEXT NOT NULL,kind TEXT NOT NULL,id TEXT NOT NULL,payload TEXT NOT NULL,revision INTEGER NOT NULL,updated REAL NOT NULL,PRIMARY KEY(owner,kind,id),FOREIGN KEY(owner) REFERENCES users(id));
            CREATE TABLE IF NOT EXISTS changes(seq INTEGER PRIMARY KEY AUTOINCREMENT,owner TEXT NOT NULL,kind TEXT NOT NULL,id TEXT NOT NULL,revision INTEGER NOT NULL,at REAL NOT NULL);
            CREATE INDEX IF NOT EXISTS change_owner ON changes(owner,seq);
            CREATE TABLE IF NOT EXISTS operations(owner TEXT NOT NULL,key TEXT NOT NULL,payload_hash TEXT NOT NULL,result TEXT NOT NULL,at REAL NOT NULL,PRIMARY KEY(owner,key));
            CREATE TABLE IF NOT EXISTS oauth_clients(id TEXT PRIMARY KEY,payload TEXT NOT NULL,created REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS oauth_pending(id TEXT PRIMARY KEY,payload TEXT NOT NULL,expires REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS oauth_codes(hash TEXT PRIMARY KEY,payload TEXT NOT NULL,expires REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS tokens(hash TEXT PRIMARY KEY,kind TEXT NOT NULL,payload TEXT NOT NULL,family TEXT NOT NULL,expires REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS rate_limits(key TEXT PRIMARY KEY,count INTEGER NOT NULL,expires REAL NOT NULL);
            ''')
        from server import brains
        with self.db() as db:brains.initialize(db)
        self.path.chmod(0o600)
    @contextmanager
    def db(self):
        db=sqlite3.connect(self.path,timeout=15);db.row_factory=sqlite3.Row
        db.execute('PRAGMA journal_mode=WAL');db.execute('PRAGMA foreign_keys=ON');db.execute('PRAGMA secure_delete=ON')
        try:
            with db:yield db
        finally:db.close()
    def create_user(self,username,password):
        if not username or len(username)>80 or len(password)<8:raise ValueError('Username and a password of at least eight characters required')
        with self.db() as db:
            ident=str(uuid.uuid4());db.execute('INSERT INTO users(id,username,password_hash) VALUES(?,?,?)',(ident,username,PASSWORDS.hash(password)))
            from server.brains import COMPANY
            db.execute('INSERT INTO workspace_member VALUES(?,?)',(COMPANY,ident))
            return ident
    def authenticate(self,username,password):
        with self.db() as db:r=db.execute('SELECT * FROM users WHERE username=? AND active=1',(username,)).fetchone()
        try:ok=PASSWORDS.verify(r['password_hash'] if r else DUMMY,password)
        except (VerificationError,InvalidHashError):ok=False
        return dict(r) if r and ok else None
    def active(self,owner):
        with self.db() as db:return db.execute('SELECT id,username FROM users WHERE id=? AND active=1',(owner,)).fetchone()
    def limit(self,key,maximum=20,seconds=900):
        now=time.time()
        with self.db() as db:
            db.execute('DELETE FROM rate_limits WHERE expires<?',(now,))
            db.execute('INSERT INTO rate_limits VALUES(?,1,?) ON CONFLICT(key) DO UPDATE SET count=count+1',(key,now+seconds))
            return db.execute('SELECT count FROM rate_limits WHERE key=?',(key,)).fetchone()[0]<=maximum
    @staticmethod
    def row(row):
        return dict(id=row['id'],kind=row['kind'],revision=row['revision'],updated=row['updated'],data=clean_task(json.loads(row['payload'])) if row['kind']=='task' else json.loads(row['payload'])) if row else None
    def get(self,owner,kind,ident):
        with self.db() as db:return self.row(db.execute('SELECT * FROM entities WHERE owner=? AND kind=? AND id=?',(owner,kind,identifier(ident))).fetchone())
    def listing(self,owner,kind,after='',limit=100):
        if kind not in ('task','project'):raise ValueError('Invalid kind')
        with self.db() as db:
            rows=db.execute('SELECT * FROM entities WHERE owner=? AND kind=? AND id>? ORDER BY id LIMIT ?',(owner,kind,after,min(max(int(limit),1),200)+1)).fetchall()
            more=len(rows)>min(max(int(limit),1),200);rows=rows[:min(max(int(limit),1),200)]
            return {'items':[self.row(r) for r in rows],'next':rows[-1]['id'] if more else None}
    def changes(self,owner,after=0):
        with self.db() as db:
            rows=db.execute('SELECT * FROM changes WHERE owner=? AND seq>? ORDER BY seq LIMIT 200',(owner,int(after))).fetchall()
            items=[self.row(db.execute('SELECT * FROM entities WHERE owner=? AND kind=? AND id=?',(owner,r['kind'],r['id'])).fetchone()) for r in rows]
            return {'items':items,'cursor':rows[-1]['seq'] if rows else int(after),'more':len(rows)==200}
    def mutate(self,owner,operations,key,*,intent=None):
        if not isinstance(key,str) or not 8<=len(key)<=160:raise ValueError('An idempotency key is required')
        if not isinstance(operations,list) or not 1<=len(operations)<=100:raise ValueError('Use 1–100 changes')
        digest=hashlib.sha256(json.dumps(operations if intent is None else intent,sort_keys=True).encode()).hexdigest()
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            old=db.execute('SELECT * FROM operations WHERE owner=? AND key=?',(owner,key)).fetchone()
            if old:
                if old['payload_hash']!=digest:raise Conflict('Idempotency key already used for different changes')
                return json.loads(old['result'])
            if not db.execute('SELECT 1 FROM users WHERE id=? AND active=1',(owner,)).fetchone():raise PermissionError('Account disabled')
            result=[];seen=set()
            for op in operations:
                if not isinstance(op,dict) or set(op)-{'kind','id','revision','data'}:raise ValueError('Invalid change')
                kind=op['kind'];ident=identifier(op['id']);version=op.get('revision',0)
                if type(version) is not int or version<0 or (kind,ident) in seen:raise ValueError('Invalid or duplicate revision')
                seen.add((kind,ident))
                if kind not in ('task','project'):raise ValueError('Only tasks and projects may be stored remotely')
                data=clean_task(op['data']) if kind=='task' else clean_project(op['data'])
                current=db.execute('SELECT revision FROM entities WHERE owner=? AND kind=? AND id=?',(owner,kind,ident)).fetchone()
                if (current['revision'] if current else 0)!=version:raise Conflict('This record changed; refresh before editing')
                now=time.time();revision=version+1
                db.execute('INSERT INTO entities VALUES(?,?,?,?,?,?) ON CONFLICT(owner,kind,id) DO UPDATE SET payload=excluded.payload,revision=excluded.revision,updated=excluded.updated',(owner,kind,ident,json.dumps(data),revision,now))
                db.execute('INSERT INTO changes(owner,kind,id,revision,at) VALUES(?,?,?,?,?)',(owner,kind,ident,revision,now))
                result.append(dict(kind=kind,id=ident,data=data,revision=revision,updated=now))
            # Validate all references after writing the batch, allowing forward references.
            tasks={r['id']:json.loads(r['payload']) for r in db.execute("SELECT id,payload FROM entities WHERE owner=? AND kind='task'",(owner,))}
            projects={r[0] for r in db.execute("SELECT id FROM entities WHERE owner=? AND kind='project'",(owner,))}
            for ident,data in tasks.items():
                if data['project_id'] and data['project_id'] not in projects:raise ValueError('Project belongs to another account or does not exist')
                for ref in data['dependencies']+([data['parent_id']] if data['parent_id'] else [])+([data['duplicate_of']] if data.get('duplicate_of') else []):
                    if ref==ident or ref not in tasks:raise ValueError('Invalid task reference')
            def cycles(field):
                visiting=set();done=set()
                def visit(ident):
                    if ident in visiting:raise ValueError('Task relationships cannot contain cycles')
                    if ident in done:return
                    visiting.add(ident)
                    refs=tasks[ident].get(field) if field=='dependencies' else ([tasks[ident].get(field)] if tasks[ident].get(field) else [])
                    for ref in refs:visit(ref)
                    visiting.remove(ident);done.add(ident)
                for ident in tasks:visit(ident)
            cycles('dependencies');cycles('parent_id');cycles('duplicate_of')
            value={'items':result}
            db.execute('INSERT INTO operations VALUES(?,?,?,?,?)',(owner,key,digest,json.dumps(value),time.time()))
            return value
    def prune(self):
        with self.db() as db:
            for table in ('oauth_pending','oauth_codes','tokens','rate_limits'):db.execute(f'DELETE FROM {table} WHERE expires<?',(time.time(),))
            db.execute('DELETE FROM operations WHERE at<?',(time.time()-90*86400,))
            db.execute("DELETE FROM oauth_clients WHERE created<? AND id NOT IN (SELECT json_extract(payload,'$.client_id') FROM tokens) AND id NOT IN (SELECT json_extract(payload,'$.client_id') FROM oauth_pending)",(time.time()-86400,))
    def backup(self,directory):
        directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
        path=directory/(time.strftime('%Y-%m-%d')+'.sqlite3')
        with self.db() as source,sqlite3.connect(path) as dest:source.backup(dest)
        path.chmod(0o600)
        for old in sorted(directory.glob('*.sqlite3'))[:-7]:old.unlink()
        return path
