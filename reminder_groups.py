"""Local, reversible groupings for reminder delivery. Tasks keep their own state."""
from datetime import datetime
from itertools import combinations
import hashlib
import json
import time

REASON = 'Related tasks'
GROUP_QUEUED = object()


def initialize(db):
    db.executescript("""
        CREATE TABLE IF NOT EXISTS reminder_member(task INTEGER PRIMARY KEY, cohort TEXT, label TEXT, signature TEXT);
        CREATE TABLE IF NOT EXISTS reminder_delivery(notification INTEGER,task INTEGER,PRIMARY KEY(notification,task));
        CREATE INDEX IF NOT EXISTS reminder_delivery_task ON reminder_delivery(task);
        CREATE TABLE IF NOT EXISTS reminder_example(cohort TEXT PRIMARY KEY,label TEXT,reason TEXT,members TEXT);
        CREATE TABLE IF NOT EXISTS reminder_separate(a INTEGER,b INTEGER,PRIMARY KEY(a,b));
    """)


def signature(task):
    values = [task[k] for k in ('title','description','project','kind','owner','deadline')]
    return hashlib.sha256(json.dumps(values).encode()).hexdigest()


def separate_pairs(db):
    return {tuple(r) for r in db.execute('SELECT a,b FROM reminder_separate')}


def remember_example(db, label, reason, tasks):
    members = [{'id':t['id'],'title':t['title'],'source':t['source'],'signature':signature(t)} for t in tasks]
    key = ','.join(map(str,sorted(t['id'] for t in tasks)))
    db.execute('INSERT OR REPLACE INTO reminder_example VALUES(?,?,?,?)',(key,label,reason,json.dumps(members)))


def distinct_pairs(db, tasks):
    pairs=separate_pairs(db)
    for row in db.execute('SELECT members FROM reminder_example'):
        ids=[m['id'] for m in json.loads(row[0]) if m['id'] in tasks and signature(tasks[m['id']])==m['signature']]
        pairs.update(combinations(sorted(ids),2))
    return pairs


def examples(db, permitted):
    result=[]
    for row in db.execute('SELECT * FROM reminder_example ORDER BY rowid DESC LIMIT 20'):
        members=json.loads(row['members'])
        if all(permitted(m['source']) for m in members):
            result.append({'label':row['label'],'reason':row['reason'],'tasks':[m['title'] for m in members]})
    return result


def replace(db, proposals, tasks, excluded):
    """Accept well-grounded, nonoverlapping proposals from the current snapshot."""
    if not isinstance(proposals,list):
        raise ValueError('Invalid reminder groups')
    blocked = separate_pairs(db)
    used = set(excluded)
    db.execute('DELETE FROM reminder_member')
    reviewed=[]
    for row in db.execute('SELECT * FROM reminder_example ORDER BY rowid DESC'):
        members=[m for m in json.loads(row['members']) if m['id'] in tasks and signature(tasks[m['id']])==m['signature']
                 and tasks[m['id']]['state']=='open']
        reviewed.append({'tasks':[m['id'] for m in members],'label':row['label'],'confidence':'high',
                         'quotes':[{'task':m['id'],'quote':m['title']} for m in members]})
    for group in reviewed+proposals:
        if not isinstance(group,dict) or group.get('confidence') != 'high':
            continue
        ids, label, refs = group.get('tasks'), group.get('label'), group.get('quotes')
        if not isinstance(label,str) or not 1<=len(label.strip())<=60 or not isinstance(refs,list):
            continue
        if not isinstance(ids,list) or not 2<=len(ids)<=8 or any(type(i)!=int or i not in tasks for i in ids):
            continue
        if len(set(ids))!=len(ids) or used.intersection(ids) or blocked.intersection(combinations(sorted(ids),2)):
            continue
        members = [tasks[i] for i in ids]
        if len({m['project'] for m in members})!=1 or len({m['kind'] for m in members})!=1:
            continue
        if len({m['deadline'] for m in members})!=1:
            continue
        def grounded(m):
            sources = [m['title'], m.get('description') or ''] + [e['text'] for e in m['evidence']]
            return any(isinstance(q,dict) and q.get('task')==m['id'] and isinstance(q.get('quote'),str)
                       and q['quote'].strip() and any(q['quote'] in s for s in sources) for q in refs)
        if any(m['state']!='open' or m['status']!='accepted' or not grounded(m) for m in members):
            continue
        cohort = ','.join(map(str,sorted(ids)))
        db.executemany('INSERT INTO reminder_member VALUES(?,?,?,?)',
                       [(m['id'],cohort,label.strip(),signature(m)) for m in members])
        used.update(ids)


