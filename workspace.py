"""Local workspace editing and focus sessions. No activity history is retained here."""
from contextlib import nullcontext
import json
import time
from task_contract import clean_task


def initialize(db):
    db.executescript('''CREATE TABLE IF NOT EXISTS focus_session(id INTEGER PRIMARY KEY, intention TEXT NOT NULL,
        task INTEGER, started REAL NOT NULL, ends REAL NOT NULL, stopped REAL);
        CREATE TABLE IF NOT EXISTS focus_timing(session INTEGER PRIMARY KEY,duration REAL NOT NULL,
        remaining REAL NOT NULL,phase TEXT NOT NULL,break_minutes INTEGER NOT NULL DEFAULT 0,
        break_until REAL,completed_at REAL);''')
    with db:
        db.execute("""INSERT OR IGNORE INTO focus_timing(session,duration,remaining,phase,completed_at)
          SELECT id,MAX(0,ends-started),CASE WHEN stopped IS NULL THEN MAX(0,ends-started) ELSE MAX(0,ends-stopped) END,
          CASE WHEN stopped IS NULL THEN 'focus' WHEN stopped>=ends THEN 'completed' ELSE 'stopped' END,
          CASE WHEN stopped>=ends THEN ends ELSE NULL END FROM focus_session""")


def describe(row,now):
    item=dict(row);phase=item['phase'];remaining=item['remaining']
    if phase=='focus':
        remaining=max(0,item['ends']-now)
        if remaining==0:
            item['completed_at']=item['ends']
            item['break_until']=item['ends']+item['break_minutes']*60
            phase='break' if item['break_until']>now else 'completed'
    elif phase=='break' and item['break_until']<=now:
        phase='paused' if remaining>0 else 'completed'
    item.update(phase=phase,remaining=remaining,successful=item['completed_at'] is not None)
    item['focused_seconds']=item['duration'] if item['successful'] else max(0,item['duration']-remaining)
    return item


def history(db,now=None,limit=20):
    now=time.time() if now is None else now
    return [describe(r,now) for r in db.execute("""SELECT s.*,f.duration,f.remaining,f.phase,f.break_minutes,f.break_until,f.completed_at
        FROM focus_session s JOIN focus_timing f ON f.session=s.id ORDER BY s.id DESC LIMIT ?""",(limit,))]


def active(db, now=None):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='focus_timing'").fetchone():return None
    now=time.time() if now is None else now
    for item in history(db,now):
        if item['stopped'] is None and item['phase'] in ('focus','break','paused'):return item
    return None


def stats(db,now=None):
    now=time.time() if now is None else now
    rows=db.execute("""SELECT s.*,f.duration,f.remaining,f.phase,f.break_minutes,f.break_until,f.completed_at
        FROM focus_session s JOIN focus_timing f ON f.session=s.id
        WHERE s.ends>=? OR f.completed_at>=?""",(now-7*86400,now-7*86400))
    completed=[r for r in (describe(row,now) for row in rows) if r['completed_at'] is not None and now-7*86400<=r['completed_at']<=now]
    return dict(completed=len(completed),minutes=round(sum(r['duration'] for r in completed)/60),days=7)


def start(db, data, now):
    minutes=data.get('minutes',25);break_minutes=data.get('break_minutes',0)
    intention=str(data.get('intention','')).strip()
    if type(minutes) is not int or not 1<=minutes<=240:raise ValueError('Choose 1–240 minutes')
    if type(break_minutes) is not int or not 0<=break_minutes<=30:raise ValueError('Choose a break of up to 30 minutes')
    if not intention or len(intention)>500:raise ValueError('Describe your focus in up to 500 characters')
    task=data.get('task')
    if task is not None and not db.execute("SELECT 1 FROM task WHERE id=? AND state NOT IN ('done','archived','cancelled','incorrect')",(task,)).fetchone():raise ValueError('Choose an active task')
    with db:
        if not db.in_transaction:db.execute('BEGIN IMMEDIATE')
        if active(db,now):raise ValueError('Finish your current focus session first')
        ident=db.execute('INSERT INTO focus_session(intention,task,started,ends) VALUES(?,?,?,?)',(intention,task,now,now+minutes*60)).lastrowid
        db.execute("INSERT INTO focus_timing VALUES(?,?,?,'focus',?,NULL,NULL)",(ident,minutes*60,minutes*60,break_minutes))
    return {'id':ident}


