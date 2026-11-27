import tempfile,time,unittest,uuid
from pathlib import Path
from unittest.mock import Mock
import app,attention,paco,project_brains,responsibility as r,tagging,workspace

class AdaptiveResponsibility(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.db=paco.connect(Path(self.tmp.name)/'db');self.addCleanup(self.db.close);app.initialize(self.db);r.initialize(self.db)
        with self.db:attention.add_identities(self.db,['nathalia','nathalia@example.test'])
        self.config={'provider':'codex_cli','allowed_sources':['chat','gmail','mattermost','calendar']}
        self.settings={'model':self.config}
        self.context={'messages':[{'text':'Nathalia, please approve the budget.', 'mine':False,'addressed':True,'bulk':False}]}
    def task(self,title='Approve the budget',source='gmail',**fields):
        ident=workspace.edit_task(self.db,{'changes':dict(title=title,**fields)})['id']
        with self.db:attention.record(self.db,ident,'suggested','Needs review',source)
        return ident
    def decision(self,ident,**fields):
        return dict(task=ident,verdict='mine',confidence='high',owner='nathalia',basis='direct_request',quote='please approve the budget.',reason='Explicit personal request',**fields)
    def apply(self,ident,d=None,context=None):
        return r.apply(self.db,r.snapshot(self.db,ident,self.config),context or self.context,d or self.decision(ident),self.config)
    def test_clear_request_activates_and_automatic_choices_are_not_examples(self):
        t=self.task();self.assertTrue(self.apply(t));self.assertTrue(attention.eligible(self.db,t))
        self.assertEqual(attention.corrections(self.db,self.config),[])
        self.assertIn('Automatically added',attention.info(self.db,t)['reason'])
    def test_personally_addressed_account_email_does_not_become_a_commitment(self):
        t=self.task('Verify your email to activate your account')
        self.assertTrue(self.apply(t))
        self.assertEqual(attention.info(self.db,t)['status'],'reference')
        self.assertFalse(attention.eligible(self.db,t))
    def test_explicitly_accepted_small_task_is_kept(self):
        t=self.task('Verify your email to activate your account')
        attention.decision(self.db,t,'accept')
        self.assertFalse(self.apply(t))
        self.assertTrue(attention.eligible(self.db,t))
    def test_uncertain_foreign_and_ungrounded_decisions_remain_review(self):
        for fields in ({'confidence':'medium'},{'owner':'Juan'},{'quote':'invented'},{'basis':'unclear'}):
            t=self.task();d=self.decision(t);d.update(fields);self.assertFalse(self.apply(t,d));self.assertEqual(attention.info(self.db,t)['status'],'suggested')
    def test_bulk_cc_and_own_request_do_not_pass_direct_proof(self):
        for changes in ({'bulk':True},{'addressed':False},{'mine':True}):
            t=self.task();m=dict(self.context['messages'][0]);m.update(changes)
            self.assertFalse(self.apply(t,context={'messages':[m]}))
    def test_named_personal_request_can_be_addressed_to_a_cc_recipient(self):
        t=self.task();m=dict(self.context['messages'][0],addressed=False,named_recipient=True)
        self.assertTrue(self.apply(t,context={'messages':[m]}))
    def test_self_note_cannot_be_rejected_as_someone_elses_request(self):
        t=self.task(source='mattermost');d=self.decision(t);d['verdict']='not_mine'
        self.assertFalse(self.apply(t,d,dict(self.context,self_conversation=True)))
    def test_dismissal_and_reassignment_during_model_are_preserved(self):
        for changes in ({'assignee':'Juan'},):
            t=self.task();v=r.snapshot(self.db,t,self.config);workspace.edit_task(self.db,{'id':t,'changes':changes})
            self.assertFalse(r.apply(self.db,v,self.context,self.decision(t),self.config))
        t=self.task();v=r.snapshot(self.db,t,self.config);attention.decision(self.db,t,'dismiss')
        self.assertFalse(r.apply(self.db,v,self.context,self.decision(t),self.config));self.assertEqual(attention.info(self.db,t)['status'],'dismissed')
    def test_negative_paraphrase_blocks_new_auto_task(self):
        old=self.task('Prepare final project budget');attention.decision(self.db,old,'dismiss')
        new=self.task('Prepare the final project budget');self.assertFalse(self.apply(new))
    def test_older_relevant_corrections_survive_many_unrelated_choices(self):
        old=self.task('Prepare final project budget');attention.decision(self.db,old,'dismiss')
        for i in range(35):
            t=self.task('Unrelated task '+str(i));attention.decision(self.db,t,'accept')
        new=self.task('Prepare the final project budget')
        self.assertIn(old,[c['task'] for c in r.snapshot(self.db,new,self.config)['corrections']])
        self.assertFalse(self.apply(new))
    def test_learning_needs_two_explicit_comparable_positive_examples(self):
        refs=[]
        for i in range(2):
            t=self.task('Approve monthly budget '+str(i));attention.decision(self.db,t,'accept')
            refs.append(attention.corrections(self.db,self.config)[0]['correction_id'])
            new=self.task('Approve next monthly budget '+str(i));d=self.decision(new);d.update(basis='learned_pattern',correction_ids=refs)
            self.assertEqual(self.apply(new,d),i==1)
        other=self.task(source='mattermost');d=self.decision(other);d.update(basis='learned_pattern',correction_ids=refs)
        self.assertFalse(self.apply(other,d))
    def test_manager_not_automatically_executor(self):
        project=tagging.save_project(self.db,{'name':'quila'})
        project_brains.apply(self.db,dict(id=str(uuid.uuid4()),revision=1,updated=1,actor='user',data={'name':'quila','roles':[{'id':str(uuid.uuid4()),'person':'nathalia','mode':'manage','responsibilities':'Coordinate'}]}),project)
        t=self.task(project=project);self.assertFalse(self.apply(t))
    def test_closed_backlog_and_cancelled_calendar_cannot_auto_activate(self):
        t=self.task();self.assertFalse(self.apply(t,context=dict(self.context,state='closed')))
        t=self.task('[Backlog] approve budget');self.assertFalse(self.apply(t))
        t=self.task(source='calendar');d=self.decision(t);d['basis']='personal_calendar'
        self.assertFalse(self.apply(t,d,dict(self.context,personal=True,events=[{'status':'cancelled'}])))
        self.assertTrue(self.apply(t,d,dict(self.context,personal=True,events=[{'end':time.time()+1000}])))
    def test_source_reference_never_marks_task_completed(self):
        t=self.task();d=self.decision(t);d['verdict']='obsolete';self.assertTrue(self.apply(t,d))
        self.assertEqual(attention.info(self.db,t)['status'],'reference');self.assertEqual(self.db.execute('SELECT state FROM task WHERE id=?',(t,)).fetchone()[0],'open')
    def test_permission_and_cache_and_new_corrections(self):
        t=self.task();reader=Mock(return_value=self.context);d=self.decision(t);d['confidence']='low'
        model=Mock(return_value=({'decisions':[d]},{}))
        self.assertEqual(r.review(self.db,{'model':dict(self.config,allowed_sources=['chat'])},model,reader,now=100),0);reader.assert_not_called()
        r.review(self.db,self.settings,model,reader,now=100);r.review(self.db,self.settings,model,reader,now=101);self.assertEqual(model.call_count,1)
        other=self.task('Other work');attention.decision(self.db,other,'dismiss')
        r.review(self.db,self.settings,model,reader,now=102);self.assertEqual(model.call_count,2)
    def test_separate_permissions_and_sources(self):
        self.task(source='gmail');self.task(source='mattermost')
        model=Mock(return_value=({'decisions':[]},{}));r.review(self.db,self.settings,model,Mock(return_value=self.context))
        self.assertEqual({c.args[3] for c in model.call_args_list},{'gmail','mattermost'})
        self.assertTrue(all(len(c.args[2]['tasks'])==1 for c in model.call_args_list))
    def test_failed_source_keeps_task_in_review_without_model(self):
        t=self.task();model=Mock();r.review(self.db,self.settings,model,Mock(side_effect=RuntimeError('unavailable')))
        model.assert_not_called();self.assertEqual(attention.info(self.db,t)['status'],'suggested')

if __name__=='__main__':unittest.main()