def covered(db,now):
    midnight = datetime.fromtimestamp(now).replace(hour=0,minute=0,second=0,microsecond=0).timestamp()
    return {r[0] for r in db.execute("""SELECT DISTINCT d.task FROM reminder_delivery d JOIN notification n ON n.id=d.notification
        WHERE ((n.shown IS NULL AND n.created>?) OR n.shown>=?)
        AND NOT EXISTS(SELECT 1 FROM intervention i WHERE i.task=d.task AND i.at>=n.created AND i.action!='notify')""",(now-300,midnight))}


def ready(db,now):
    import planning,tagging
    if planning.reason_to_wait(db,now):
        return {}
    candidates = {r['id']:r for r in planning.ranked(db,now) if r['state']=='open' and not r['critical']
                  and not r['urgent'] and tagging.allowed(db,now,r)}
    result = {}
    for m in db.execute("""SELECT m.*,t.title,x.description,p.project,a.kind,COALESCE(o.owner,'') owner,d.deadline
        FROM reminder_member m JOIN task t ON t.id=m.task JOIN task_attention a ON a.task=m.task
        LEFT JOIN task_extra x ON x.task=m.task LEFT JOIN task_project p ON p.task=m.task
        LEFT JOIN ownership o ON o.task=m.task LEFT JOIN details d ON d.task=m.task"""):
        if m['task'] in candidates and signature(m)==m['signature'] and not planning.meeting_start(db,m['task']):
            result[m['task']]=m
    return result


def enqueue(db,task,now):
    if not db.execute('SELECT 1 FROM reminder_member WHERE task=?',(task,)).fetchone():
        return False
    candidates=ready(db,now)
    leader=candidates.get(task)
    if not leader:
        return False
    seen=covered(db,now)
    ids=[i for i,m in candidates.items() if m['cohort']==leader['cohort'] and i not in seen]
    if len(ids)<2:
        return False
    note=db.execute("INSERT INTO notification(message,mood,reason,created) VALUES(?,'friendly',?,?)",
                    (leader['label'],REASON,now)).lastrowid
    db.executemany('INSERT INTO reminder_delivery VALUES(?,?)',[(note,i) for i in ids])
    return True


def members(db,note):
    return [r[0] for r in db.execute('SELECT task FROM reminder_delivery WHERE notification=? ORDER BY task',(note,))]


def current(db,note,now):
    ids=members(db,note)
    available=ready(db,now)
    original=set(map(str,ids))
    return [i for i in ids if i in available and original.issubset(available[i]['cohort'].split(','))]



def split(db,note):
    ids=members(db,note)
    if len(ids)<2:
        raise ValueError('Unknown grouped reminder')
    with db:
        for example in db.execute('SELECT cohort,members FROM reminder_example').fetchall():
            if len(set(ids).intersection(m['id'] for m in json.loads(example['members'])))>=2:
                db.execute('DELETE FROM reminder_example WHERE cohort=?',(example['cohort'],))
        db.executemany('INSERT OR IGNORE INTO reminder_separate VALUES(?,?)',combinations(ids,2))
        db.executemany('DELETE FROM reminder_member WHERE task=?',[(i,) for i in ids])
        db.executemany("INSERT INTO intervention VALUES(?,'separate_reminders',?)",[(i,time.time()) for i in ids])
        db.execute("DELETE FROM preference WHERE key='relationships_checked'")
