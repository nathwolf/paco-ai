"""Project isolation, deadlines, dependency blockers and durable progress tracking."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import app, paco, project_tracking, tagging, workspace

class Trackers(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'db';self.db=paco.connect(self.path);self.addCleanup(self.db.close);app.initialize(self.db)
        self.oles=tagging.save_project(self.db,{'name':'oles'})
        self.quila=tagging.save_project(self.db,{'name':'quila'})
        self.now=1800000000
    def task(self,title,project,**fields):
        return workspace.edit_task(self.db,{'changes':dict(title=title,project=project,**fields)})['id']
    def tracker(self,project,now=None):return project_tracking.summaries(self.db,self.now if now is None else now,project)[0]
    def test_projects_have_independent_trackers_and_empty_is_not_done(self):
        self.task('Solver release',self.oles,deadline=self.now-1,urgent=True)
        first=self.tracker(self.oles);second=self.tracker(self.quila)
        self.assertEqual((first['active'],first['overdue'],first['urgent'],first['status']),(1,1,1,'attention'))
        self.assertEqual((second['total'],second['status']),(0,'empty'))
        self.assertEqual(self.db.execute('SELECT count(*) FROM project_tracker').fetchone()[0],2)
        self.assertNotIn('Solver release',json.dumps(second))
    def test_completed_and_dependency_blocked_tasks_are_distinguished(self):
        prerequisite=self.task('External approval',self.quila)
        blocked=self.task('Ship solver',self.oles,deadline=self.now+100)
        ready=self.task('Write release notes',self.oles)
        with self.db:self.db.execute('INSERT INTO dependency VALUES(?,?)',(blocked,prerequisite))
        before=self.tracker(self.oles)
        self.assertEqual((before['blocked'],before['upcoming'],before['next_task']['id']),(1,1,ready))
        self.assertEqual(before['blockers'][0]['waiting_on'][0]['id'],prerequisite)
        with self.db:self.db.execute("UPDATE task SET state='done' WHERE id=?",(prerequisite,))
        after=self.tracker(self.oles,self.now+1)
        self.assertEqual(after['blocked'],0);self.assertEqual(after['next_task']['id'],blocked)
        with self.db:self.db.execute("UPDATE task SET state='done' WHERE id IN (?,?)",(blocked,ready))
        final=self.tracker(self.oles,self.now+2)
        self.assertEqual((final['completed'],final['active'],final['status']),(2,0,'complete'))
        self.assertEqual(final['recent_changes'][-1]['kind'],'completed')
    def test_time_crossing_deadline_is_detected_without_task_edits(self):
        self.task('Review',self.oles,deadline=self.now+10)
        self.assertEqual(self.tracker(self.oles)['overdue'],0)
        self.assertEqual(self.tracker(self.oles,self.now+11)['overdue'],1)
    def test_rename_move_and_delete_are_reflected(self):
        task=self.task('Prepare notes',self.oles);self.tracker(self.oles)
        tagging.tag(self.db,task,self.quila)
        self.assertEqual(self.tracker(self.oles,self.now+1)['active'],0)
        self.assertEqual(self.tracker(self.quila,self.now+1)['active'],1)
        tagging.save_project(self.db,{'id':self.quila,'name':'quila launch'})
        self.assertEqual(self.tracker(self.quila)['name'],'quila launch')
        tagging.delete_project(self.db,self.oles);project_tracking.refresh(self.db,self.now)
        self.assertIsNone(self.db.execute('SELECT 1 FROM project_tracker WHERE project=?',(self.oles,)).fetchone())
    def test_snapshots_persist_and_checks_do_not_invent_changes(self):
        self.task('Prepare notes',self.oles);first=self.tracker(self.oles)
        second=self.tracker(self.oles,self.now+60)
        self.assertEqual(first['changed'],second['changed']);self.assertEqual(second['recent_changes'],[])
        self.assertEqual(second['checked'],self.now+60)
        other=paco.connect(self.path)
        try:self.assertEqual(json.loads(other.execute('SELECT snapshot FROM project_tracker WHERE project=?',(self.oles,)).fetchone()[0])['active'],1)
        finally:other.close()
    def test_notification_has_short_category_without_repository_owner(self):
        task=self.task('Review solver',self.oles)
        value=app.banner_payload(self.db,{'task':task,'message':'Review solver','reason':'Due','mood':'friendly'},self.now)
        self.assertEqual(value['category']['label'],'#oles')
        tagging.save_project(self.db,{'id':self.oles,'name':'optimai/oles'})
        self.assertEqual(project_tracking.notification_category(self.db,task)['label'],'#oles')
        self.assertIsNone(project_tracking.notification_category(self.db,None))
    def test_chat_receives_current_project_context(self):
        self.task('Solver review',self.oles)
        with patch('app.settings',return_value={'model':{'provider':'ollama'}}), patch('app.models.complete',return_value=({'answer':'One known task.'},{})) as model:
            app.act(self.db,self.path,paco.connect,{'action':'chat','text':'How is oles doing?'})
        payload=model.call_args.args[2]
        self.assertEqual(next(t for t in payload['project_trackers'] if t['name']=='oles')['active'],1)
