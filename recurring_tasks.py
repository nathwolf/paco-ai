"""Explicit local weekly task schedules, preserving each completed occurrence."""
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
import time
import workflows


def initialize(db):
    db.executescript('''CREATE TABLE IF NOT EXISTS task_recurrence(
        task INTEGER PRIMARY KEY,zone TEXT,weekday INTEGER,hour INTEGER,minute INTEGER,
        occurrence REAL,enabled INTEGER NOT NULL DEFAULT 1);
        CREATE TABLE IF NOT EXISTS task_occurrence(task INTEGER,scheduled REAL,completed REAL,
        PRIMARY KEY(task,scheduled));''')


def next_weekly(after,zone,weekday,hour,minute):
    local=datetime.fromtimestamp(after,ZoneInfo(zone))
    candidate=local.replace(hour=hour,minute=minute,second=0,microsecond=0)
    candidate+=timedelta(days=(weekday-local.weekday())%7)
    if candidate.timestamp()<=after:candidate+=timedelta(days=7)
    return candidate.timestamp()


def configure(db,task,zone,weekday,hour,minute=0,now=None):
    if not db.execute('SELECT 1 FROM task WHERE id=?',(task,)).fetchone():raise ValueError('Unknown task')
    if type(weekday) is not int or not 0<=weekday<=6 or type(hour) is not int or not 0<=hour<=23 or type(minute) is not int or not 0<=minute<=59:raise ValueError('Invalid weekly schedule')
    due=next_weekly(time.time() if now is None else now,zone,weekday,hour,minute)
    with db:
        db.execute('INSERT OR REPLACE INTO task_recurrence VALUES(?,?,?,?,?,?,1)',(task,zone,weekday,hour,minute,due))
        db.execute('UPDATE task SET due=? WHERE id=?',(due,task))
        db.execute('INSERT INTO details(task,goal,minutes,deadline) VALUES(?,\'\',30,?) ON CONFLICT(task) DO UPDATE SET deadline=excluded.deadline',(task,due))
        workflows.changed(db,'task.recurrence_configured',{'id':task,'zone':zone,'weekday':weekday,'hour':hour,'minute':minute})
    return due


def advance(db,now=None):
    now=time.time() if now is None else now
    with db:
        db.execute('BEGIN IMMEDIATE')
        for rule in db.execute("SELECT r.* FROM task_recurrence r JOIN task t ON t.id=r.task WHERE r.enabled=1 AND t.state='done'").fetchall():
            due=next_weekly(max(now,rule['occurrence']),rule['zone'],rule['weekday'],rule['hour'],rule['minute'])
            db.execute('INSERT OR IGNORE INTO task_occurrence VALUES(?,?,?)',(rule['task'],rule['occurrence'],now))
            db.execute("UPDATE task SET state='open',due=?,nudges=0 WHERE id=?",(due,rule['task']))
            db.execute('UPDATE details SET deadline=? WHERE task=?',(due,rule['task']))
            db.execute("INSERT INTO task_override(task,state) VALUES(?,'open') ON CONFLICT(task) DO UPDATE SET state='open'",(rule['task'],))
            db.execute('UPDATE task_recurrence SET occurrence=? WHERE task=?',(due,rule['task']))
            workflows.changed(db,'task.recurrence_advanced',{'id':rule['task'],'due':due})