def change_focus(db,ident,action,now,minutes=5):
    if action not in ('pause','resume','stop'):raise ValueError('Unknown focus action')
    with db:
        if not db.in_transaction:db.execute('BEGIN IMMEDIATE')
        row=db.execute("""SELECT s.*,f.duration,f.remaining,f.phase,f.break_minutes,f.break_until,f.completed_at
            FROM focus_session s JOIN focus_timing f ON f.session=s.id WHERE s.id=?""",(ident,)).fetchone()
        if not row:raise ValueError('Session not found')
        item=describe(row,now)
        if action=='stop':
            if item['stopped'] is not None:return {'ok':True}
            db.execute('UPDATE focus_session SET stopped=? WHERE id=?',(now,ident))
            db.execute('UPDATE focus_timing SET phase=?,remaining=?,completed_at=? WHERE session=?',
                       ('completed' if item['successful'] else 'stopped',item['remaining'],item['completed_at'],ident))
        elif action=='pause':
            if item['stopped'] is not None or item['phase']!='focus':raise ValueError('Only a running focus timer can pause')
            if type(minutes) is not int or not 1<=minutes<=30:raise ValueError('Choose a 1–30 minute break')
            db.execute("UPDATE focus_timing SET remaining=?,phase='break',break_until=? WHERE session=?",(item['remaining'],now+minutes*60,ident))
        else:
            if item['stopped'] is not None or item['phase'] not in ('break','paused') or item['remaining']<=0:raise ValueError('There is no unfinished focus time to resume')
            db.execute('UPDATE focus_session SET ends=? WHERE id=?',(now+item['remaining'],ident))
            db.execute("UPDATE focus_timing SET phase='focus',break_until=NULL WHERE session=?",(ident,))
    return {'ok':True}


def edit_task(db, data, commit=True):
    ident=int(data['id']) if data.get('id') is not None else None;changes=data.get('changes',{})
    allowed={'title','description','tags','priority','urgent','deadline','estimate_minutes','assignee','project','responsibility'}
    if not isinstance(changes,dict) or set(changes)-allowed:raise ValueError('Unsupported task edit')
    fields=clean_task({k:v for k,v in changes.items() if k!='project'},partial=True)
    if ident is None and not fields.get('title'):raise ValueError('A task needs a title')
    project=changes.get('project')
    if project is not None and (type(project) is not int or not db.execute('SELECT 1 FROM project WHERE id=?',(project,)).fetchone()):raise ValueError('Unknown project')
    with (db if commit else nullcontext()):
        if ident is None:
            ident=db.execute("INSERT INTO task(title,priority,state,due) VALUES(?,?,'open',?)",(fields['title'],fields.get('priority',3),time.time())).lastrowid
        if data.get('id') is None:
            import attention
            attention.record(db,ident,'accepted','Explicit task creation','direct')
        if not db.execute('SELECT 1 FROM task WHERE id=?',(ident,)).fetchone():raise ValueError('Unknown task')
        for key in ('title','priority'):
            if key in fields:db.execute(f'UPDATE task SET {key}=? WHERE id=?',(fields[key],ident))
        if 'title' in fields:db.execute('INSERT INTO task_override(task,title) VALUES(?,?) ON CONFLICT(task) DO UPDATE SET title=excluded.title',(ident,fields['title']))
        if 'urgent' in fields:db.execute('INSERT OR REPLACE INTO urgency VALUES(?,?)',(ident,fields['urgent']))
        old=db.execute('SELECT * FROM details WHERE task=?',(ident,)).fetchone()
        if 'deadline' in fields or 'estimate_minutes' in fields:
            db.execute('INSERT OR REPLACE INTO details VALUES(?,?,?,?)',(ident,old['goal'] if old else '',fields.get('estimate_minutes',old['minutes'] if old else 30),fields.get('deadline',old['deadline'] if old else None)))
        if 'description' in fields or 'tags' in fields:
            old=db.execute('SELECT * FROM task_extra WHERE task=?',(ident,)).fetchone()
            db.execute('INSERT OR REPLACE INTO task_extra VALUES(?,?,?,?)',(ident,fields.get('description',old['description'] if old else ''),old['parent'] if old else None,json.dumps(fields['tags']) if 'tags' in fields else old['tags'] if old else '[]'))
        if 'responsibility' in fields:
            import attention
            old_attention=attention.info(db,ident)
            attention.record(db,ident,old_attention['status'],old_attention['reason'],old_attention['source'],fields['responsibility'],old_attention['duplicate_of'])
        import attention
        for field,action in [('assignee','reassign'),('responsibility','role')]:
            if field not in fields or data.get('id') is None:continue
            old_owner=db.execute('SELECT owner FROM ownership WHERE task=?',(ident,)).fetchone()
            old_value=(old_owner[0] if old_owner else '') if field=='assignee' else old_attention['kind']
            if fields[field]!=old_value:
                db.execute('INSERT INTO attention_event(task,action,reason,at) VALUES(?,?,?,?)',
                           (ident,action,'Explicit task correction',time.time()))
        if 'assignee' in fields:db.execute("INSERT INTO ownership VALUES(?,?,'') ON CONFLICT(task) DO UPDATE SET owner=excluded.owner",(ident,fields['assignee']))
        previous_project = db.execute('SELECT project FROM task_project WHERE task=?', (ident,)).fetchone()
        if 'project' in changes and ((previous_project and previous_project['project'] != project) or (not previous_project and project is not None)):
            db.execute("INSERT OR REPLACE INTO task_project VALUES(?,?,'manual')",(ident,project))
            db.execute('DELETE FROM task_catalog WHERE task=?',(ident,))
    return {'ok':True,'id':ident}
