"""Paco company task API and authenticated Streamable HTTP MCP."""
import argparse
import json
import os
from pathlib import Path
import sys
import time
import uuid
from urllib.parse import urlsplit
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from server.store import Store,Conflict
from server.auth import Auth,SCOPES
from task_contract import clean_task,clean_project,identifier
from mcp.server.fastmcp import FastMCP
from mcp.server.auth.settings import AuthSettings,ClientRegistrationOptions,RevocationOptions
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.routes import create_protected_resource_routes
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from starlette.responses import JSONResponse,HTMLResponse
from starlette.middleware import Middleware
from starlette.middleware.trustedhost import TrustedHostMiddleware


def create_app(path,base):
    base=base.rstrip('/');store=Store(path);auth=Auth(store,base)
    server=FastMCP('Paco',instructions='Internal company task manager. Each account sees only its own tasks. Read current projects before cataloging work. Turn pasted briefs into concrete tasks and dependencies; separate suggestions from commitments. Never send raw transcripts, activity history or audio. Preview a breakdown and obtain user agreement before applying it.',
        auth_server_provider=auth,auth=AuthSettings(issuer_url=base,resource_server_url=base+'/mcp',validate_token_resource=True,
        required_scopes=['tasks.read'],client_registration_options=ClientRegistrationOptions(enabled=True,valid_scopes=SCOPES,default_scopes=SCOPES),revocation_options=RevocationOptions(enabled=True)),
        stateless_http=True,json_response=True,max_request_body_size=256*1024,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=True,allowed_hosts=[urlsplit(base).netloc,'localhost:*','127.0.0.1:*'],allowed_origins=[base]))
    def owner(write=False):
        token=get_access_token()
        if not token or not token.subject or ('tasks.write' if write else 'tasks.read') not in token.scopes:raise PermissionError('Sign in to Paco with the required task scope')
        return token.subject
    read=ToolAnnotations(readOnlyHint=True,destructiveHint=False,openWorldHint=False)
    write=ToolAnnotations(readOnlyHint=False,destructiveHint=False,idempotentHint=True,openWorldHint=False)
    @server.tool(annotations=read)
    def tasks_list(after:str='',limit:int=100)->dict:
        """List your tasks with project IDs, deadlines, parents, dependencies and revisions. Follow next for pagination."""
        return store.listing(owner(),'task',after,limit)
    @server.tool(annotations=read)
    def task_get(id:str)->dict:
        """Read one of your tasks before editing. Its revision is required for updates."""
        value=store.get(owner(),'task',id)
        if not value:raise ValueError('Task not found')
        return value
    @server.tool(annotations=read)
    def projects_list(after:str='',limit:int=100)->dict:
        """List your project catalog and areas. Reuse existing projects where appropriate."""
        return store.listing(owner(),'project',after,limit)
    @server.tool(annotations=write)
    def task_create(title:str,request_id:str,description:str='',project_id:str|None=None,assignee:str='',deadline:float|None=None,estimate_minutes:int=30)->dict:
        """Create an explicitly requested task. request_id is a unique stable UUID for safe retries. Deadline is UTC Unix seconds; do not invent dates or owners."""
        who=owner(True);ident=str(uuid.uuid5(uuid.UUID(who),'task:'+request_id))
        data=clean_task(dict(title=title,description=description,project_id=project_id,assignee=assignee,deadline=deadline,estimate_minutes=estimate_minutes))
        return store.mutate(who,[dict(kind='task',id=ident,revision=0,data=data)],request_id)
    @server.tool(annotations=write)
    def task_update(id:str,revision:int,changes:dict,request_id:str)->dict:
        """Update your task after reading its revision. Allowed fields: title, description, status (open/done/blocked/archived/cancelled), priority (1-5), urgent, project_id, assignee, deadline, remind_at, estimate_minutes, goal, parent_id, dependencies, tags, source_url. No activity or meeting text."""
        who=owner(True);current=store.get(who,'task',id)
        if not current:raise ValueError('Task not found')
        patch=clean_task(changes,partial=True);data=dict(current['data'],**patch)
        return store.mutate(who,[dict(kind='task',id=id,revision=revision,data=data)],request_id,
                            intent={'kind':'task','id':id,'revision':revision,'changes':patch})
    @server.tool(annotations=write)
    def project_create(name:str,request_id:str,area:str='',hints:str='')->dict:
        """Create a project and optional area after checking the existing catalog. Hints are comma-separated identifying phrases, domains or repository paths."""
        who=owner(True);ident=str(uuid.uuid5(uuid.UUID(who),'project:'+request_id))
        return store.mutate(who,[dict(kind='project',id=ident,revision=0,data=clean_project(dict(name=name,area=area,hints=hints)))],request_id)
    @server.tool(annotations=read)
    def plan_format()->dict:
        """Read the structured project-breakdown format before proposing a batch. Paste source text into the conversation, not into this server."""
        return {'schema_version':1,'format':{'projects':[{'ref':'p1','name':'Launch','area':'Marketing','hints':'launch'}],
            'tasks':[{'ref':'t1','title':'Draft launch copy','description':'A concrete next step','project':'p1 or existing project UUID','parent':None,'depends_on':[],
                      'assignee':'Only when explicit','deadline':None,'estimate_minutes':30,'priority':3,'urgent':False,'tags':[]}],
            'questions':['Unresolved ownership or scope']},'max_tasks':80,'dates':'UTC Unix seconds, only explicit deadlines','privacy':'No transcripts, activity history or pasted source text.'}
    @server.tool(annotations=read)
    def plan_preview(plan:dict)->dict:
        """Validate a proposed project/task breakdown without creating work. Show tasks and unresolved questions to the user before plan_apply."""
        from intake import validate_plan
        value=validate_plan(plan,existing_projects={p['id'] for p in store.listing(owner(),'project',limit=200)['items']})
        return {'plan':value,'task_count':len(value['tasks']),'requires_confirmation':True}
    @server.tool(annotations=write)
    def plan_apply(plan:dict,request_id:str)->dict:
        """Apply the user's approved structured breakdown atomically. Use the plan returned by plan_preview and a stable unique request_id. Does not store the pasted brief."""
        from intake import remote_operations
        who=owner(True)
        operations=remote_operations(plan,who,request_id,{p['id'] for p in store.listing(who,'project',limit=200)['items']})
        return store.mutate(who,operations,request_id)
    @server.custom_route('/health',methods=['GET'])
    async def health(request):return JSONResponse({'ok':True,'service':'paco','schema_version':1})
    @server.custom_route('/',methods=['GET'])
    async def home(request):return HTMLResponse('<!doctype html><title>Paco</title><h1>Paco · Internal task service</h1><p>Connect your company account from Paco settings or ChatGPT. MCP endpoint: /mcp.</p><p>Meeting transcripts and activity stay on your Mac. Accounts are created by your administrator.</p>')
    server.custom_route('/login',methods=['GET','POST'])(auth.login)
    @server.custom_route('/api/login',methods=['POST'])
    async def device_login(request):
        data=await request.json()
        if not isinstance(data,dict):raise ValueError('Expected a JSON object')
        name=str(data.get('username',''))[:80]
        if not store.limit('login:'+name.casefold(),10) or not store.limit('login-global',100):return JSONResponse({'error':'Too many attempts; wait 15 minutes'},429)
        user=store.authenticate(name,str(data.get('password',''))[:512])
        if not user:return JSONResponse({'error':'Incorrect username or password'},401)
        with store.db() as db:token=auth.issue(db,user['id'],'paco-desktop',SCOPES,device=True)
        return JSONResponse({'token':token.access_token,'expires_in':token.expires_in,'user':{'id':user['id'],'username':user['username']}})
    @server.custom_route('/api/logout',methods=['POST'])
    async def device_logout(request):
        owner();await auth.revoke_token(get_access_token())
        return JSONResponse({'ok':True})
    @server.custom_route('/api/changes',methods=['GET'])
    async def changes(request):return JSONResponse(store.changes(owner(),int(request.query_params.get('after',0))))
    @server.custom_route('/api/entities/{kind}',methods=['GET'])
    async def entities(request):return JSONResponse(store.listing(owner(),request.path_params['kind'],request.query_params.get('after',''),200))
    @server.custom_route('/api/apply',methods=['POST'])
    async def apply(request):
        who=owner(True);data=await request.json()
        if not isinstance(data,dict):raise ValueError('Expected a JSON object')
        return JSONResponse(store.mutate(who,data['operations'],data['request_id']))
    app=server.streamable_http_app()
    # The SDK derives advertised scopes from required_scopes. Reading is the
    # minimum permission, but clients must discover writing and refresh access too.
    app.routes[:] = [r for r in app.routes if getattr(r, 'path', '') != '/.well-known/oauth-protected-resource/mcp']
    app.routes.extend(create_protected_resource_routes(
        resource_url=base+'/mcp', authorization_servers=[base+'/'], scopes_supported=SCOPES))
    app.add_middleware(TrustedHostMiddleware,allowed_hosts=[urlsplit(base).hostname,'localhost','127.0.0.1'])
    async def permission(request,exc):return JSONResponse({'error':'Sign in to your Paco account'},401)
    async def conflict(request,exc):return JSONResponse({'error':str(exc)},409)
    async def bad(request,exc):return JSONResponse({'error':str(exc)},400)
    async def missing(request,exc):return JSONResponse({'error':'Missing required field'},400)
    app.exception_handlers.update({PermissionError:permission,Conflict:conflict,ValueError:bad,KeyError:missing})
    return Guard(app,store),store,auth

