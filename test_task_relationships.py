import json,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock
import app,paco,workspace,workflows,attention,mail_reasoning,task_relationships as r,task_completion as c

class Relationships(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.db=paco.connect(Path(self.tmp.name)/'db');self.addCleanup(self.db.close);app.initialize(self.db);mail_reasoning.initialize(self.db);self.db.execute("CREATE TABLE mattermost_task(key TEXT,quote TEXT,task INTEGER,PRIMARY KEY(key,quote))")
  with self.db:attention.add_identities(self.db,['nathalia','nathalia@example.test'])
  self.config={'provider':'codex_cli','allowed_sources':['chat','gmail','calendar']}
 def task(self,title='Prepare visa documents',**extra):return workspace.edit_task(self.db,{'changes':dict(title=title,assignee='nathalia',**extra)})['id']
 def evidence(self,t,text,source='gmail'):
  with self.db:return workflows.remember(self.db,source,str(t),text,task=t)
 def proposal(self,a,b,kind='duplicate'):
  return {'merges':[dict(keep=a,other=b,relationship=kind,confidence='high',reason='Same obligation',quotes=[dict(task=t,evidence=self.evidence(t,'Prepare and print documents'),quote='print documents') for t in (a,b)])]}
 def model(self,value):return Mock(return_value=(value,{}))
 def test_manual_merge_preserves_all_links_and_checklist(self):
  a=self.task();b=self.task('Review invitation',description='Check purpose and dates',tags=['visa']);e=self.evidence(b,'Review invitation')
  with self.db:
   self.db.execute("INSERT INTO mail_task VALUES('owner/thread','m','q',?)",(b,))
   self.db.execute("INSERT INTO calendar_task_link VALUES('event','action',?)",(b,))
   self.db.execute("INSERT INTO mattermost_task VALUES('post','q',?)",(b,))
  workflows.merge(self.db,a,b)
  for table in ['evidence','mail_task','calendar_task_link','mattermost_task']:self.assertEqual(self.db.execute('SELECT task FROM '+table).fetchone()[0],a)
  self.assertEqual(attention.info(self.db,b)['duplicate_of'],a)
  self.assertEqual(self.db.execute('SELECT state FROM task WHERE id=?',(b,)).fetchone()[0],'archived')
  self.assertIn('Check purpose',self.db.execute('SELECT description FROM task_extra WHERE task=?',(a,)).fetchone()[0])
  self.assertEqual(self.db.execute('SELECT manual FROM task_merge').fetchone()[0],1)
 def test_grounded_duplicate_merges_and_replay_is_quiet(self):
  a=self.task();b=self.task('Print the visa documents');m=self.model(self.proposal(a,b))
  self.assertEqual(r.reconcile(self.db,self.config,m),1);self.assertEqual(r.reconcile(self.db,self.config,m),0)
  self.assertEqual(self.db.execute('SELECT manual FROM task_merge').fetchone()[0],0)
 def test_different_owner_or_date_not_merged(self):
  for changes in [{'assignee':'Juan'},{'deadline':500}]:
   a=self.task();b=self.task('Other');workspace.edit_task(self.db,{'id':b,'changes':changes});m=self.model(self.proposal(a,b))
   self.assertEqual(r.reconcile(self.db,self.config,m),0)
 def test_checklist_needs_shared_calendar_event(self):
  a=self.task();b=self.task('Review letter');proposal=self.proposal(a,b,'checklist')
  self.assertEqual(r.reconcile(self.db,self.config,self.model(proposal)),0)
  with self.db:
   for t in [a,b]:self.db.execute('INSERT INTO calendar_task_link VALUES(?,?,?)',('event',str(t),t))
  self.assertEqual(r.reconcile(self.db,self.config,self.model(proposal)),1)
 def test_done_canonical_is_not_reopened_and_partial_checklist_cannot_close_it(self):
  a=self.task();b=self.task();workflows.correct_task(self.db,a,state='done')
  self.assertEqual(r.reconcile(self.db,self.config,self.model(self.proposal(a,b,'checklist'))),0)
  self.assertEqual(r.reconcile(self.db,self.config,self.model(self.proposal(a,b))),0) # unchanged inputs cached
  with self.db:self.db.execute("DELETE FROM preference WHERE key='relationships_checked'")
  self.assertEqual(r.reconcile(self.db,self.config,self.model(self.proposal(a,b))),1)
  self.assertEqual(self.db.execute('SELECT state FROM task WHERE id=?',(a,)).fetchone()[0],'done')
 def test_user_edit_while_model_runs_discards_merge(self):
  a=self.task();b=self.task();p=self.proposal(a,b)
  def model(*args):workspace.edit_task(self.db,{'id':b,'changes':{'title':'Different obligation'}});return p,{}
  self.assertEqual(r.reconcile(self.db,self.config,model),0)
 def test_invented_evidence_and_missing_consent_do_not_merge(self):
  a=self.task();b=self.task();p=self.proposal(a,b);p['merges'][0]['quotes'][1]['quote']='invented'
  self.assertEqual(r.reconcile(self.db,self.config,self.model(p)),0)
  m=self.model(p);self.assertEqual(r.reconcile(self.db,dict(self.config,allowed_sources=['gmail']),m),0);m.assert_not_called()
 def test_dependent_milestones_are_not_merged(self):
  a=self.task();b=self.task('Next milestone')
  with self.db:self.db.execute('INSERT INTO dependency VALUES(?,?)',(b,a))
  with self.assertRaises(ValueError):workflows.merge(self.db,a,b)
  self.assertEqual(self.db.execute('SELECT state FROM task WHERE id=?',(b,)).fetchone()[0],'open')
 def test_oversize_merge_rolls_back_source_links(self):
  a=self.task(description='a'*4000);b=self.task(description='b'*4000);self.evidence(b,'receipt')
  with self.assertRaises(ValueError):workflows.merge(self.db,a,b)
  self.assertEqual(self.db.execute('SELECT task FROM evidence').fetchone()[0],b)

class Completions(unittest.TestCase):
 setUp=Relationships.setUp
 task=Relationships.task
 model=Relationships.model
 def setup_completion(self):
  task=self.task('Upload flight receipt to Spendesk')
  with self.db:self.db.execute("INSERT INTO mail_task VALUES(?,'m1','Upload receipt',?)",('nathalia@example.test/original'+str(task),task))
  original=dict(id='m1',text='Upload receipt',sender='Bridge <travel@bridge.test>',to='nathalia@example.test',sent=False,date='100000',automated=False)
  confirmation=dict(id='m2',text='Your flight receipt has been submitted.',sender='Spendesk <no-reply@spendesk.com>',to='nathalia@example.test',sent=False,date='200000',automated=True)
  context=dict(since=100,originals=[original],messages=[original,confirmation])
  result=dict(verdict='completed',confidence='high',coverage='full',proof_type='service_confirmation',message='m2',quote='Your flight receipt has been submitted.',reason='Confirmed upload')
  return task,context,result
 def test_later_service_confirmation_closes_task_and_preserves_proof(self):
  task,context,result=self.setup_completion();reader=Mock(return_value=context);m=self.model(result)
  self.assertEqual(c.review(self.db,self.config,m,reader,now=300),1)
  self.assertEqual(self.db.execute('SELECT state FROM task WHERE id=?',(task,)).fetchone()[0],'done')
  self.assertEqual(self.db.execute('SELECT outcome FROM source_event').fetchone()[0],'automatic_completion')
  self.assertEqual(c.review(self.db,self.config,m,reader,now=301),0)
 def test_partial_future_unknown_sender_and_older_proof_do_not_close(self):
  for scenario in ['partial','old','foreign','future','invented']:
   task,context,result=self.setup_completion()
   if scenario=='partial':result['coverage']='partial'
   if scenario=='old':context['messages'][1]['date']='90000'
   if scenario=='foreign':context['messages'][1]['sender']='stranger@unrelated.test'
   if scenario=='future':result['verdict']='pending'
   if scenario=='invented':result['quote']='Not in the email'
   self.assertIsNone(c.proof(self.db,next(t for t in r.snapshot(self.db,self.config) if t['id']==task),context,result))
 def test_reopened_task_not_closed_from_older_proof(self):
  task,context,result=self.setup_completion();workflows.correct_task(self.db,task,state='open')
  self.assertEqual(c.review(self.db,self.config,self.model(result),Mock(return_value=context)),0)
 def test_user_edit_during_completion_model_is_preserved(self):
  task,context,result=self.setup_completion()
  def model(*args):workspace.edit_task(self.db,{'id':task,'changes':{'title':'Different task'}});return result,{}
  self.assertEqual(c.review(self.db,self.config,model,Mock(return_value=context)),0)
 def test_source_permissions_and_unavailable_source(self):
  task,context,result=self.setup_completion();m=self.model(result);reader=Mock(return_value=context)
  self.assertEqual(c.review(self.db,dict(self.config,allowed_sources=['chat']),m,reader),0);reader.assert_not_called()
  self.assertEqual(c.review(self.db,self.config,m,Mock(side_effect=RuntimeError('offline'))),0);m.assert_not_called()
 def test_search_finds_service_receipt_outside_broad_results_and_original_thread(self):
  from test_mail_reasoning import message
  task,_,_=self.setup_completion();workspace.edit_task(self.db,{'id':task,'changes':{'title':'Sign the WINTER27 release in Yoti Sign'}})
  original=message('m1','Please sign release');original['internalDate']='100000';original['payload']['headers']=[{'name':'From','value':'no-reply@yotisign.com'}]
  receipt=message('m2','Everyone has signed the WINTER27 release');receipt['internalDate']='200000';receipt['payload']['headers']=[{'name':'From','value':'no-reply@yotisign.com'}]
  reader=c.Reader();reader.session=Mock()
  def get(path,**params):
   if path.startswith('threads/'):return {'messages':[original]}
   if path=='messages':return {'messages':[{'id':'m2'}]} if 'from:yotisign.com' in params['q'] else {}
   if path=='messages/m2':return receipt
   raise AssertionError(path)
  reader.get=Mock(side_effect=get)
  context=reader.read(self.db,next(t for t in r.snapshot(self.db,self.config) if t['id']==task))
  self.assertIn('m2',[m['id'] for m in context['messages']]);self.assertEqual(context['since'],100)
 def test_related_completed_action_proves_only_grounded_prerequisite(self):
  task,context,result=self.setup_completion();related=self.task('Submit flight receipt')
  with self.db:self.db.execute("INSERT INTO mail_task VALUES(?,'m3','receipt',?)",('nathalia@example.test/original'+str(task),related))
  workflows.correct_task(self.db,related,state='done');context['completed_related']=c.completed_related(self.db,task)
  result.update(proof_type='necessary_prerequisite',related_task=related,quote=context['completed_related'][0]['confirmation'])
  current=next(t for t in r.snapshot(self.db,self.config) if t['id']==task)
  self.assertIsNotNone(c.proof(self.db,current,context,result))
  result['related_task']=999;self.assertIsNone(c.proof(self.db,current,context,result))
 def test_reopening_related_task_while_assessing_discards_completion(self):
  task,context,result=self.setup_completion();related=self.task('Submit flight receipt')
  with self.db:self.db.execute("INSERT INTO mail_task VALUES(?,'m3','receipt',?)",('nathalia@example.test/original'+str(task),related))
  workflows.correct_task(self.db,related,state='done');context['completed_related']=c.completed_related(self.db,task)
  result.update(proof_type='necessary_prerequisite',related_task=related,quote=context['completed_related'][0]['confirmation'])
  def model(*args):workflows.correct_task(self.db,related,state='open');return result,{}
  self.assertEqual(c.review(self.db,self.config,model,Mock(return_value=context),task_ids=[task]),0)
 def test_owner_confirmation_supported_but_incoming_impersonation_is_not(self):
  task,context,result=self.setup_completion();result['proof_type']='owner_confirmation'
  t=next(t for t in r.snapshot(self.db,self.config) if t['id']==task)
  self.assertIsNone(c.proof(self.db,t,context,result));context['messages'][1]['sent']=True
  self.assertIsNotNone(c.proof(self.db,t,context,result))

if __name__=='__main__':unittest.main()
