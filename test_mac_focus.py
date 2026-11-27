import tempfile,unittest
from pathlib import Path
import app,paco,planning,mac_focus

class MacFocus(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.db=paco.connect(Path(self.tmp.name)/'db');app.initialize(self.db);self.addCleanup(self.db.close)
  with self.db:
   self.db.execute("INSERT INTO task VALUES(1,'Critical',5,'open',0,0)")
   self.db.execute('INSERT INTO urgency VALUES(1,1)')
 def test_focus_stops_even_urgent_work_and_off_resumes(self):
  mac_focus.observe(self.db,True,100)
  self.assertEqual(planning.reason_to_wait(self.db,100),mac_focus.REASON)
  alerts=[];paco.tick(self.db,100,alerts.append);self.assertEqual(alerts,[])
  mac_focus.observe(self.db,False,101)
  paco.tick(self.db,101,alerts.append);self.assertEqual(len(alerts),1)
 def test_unknown_and_stale_are_not_false_off_or_permanent_locks(self):
  mac_focus.observe(self.db,True,100)
  self.assertIsNone(mac_focus.status(self.db,146)['active'])
  mac_focus.observe(self.db,None,122)
  self.assertIsNone(mac_focus.status(self.db,122)['active'])
  self.assertIn('unavailable',mac_focus.status(self.db,122)['message'])
 def test_invalid_heartbeat_rejected(self):
  with self.assertRaises(ValueError):mac_focus.observe(self.db,'false')
 def test_without_provider_shows_limitation_and_manual_alternative(self):
  self.assertIsNone(mac_focus.status(self.db)['active'])
  self.assertIn('unavailable in this build',mac_focus.status(self.db)['message'])
  self.assertIn('Paco focus session',mac_focus.status(self.db)['message'])


