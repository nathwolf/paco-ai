import tempfile
import unittest
import uuid
from pathlib import Path
from starlette.testclient import TestClient
from server.main import create_app
from server.store import Store,Conflict
from server import brains
import app,paco,project_brains,tagging

class SharedBrains(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.store=Store(self.root/'server.db')
        self.nathalia=self.store.create_user('nathalia','test-password-123')
        self.juan=self.store.create_user('juan','test-password-456')
    def test_both_members_edit_and_stale_changes_do_not_overwrite(self):
        one=brains.save(self.store,self.nathalia,{'name':'oles','objective':'Ship the solver'},0,'create-oles')
        self.assertEqual(brains.listing(self.store,self.juan)['items'][0]['id'],one['id'])
        role={'id':str(uuid.uuid4()),'person':'juan','mode':'execute','responsibilities':'Implement solver changes'}
        two=brains.save(self.store,self.juan,dict(one['data'],roles=[role]),1,'juan-edit',one['id'])
        with self.assertRaises(Conflict):brains.save(self.store,self.nathalia,dict(one['data'],objective='Stale change'),1,'stale-edit',one['id'])
        self.assertEqual(brains.listing(self.store,self.nathalia)['items'][0]['data']['roles'][0]['person'],'juan')
        self.assertEqual(brains.save(self.store,self.juan,dict(one['data'],roles=[role]),1,'juan-edit',one['id']),two)
        with self.store.db() as db:self.assertEqual(db.execute('SELECT count(*) FROM brain_audit').fetchone()[0],2)
    def test_workspace_membership_and_private_tasks_remain_isolated(self):
        with self.store.db() as db:
            db.execute('INSERT INTO workspace VALUES(?,?)',('other','Other company'))
            db.execute('INSERT INTO workspace_member VALUES(?,?)',('other',self.juan))
        private=brains.save(self.store,self.juan,{'name':'Other workspace'},0,'other-brain',workspace='other')
        with self.assertRaises(PermissionError):brains.listing(self.store,self.nathalia,'other')
        with self.assertRaises(PermissionError):brains.save(self.store,self.nathalia,{'name':'Hijack'},1,'hijack-req',private['id'])
        self.assertEqual(self.store.listing(self.juan,'task')['items'],[])
        with self.store.db() as db:db.execute('DELETE FROM workspace_member WHERE user=?',(self.juan,))
        Store(self.root/'server.db')
        with self.assertRaises(PermissionError):brains.listing(self.store,self.juan)
    def test_private_raw_fields_are_rejected(self):
        for field in ['transcript','messages','activity','password']:
            with self.assertRaises(ValueError):brains.save(self.store,self.nathalia,{'name':'oles',field:'private'},0,'invalid-'+field)
    def test_two_mac_caches_share_stable_identity_and_preserve_roles(self):
        a=paco.connect(self.root/'a.db');b=paco.connect(self.root/'b.db');app.initialize(a);app.initialize(b)
        try:
            local=tagging.save_project(a,{'name':'oles'})
            def call(user):
                return lambda path,data=None:brains.listing(self.store,user) if data is None else brains.save(self.store,user,data['data'],data['revision'],data['request_id'],data.get('id'))
            saved=project_brains.save(a,{'name':'oles','objective':'Reliable solver'},local,0,'publish-oles',call(self.nathalia))
            project_brains.sync(b,call(self.juan));juan=project_brains.all_briefs(b)[0]
            self.assertEqual(juan['id'],saved['id'])
            project_brains.save(b,dict(juan['data'],milestone='Benchmark release'),juan['project'],juan['revision'],'juan-milestone',call(self.juan))
            project_brains.sync(a,call(self.nathalia));self.assertEqual(project_brains.get(a,local)['data']['milestone'],'Benchmark release')
            self.assertEqual(a.execute('SELECT count(*) FROM project').fetchone()[0],1)
        finally:a.close();b.close()
    def test_authenticated_http_api_and_revision_conflict(self):
        application,_,_=create_app(self.root/'server.db','https://paco.example')
        with TestClient(application,base_url='https://paco.example') as client:
            self.assertEqual(client.get('/api/project-brains').status_code,401)
            login=client.post('/api/login',json={'username':'nathalia','password':'test-password-123'}).json()
            headers={'Authorization':'Bearer '+login['token']}
            response=client.post('/api/project-brains',headers=headers,json={'revision':0,'request_id':'create-http','data':{'name':'HTTP project'}})
            self.assertEqual(response.status_code,200)
            self.assertEqual(client.get('/api/project-brains',headers=headers).json()['items'][0]['data']['name'],'HTTP project')
            self.assertEqual(client.post('/api/project-brains',headers=headers,json={'id':response.json()['id'],'revision':0,'request_id':'stale-http','data':{'name':'HTTP project'}}).status_code,409)
