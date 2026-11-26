"""Explicit local-agent connections and restart-safe, isolated work sessions."""
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import threading
import time
import uuid

RUNNING = {}
ACTIVE = set()
LOCK = threading.Lock()


def initialize(db):
    db.executescript('''
    CREATE TABLE IF NOT EXISTS agent_connection(provider TEXT PRIMARY KEY,executable TEXT,workspace TEXT,enabled INTEGER);
    CREATE TABLE IF NOT EXISTS agent_session(id TEXT PRIMARY KEY,provider TEXT,workspace TEXT,worktree TEXT,
      remote_id TEXT,status TEXT,brief TEXT,result TEXT,created REAL);
    CREATE TABLE IF NOT EXISTS agent_event(id INTEGER PRIMARY KEY,session TEXT,at REAL,kind TEXT,text TEXT);
    CREATE TABLE IF NOT EXISTS agent_process(session TEXT PRIMARY KEY,pid INTEGER,started TEXT);
    ''')


def connect_agent(db, provider, workspace):
    if provider not in ('claude','codex'):
        raise ValueError('Choose Claude or Codex')
    exe = shutil.which(provider)
    if not exe:
        raise ValueError('Install '+provider+' and sign in first')
    path = str(Path(workspace).expanduser().resolve())
    subprocess.run(['git','-C',path,'rev-parse','--show-toplevel'],check=True,capture_output=True,timeout=5)
    with db:
        db.execute('INSERT OR REPLACE INTO agent_connection VALUES(?,?,?,1)',(provider,exe,path))
    return {'provider':provider,'workspace':path,'executable':exe,
            'access':'Uses this local agent’s authentication and configured tools; tool access is reported when a session starts.',
            'history':'Only the session selected in Paco is resumed. Consumer chats are not imported.'}


def prepare(db, provider, objective, context=None):
    row = db.execute('SELECT * FROM agent_connection WHERE provider=? AND enabled=1',(provider,)).fetchone()
    if not row:
        raise ValueError('Connect '+provider+' in Settings first')
    if not objective.strip():
        raise ValueError('Enter a request')
    ident = uuid.uuid4().hex
    brief = {'objective':objective,'repo':row['workspace'],'context':context or [],
             'base_commit':subprocess.check_output(['git','-C',row['workspace'],'rev-parse','HEAD'],text=True,timeout=5).strip(),
             'uncommitted_changes_not_included':bool(subprocess.check_output(['git','-C',row['workspace'],'status','--porcelain'],text=True,timeout=5).strip()),
             'acceptance':['Report changed files, checks, blockers and actual result links.'],
             'permissions':'Use existing tool permissions. Stop and report any denied action. Do not bypass approvals.'}
    with db:
        db.execute("INSERT INTO agent_session VALUES(?,?,?,?,NULL,'draft',?,'',?)",
                   (ident,provider,row['workspace'],'',json.dumps(brief),time.time()))
    return ident


def command(connection, session, followup=None):
    exe, provider = connection['executable'], connection['provider']
    if provider == 'claude':
        args = [exe,'-p','--output-format','stream-json','--verbose','--permission-mode','default']
        if session['remote_id']:
            args += ['--resume',session['remote_id']]
    else:
        args = [exe,'exec','-c','approval_policy="never"','-c','sandbox_mode="workspace-write"']
        if session['remote_id']:
            args += ['resume',session['remote_id']]
        args += ['--json','-']
    return args


