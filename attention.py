"""Task admission and responsibility are checked separately from task completion."""
import json
import re
import time
import unicodedata
from email.utils import parseaddr

STATES={'accepted','suggested','reference','dismissed','duplicate'}
KINDS={'execute','review','decide','follow_up','informed'}


def initialize(db):
    db.executescript('''CREATE TABLE IF NOT EXISTS task_attention(
        task INTEGER PRIMARY KEY,status TEXT NOT NULL DEFAULT 'accepted',kind TEXT NOT NULL DEFAULT 'execute',
        reason TEXT NOT NULL DEFAULT '',duplicate_of INTEGER,source TEXT NOT NULL DEFAULT 'direct');
        CREATE TABLE IF NOT EXISTS attention_event(id INTEGER PRIMARY KEY,task INTEGER,action TEXT,reason TEXT,at REAL);''')


def normalize(value):
    value=unicodedata.normalize('NFKC',str(value or '')).strip().casefold()
    if value.startswith('@') and value.count('@')==1:return value[1:]
    address=parseaddr(value)[1]
    return address if '@' in address else value.lstrip('@')


def identities(db):
    row=db.execute("SELECT value FROM preference WHERE key='my_identities'").fetchone()
    return set(json.loads(row[0])) if row else set()


def add_identities(db,values):
    known=identities(db)|{normalize(v) for v in values if v}
    db.execute("INSERT OR REPLACE INTO preference VALUES('my_identities',?)",(json.dumps(sorted(known)),))


def configure(db,config):
    import company_sync
    account=company_sync.setting(db,'account') or {}
    values=[account.get('username'),account.get('user')]
    gh=config.get('github')
    if isinstance(gh,list) and len(gh)>1:values.append(gh[1])
    mm=config.get('connectors',{}).get('mattermost',{})
    values.extend([mm.get('username'),mm.get('user_id')])
    with db:add_identities(db,values)


def mine(db,person):
    return normalize(person) in identities(db)|{'me','myself','yo','self'}


def info(db,task):
    row=db.execute('SELECT * FROM task_attention WHERE task=?',(task,)).fetchone()
    return dict(row) if row else dict(task=task,status='accepted',kind='execute',reason='Explicit task or assigned source',duplicate_of=None,source='direct')


def record(db,task,status,reason='',source='direct',kind='execute',duplicate_of=None):
    if not isinstance(status,str) or not isinstance(kind,str) or status not in STATES or kind not in KINDS:raise ValueError('Invalid task admission')
    if duplicate_of==task:raise ValueError('A task cannot duplicate itself')
    db.execute('INSERT OR REPLACE INTO task_attention VALUES(?,?,?,?,?,?)',(task,status,kind,reason[:500],duplicate_of,source))


def eligible(db,task):
    """Urgency never makes somebody else's work your obligation."""
    import tagging
    if not tagging.repository_allowed(db,task):return False
    item=info(db,task)
    if item['status']!='accepted' or item['kind']=='informed':return False
    owner=db.execute('SELECT owner FROM ownership WHERE task=?',(task,)).fetchone()
    if owner and owner[0] and not mine(db,owner[0]):return False
    if item['source']!='direct' and item['reason']!='Your explicit choice':
        project=db.execute('SELECT project FROM task_project WHERE task=?',(task,)).fetchone()
        if project and project[0]:
            import project_brains
            roles=project_brains.context(db,project[0])[0]['my_roles']
            if roles and all(r['mode']=='informed' for r in roles):return False
            if roles and item['kind']=='execute' and not any(r['mode']=='execute' for r in roles):return False
    return True


def decision(db,task,choice):
    if not db.execute('SELECT 1 FROM task WHERE id=?',(task,)).fetchone():raise ValueError('Task not found')
    old=info(db,task)
    if choice not in ('accept','dismiss'):raise ValueError('Choose accept or dismiss')
    if choice=='accept':
        owner=db.execute('SELECT owner FROM ownership WHERE task=?',(task,)).fetchone()
        if owner and owner[0] and not mine(db,owner[0]):raise ValueError('This belongs to someone else. Edit its assignee only if you are taking responsibility.')
        if old['status']=='duplicate':raise ValueError('This is a linked duplicate. Open the original task.')
    with db:
        record(db,task,'accepted' if choice=='accept' else 'dismissed','Your explicit choice',old['source'],old['kind'])
        db.execute('INSERT INTO attention_event(task,action,reason,at) VALUES(?,?,?,?)',(task,choice,old['reason'],time.time()))


def find_duplicate(db,title,owner='',project=None,exclude=None,deadline=None):
    """Merge only exact substantive obligations with compatible ownership/category/date."""
    title=' '.join(unicodedata.normalize('NFKC',title).casefold().split())
    if len(title)<24:return None
    for row in db.execute('''SELECT t.id,t.title,t.state,o.owner,p.project,d.deadline FROM task t
        LEFT JOIN ownership o ON o.task=t.id LEFT JOIN task_project p ON p.task=t.id
        LEFT JOIN details d ON d.task=t.id ORDER BY t.id'''):
        if row['id']==exclude or ' '.join(unicodedata.normalize('NFKC',row['title']).casefold().split())!=title:continue
        if row['state'] not in ('open','focus','blocked'):continue
        if info(db,row['id'])['status']=='duplicate':continue
        if row['project']!=project:continue
        a,b=normalize(owner),normalize(row['owner'])
        if a!=b and not ((not a or mine(db,a)) and (not b or mine(db,b))):continue
        if deadline!=row['deadline']:continue
        return row['id']
    return None


