"""Explicit local weekly and monthly task schedules, preserving each completed occurrence."""
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
import time
import calendar
from contextlib import nullcontext
import workflows


def initialize(db):
    db.executescript('''CREATE TABLE IF NOT EXISTS task_recurrence(
        task INTEGER PRIMARY KEY,zone TEXT,weekday INTEGER,hour INTEGER,minute INTEGER,
        occurrence REAL,enabled INTEGER NOT NULL DEFAULT 1);
        CREATE TABLE IF NOT EXISTS task_occurrence(task INTEGER,scheduled REAL,completed REAL,
        PRIMARY KEY(task,scheduled));''')

    columns={r[1] for r in db.execute('PRAGMA table_info(task_recurrence)')}
    if 'frequency' not in columns:db.execute("ALTER TABLE task_recurrence ADD COLUMN frequency TEXT NOT NULL DEFAULT 'weekly'")
    if 'monthday' not in columns:db.execute("ALTER TABLE task_recurrence ADD COLUMN monthday INTEGER NOT NULL DEFAULT 1")


def validate(rule):
    if rule is None:return None
    if not isinstance(rule,dict) or set(rule)-{'frequency','zone','weekday','monthday','hour','minute'}:
        raise ValueError('Invalid repeat settings')
    value=dict(frequency='weekly',zone='Europe/Paris',weekday=0,monthday=1,hour=9,minute=0)
    value.update(rule)
    if value['frequency'] not in ('weekly','monthly'):raise ValueError('Choose weekly or monthly')
    try:ZoneInfo(value['zone'])
    except (ValueError,TypeError,KeyError):raise ValueError('Choose a valid timezone') from None
    for field,low,high in [('weekday',0,6),('monthday',1,31),('hour',0,23),('minute',0,59)]:
        if type(value[field]) is not int or not low<=value[field]<=high:raise ValueError('Invalid '+field)
    return value


def next_occurrence(after,rule):
    if rule['frequency']=='weekly':
        return next_weekly(after,rule['zone'],rule['weekday'],rule['hour'],rule['minute'])
    local=datetime.fromtimestamp(after,ZoneInfo(rule['zone']))
    year,month=local.year,local.month
    for _ in range(24):
        # A 31st schedule skips months without that date.
        if rule['monthday']<=calendar.monthrange(year,month)[1]:
            candidate=local.replace(year=year,month=month,day=rule['monthday'],hour=rule['hour'],minute=rule['minute'],second=0,microsecond=0)
            if candidate.timestamp()>after:return candidate.timestamp()
        month+=1
        if month==13:year+=1;month=1
    raise ValueError('No next occurrence')


def save(db,task,rule,now=None,commit=True):
    rule=validate(rule)
    if not db.execute('SELECT 1 FROM task WHERE id=?',(task,)).fetchone():raise ValueError('Unknown task')
    with (db if commit else nullcontext()):
        if rule is None:
            db.execute('UPDATE task_recurrence SET enabled=0 WHERE task=?',(task,))
            return
        old=db.execute('SELECT * FROM task_recurrence WHERE task=?',(task,)).fetchone()
        if old and old['enabled'] and all(old[k]==v for k,v in rule.items()):return old['occurrence']
        due=next_occurrence(time.time() if now is None else now,rule)
        db.execute("""INSERT OR REPLACE INTO task_recurrence(task,zone,weekday,hour,minute,occurrence,enabled,frequency,monthday)
            VALUES(?,?,?,?,?,?,1,?,?)""",(task,rule['zone'],rule['weekday'],rule['hour'],rule['minute'],due,rule['frequency'],rule['monthday']))
        db.execute('UPDATE task SET due=?,nudges=0 WHERE id=?',(due,task))
        db.execute("INSERT INTO details(task,goal,minutes,deadline) VALUES(?,'',30,?) ON CONFLICT(task) DO UPDATE SET deadline=excluded.deadline",(task,due))
        db.execute('DELETE FROM scheduled_check WHERE task=?',(task,))
        workflows.changed(db,'task.recurrence_configured',{'id':task,**rule})
        return due


def label(rule):
    day=calendar.day_name[rule['weekday']] if rule['frequency']=='weekly' else 'day '+str(rule['monthday'])+' of each month'
    return 'Every '+day+' at '+f"{rule['hour']:02}:{rule['minute']:02}"+' ('+rule['zone']+')'


def next_weekly(after,zone,weekday,hour,minute):
    local=datetime.fromtimestamp(after,ZoneInfo(zone))
    candidate=local.replace(hour=hour,minute=minute,second=0,microsecond=0)
    candidate+=timedelta(days=(weekday-local.weekday())%7)
    if candidate.timestamp()<=after:candidate+=timedelta(days=7)
    return candidate.timestamp()


def configure(db,task,zone,weekday,hour,minute=0,now=None):
    return save(db,task,dict(zone=zone,weekday=weekday,hour=hour,minute=minute),now)


def advance(db,now=None):
    now=time.time() if now is None else now
    with db:
        db.execute('BEGIN IMMEDIATE')
        for rule in db.execute("SELECT r.* FROM task_recurrence r JOIN task t ON t.id=r.task WHERE r.enabled=1 AND t.state='done'").fetchall():
            due=next_occurrence(max(now,rule['occurrence']),rule)
            db.execute('INSERT OR IGNORE INTO task_occurrence VALUES(?,?,?)',(rule['task'],rule['occurrence'],now))
            db.execute("UPDATE task SET state='open',due=?,nudges=0 WHERE id=?",(due,rule['task']))
            db.execute('UPDATE details SET deadline=? WHERE task=?',(due,rule['task']))
            db.execute("INSERT INTO task_override(task,state) VALUES(?,'open') ON CONFLICT(task) DO UPDATE SET state='open'",(rule['task'],))
            db.execute('UPDATE task_recurrence SET occurrence=? WHERE task=?',(due,rule['task']))
            workflows.changed(db,'task.recurrence_advanced',{'id':rule['task'],'due':due})