def execute(path, connect, ident, followup=None):
    """Claim once; no automatic replay of actions after a crash or uncertain delivery."""
    with LOCK:
        if ident in ACTIVE:
            raise ValueError('The previous turn is still stopping; wait before continuing')
    with connect(path) as db:
        initialize(db)
        row = db.execute('SELECT * FROM agent_session WHERE id=?',(ident,)).fetchone()
        if not row:
            raise ValueError('Unknown session')
        connection = db.execute('SELECT * FROM agent_connection WHERE provider=? AND enabled=1',(row['provider'],)).fetchone()
        if not connection:
            raise ValueError('Agent connection revoked')
        eligible = ('completed','blocked','cancelled') if followup else ('draft',)
        if row['status'] not in eligible:
            raise ValueError('Session is already running or needs a follow-up after review')
        if followup and not row['remote_id']:
            raise ValueError('No reusable provider session was returned; prepare a new request')
        prior = db.execute('SELECT pid,started FROM agent_process WHERE session=?',(ident,)).fetchone()
        if prior and prior['started'] and process_stamp(prior['pid'])==prior['started']:
            raise ValueError('The previous process is still running; cancel or wait before continuing')
        if db.execute('UPDATE agent_session SET status=\'running\' WHERE id=? AND status=?',(ident,row['status'])).rowcount != 1:
            raise ValueError('Session already claimed')
    with LOCK:
        ACTIVE.add(ident)
    def worker():
        db = connect(path)
        proc = None
        try:
            session = dict(row)
            worktree = session['worktree']
            if not worktree:
                worktree = str(path.parent/'worktrees'/ident)
                Path(worktree).parent.mkdir(parents=True,exist_ok=True)
                base=json.loads(session['brief']).get('base_commit','HEAD')
                subprocess.run(['git','-C',session['workspace'],'worktree','add','-b',session['provider']+'/paco-'+ident[:12],worktree,base],
                               check=True,capture_output=True,timeout=30)
                with db:
                    db.execute('UPDATE agent_session SET worktree=? WHERE id=?',(worktree,ident))
            prompt = followup or json.dumps(json.loads(session['brief']),ensure_ascii=False)
            status = db.execute('SELECT status FROM agent_session WHERE id=?',(ident,)).fetchone()[0]
            enabled = db.execute('SELECT enabled FROM agent_connection WHERE provider=?',(session['provider'],)).fetchone()[0]
            if status!='running' or not enabled:
                return
            proc = subprocess.Popen(command(connection,session,followup),cwd=worktree,stdin=subprocess.PIPE,
                                    stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,start_new_session=True)
            with db:
                db.execute('INSERT OR REPLACE INTO agent_process VALUES(?,?,?)',(ident,proc.pid,process_stamp(proc.pid)))
            with LOCK:
                RUNNING[ident] = proc
            if db.execute('SELECT status FROM agent_session WHERE id=?',(ident,)).fetchone()[0]!='running':
                stop_process(proc)
                return
            proc.stdin.write(prompt+'\n')
            proc.stdin.close()
            final, denied = '', False
            timer = threading.Timer(900,lambda: stop_process(proc))
            timer.start()
            try:
                for line in proc.stdout:
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    kind = event.get('type','event')
                    remote = event.get('session_id') or event.get('thread_id')
                    # Retain useful events, never opaque environment/config/credential payloads.
                    message = ''
                    if kind == 'system' and event.get('subtype') == 'init':
                        message = json.dumps({'tools':event.get('tools',[]),'mcp_servers':event.get('mcp_servers',[]),'model':event.get('model')})
                    if kind == 'result':
                        final = event.get('result','')
                        denied = bool(event.get('permission_denials')) or event.get('is_error',False)
                        message = final
                        if event.get('permission_denials'):
                            message += '\nPermission needed: '+json.dumps(event['permission_denials'])
                    if kind == 'item.completed':
                        item = event.get('item',{})
                        if item.get('type') == 'agent_message':
                            final = message = item.get('text','')
                    if kind in ('error','turn.failed'):
                        denied = True
                        message = 'Agent failed; inspect your provider session.'
                    with db:
                        if remote:
                            db.execute('UPDATE agent_session SET remote_id=? WHERE id=?',(remote,ident))
                        if message:
                            db.execute('INSERT INTO agent_event(session,at,kind,text) VALUES(?,?,?,?)',(ident,time.time(),kind,redact(message)[:16000]))
                code = proc.wait()
            finally:
                timer.cancel()
            with db:
                db.execute("UPDATE agent_session SET status=?,result=? WHERE id=? AND status='running'",
                           ('completed' if code == 0 and not denied and final else 'blocked',redact(final)[:32000],ident))
        except Exception as exc:
            with db:
                db.execute("UPDATE agent_session SET status='blocked',result=? WHERE id=? AND status='running'",
                           ('Agent stopped ('+type(exc).__name__+'). Review before retrying.',ident))
        finally:
            with LOCK:
                RUNNING.pop(ident,None)
                ACTIVE.discard(ident)
            with db:
                db.execute('DELETE FROM agent_process WHERE session=?',(ident,))
            if proc:
                for stream in (proc.stdin,proc.stdout):
                    if stream and not stream.closed:
                        stream.close()
                if proc.poll() is not None:
                    proc.wait()
            db.close()
    threading.Thread(target=worker,daemon=True).start()


def redact(text):
    import re
    return re.sub(r'(?i)(sk-[\w-]{12,}|gh[pousr]_[\w]{16,}|bearer\s+\S+)', '[redacted]',text)


def stop_process(proc):
    if proc.poll() is None:
        try:
            os.killpg(proc.pid,signal.SIGTERM)
        except ProcessLookupError:
            pass


def process_stamp(pid):
    try:
        return subprocess.check_output(['ps','-p',str(int(pid)),'-o','lstart='],text=True,timeout=3).strip() or None
    except subprocess.CalledProcessError:
        return None


def cancel(db, ident):
    with LOCK:
        proc = RUNNING.get(ident)
        if proc:
            stop_process(proc)
        else:
            prior = db.execute('SELECT pid,started FROM agent_process WHERE session=?',(ident,)).fetchone()
            if prior and prior['started'] and process_stamp(prior['pid'])==prior['started']:
                try:
                    os.killpg(prior['pid'],signal.SIGTERM)
                except ProcessLookupError:
                    pass
    with db:
        db.execute("UPDATE agent_session SET status='cancelled' WHERE id=? AND status IN ('running','blocked')",(ident,))


def recover(db):
    with db:
        db.execute("UPDATE agent_session SET status='blocked',result='Paco restarted. Inspect the provider session and worktree before continuing; actions were not replayed.' WHERE status='running'")
