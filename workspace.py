"""Local workspace editing and focus sessions. No activity history is retained here."""
from contextlib import nullcontext
import json
import time
from task_contract import clean_task


def initialize(db):
    db.execute('''CREATE TABLE IF NOT EXISTS focus_session(id INTEGER PRIMARY KEY, intention TEXT NOT NULL,
        task INTEGER, started REAL NOT NULL, ends REAL NOT NULL, stopped REAL)''')


def active(db, now=None):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='focus_session'").fetchone():return None
    row=db.execute('SELECT * FROM focus_session WHERE stopped IS NULL AND ends>? ORDER BY id DESC LIMIT 1',
                   (time.time() if now is None else now,)).fetchone()
    return dict(row) if row else None


def start(db, data, now):
    minutes=data.get('minutes',25)
    intention=str(data.get('intention','')).strip()
    if type(minutes) is not int or not 1<=minutes<=240:raise ValueError('Choose 1–240 minutes')
    if not intention or len(intention)>500:raise ValueError('Describe your focus in up to 500 characters')
    task=data.get('task')
    if task is not None and not db.execute("SELECT 1 FROM task WHERE id=? AND state NOT IN ('done','archived','cancelled','incorrect')",(task,)).fetchone():raise ValueError('Choose an active task')
    with db:
        if active(db,now):raise ValueError('Finish your current focus session first')
        ident=db.execute('INSERT INTO focus_session(intention,task,started,ends) VALUES(?,?,?,?)',(intention,task,now,now+minutes*60)).lastrowid
    return {'id':ident}


def edit_task(db, data, commit=True):
    ident=int(data['id']) if data.get('id') is not None else None;changes=data.get('changes',{})
    allowed={'title','description','tags','priority','urgent','deadline','estimate_minutes','assignee','project'}
    if not isinstance(changes,dict) or set(changes)-allowed:raise ValueError('Unsupported task edit')
    fields=clean_task({k:v for k,v in changes.items() if k!='project'},partial=True)
    if ident is None and not fields.get('title'):raise ValueError('A task needs a title')
    project=changes.get('project')
    if project is not None and (type(project) is not int or not db.execute('SELECT 1 FROM project WHERE id=?',(project,)).fetchone()):raise ValueError('Unknown project')
    with (db if commit else nullcontext()):
        if ident is None:
            ident=db.execute("INSERT INTO task(title,priority,state,due) VALUES(?,?,'open',?)",(fields['title'],fields.get('priority',3),time.time())).lastrowid
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
        if 'assignee' in fields:db.execute("INSERT INTO ownership VALUES(?,?,'') ON CONFLICT(task) DO UPDATE SET owner=excluded.owner",(ident,fields['assignee']))
        previous_project = db.execute('SELECT project FROM task_project WHERE task=?', (ident,)).fetchone()
        if 'project' in changes and ((previous_project and previous_project['project'] != project) or (not previous_project and project is not None)):
            db.execute("INSERT OR REPLACE INTO task_project VALUES(?,?,'manual')",(ident,project))
            db.execute('DELETE FROM task_catalog WHERE task=?',(ident,))
    return {'ok':True,'id':ident}