def candidate(db,task,source,reason='Detected from a conversation; confirm that this is your commitment',kind='execute'):
    current=db.execute('SELECT t.title,o.owner,p.project,d.deadline FROM task t LEFT JOIN ownership o ON o.task=t.id LEFT JOIN task_project p ON p.task=t.id LEFT JOIN details d ON d.task=t.id WHERE t.id=?',(task,)).fetchone()
    duplicate=find_duplicate(db,current['title'],current['owner'],current['project'],task,current['deadline'])
    if duplicate:
        record(db,task,'duplicate','Same obligation already tracked',source,kind,duplicate)
        db.execute('UPDATE evidence SET task=? WHERE task=?',(duplicate,task))
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='mail_task'").fetchone():
            db.execute('UPDATE mail_task SET task=? WHERE task=?',(duplicate,task))
    else:record(db,task,'suggested',reason,source,kind)
    return duplicate or task


def migrate(db):
    """Reversible one-time cleanup; retain source evidence, history, and explicit user choices."""
    if db.execute("SELECT 1 FROM preference WHERE key='attention_migrated_v1'").fetchone():return
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='mail_task'").fetchone():
        import mail_reasoning
        mail_reasoning.initialize(db)
    with db:
        # Legacy email tasks carry the mailbox identity; this is not inferred from names.
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='gmail_work'").fetchone():
            add_identities(db,[r[0] for r in db.execute('SELECT DISTINCT owner FROM gmail_work')])
        for row in db.execute("SELECT id FROM task WHERE state IN ('open','focus','blocked') ORDER BY id").fetchall():
            task=row[0]
            if db.execute('SELECT 1 FROM task_attention WHERE task=?',(task,)).fetchone():continue
            if db.execute("SELECT 1 FROM intervention WHERE task=? AND action IN ('start','snooze','resume','done')",(task,)).fetchone():continue
            discovery=db.execute('SELECT source FROM discovered WHERE task_id=?',(task,)).fetchone() if db.execute("SELECT 1 FROM sqlite_master WHERE name='discovered'").fetchone() else None
            if discovery and discovery[0] in ('github','github_reviews'):
                record(db,task,'accepted','Assigned source',discovery[0],'review' if discovery[0]=='github_reviews' else 'execute');continue
            if discovery and discovery[0] in ('calendar','apple_calendar','outlook_calendar'):
                record(db,task,'reference','Calendar event; no preparation commitment was established','calendar');continue
            source=db.execute("SELECT source FROM evidence WHERE task=? AND deleted=0 AND source IN ('gmail','mattermost') ORDER BY at LIMIT 1",(task,)).fetchone()
            if source:
                if source[0]=='mattermost' and db.execute("SELECT 1 FROM sqlite_master WHERE name='mattermost_dm'").fetchone():
                    direct=db.execute("SELECT 1 FROM evidence e JOIN mattermost_dm d ON e.source_key LIKE d.account||'/'||d.post||'/%' WHERE e.task=? AND e.source='mattermost' AND d.state='sent'",(task,)).fetchone()
                    if direct:continue
                candidate(db,task,source[0])
        db.execute("INSERT INTO preference VALUES('attention_migrated_v1','yes')")


def self_commitment(quote, mine_message):
    return bool(mine_message and re.search(r"(?:^|[.!?]\s+)(?:I will|I['’]ll|voy a|me encargo|yo me ocupo|haré)\b",quote,re.I))


def reconcile_duplicates(db):
    """Retry exact matching after categorization; user decisions remain authoritative."""
    with db:
        rows=db.execute("SELECT a.task,a.source,a.kind FROM task_attention a JOIN task t ON t.id=a.task WHERE a.status='suggested' AND t.state IN ('open','focus','blocked') ORDER BY a.task").fetchall()
        for row in rows:candidate(db,row['task'],row['source'],kind=row['kind'])


def review_imported_assignments(db):
    """A tracker assignment is evidence to review, not proof of personal execution."""
    with db:
        db.execute("""UPDATE task_attention SET status='suggested',
            reason='Imported assignment; confirm your responsibility before reminders'
            WHERE source IN ('github','github_reviews') AND status='accepted'
            AND reason IN ('Assigned source','Assigned to your connected source account')""")
        if not db.execute("SELECT 1 FROM preference WHERE key='unconfirmed_owners_v1'").fetchone():
            for row in db.execute("""SELECT o.task,o.owner FROM ownership o JOIN task_attention a ON a.task=o.task
                WHERE a.status='suggested' AND a.source IN ('gmail','mattermost')
                AND a.reason='Detected from a conversation; confirm that this is your commitment'""").fetchall():
                if mine(db,row['owner']):db.execute("UPDATE ownership SET owner='' WHERE task=?",(row['task'],))
            db.execute("INSERT INTO preference VALUES('unconfirmed_owners_v1','yes')")


def corrections(db, config=None, limit=30):
    """Private task-level examples, never inferred company roles or raw source messages."""
    import models
    if config is not None and not (models.is_local(config) or 'chat' in config.get('allowed_sources',[])):return []
    return [dict(r) for r in db.execute("""SELECT t.title,p.name AS project,a.kind AS responsibility,
        COALESCE(o.owner,'') AS assignee,e.action AS correction,a.status AS current_status
        FROM attention_event e JOIN task t ON t.id=e.task
        LEFT JOIN task_attention a ON a.task=t.id LEFT JOIN ownership o ON o.task=t.id
        LEFT JOIN task_project tp ON tp.task=t.id LEFT JOIN project p ON p.id=tp.project
        WHERE e.action IN ('accept','dismiss','not_mine','reassign','role')
        AND e.id=(SELECT MAX(e2.id) FROM attention_event e2 WHERE e2.task=e.task
                  AND e2.action IN ('accept','dismiss','not_mine','reassign','role'))
        ORDER BY e.id DESC LIMIT ?""",(limit,))]
