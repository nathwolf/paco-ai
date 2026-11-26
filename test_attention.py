import json
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import Mock
import app,attention,company_sync,discovery,mail_reasoning,paco,planning,project_brains,tagging,workspace
from test_mail_reasoning import message

class Attention(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'db';self.db=paco.connect(self.path);self.addCleanup(self.db.close);app.initialize(self.db)
        with self.db:attention.add_identities(self.db,['nathalia','nwolf','nathalia@example.test'])
    def task(self,title='Review the project launch document',**fields):
        return workspace.edit_task(self.db,{'changes':dict(title=title,**fields)})['id']
    def test_foreign_urgent_task_never_enters_reminders_or_plan(self):
        ident=self.task(assignee='Juan',urgent=True)
        self.assertFalse(attention.eligible(self.db,ident))
        self.assertIsNone(planning.ranked(self.db,time.time()).fetchone())
        self.assertEqual(planning.morning_plan(self.db,time.time()),[])
        self.assertFalse(app.state(self.db)['tasks'][0]['my_responsibility'])
    def test_identity_matching_is_exact_not_substring(self):
        self.assertTrue(attention.mine(self.db,'Nathalia <nathalia@example.test>'))
        self.assertTrue(attention.mine(self.db,'@nwolf'))
        self.assertFalse(attention.mine(self.db,'nathalia-other'))
        self.assertFalse(attention.mine(self.db,'juan'))
    def test_suggestion_accept_dismiss_and_urgency(self):
        task=self.task(assignee='nathalia',urgent=True)
        with self.db:attention.candidate(self.db,task,'gmail')
        self.assertFalse(attention.eligible(self.db,task))
        attention.decision(self.db,task,'accept');self.assertTrue(attention.eligible(self.db,task))
        attention.decision(self.db,task,'dismiss');self.assertFalse(attention.eligible(self.db,task))
        other=self.task('Juan must send the project report',assignee='Juan')
        with self.assertRaises(ValueError):attention.decision(self.db,other,'accept')
    def test_calendar_is_reference_and_imported_assignment_needs_confirmation(self):
        discovery.reconcile(self.db,'calendar',[('event1','Prepare for weekly meeting',time.time())],time.time())
        discovery.reconcile(self.db,'github',[('issue1','Fix the solver initialization problem',time.time())],time.time())
        values=app.state(self.db)['tasks'];bytitle={t['title']:t for t in values}
        self.assertFalse(bytitle['Prepare for weekly meeting']['my_responsibility'])
        self.assertEqual(bytitle['Prepare for weekly meeting']['attention']['status'],'reference')
        self.assertFalse(bytitle['Fix the solver initialization problem']['my_responsibility'])
        ident=bytitle['Fix the solver initialization problem']['id']
        attention.decision(self.db,ident,'accept')
        self.assertTrue(attention.eligible(self.db,ident))
    def test_cross_thread_duplicate_links_to_one_commitment(self):
        mail_reasoning.initialize(self.db)
        for index in ('1','2'):
            thread=dict(id='thread'+index,historyId=index,messages=[message(index,'Please review the final project budget.')])
            model=Mock(return_value={'actions':[dict(kind='add',title='Review the final project budget',message=index,quote='review the final project budget')]})
            mail_reasoning.analyze(self.db,thread,{},'nathalia@example.test',model)
        rows=[dict(r) for r in self.db.execute('SELECT * FROM task_attention ORDER BY task')]
        self.assertEqual([r['status'] for r in rows],['suggested','duplicate'])
        self.assertEqual(rows[1]['duplicate_of'],rows[0]['task'])
        self.assertEqual(self.db.execute('SELECT count(DISTINCT task) FROM mail_task').fetchone()[0],1)
        self.assertEqual(self.db.execute('SELECT count(DISTINCT task) FROM evidence').fetchone()[0],1)
    def test_distinct_project_owner_date_and_short_title_do_not_merge(self):
        project=tagging.save_project(self.db,{'name':'oles'})
        task=self.task(assignee='nathalia',project=project,deadline=100)
        self.assertIsNone(attention.find_duplicate(self.db,'Review the project launch document','Juan',project,deadline=100))
        self.assertIsNone(attention.find_duplicate(self.db,'Review the project launch document','nathalia',project,deadline=200))
        self.assertIsNone(attention.find_duplicate(self.db,'Review the project launch document','nathalia',None,deadline=100))
        self.assertEqual(attention.find_duplicate(self.db,'Review the project launch document','nathalia',project,deadline=100),task)
    def test_sent_self_commitment_is_accepted_but_other_peoples_promises_are_not(self):
        self.assertTrue(attention.self_commitment("I'll prepare the release notes",True))
        self.assertFalse(attention.self_commitment("I'll prepare the release notes",False))
        self.assertTrue(attention.self_commitment('Me encargo de revisar los resultados',True))
        self.assertFalse(attention.self_commitment('Juan will handle the release',True))
        self.assertFalse(attention.self_commitment("Juan said I'll prepare the release",True))
    def test_manager_role_does_not_inherit_execution_but_direct_request_wins(self):
        project=tagging.save_project(self.db,{'name':'quila'})
        project_brains.apply(self.db,dict(id=str(uuid.uuid4()),revision=1,updated=1,actor='user',data={'name':'quila','roles':[{'id':str(uuid.uuid4()),'person':'nathalia','mode':'manage','responsibilities':'Coordinate stakeholders'}]}),project)
        task=self.task(project=project)
        with self.db:attention.record(self.db,task,'accepted','Imported assignment','github')
        self.assertFalse(attention.eligible(self.db,task))
        with self.db:attention.record(self.db,task,'accepted','Review requested','github_reviews','review')
        self.assertTrue(attention.eligible(self.db,task))
        with self.db:attention.record(self.db,task,'accepted','Explicit request','direct')
        self.assertTrue(attention.eligible(self.db,task))
    def test_admission_and_duplicate_reference_survive_company_wire_format(self):
        a=self.task();b=self.task()
        with self.db:attention.candidate(self.db,b,'gmail')
        company_sync.ensure_links(self.db)
        data=company_sync.local_data(self.db,'task',b)
        self.assertEqual(data['intake_status'],'duplicate')
        self.assertEqual(data['duplicate_of'],company_sync.remote_id(self.db,'task',a))
        with self.db:company_sync.apply_local(self.db,'task',b,data)
        self.assertFalse(attention.eligible(self.db,b))

    def test_legacy_mail_migration_keeps_all_evidence_and_is_repeatable(self):
        a=self.task();b=self.task()
        with self.db:
            self.db.execute('DELETE FROM task_attention')
            self.db.execute('CREATE TABLE mail_task(thread TEXT,message TEXT,quote TEXT,task INTEGER PRIMARY KEY,UNIQUE(thread,message,quote))')
            self.db.execute("INSERT INTO mail_task VALUES('a','1','quote',?)",(a,))
            self.db.execute("INSERT INTO mail_task VALUES('b','2','quote',?)",(b,))
            import workflows
            workflows.remember(self.db,'gmail','a/1/quote','quote',task=a)
            workflows.remember(self.db,'gmail','b/2/quote','quote',task=b)
        attention.migrate(self.db);attention.migrate(self.db)
        self.assertEqual(self.db.execute('SELECT count(*) FROM mail_task').fetchone()[0],2)
        self.assertEqual(self.db.execute('SELECT count(DISTINCT task) FROM mail_task').fetchone()[0],1)
        self.assertEqual(sorted(r[0] for r in self.db.execute('SELECT status FROM task_attention')),['duplicate','suggested'])

    def test_email_addresses_in_titles_do_not_erase_the_task_text(self):
        self.task('Email stakeholder.longname@example.test about the budget')
        self.assertIsNone(attention.find_duplicate(self.db,'Email stakeholder.longname@example.test about the launch'))

    def test_unknown_repo_ignored_until_chosen_project_exists(self):
        url='https://github.com/acme/laboteca/issues/1'
        rows=[(url,'Fix document export',100)]
        discovery.reconcile(self.db,'github',rows,100)
        self.assertEqual(self.db.execute('SELECT count(*) FROM task').fetchone()[0],0)
        project=tagging.save_project(self.db,{'name':'Documents','hints':'github.com/acme/laboteca/'})
        discovery.reconcile(self.db,'github',rows,200)
        task=self.db.execute('SELECT id FROM task').fetchone()[0]
        self.assertEqual(attention.info(self.db,task)['status'],'suggested')
        attention.decision(self.db,task,'accept')
        self.assertTrue(attention.eligible(self.db,task))
        tagging.delete_project(self.db,project)
        self.assertFalse(attention.eligible(self.db,task))
        discovery.reconcile(self.db,'github',rows,300)
        self.assertEqual(self.db.execute('SELECT state FROM task').fetchone()[0],'unavailable')
        tagging.save_project(self.db,{'name':'Documents','hints':'github.com/acme/laboteca/'})
        discovery.reconcile(self.db,'github',rows,400)
        self.assertEqual(self.db.execute('SELECT count(*) FROM task').fetchone()[0],1)
        self.assertTrue(attention.eligible(self.db,task))

    def test_shared_project_source_link_admits_repo_without_name_match(self):
        project=tagging.save_project(self.db,{'name':'Research'})
        project_brains.apply(self.db,dict(id=str(uuid.uuid4()),revision=1,updated=1,actor='user',data={'name':'Research','sources':['https://github.com/acme/laboteca']}),project)
        self.assertEqual(tagging.repository_project(self.db,'https://github.com/acme/laboteca/issues/1','Export'),project)
        discovery.reconcile(self.db,'github',[('https://github.com/acme/laboteca/issues/1','Export',0)],0)
        task=self.db.execute('SELECT id FROM task').fetchone()[0]
        attention.decision(self.db,task,'accept')
        self.assertTrue(attention.eligible(self.db,task))
        self.assertIsNone(tagging.repository_project(self.db,'https://github.com/acme/laboteca-other/issues/1','Export'))

    def test_upgrade_preserves_explicit_acceptance_and_foreign_owner(self):
        imported=self.task();explicit=self.task('Another action to keep personally')
        foreign=self.task('Juan will prepare the final report',assignee='juan')
        with self.db:
            attention.record(self.db,imported,'accepted','Assigned source','github')
            attention.record(self.db,explicit,'accepted','Your explicit choice','github')
            attention.candidate(self.db,foreign,'gmail')
        attention.review_imported_assignments(self.db)
        self.assertEqual(attention.info(self.db,imported)['status'],'suggested')
        self.assertTrue(attention.eligible(self.db,explicit))
        self.assertEqual(self.db.execute('SELECT owner FROM ownership WHERE task=?',(foreign,)).fetchone()[0],'juan')
        attention.decision(self.db,imported,'accept')
        attention.review_imported_assignments(self.db)
        self.assertTrue(attention.eligible(self.db,imported))

    def test_foreign_mail_action_is_not_imported_and_suggestion_is_unassigned(self):
        mail_reasoning.initialize(self.db)
        thread=dict(id='t',historyId='1',messages=[message('1','Juan will send the budget. Please check the draft.')])
        actions=[dict(kind='add',title='Send the budget',message='1',quote='Juan will send the budget',owner='juan@example.test'),dict(kind='add',title='Check the draft',message='1',quote='Please check the draft',owner='nathalia@example.test')]
        mail_reasoning.analyze(self.db,thread,{},'nathalia@example.test',Mock(return_value={'actions':actions}))
        self.assertEqual(self.db.execute('SELECT count(*) FROM task').fetchone()[0],1)
        self.assertEqual(self.db.execute('SELECT owner FROM ownership').fetchone()[0],'')
        self.assertFalse(attention.eligible(self.db,self.db.execute('SELECT id FROM task').fetchone()[0]))

    def test_manual_category_teaches_repository_scope(self):
        project=tagging.save_project(self.db,{'name':'Research'})
        task=self.task()
        with self.db:
            self.db.execute('CREATE TABLE discovered(source TEXT,key TEXT,task_id INTEGER,scheduled REAL,PRIMARY KEY(source,key))')
            self.db.execute("INSERT INTO discovered VALUES('github','https://github.com/acme/library/issues/1',?,0)",(task,))
        tagging.tag(self.db,task,project)
        self.assertEqual(tagging.repository_project(self.db,'https://github.com/acme/library/issues/2','Another document'),project)
