"""One local, persistent tracker per project, grounded in synchronized task facts.

No independent messages, invented progress, raw source text, or extra model calls.
Paco's conversation model can reason over these scoped snapshots when asked.
"""
import hashlib
import json
import time
import tagging

ACTIVE = {'open', 'focus', 'blocked'}


def initialize(db):
    db.execute('''CREATE TABLE IF NOT EXISTS project_tracker(
        project INTEGER PRIMARY KEY, fingerprint TEXT NOT NULL, snapshot TEXT NOT NULL,
        changes TEXT NOT NULL, checked REAL NOT NULL, changed REAL NOT NULL)''')


def _snapshot(db, project, now):
    rows = [dict(row) for row in db.execute('''
        SELECT t.id,t.title,t.state,t.priority,d.deadline,COALESCE(u.critical,0) AS urgent
        FROM task t JOIN task_project tp ON tp.task=t.id
        LEFT JOIN details d ON d.task=t.id LEFT JOIN urgency u ON u.task=t.id
        WHERE tp.project=? AND t.state IN ('open','focus','blocked','done') ORDER BY t.id
    ''', (project['id'],))]
    for task in rows:
        task['waiting_on'] = [dict(r) for r in db.execute('''
            SELECT p.id,p.title,p.state FROM dependency e JOIN task p ON p.id=e.prerequisite
            WHERE e.task=? AND p.state!='done' ORDER BY p.id''', (task['id'],))] if task['state'] in ACTIVE else []
    import attention, project_brains
    suggested=sum(attention.info(db,t['id'])['status']=='suggested' for t in rows)
    rows=[t for t in rows if attention.info(db,t['id'])['status']=='accepted']
    for task in rows:task['mine']=attention.eligible(db,task['id'])
    active = [t for t in rows if t['state'] in ACTIVE]
    blocked = [t for t in active if t['state']=='blocked' or t['waiting_on']]
    overdue = [t for t in active if t['deadline'] is not None and t['deadline'] < now]
    upcoming = [t for t in active if t['deadline'] is not None and now <= t['deadline'] <= now+3*86400]
    urgent = [t for t in active if t['urgent']]
    completed = sum(t['state']=='done' for t in rows)
    ready = [t for t in active if t not in blocked and t['mine']]
    ready.sort(key=lambda t:(not t['urgent'],t['deadline'] if t['deadline'] is not None else float('inf'),-t['priority'],t['id']))
    status = ('empty' if not rows else 'complete' if not active else 'blocked' if blocked else
              'attention' if overdue or urgent else 'active')
    return dict(project=project['id'],name=project['name'],area=project['area'],user_created=bool(project['user_created']),
                status=status,suggested=suggested,my_active=sum(t['mine'] for t in active),brief=project_brains.context(db,project['id'])[0],active=len(active),completed=completed,total=len(rows),
                blocked=len(blocked),overdue=len(overdue),upcoming=len(upcoming),urgent=len(urgent),
                next_task=ready[0] if ready else None,blockers=blocked[:10],
                deadlines=sorted(overdue+upcoming,key=lambda t:(t['deadline'],t['id']))[:10],tasks=rows)


def refresh(db, now=None):
    """Cheap fact checks; write only once per interval or when a project's facts change."""
    now = time.time() if now is None else now
    initialize(db)
    with db:
        db.execute('DELETE FROM project_tracker WHERE project NOT IN (SELECT id FROM project)')
        for project in tagging.projects(db):
            snapshot = _snapshot(db, project, now)
            encoded = json.dumps(snapshot,sort_keys=True)
            fingerprint = hashlib.sha256(encoded.encode()).hexdigest()
            old = db.execute('SELECT * FROM project_tracker WHERE project=?',(project['id'],)).fetchone()
            if old and old['fingerprint']==fingerprint:
                if now-old['checked'] >= 30:
                    db.execute('UPDATE project_tracker SET checked=? WHERE project=?',(now,project['id']))
                continue
            changes = json.loads(old['changes']) if old else []
            if old:
                before = {t['id']:t for t in json.loads(old['snapshot'])['tasks']}
                after = {t['id']:t for t in snapshot['tasks']}
                for ident in sorted(before.keys() | after.keys()):
                    a,b = before.get(ident),after.get(ident)
                    if a == b:continue
                    kind = 'added' if a is None else 'removed' if b is None else 'completed' if b['state']=='done' and a['state']!='done' else 'updated'
                    changes.append(dict(task=ident,title=(b or a)['title'],kind=kind,at=now))
            db.execute('INSERT OR REPLACE INTO project_tracker VALUES(?,?,?,?,?,?)',
                       (project['id'],fingerprint,encoded,json.dumps(changes[-20:]),now,now))


def summaries(db, now=None, project=None):
    refresh(db,now)
    result=[]
    for row in db.execute('SELECT * FROM project_tracker ORDER BY project'):
        if project is not None and row['project'] != project:continue
        value=json.loads(row['snapshot']);value.pop('tasks')
        value.update(checked=row['checked'],changed=row['changed'],recent_changes=json.loads(row['changes'])[-5:])
        result.append(value)
    return sorted(result,key=lambda p:p['name'].casefold())


def notification_category(db, task):
    project=tagging.of_task(db,task) if task else None
    if not project:return None
    # Old repository buckets can still exist; never put an owner/repository path in the banner.
    name=project['name'].rsplit('/',1)[-1]
    return {'id':project['id'],'name':project['name'],'label':'#'+name}
