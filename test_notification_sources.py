"""Notification origin and compact payload regressions."""
import unittest
from pathlib import Path
import links, app, tagging, company_sync
from test_tagging import CatalogFixture
from task_contract import clean_task

class Sources(CatalogFixture, unittest.TestCase):
    def test_source_stays_github_after_message_update(self):
        task=self.task('Review login changes','https://github.com/optimai/quila/issues/17')
        with self.db:
            self.db.execute("INSERT INTO evidence(id,source,source_key,text,task,at) VALUES('update','mattermost','m','done',?,100)",(task,))
        self.assertEqual(links.source_for_task(self.db,task)['id'],'github')
        self.project('optimai/quila','quila')
        value=app.banner_payload(self.db,{'task':task,'message':'Check: Review login changes','mood':'friendly','reason':'Due','created':0},now=1)
        self.assertEqual(value['title'],'Review login changes')
        self.assertEqual(value['source']['id'],'github')
        self.assertNotIn('optimai/quila',str(value['badges']))
        self.assertNotIn('project',value)

    def test_calendar_origin_and_remote_chatgpt_link(self):
        task=self.task('Join planning')
        with self.db:self.db.execute("INSERT INTO discovered VALUES('calendar:work','evt',?,0)",(task,))
        self.assertEqual(links.source_for_task(self.db,task)['id'],'calendar')
        remote=self.task('Follow up')
        with self.db:self.db.execute('INSERT INTO company_task_fields VALUES(?,?)',(remote,'https://chatgpt.com/c/example'))
        self.assertEqual(links.source_for_task(self.db,remote)['id'],'chatgpt')
        with self.db:self.db.execute('UPDATE company_task_fields SET source_url=? WHERE task=?',('https://chatgpt.com.evil.test/c/x',remote))
        self.assertNotEqual(links.source_for_task(self.db,remote)['id'],'chatgpt')

    def test_sync_does_not_pin_unassigned_or_automatic_tasks(self):
        task=self.task('Prepare invoice')
        data=clean_task({'title':'Prepare invoice'})
        with self.db:company_sync.apply_local(self.db,'task',task,data)
        self.assertIsNone(self.db.execute('SELECT * FROM task_project WHERE task=?',(task,)).fetchone())
        project=self.project('Finance','invoice')
        with self.db:
            self.db.execute("INSERT INTO company_link(kind,local,remote,revision,base) VALUES('project',?,'project-remote',1,'{}')",(project,))
            data['project_id']='project-remote'
            # Valid UUID is required by the contract.
            data['project_id']='11111111-1111-4111-8111-111111111111'
            self.db.execute('UPDATE company_link SET remote=? WHERE local=?',(data['project_id'],project))
            company_sync.apply_local(self.db,'task',task,data)
        self.assertEqual(tagging.of_task(self.db,task)['how'],'rule')
        with self.db:
            data['project_id']=None
            company_sync.apply_local(self.db,'task',task,data)
        self.assertEqual(self.db.execute('SELECT how FROM task_project WHERE task=?',(task,)).fetchone()[0],'manual')

    def test_every_source_has_asset(self):
        import struct
        for source in links.SOURCE_LABELS:
            content=(Path(__file__).parent/'assets'/'sources'/(source+'.png')).read_bytes()
            self.assertEqual(content[:8], b'\x89PNG\r\n\x1a\n')
            self.assertEqual(struct.unpack('>II',content[16:24]),(48,48))
