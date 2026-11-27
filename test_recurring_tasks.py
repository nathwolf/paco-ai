import tempfile,unittest
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import app,paco,planning,recurring_tasks as r

class RecurringAndDelivery(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
  self.db=paco.connect(Path(self.temp.name)/'db');app.initialize(self.db);self.addCleanup(self.db.close)
  self.db.execute("INSERT INTO task(id,title,priority,state,due) VALUES(1,'Weekly post',3,'open',0)")
  self.db.commit()
 def stamp(self,iso,zone='America/Santiago'):return datetime.fromisoformat(iso).replace(tzinfo=ZoneInfo(zone)).timestamp()
 def test_weekly_local_hour_survives_chile_clock_change(self):
  first=r.next_weekly(self.stamp('2027-03-31T12:00:00'),'America/Santiago',2,13,0)
  second=r.next_weekly(first,'America/Santiago',2,13,0)
  self.assertEqual(datetime.fromtimestamp(second,ZoneInfo('America/Santiago')).hour,13)
  self.assertEqual(second-first,7*86400+3600)
 def test_done_keeps_history_and_schedules_one_next_occurrence(self):
  due=r.configure(self.db,1,'America/Santiago',2,13,now=self.stamp('2026-11-26T12:00:00'))
  with self.db:self.db.execute("UPDATE task SET state='done' WHERE id=1")
  r.advance(self.db,due+60);r.advance(self.db,due+120)
  state,new=self.db.execute('SELECT state,due FROM task WHERE id=1').fetchone()
  self.assertEqual(state,'open');self.assertEqual(new,due+7*86400)
  self.assertEqual(self.db.execute('SELECT count(*) FROM task_occurrence').fetchone()[0],1)
 def test_open_overdue_task_is_not_duplicated_or_silently_completed(self):
  due=r.configure(self.db,1,'America/Santiago',2,13,now=self.stamp('2026-11-26T12:00:00'))
  r.advance(self.db,due+15*86400)
  self.assertEqual(self.db.execute('SELECT due FROM task').fetchone()[0],due)
  self.assertEqual(self.db.execute('SELECT count(*) FROM task').fetchone()[0],1)
 def test_old_morning_burst_does_not_silence_afternoon(self):
  now=self.stamp('2026-11-26T16:00:00','Europe/Paris')
  with self.db:self.db.executemany("INSERT INTO intervention VALUES(NULL,'notify',?)",[(now-4*3600+i,) for i in range(12)])
  self.assertEqual(planning.next_reminder(self.db,now)['id'],1)
 def test_rolling_allowance_delays_routine_but_not_due_commitment(self):
  now=self.stamp('2026-11-26T16:00:00','Europe/Paris')
  with self.db:self.db.executemany("INSERT INTO intervention VALUES(NULL,'notify',?)",[(now-600-i,) for i in range(4)])
  self.assertIsNone(planning.next_reminder(self.db,now))
  self.assertIn('four per three hours',planning.delivery_status(self.db,now))
  with self.db:self.db.execute("INSERT INTO details VALUES(1,'',30,?)",(now+3600,))
  self.assertEqual(planning.next_reminder(self.db,now)['id'],1)
 def test_explicit_recurrence_survives_calendar_reschedule(self):
  import calendar_sync
  due=r.configure(self.db,1,'America/Santiago',2,13,now=self.stamp('2026-11-26T12:00:00'))
  with self.db:
   self.db.execute("INSERT INTO calendar_task_link VALUES('event','post',1)")
   calendar_sync.refresh_schedule(self.db,{'start':due},{'id':'event','start':due+86400})
  self.assertEqual(self.db.execute('SELECT deadline FROM details WHERE task=1').fetchone()[0],due)

if __name__=='__main__':unittest.main()

class RepeatEditor(RecurringAndDelivery):
 def test_monthly_first_and_31st(self):
  rule=r.validate(dict(frequency='monthly',zone='Europe/Paris',monthday=1))
  due=r.next_occurrence(self.stamp('2026-12-31T17:00:00','Europe/Paris'),rule)
  self.assertEqual(due,self.stamp('2027-01-01T09:00:00','Europe/Paris'))
  rule['monthday']=31
  due=r.next_occurrence(self.stamp('2027-01-31T10:00:00','Europe/Paris'),rule)
  self.assertEqual(due,self.stamp('2027-03-31T09:00:00','Europe/Paris'))
 def test_editor_save_disable_and_atomic_validation(self):
  import workspace
  data=dict(title='Send monthly report',recurrence=dict(frequency='monthly',zone='Europe/Paris',monthday=1))
  task=workspace.edit_task(self.db,{'changes':data})['id']
  due=self.db.execute('SELECT due FROM task WHERE id=?',(task,)).fetchone()[0]
  workspace.edit_task(self.db,{'id':task,'changes':data})
  self.assertEqual(self.db.execute('SELECT due FROM task WHERE id=?',(task,)).fetchone()[0],due)
  with self.assertRaises(ValueError):workspace.edit_task(self.db,{'changes':dict(data,recurrence={'monthday':32})})
  self.assertEqual(self.db.execute('SELECT count(*) FROM task').fetchone()[0],2)
  workspace.edit_task(self.db,{'id':task,'changes':{'recurrence':None}})
  with self.db:self.db.execute("UPDATE task SET state='done' WHERE id=?",(task,))
  r.advance(self.db,due)
  self.assertEqual(self.db.execute('SELECT state FROM task WHERE id=?',(task,)).fetchone()[0],'done')
 def test_calendar_series_and_patterns_do_not_create_tasks(self):
  import calendar_tasks,calendar_series
  events=[dict(id='cal:'+str(i),title='Weekly review',start=self.stamp('2026-11-02T10:00:00')+i*7*86400) for i in range(3)]
  events.append(dict(id='other:moved',title='Standup',start=1000,recurringEventId='series1',iCalUID='uid1',originalStartTime={'dateTime':'2026-11-03T10:00:00Z'}))
  with self.db:calendar_tasks.replace_context(self.db,events)
  found=calendar_series.info(self.db)
  self.assertEqual(found['cal:0']['label'],'Weekly pattern')
  self.assertEqual(found['other:moved']['id'],'uid1')
  self.assertEqual(self.db.execute('SELECT count(*) FROM task').fetchone()[0],1)