class Guard:
    def __init__(self,app,store):self.app=app;self.store=store
    async def __call__(self,scope,receive,send):
        if scope['type']!='http':return await self.app(scope,receive,send)
        headers=dict(scope['headers']);size=0
        async def limited():
            nonlocal size
            message=await receive();size+=len(message.get('body',b''))
            if size>256*1024:raise ValueError('Request too large')
            return message
        async def secure(message):
            if message['type']=='http.response.start':
                message['headers']+= [(b'cache-control',b'no-store'),(b'x-content-type-options',b'nosniff'),(b'referrer-policy',b'no-referrer'),(b'x-frame-options',b'DENY'),(b'content-security-policy',b"default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'")]
            await send(message)
        try:
            if int(headers.get(b'content-length',b'0'))>256*1024:return await JSONResponse({'error':'Request too large'},413)(scope,receive,secure)
        except ValueError:return await JSONResponse({'error':'Invalid length'},400)(scope,receive,secure)
        await self.app(scope,limited,secure)

if __name__=='__main__':
    os.umask(0o077)
    import uvicorn
    parser=argparse.ArgumentParser();parser.add_argument('--db',required=True)
    address=parser.add_mutually_exclusive_group(required=True);address.add_argument('--base');address.add_argument('--base-file')
    parser.add_argument('--port',type=int,default=8765);a=parser.parse_args()
    base=a.base or Path(a.base_file).read_text().strip()
    if urlsplit(base).scheme!='https' or not urlsplit(base).hostname:parser.error('A public HTTPS address is required')
    app,store,auth=create_app(a.db,base);store.prune()
    uvicorn.run(app,host='127.0.0.1',port=a.port,access_log=False,proxy_headers=False,log_level='warning')
