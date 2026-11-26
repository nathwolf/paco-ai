"""Versioned shared project facts; never transcripts, private messages or activity logs."""
import uuid
from urllib.parse import urlsplit

MODES={'execute','manage','review','decide','informed'}
FIELDS={'name','area','hints','objective','milestone','done_when','out_of_scope','roles','sources','decisions','stakeholders'}


def clean_brain(value):
    if not isinstance(value,dict) or set(value)-FIELDS:raise ValueError('Only structured project brief fields are accepted')
    result={}
    for field in FIELDS-{'roles','sources'}:
        text=value.get(field,'')
        limit={'name':60,'area':40,'hints':2000}.get(field,4000)
        if not isinstance(text,str) or len(text)>limit:raise ValueError('Invalid '+field)
        result[field]=text.strip()
    if not result['name']:raise ValueError('A project needs a name')
    roles=value.get('roles',[])
    if not isinstance(roles,list) or len(roles)>100:raise ValueError('Use up to 100 project roles')
    result['roles']=[];seen=set()
    for role in roles:
        if not isinstance(role,dict) or set(role)-{'id','person','mode','responsibilities','aliases'}:raise ValueError('Invalid role fields')
        ident=str(uuid.UUID(str(role['id'])))
        if ident in seen:raise ValueError('Duplicate role ID')
        seen.add(ident)
        if not isinstance(role.get('mode'),str) or role.get('mode') not in MODES:raise ValueError('Invalid project role')
        for field,limit in [('person',120),('responsibilities',2000)]:
            if not isinstance(role.get(field,''),str) or len(role.get(field,''))>limit:raise ValueError('Invalid role '+field)
        if not role.get('person','').strip():raise ValueError('Name the person for each role')
        aliases=role.get('aliases',[])
        if not isinstance(aliases,list) or len(aliases)>15 or any(not isinstance(a,str) or not 0<len(a)<=120 for a in aliases):raise ValueError('Invalid identity aliases')
        result['roles'].append(dict(id=ident,person=role['person'].strip(),mode=role['mode'],responsibilities=role.get('responsibilities','').strip(),aliases=aliases))
    sources=value.get('sources',[])
    if not isinstance(sources,list) or len(sources)>50:raise ValueError('Use up to 50 project source links')
    result['sources']=[]
    for source in sources:
        if not isinstance(source,str) or len(source)>2000:raise ValueError('Invalid source link')
        u=urlsplit(source)
        if u.scheme not in ('https','http') or not u.hostname or u.username or u.password:raise ValueError('Source links must be web addresses without credentials')
        result['sources'].append(source)
    return result
