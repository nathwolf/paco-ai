"""The explicit task-only wire contract. No meeting or activity records belong here."""
import math
import uuid
from urllib.parse import urlsplit

TASK_FIELDS = {'title','description','status','priority','urgent','project_id','assignee','deadline',
               'remind_at','estimate_minutes','goal','parent_id','dependencies','tags','source_url','intake_status','responsibility','duplicate_of'}
STATES = {'open','done','blocked','archived','cancelled'}


def identifier(value):
    try:return str(uuid.UUID(str(value)))
    except (ValueError,TypeError,AttributeError):raise ValueError('Expected a UUID') from None


def clean_task(data, partial=False):
    if not isinstance(data,dict) or set(data)-TASK_FIELDS:
        raise ValueError('Unknown task fields; only structured task data is accepted')
    defaults=dict(title='',description='',status='open',priority=3,urgent=False,project_id=None,assignee='',
                  deadline=None,remind_at=None,estimate_minutes=30,goal='',parent_id=None,dependencies=[],tags=[],source_url='',intake_status='accepted',responsibility='execute',duplicate_of=None)
    out={} if partial else defaults
    for key,value in data.items():
        if key in ('title','description','assignee','goal','source_url'):
            limit={'title':500,'description':6000,'assignee':120,'goal':1000,'source_url':2000}[key]
            if not isinstance(value,str) or len(value)>limit:raise ValueError('Invalid '+key)
            out[key]=value.strip()
        elif key=='intake_status':
            if not isinstance(value,str) or value not in ('accepted','suggested','reference','dismissed','duplicate'):raise ValueError('Invalid intake status')
            out[key]=value
        elif key=='responsibility':
            if not isinstance(value,str) or value not in ('execute','review','decide','follow_up','informed'):raise ValueError('Invalid responsibility')
            out[key]=value
        elif key=='status':
            if not isinstance(value,str) or value not in STATES:raise ValueError('Invalid status')
            out[key]=value
        elif key in ('priority','estimate_minutes'):
            if type(value) is not int or not 1<=value<=(5 if key=='priority' else 10080):raise ValueError('Invalid '+key)
            out[key]=value
        elif key=='urgent':
            if type(value) is not bool:raise ValueError('Urgent must be true or false')
            out[key]=value
        elif key in ('deadline','remind_at'):
            if value is not None and (type(value) not in (float,int) or not math.isfinite(value) or value<0 or value>32503680000):raise ValueError('Invalid timestamp')
            out[key]=value
        elif key in ('project_id','parent_id','duplicate_of'):
            out[key]=identifier(value) if value else None
        elif key=='dependencies':
            if not isinstance(value,list) or len(value)>80:raise ValueError('Invalid dependencies')
            out[key]=list(dict.fromkeys(identifier(x) for x in value))
        elif key=='tags':
            if not isinstance(value,list) or len(value)>20 or any(not isinstance(x,str) or not 0<len(x)<=60 for x in value):raise ValueError('Invalid tags')
            out[key]=list(dict.fromkeys(value))
    if ('title' in out and not out['title']):raise ValueError('A task needs a title')
    if out.get('source_url'):
        p=urlsplit(out['source_url'])
        if p.scheme not in ('http','https') or not p.hostname or p.username or p.password:raise ValueError('Invalid source URL')
    return out


def clean_project(data):
    if not isinstance(data,dict) or set(data)-{'name','area','hints'}:raise ValueError('Invalid project fields')
    if any(not isinstance(v,str) for v in data.values()):raise ValueError('Project fields must be text')
    out={k:data.get(k,'').strip() for k in ('name','area','hints')}
    if not 0<len(out['name'])<=60 or len(out['area'])>40 or len(out['hints'])>2000:raise ValueError('Invalid project')
    return out
