"""User-approved reminder sessions and the source conditions that release them."""
from datetime import datetime, timedelta
from email.utils import parseaddr
import re

REASON = 'Scheduled check'

def initialize(db):
    db.executescript("""
        CREATE TABLE IF NOT EXISTS scheduled_check(task INTEGER PRIMARY KEY, at REAL, label TEXT, note INTEGER);
        CREATE TABLE IF NOT EXISTS first_check_pair(a INTEGER,b INTEGER,PRIMARY KEY(a,b));
        CREATE TABLE IF NOT EXISTS check_example(id INTEGER PRIMARY KEY,label TEXT,reason TEXT,hour INTEGER,minute INTEGER);
        CREATE TABLE IF NOT EXISTS check_example_task(example INTEGER,task INTEGER,PRIMARY KEY(example,task));
        CREATE TABLE IF NOT EXISTS reminder_condition(task INTEGER PRIMARY KEY,source TEXT,scope TEXT,
            sender TEXT,subject_hint TEXT,instruction TEXT,lead INTEGER,created REAL);
    """)


def schedule(db,task,at,label,now):
    db.execute('INSERT OR REPLACE INTO scheduled_check(task,at,label) VALUES(?,?,?)',(task,at,label))
    db.execute('UPDATE task SET due=?,nudges=0 WHERE id=?',(at,task))
    db.execute("INSERT INTO intervention VALUES(?,'snooze',?)",(task,now))


def eligible(db,now):
    import planning,tagging
    if planning.reason_to_wait(db,now):
        return {}
    return {r['id']:r for r in planning.ranked(db,now,fit_before_meeting=False)
            if r['state']=='open' and tagging.allowed(db,now,r)}


def queue(db,now):
    with db:
        db.execute('BEGIN IMMEDIATE')
        rows=list(db.execute("""SELECT s.* FROM scheduled_check s JOIN task t ON t.id=s.task
            LEFT JOIN notification n ON n.id=s.note
            WHERE t.due=s.at AND s.at<=? AND (n.id IS NULL OR (n.shown IS NULL AND n.created<=?))
            ORDER BY s.at,s.task""",(now,now-300)))
        if not rows:return
        available=eligible(db,now)
        sessions={}
        for r in rows:
            if r['task'] in available:
                sessions.setdefault((r['at'],r['label']),[]).append(r['task'])
        for (_,label),ids in sessions.items():
            ident=db.execute("INSERT INTO notification(message,mood,reason,created) VALUES(?,'friendly',?,?)",
                             (label,REASON,now)).lastrowid
            db.executemany('INSERT INTO reminder_delivery VALUES(?,?)',[(ident,i) for i in ids])
            db.executemany('UPDATE scheduled_check SET note=? WHERE task=?',[(ident,i) for i in ids])


def current(db,note,now):
    ready=eligible(db,now)
    return [r[0] for r in db.execute('''SELECT s.task FROM scheduled_check s JOIN task t ON s.task=t.id
        WHERE s.note=? AND t.due=s.at''',(note,)) if r[0] in ready]


def acknowledge(db,note,now):
    for r in db.execute('''SELECT s.task,s.at,c.task AS waiting FROM scheduled_check s
            LEFT JOIN reminder_condition c ON c.task=s.task JOIN reminder_delivery d ON d.task=s.task AND d.notification=s.note
            WHERE s.note=?''',(note,)).fetchall():
        if r['waiting']:
            db.execute("UPDATE task SET state='blocked' WHERE id=? AND due=? AND state='open'",(r['task'],r['at']))
        db.execute('DELETE FROM scheduled_check WHERE task=? AND note=?',(r['task'],note))


def conditions(db,source,scope):
    return [dict(r) for r in db.execute("""SELECT c.*,t.title FROM reminder_condition c JOIN task t ON t.id=c.task
          WHERE c.source=? AND (c.scope='' OR c.scope=?) AND t.state IN ('open','blocked')""",(source,scope))]


PROMPT = """When a supplied reminder_condition is explicitly fulfilled by a NEW incoming message, return
signals:[{task:number,message:"id",quote:"exact text proving condition",event_time:"ISO datetime with timezone or null"}].
Check the named document, person and occasion. Exclude requests for confirmation, generic assent without context,
forwarded guesses and superseded confirmations. For an appointment require a definitive booking with explicit date AND time.
Do not add a duplicate task when a message activates an existing reminder. Otherwise signals is empty."""


def booked_time(value, quote):
    """Require the proposed local date and clock time to agree with the booking text."""
    if not isinstance(value,str) or 'T' not in value:return None
    try:dt=datetime.fromisoformat(value.replace('Z','+00:00'))
    except ValueError:return None
    if dt.tzinfo is None:return None
    month_names=('jan ene','feb fév fev','mar','apr avr abr','may mai','jun juin','jul juil','aug août aout ago',
                 'sep sept','oct','nov','dec déc dic')[dt.month-1].split()
    month='(?:'+'|'.join(month_names)+r')\w*'
    day=f'0?{dt.day}'
    numbered=f'0?{dt.month}'
    year=f'(?:{dt.year}|{dt.year%100:02})'
    dates=[f'{dt.year}[-/]{numbered}[-/]{day}',f'{day}[-/.]{numbered}[-/.]{year}',
           f'{numbered}[-/.]{day}[-/.]{year}',rf'{day}(?: de)?[ -]+{month}',rf'{month}[ .-]+{day}']
    if not re.search(r'(?<!\w)(?:'+'|'.join(dates)+r')(?!\w)',quote,re.I):return None
    minute=f'{dt.minute:02}'
    clock=rf'0?{dt.hour}[:h]{minute}(?!\s*[ap]\.?m)'
    part='am' if dt.hour<12 else 'pm'
    twelve=dt.hour%12 or 12
    ampm=rf'0?{twelve}(?:[:h]{minute})'+('?' if dt.minute==0 else '')+rf'\s*{part[0]}\.?m\.?'
    if not re.search(r'(?<!\d)(?:'+clock+'|'+ampm+r')(?!\w)',quote,re.I):return None
    return dt.timestamp()


