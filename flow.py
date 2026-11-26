"""Local, content-free flow protection. Retains only the latest activity snapshot."""
import json
import math
from pathlib import Path
import subprocess
import time

DEFAULT_APPS = 'Xcode, Visual Studio Code, Cursor, Terminal, iTerm2, Codex, Claude, Figma, Pages, Numbers, Keynote, Microsoft Word, Microsoft Excel, Microsoft PowerPoint, Notion'
# macOS may display Codex as ChatGPT; use bundle identity for selected work apps.
APP_BUNDLES = {'codex': {'com.openai.codex'}, 'claude': {'com.anthropic.claudefordesktop'},
               'visual studio code': {'com.microsoft.VSCode'}}

def work_app(names,app,bundle):
    selected={s.strip().casefold() for s in names if s.strip()}
    return app.casefold() in selected or bundle.casefold() in selected or any(
        bundle in APP_BUNDLES.get(name,set()) for name in selected)
FLOW_REASON = 'Protecting your work flow'
AWAY_REASON = 'Computer is idle or locked'


def initialize(db):
    db.execute('''CREATE TABLE IF NOT EXISTS flow_state(
        id INTEGER PRIMARY KEY CHECK(id=1), at REAL, app TEXT, idle REAL,
        until REAL, status TEXT)''')


def pref(db,key,default=''):
    row=db.execute('SELECT value FROM preference WHERE key=?',(key,)).fetchone()
    return row[0] if row else default


def enabled(db):return pref(db,'flow_protection','off')=='on'


def configure(db, data):
    if type(data.get('enabled')) is not bool or type(data.get('urgent_interrupts',False)) is not bool:
        raise ValueError('Choose whether flow protection and urgent interruptions are enabled')
    apps=data.get('apps',DEFAULT_APPS)
    if not isinstance(apps,str) or len(apps)>3000:
        raise ValueError('Enter work app names separated by commas')
    names=[s.strip() for s in apps.split(',') if s.strip()]
    if data['enabled'] and not names:
        raise ValueError('Choose at least one work app')
    seconds=data.get('pause_seconds',120)
    if type(seconds) is not int or seconds not in (60,120,180,300):
        raise ValueError('Choose a pause of 1, 2, 3 or 5 minutes')
    with db:
        db.executemany('INSERT OR REPLACE INTO preference VALUES(?,?)',[
            ('flow_protection','on' if data['enabled'] else 'off'),('flow_apps',', '.join(names)),
            ('flow_urgent','on' if data.get('urgent_interrupts') else 'off'),('flow_pause',str(seconds))])
        db.execute('DELETE FROM flow_state')


def observe(db, meta, now):
    """Called inside a transaction. Never persist titles, content, or event values."""
    if not enabled(db):
        db.execute('DELETE FROM flow_state');return
    app=meta.get('app');bundle=meta.get('bundle');idle=meta.get('idle');locked=meta.get('locked')
    if not isinstance(app,str) or not isinstance(bundle,str) or type(locked) is not bool or type(idle) not in (int,float) or not math.isfinite(idle) or idle<0:
        raise ValueError('Activity signal unavailable')
    previous=db.execute('SELECT * FROM flow_state WHERE id=1').fetchone()
    pause=int(pref(db,'flow_pause','120'))
    names={s.strip().casefold() for s in pref(db,'flow_apps',DEFAULT_APPS).split(',')}
    work=work_app(names,app,bundle)
    # Long idle means absent, not a good moment to show a banner. A shorter pause
    # is a delivery opportunity. Brief app switches get 30 seconds of grace.
    until=0
    if locked or idle>=max(600,pause+120):
        status='away'
    elif work and idle<pause:
        status='working';until=now+pause-idle
    elif previous and previous['status']=='working' and 0<=now-previous['at']<=45 and previous['until']>now and not work:
        status='switching';until=min(previous['until'],now+30)
    elif previous and previous['status']=='switching' and 0<=now-previous['at']<=45 and previous['until']>now and not work:
        status='switching';until=previous['until']
    else:
        status='available'
    db.execute('INSERT OR REPLACE INTO flow_state VALUES(1,?,?,?,?,?)',(now,app[:200],idle,until,status))


def sample(db, now=None, reader=None, force=False):
    """The pre-interruption activity check, shared by flow protection and call-outs."""
    import slacking
    now=time.time() if now is None else now
    callout=slacking.enabled(db)
    if not enabled(db) and not callout:return
    last=db.execute('SELECT MAX(at) FROM (SELECT at FROM flow_state UNION ALL SELECT at FROM callout_activity)').fetchone()[0]
    if not force and last and 0<=now-last<10:return
    try:
        if reader:
            meta=reader()
        else:
            binary=Path(__file__).parent/'build/Paco.app/Contents/MacOS/Paco'
            # "titles" asks for the front browser window's title, only for call-out matching; it is never stored.
            meta=json.loads(subprocess.check_output([str(binary),'--capture','activity',*(['titles'] if callout else [])],text=True,stderr=subprocess.DEVNULL,timeout=3))
        with db:
            db.execute('BEGIN IMMEDIATE')
            observe(db,meta,now)
            # Records the snapshot only. Judging (possibly a model call) happens in its own loop, outside this transaction.
            slacking.observe(db,meta,now)
    except (OSError,subprocess.SubprocessError,ValueError,TypeError):
        with db:
            if enabled(db):db.execute("INSERT OR REPLACE INTO flow_state VALUES(1,?,'',0,0,'unavailable')",(now,))
            db.execute('DELETE FROM callout_activity')
        with slacking._LOCK:slacking._PENDING.pop(slacking._database(db),None)


def reason(db,now,critical=False):
    if not enabled(db):return None
    row=db.execute('SELECT * FROM flow_state WHERE id=1').fetchone()
    # Sleep, crashes and revoked collection must not leave a permanent block.
    if not row or not 0<=now-row['at']<=45:return None
    if row['status']=='away':return AWAY_REASON
    if row['status'] in ('working','switching') and row['until']>now:
        if critical and pref(db,'flow_urgent','off')=='on':return None
        return FLOW_REASON


def status(db,now=None):
    now=time.time() if now is None else now
    row=db.execute('SELECT * FROM flow_state WHERE id=1').fetchone()
    if not enabled(db):message='Off. Paco is not observing app activity.'
    elif not row or not 0<=now-row['at']<=45:message='Waiting for a fresh activity check.'
    elif row['status']=='unavailable':message='Activity unavailable. Calendar and manual focus protection still apply.'
    elif reason(db,now):message=(reason(db,now)+(' · '+row['app'] if row['status']!='away' else ''))
    else:message='No active work detected in your selected apps.'
    return {'enabled':enabled(db),'apps':pref(db,'flow_apps',DEFAULT_APPS),
            'pause_seconds':int(pref(db,'flow_pause','120')),'urgent_interrupts':pref(db,'flow_urgent','off')=='on','message':message}
