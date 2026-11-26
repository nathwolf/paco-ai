"""Local newline-delimited MCP. Per-client grants are rechecked on every operation."""
import json
import sys
import time
import workflows

TOOLS = {
 'tasks_list': ('tasks.read','List tasks',{'type':'object','properties':{}}),
 'task_create': ('tasks.write','Create a task',{'type':'object','properties':{'title':{'type':'string'}},'required':['title']}),
 'task_update': ('tasks.write','Edit a task',{'type':'object','properties':{'id':{'type':'integer'},'title':{'type':'string'},'state':{'type':'string'}},'required':['id']}),
 'memory_search': ('memory.read','Find cited personal context',{'type':'object','properties':{'query':{'type':'string'},'person':{'type':'string'},'project':{'type':'string'}}}),
 'context_pack': ('memory.read','Task evidence and details',{'type':'object','properties':{'id':{'type':'integer'}},'required':['id']}),
 'changes': ('tasks.read','Poll changes after a durable cursor',{'type':'object','properties':{'after':{'type':'integer'}}}),
 'session_status': ('sessions.read','Agent session status',{'type':'object','properties':{}}),
}


def initialize(db):
    db.execute('CREATE TABLE IF NOT EXISTS mcp_grant(client TEXT,scope TEXT,PRIMARY KEY(client,scope))')
    db.commit()


def grant(db, client, scopes):
    valid = {v[0] for v in TOOLS.values()}
    if set(scopes)-valid:
        raise ValueError('Unknown scope')
    with db:
        db.execute('DELETE FROM mcp_grant WHERE client=?',(client,))
        db.executemany('INSERT INTO mcp_grant VALUES(?,?)',((client,s) for s in scopes))


def dispatch(db, client, request):
    method, params = request.get('method'),request.get('params',{})
    if method == 'initialize':
        return {'protocolVersion':'2025-11-25','capabilities':{'tools':{}},'serverInfo':{'name':'paco','version':'0.2.0'}}
    if method == 'ping':
        return {}
    grants = {r[0] for r in db.execute('SELECT scope FROM mcp_grant WHERE client=?',(client,))}
    if method == 'tools/list':
        return {'tools':[{'name':name,'description':v[1],'inputSchema':v[2]} for name,v in TOOLS.items() if v[0] in grants]}
    if method != 'tools/call':
        raise ValueError('Unknown method')
    name,args = params.get('name'),params.get('arguments',{})
    if name not in TOOLS or TOOLS[name][0] not in grants:
        raise PermissionError('Client grant is missing or revoked')
    if name == 'tasks_list':
        result = [dict(r) for r in db.execute('SELECT * FROM task ORDER BY id LIMIT 200')]
    elif name == 'task_create':
        title = args['title'].strip()
        if not title or len(title)>500:
            raise ValueError('Invalid title')
        with db:
            ident = db.execute("INSERT INTO task(title,priority,state,due) VALUES(?,3,'open',?)",(title,time.time())).lastrowid
            workflows.changed(db,'task.created',{'id':ident})
        result = {'id':ident}
    elif name == 'task_update':
        workflows.correct_task(db,args['id'],**{k:v for k,v in args.items() if k!='id'})
        result = {'updated':args['id']}
    elif name == 'memory_search':
        result = workflows.search(db,**args)
    elif name == 'context_pack':
        import meetings
        result = [dict(r) for r in db.execute('SELECT * FROM evidence WHERE task=? AND deleted=0',(args['id'],))]
        result += [{'source':'meeting_note',**r} for r in meetings.task_context(db,args['id'])]
    elif name == 'changes':
        result = [dict(r) for r in db.execute('SELECT * FROM change_log WHERE id>? ORDER BY id LIMIT 100',(args.get('after',0),))]
    else:
        result = [dict(r) for r in db.execute('SELECT id,provider,status,result FROM agent_session ORDER BY created DESC LIMIT 20')]
    return {'content':[{'type':'text','text':json.dumps(result,ensure_ascii=False)}]}


def serve(db, client, stdin=None, stdout=None):
    initialize(db)
    stdin,stdout = stdin or sys.stdin,stdout or sys.stdout
    for line in stdin:
        request = None
        try:
            if len(line)>1024*1024:
                raise ValueError('Message too large')
            request = json.loads(line)
            if 'id' not in request:
                continue
            result = dispatch(db,client,request)
            reply = {'jsonrpc':'2.0','id':request['id'],'result':result}
        except Exception as exc:
            reply = {'jsonrpc':'2.0','id':request.get('id') if isinstance(request,dict) else None,
                     'error':{'code':-32600 if isinstance(exc,ValueError) else -32603,'message':str(exc) if isinstance(exc,(ValueError,PermissionError)) else 'Operation failed'}}
        stdout.write(json.dumps(reply)+'\n')
        stdout.flush()