def release(db,watches,signals,messages,now):
    import attention
    known={w['task']:w for w in watches}
    for signal in signals if isinstance(signals,list) else []:
        if not isinstance(signal,dict) or type(signal.get('task'))!=int:continue
        w=known.get(signal['task'])
        m=next((m for m in messages if m['id']==signal.get('message')),None)
        if not w or not m or m.get('mine') or m.get('sent') or not attention.eligible(db,w['task']):continue
        received=m['at'] if 'at' in m else int(m['date'])/1000
        if received<w['created'] or not db.execute(
                "SELECT 1 FROM task WHERE id=? AND state IN ('open','blocked')",(w['task'],)).fetchone():continue
        if w['sender'] and parseaddr(m.get('sender') or '')[1].casefold()!=w['sender'].casefold():continue
        subject=m.get('subject') or ''
        content=subject+'\n'+m['text']
        if w['subject_hint'] and w['subject_hint'].casefold() not in content.casefold():continue
        quote=signal.get('quote')
        if not isinstance(quote,str) or not quote.strip() or quote not in content:continue
        at=now
        if w['lead']:
            event=booked_time(signal.get('event_time'),quote)
            if event is None or event<=now:continue
            at=max(now,event-w['lead'])
        if not db.execute('DELETE FROM reminder_condition WHERE task=? AND created=?',(w['task'],w['created'])).rowcount:continue
        db.execute("UPDATE task SET state='open' WHERE id=? AND state='blocked'",(w['task'],))
        schedule(db,w['task'],at,w['title'],now)


def remember(db, label, reason, tasks, at):
    """Learn the local time of day from an approved initial check."""
    when = datetime.fromtimestamp(at)
    example = db.execute('INSERT INTO check_example(label,reason,hour,minute) VALUES(?,?,?,?)',
                         (label,reason,when.hour,when.minute)).lastrowid
    db.executemany('INSERT INTO check_example_task VALUES(?,?)', [(example,i) for i in tasks])
    db.execute("""INSERT OR IGNORE INTO preference SELECT 'check_learning_after',CAST(MAX(id) AS TEXT) FROM task""")


def examples(db, permitted):
    results = []
    for example in db.execute('SELECT * FROM check_example ORDER BY id DESC LIMIT 30'):
        members = list(db.execute("""SELECT t.title,COALESCE(a.source,'direct') source FROM check_example_task m
                        JOIN task t ON t.id=m.task LEFT JOIN task_attention a ON a.task=t.id WHERE m.example=?""",(example['id'],)))
        if members and all(permitted(m['source']) for m in members):
            results.append(dict(example, tasks=[m['title'] for m in members]))
    return results


def first_slot(db, example, now):
    import planning
    candidate = datetime.fromtimestamp(now).replace(hour=example['hour'], minute=example['minute'],second=0,microsecond=0)
    for day in range(14):
        slot = candidate + timedelta(days=day)
        at = slot.timestamp()
        if slot.weekday()>=5 or at<=now or planning.time_off(db,at):
            continue
        occupied = db.execute("""SELECT 1 FROM busy WHERE start<? AND end>?
            UNION ALL SELECT 1 FROM scheduled_check s JOIN task t ON t.id=s.task
            WHERE t.due=s.at AND t.state='open' AND s.at<? AND s.at>? LIMIT 1""",(at+1800,at,at+1800,at-1800)).fetchone()
        if not occupied:
            return at


def apply_checks(db, proposals, tasks, examples_by_id, after, excluded, now):
    import attention, reminder_groups
    from itertools import combinations
    blocked = reminder_groups.separate_pairs(db)
    for check in proposals if isinstance(proposals,list) else []:
        if not isinstance(check,dict) or check.get('confidence')!='high':
            continue
        ids, label, example = check.get('tasks'), check.get('label'), check.get('example')
        if type(example)!=int or example not in examples_by_id or not isinstance(label,str) or not 1<=len(label.strip())<=60:
            continue
        if not isinstance(ids,list) or not 1<=len(ids)<=8 or any(type(i)!=int or i<=after or i not in tasks for i in ids):
            continue
        if len(set(ids))!=len(ids) or excluded.intersection(ids) or blocked.intersection(combinations(sorted(ids),2)):
            continue
        if len({(tasks[i]['project'],tasks[i]['kind']) for i in ids})!=1:
            continue
        for i in ids:
            t=tasks[i]
            if t['state']!='open' or t['deadline'] or not attention.eligible(db,i) or not reminder_groups.grounded(t,check.get('quotes')):
                break
            if db.execute("""SELECT 1 FROM task WHERE id=? AND (due>? OR EXISTS(
                SELECT 1 FROM intervention WHERE task=id AND action IN ('snooze','separate_reminders'))
                OR EXISTS(SELECT 1 FROM reminder_condition WHERE task=id)
                OR EXISTS(SELECT 1 FROM dependency WHERE task=id)
                OR EXISTS(SELECT 1 FROM urgency WHERE task=id AND critical=1))""",(i,now)).fetchone():
                break
        else:
            at=first_slot(db,examples_by_id[example],now)
            if at:
                db.executemany('INSERT OR IGNORE INTO first_check_pair VALUES(?,?)',combinations(sorted(ids),2))
                for i in ids:
                    schedule(db,i,at,label.strip(),now)
