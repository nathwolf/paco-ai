"""Read the current macOS Focus via Apple's Get Current Focus shortcut.

Only a boolean is retained locally. No private APIs, disk permissions or model calls.
"""
import subprocess,sys,time

REASON='macOS Focus is on'
TTL=45
SHORTCUT='Paco Focus Status'


def initialize(db):
    db.execute('CREATE TABLE IF NOT EXISTS system_focus(id INTEGER PRIMARY KEY CHECK(id=1),active INTEGER,at REAL)')


def observe(db,active,now=None):
    if active is not None and type(active) is not bool:raise ValueError('Invalid Focus status')
    with db:db.execute('INSERT OR REPLACE INTO system_focus VALUES(1,?,?)',(active,time.time() if now is None else now))


def read():
    result=subprocess.run(['/usr/bin/shortcuts','run',SHORTCUT,'--output-type','public.plain-text'],capture_output=True,text=True,timeout=10,check=True)
    # Get Current Focus yields its name when enabled, and no value when disabled.
    return bool(result.stdout.strip())


def sample(db,reader=None):
    if sys.platform!='darwin' and reader is None:return
    try:value=(reader or read)()
    except (OSError,subprocess.SubprocessError):value=None
    observe(db,value)


def status(db,now=None):
    now=time.time() if now is None else now
    row=db.execute('SELECT * FROM system_focus WHERE id=1').fetchone()
    fresh=bool(row and 0<=now-row['at']<=TTL)
    value=bool(row['active']) if fresh and row['active'] is not None else None
    message=REASON if value else 'macOS Focus is off' if value is False else 'macOS Focus unavailable — check the Paco Focus Status shortcut'
    return {'active':value,'message':message}


def active(db,now=None):return status(db,now)['active'] is True
