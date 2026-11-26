"""Task-contract privacy, transactional writes, OAuth and two-way conflict tests."""
import asyncio
import base64
import hashlib
import json
from pathlib import Path
import re
import tempfile
import unittest
import uuid
from urllib.parse import urlencode,urlsplit,parse_qs
import app,company_sync,intake,paco
try:
    from server.store import Store,Conflict
    from server.main import create_app
    from starlette.testclient import TestClient
    SERVER=True
except ImportError:SERVER=False

@unittest.skipUnless(SERVER,'Install server/requirements.txt for company integration tests')
class Company(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.store=Store(self.root/'server.db');self.user=self.store.create_user('one','test-password-123');self.other=self.store.create_user('two','test-password-456')
        self.db=paco.connect(self.root/'local.db');app.initialize(self.db)
    def tearDown(self):self.db.close();self.tmp.cleanup()
    def task(self,title='Work',**changes):
        from task_contract import clean_task
        return dict(kind='task',id=str(uuid.uuid4()),revision=0,data=clean_task(dict(title=title,**changes)))
    def transport(self,path,data=None):
        if path.startswith('/api/changes'):return self.store.changes(self.user,int(path.split('=')[1]))
        if path=='/api/apply':
            try:return self.store.mutate(self.user,data['operations'],data['request_id'])
            except Conflict as e:raise company_sync.Conflict(str(e))
        raise AssertionError(path)
    def enable(self):
        with self.db:company_sync.save(self.db,'account',{'url':'https://paco.example','user':self.user})
    def test_atomicity_idempotency_and_cross_account_links(self):
        t=self.task();result=self.store.mutate(self.user,[t],'request-123')
        self.assertEqual(result,self.store.mutate(self.user,[t],'request-123'))
        self.assertIsNone(self.store.get(self.other,'task',t['id']))
        invalid=self.task(dependencies=[t['id']])
        with self.assertRaises(ValueError):self.store.mutate(self.other,[invalid],'request-456')
        self.assertEqual(self.store.listing(self.other,'task')['items'],[])
        with self.assertRaises(Conflict):self.store.mutate(self.user,[t],'different-req')
    def test_invalid_schema_and_cycles_rollback(self):
        t=self.task();t['data']['transcript']='PRIVATE'
        with self.assertRaises(ValueError):self.store.mutate(self.user,[t],'bad-fields')
        a,b=self.task(),self.task();a['data']['dependencies']=[b['id']];b['data']['dependencies']=[a['id']]
        with self.assertRaises(ValueError):self.store.mutate(self.user,[a,b],'cycle-request')
        self.assertEqual(self.store.listing(self.user,'task')['items'],[])
    def test_patch_retry_returns_receipt_after_an_unrelated_edit(self):
        task=self.task('Original');self.store.mutate(self.user,[task],'initial-task')
        task['revision']=1;task['data']['title']='Corrected'
        intent={'id':task['id'],'revision':1,'changes':{'title':'Corrected'}}
        receipt=self.store.mutate(self.user,[task],'patch-request',intent=intent)
        task['revision']=2;task['data']['priority']=1
        self.store.mutate(self.user,[task],'later-priority')
        self.assertEqual(self.store.mutate(self.user,[task],'patch-request',intent=intent),receipt)
        self.assertEqual(self.store.get(self.user,'task',task['id'])['data']['priority'],1)
    def test_sync_transfers_only_task_allowlist(self):
        self.enable()
        with self.db:
            self.db.execute("INSERT INTO task(title,priority,state,due) VALUES('Public work',3,'open',10)")
            self.db.execute("INSERT INTO evidence(id,source,source_key,text,task) VALUES('secret','meeting','m','PRIVATE TRANSCRIPT',1)")
            self.db.execute("INSERT INTO preference VALUES('private_activity','PRIVATE ACTIVITY')")
        company_sync.sync(self.db,self.transport)
        remote=self.store.listing(self.user,'task')['items']
        self.assertEqual(remote[0]['data']['title'],'Public work')
        self.assertNotIn('PRIVATE',json.dumps(remote))
        t=remote[0];t['data']['title']='Edited in ChatGPT'
        self.store.mutate(self.user,[{k:v for k,v in t.items() if k!='updated'}],'remote-edit-1')
        company_sync.sync(self.db,self.transport)
        self.assertEqual(self.db.execute('SELECT title FROM task').fetchone()[0],'Edited in ChatGPT')
    def test_offline_retry_does_not_duplicate_remote_commit(self):
        self.enable()
        with self.db:self.db.execute("INSERT INTO task(title,priority,state,due) VALUES('One task',3,'open',10)")
        calls=[]
        def flaky(path,data=None):
            result=self.transport(path,data)
            if path=='/api/apply' and not calls:calls.append(1);raise OSError('response lost')
            return result
        company_sync.sync(self.db,flaky)
        self.assertEqual(company_sync.status(self.db)['pending'],1)
        company_sync.sync(self.db,self.transport)
        self.assertEqual(len(self.store.listing(self.user,'task')['items']),1)
        self.assertEqual(company_sync.status(self.db)['pending'],0)
    def test_conflicting_edits_are_not_silently_overwritten(self):
        self.enable();t=self.task('Original');self.store.mutate(self.user,[t],'initial-1')
        company_sync.sync(self.db,self.transport)
        with self.db:self.db.execute("UPDATE task SET title='Local edit'")
        remote=self.store.get(self.user,'task',t['id']);remote['data']['title']='Remote edit'
        self.store.mutate(self.user,[{k:v for k,v in remote.items() if k!='updated'}],'edit-remote-2')
        company_sync.sync(self.db,self.transport)
        self.assertEqual(self.db.execute('SELECT title FROM task').fetchone()[0],'Local edit')
        self.assertEqual(len(company_sync.status(self.db)['conflicts']),1)
        company_sync.resolve(self.db,t['id'],'remote')
        self.assertEqual(self.db.execute('SELECT title FROM task').fetchone()[0],'Remote edit')
    def test_project_plan_applies_once_with_parents_and_dependencies(self):
        plan={'projects':[{'ref':'p','name':'Launch','area':'Marketing'}],'tasks':[{'ref':'a','title':'Draft','project':'p'}, {'ref':'b','title':'Review','project':'p','depends_on':['a'],'parent':'a'}]}
        result=intake.preview(self.db,'Launch a project',{'provider':'fixture'},lambda *args:(plan,{}))
        applied=intake.apply(self.db,result['id'],result['plan'])
        self.assertEqual(applied,intake.apply(self.db,result['id'],result['plan']))
        self.assertEqual(self.db.execute('SELECT count(*) FROM task').fetchone()[0],2)
        self.assertEqual(self.db.execute('SELECT count(*) FROM dependency').fetchone()[0],1)
        operations=intake.remote_operations(result['plan'],self.user,'plan-request')
        self.assertEqual(len(self.store.mutate(self.user,operations,'plan-request')['items']),3)
    def test_large_offline_backlog_keeps_forward_dependencies(self):
        self.enable()
        with self.db:
            for i in range(215):self.db.execute("INSERT INTO task(title,priority,state,due) VALUES(?,3,'open',10)",(f'Work {i}',))
            self.db.execute('INSERT INTO dependency VALUES(1,215)')
        company_sync.sync(self.db,self.transport)
        self.assertIsNone(company_sync.status(self.db)['error'])
        first=self.store.listing(self.user,'task',limit=200)
        self.assertEqual(len(first['items']),200)
        self.assertEqual(len(self.store.listing(self.user,'task',first['next'])['items']),15)
    def test_unrelated_remote_edits_preserve_focus_and_local_title(self):
        self.enable()
        with self.db:self.db.execute("INSERT INTO task(title,priority,state,due) VALUES('Original',3,'focus',10)")
        company_sync.sync(self.db,self.transport)
        with self.db:self.db.execute("UPDATE task SET title='Local correction'")
        remote=self.store.listing(self.user,'task')['items'][0];remote['data']['priority']=1
        self.store.mutate(self.user,[{k:v for k,v in remote.items() if k!='updated'}],'remote-priority')
        company_sync.sync(self.db,self.transport)
        row=self.db.execute('SELECT title,state,priority FROM task').fetchone()
        self.assertEqual(tuple(row),('Local correction','focus',1))
        self.assertEqual(self.store.listing(self.user,'task')['items'][0]['data']['title'],'Local correction')
    def test_device_logout_disabled_accounts_and_backup(self):
        base='https://paco.example';asgi,store,auth=create_app(self.root/'device.db',base)
        uid=store.create_user('test','safe-test-password')
        with TestClient(asgi,base_url=base) as client:
            self.assertEqual(client.post('/api/login',json=[]).status_code,400)
            token=client.post('/api/login',json={'username':'test','password':'safe-test-password'}).json()['token']
            headers={'Authorization':'Bearer '+token}
            self.assertEqual(client.get('/api/changes',headers=headers).status_code,200)
            self.assertEqual(client.post('/api/logout',headers=headers,json={}).status_code,200)
            self.assertEqual(client.get('/api/changes',headers=headers).status_code,401)
            token=client.post('/api/login',json={'username':'test','password':'safe-test-password'}).json()['token']
            with store.db() as db:db.execute('UPDATE users SET active=0 WHERE id=?',(uid,))
            self.assertEqual(client.get('/api/changes',headers={'Authorization':'Bearer '+token}).status_code,401)
        backup=store.backup(self.root/'backups');restored=Store(backup)
        with restored.db() as db:self.assertEqual(db.execute('SELECT count(*) FROM users').fetchone()[0],1)
    def test_oauth_pkce_discovery_authenticated_mcp_and_revocation(self):
        base='https://paco.example';asgi,store,auth=create_app(self.root/'oauth.db',base)
        store.create_user('test','safe-test-password')
        with TestClient(asgi,base_url=base) as client:
            self.assertEqual(client.post('/mcp',json={}).status_code,401)
            metadata=client.get('/.well-known/oauth-protected-resource/mcp').json()
            discovery=client.get('/.well-known/oauth-authorization-server').json()
            self.assertIn('offline_access',discovery['scopes_supported'])
            self.assertEqual(metadata['resource'],base+'/mcp')
            self.assertIn('tasks.write',metadata['scopes_supported'])
            self.assertIn('offline_access',metadata['scopes_supported'])
            registration=client.post('/register',json={'client_name':'Test client','redirect_uris':['https://client.example/callback'],'token_endpoint_auth_method':'none','grant_types':['authorization_code','refresh_token'],'response_types':['code'],'scope':'tasks.read tasks.write'}).json()
            cid=registration['client_id'];verifier='v'*64
            challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
            params={'response_type':'code','client_id':cid,'redirect_uri':'https://client.example/callback','scope':'tasks.read tasks.write','state':'state123','code_challenge':challenge,'code_challenge_method':'S256','resource':base+'/mcp'}
            page=client.get('/authorize?'+urlencode(params));self.assertEqual(page.status_code,200,page.text)
            csrf=re.search('name="csrf" value="([^"]+)"',page.text)[1]
            bad=client.post(page.url,data={'username':'test','password':'safe-test-password','csrf':'wrong'},headers={'Origin':base},follow_redirects=False)
            self.assertEqual(bad.status_code,403)
            login=client.post(page.url,data={'username':'test','password':'safe-test-password','csrf':csrf},headers={'Origin':base},follow_redirects=False)
            self.assertEqual(login.status_code,303,login.text)
            callback=parse_qs(urlsplit(login.headers['location']).query);self.assertEqual(callback['state'],['state123']);code=callback['code'][0]
            token_data={'grant_type':'authorization_code','client_id':cid,'code':code,'redirect_uri':params['redirect_uri'],'code_verifier':verifier,'resource':base+'/mcp'}
            bad=client.post('/token',data=dict(token_data,code_verifier='x'*64));self.assertEqual(bad.status_code,400)
            token=client.post('/token',data=token_data);self.assertEqual(token.status_code,200,token.text);token=token.json()
            self.assertEqual(client.post('/token',data=token_data).status_code,400)
            headers={'Authorization':'Bearer '+token['access_token'],'Accept':'application/json, text/event-stream'}
            init=client.post('/mcp',headers=headers,json={'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-11-25','capabilities':{},'clientInfo':{'name':'test','version':'1'}}})
            self.assertEqual(init.status_code,200,init.text)
            listing=client.post('/mcp',headers=headers,json={'jsonrpc':'2.0','id':2,'method':'tools/list','params':{}}).json()
            self.assertIn('plan_apply',[t['name'] for t in listing['result']['tools']])
            refresh=client.post('/token',data={'grant_type':'refresh_token','client_id':cid,'refresh_token':token['refresh_token'],'resource':base+'/mcp'})
            self.assertEqual(refresh.status_code,200,refresh.text)
            self.assertEqual(client.get('/api/changes',headers=headers).status_code,401)
            self.assertEqual(client.post('/token',data={'grant_type':'refresh_token','client_id':cid,'refresh_token':token['refresh_token']}).status_code,400)

if __name__=='__main__':unittest.main()
