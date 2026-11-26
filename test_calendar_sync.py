import copy,json,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
import app,paco,workspace,workflows,attention,calendar_sync as c,calendar_tasks,responsibility

class CalendarSync(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.db=paco.connect(Path(self.tmp.name)/'db');self.addCleanup(self.db.close);app.initialize(self.db)
  with self.db:attention.add_identities(self.db,['nathalia@example.test'])
  self.inventory=[dict(id='nathalia@example.test',summary='Work',primary=True,accessRole='owner'),dict(id='personal',summary='Personal',hidden=True,selected=False,accessRole='owner')]
  self.event=dict(id='event1',iCalUID='stable@google',summary='Print visa papers',status='confirmed',start={'dateTime':'2026-11-27T10:00:00+01:00'},end={'dateTime':'2026-11-27T11:00:00+01:00'},creator={'email':'nathalia@example.test'},organizer={'email':'nathalia@example.test'},etag='v1')
  self.events={'primary':[copy.deepcopy(self.event)],'personal':[]}
  self.session=Mock();self.session.get.side_effect=self.get
 def get(self,url,params=None,**kwargs):
  response=Mock(status_code=200)
  if url.endswith('/calendarList'):response.json.return_value={'items':self.inventory}
  else:
   cal=url.split('/calendars/')[1].split('/events')[0];response.json.return_value={'items':self.events[cal]}
  return response
 def sync(self):
  with patch('discovery.google_session') as factory:
   factory.return_value.__enter__.return_value=self.session
   return c.sync(self.db,now=1795600000)
 def moved(self,reschedule=False):
  new=copy.deepcopy(self.event);new['organizer']={'email':'personal'};new['etag']='v2';new['htmlLink']='https://calendar.google.com/new-copy'
  if reschedule:new['start']['dateTime']='2026-11-28T10:00:00+01:00';new['end']['dateTime']='2026-11-28T11:00:00+01:00'
  self.events={'primary':[{'id':'event1','status':'cancelled'}],'personal':[new]}
 def linked_task(self,state='open'):
  context=json.loads(self.db.execute('SELECT payload FROM calendar_task_context').fetchone()[0])
  task=workspace.edit_task(self.db,{'changes':{'title':'Print my documents','assignee':'nathalia@example.test','deadline':context['start'],'project':None,'tags':['admin']}})['id']
  with self.db:
   self.db.execute("INSERT INTO calendar_task_link VALUES('primary:event1','print',?)",(task,))
   workflows.remember(self.db,'calendar','primary:event1/print','Print my documents','https://calendar.google.com/old-copy',task=task)
   self.db.execute('UPDATE task SET state=?,due=? WHERE id=?',(state,context['start']-900,task))
  return task,context
 def test_discovers_hidden_and_unselected_calendars(self):
  self.events['personal']=[dict(self.event,id='another',iCalUID='another@google')]
  result=self.sync();self.assertEqual(result['calendars'],2);self.assertEqual(result['events'],2)
  self.assertEqual(self.session.get.call_args_list[0].kwargs['params']['showHidden'],'true')
  self.inventory.append(dict(id='new',summary='New calendar',accessRole='reader'));self.events['new']=[]
  self.assertEqual(self.sync()['calendars'],3)
 def test_list_pagination_and_freebusy_inventory(self):
  first=Mock(status_code=200);first.json.return_value={'items':self.inventory[:1],'nextPageToken':'page2'}
  second=Mock(status_code=200);second.json.return_value={'items':self.inventory[1:]+[dict(id='limited',summary='Private availability',accessRole='freeBusyReader')]}
  session=Mock();session.get.side_effect=[first,second]
  result=c.calendars(session);self.assertEqual(len(result),3);self.assertEqual(session.get.call_args.kwargs['params']['pageToken'],'page2')
 def test_move_keeps_task_identity_reminder_tags_and_reference_identity(self):
  self.sync();task,context=self.linked_task();reference=self.db.execute("SELECT task_id FROM discovered WHERE key='primary:event1'").fetchone()[0]
  self.moved();self.assertEqual(self.sync()['moves'],1)
  self.assertEqual(self.db.execute("SELECT task_id FROM discovered WHERE key='personal:event1'").fetchone()[0],reference)
  self.assertEqual(self.db.execute('SELECT event,task FROM calendar_task_link').fetchone()[:],('personal:event1',task))
  self.assertEqual(self.db.execute('SELECT due FROM task WHERE id=?',(task,)).fetchone()[0],context['start']-900)
  self.assertEqual(self.db.execute('SELECT url FROM evidence WHERE task=?',(task,)).fetchone()[0],'https://calendar.google.com/new-copy')
  self.assertEqual(self.db.execute('SELECT tags FROM task_extra WHERE task=?',(task,)).fetchone()[0],'["admin"]')
  self.assertEqual(self.db.execute("SELECT count(*) FROM source_event WHERE outcome='unavailable'").fetchone()[0],0)
  self.sync();self.assertEqual(self.db.execute('SELECT count(*) FROM task').fetchone()[0],2)
 def test_moving_back_keeps_identity_without_alias_cycle(self):
  self.sync();task,_=self.linked_task();self.moved();self.sync()
  self.events={'primary':[copy.deepcopy(self.event)],'personal':[{'id':'event1','status':'cancelled'}]};self.sync()
  self.assertEqual(self.db.execute('SELECT event FROM calendar_task_link WHERE task=?',(task,)).fetchone()[0],'primary:event1')
  self.assertIsNone(self.db.execute("SELECT 1 FROM google_event_alias WHERE old_key='primary:event1'").fetchone())
 def test_move_and_reschedule_updates_linked_deadline_and_offset(self):
  self.sync();task,context=self.linked_task();self.moved(True);self.sync()
  self.assertEqual(self.db.execute('SELECT deadline FROM details WHERE task=?',(task,)).fetchone()[0],context['start']+86400)
  self.assertEqual(self.db.execute('SELECT due FROM task WHERE id=?',(task,)).fetchone()[0],context['start']+86400-900)
 def test_completed_task_and_custom_dates_survive_moves(self):
  self.sync();task,context=self.linked_task('done');self.moved(True);self.sync()
  self.assertEqual(self.db.execute('SELECT state FROM task WHERE id=?',(task,)).fetchone()[0],'done')
  self.assertEqual(self.db.execute('SELECT deadline FROM details WHERE task=?',(task,)).fetchone()[0],context['start'])
 def test_permission_or_partial_calendar_failure_preserves_entire_previous_snapshot(self):
  self.sync();task,context=self.linked_task()
  before=[tuple(r) for r in self.db.execute('SELECT * FROM calendar_event')]
  original=self.get
  def broken(url,**kwargs):
   if '/calendars/personal/' in url:raise RuntimeError('unavailable')
   return original(url,**kwargs)
  self.session.get.side_effect=broken
  with self.assertRaises(RuntimeError):self.sync()
  self.assertEqual([tuple(r) for r in self.db.execute('SELECT * FROM calendar_event')],before)
  denied=Mock(status_code=403);self.session.get.side_effect=None;self.session.get.return_value=denied
  with self.assertRaises(c.CalendarAccessError):self.sync()
  self.assertEqual([tuple(r) for r in self.db.execute('SELECT * FROM calendar_event')],before)
 def test_actual_cancellation_is_not_completion_of_the_action(self):
  self.sync();task,_=self.linked_task();self.events={'primary':[{'id':'event1','status':'cancelled'}],'personal':[]};result=self.sync()
  self.assertEqual(result['moves'],0);self.assertEqual(self.db.execute('SELECT state FROM task WHERE id=?',(task,)).fetchone()[0],'open')
  self.assertEqual(self.db.execute('SELECT count(*) FROM calendar_event').fetchone()[0],0)
 def test_same_title_and_different_ids_are_not_a_move(self):
  old={'old:a':dict(self.event,id='a',iCalUID='a@google')}
  raw={'new:b':dict(self.event,id='b',iCalUID='b@google')}
  self.assertEqual(c.canonical(raw,old)[1],{})
 def test_recurring_occurrences_deduplicate_copies_not_dates(self):
  first=dict(self.event,recurringEventId='series',originalStartTime={'dateTime':'2026-11-27T09:00:00Z'})
  same=dict(first,originalStartTime={'dateTime':'2026-11-27T10:00:00+01:00'})
  next_week=dict(first,id='next',originalStartTime={'dateTime':'2026-12-04T09:00:00Z'})
  chosen,aliases=c.canonical({'primary:a':first,'other:a':same,'primary:b':next_week},{})
  self.assertEqual(len(chosen),2);self.assertEqual(aliases,{'other:a':'primary:a'})
 def test_legacy_move_matches_tombstone_destination_without_title_guessing(self):
  old=dict(self.event);old.pop('iCalUID');old['status']='cancelled';old['organizer']={'email':'personal'}
  raw={'primary:event1':old,'personal:event1':dict(self.event,organizer={'email':'personal'})}
  self.assertEqual(c.canonical(raw,{})[1]['primary:event1'],'personal:event1')
 def test_foreign_calendar_does_not_create_personal_busy_time(self):
  self.events['primary']=[];self.events['personal']=[dict(self.event,creator={'email':'juan@example.test','self':True},organizer={'email':'juan@example.test','self':True})]
  self.sync();self.assertEqual(self.db.execute('SELECT count(*) FROM busy').fetchone()[0],0)
  self.assertEqual(self.db.execute('SELECT count(*) FROM calendar_task_context').fetchone()[0],1)
 def test_foreign_creator_self_flag_does_not_prove_personal_action(self):
  self.events['primary']=[];self.events['personal']=[dict(self.event,creator={'email':'juan@example.test','self':True})]
  self.sync();task=self.linked_task()[0]
  with self.db:self.db.execute("UPDATE calendar_task_link SET event='personal:event1'")
  source=responsibility.Sources({});context=source.read(self.db,{'source':'calendar','id':task})
  self.assertFalse(context['personal'])

if __name__=='__main__':unittest.main()
