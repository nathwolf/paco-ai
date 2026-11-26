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
