from pathlib import Path
import plistlib
import tempfile
import unittest
from unittest.mock import patch
import app
import paco
import planning
import startup


class Companion(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'db';self.db=paco.connect(self.path);app.initialize(self.db)
    def tearDown(self):
        self.db.close();self.tmp.cleanup()
    def test_all_five_original_assets_and_preview_paths(self):
        self.assertEqual(set(app.EXPRESSIONS),{'friendly','impatient','angry','furious','rage'})
        for mood,expression in app.EXPRESSIONS.items():
            file=app.BASE/'assets/icons'/expression['file']
            self.assertEqual(file.read_bytes()[:8],b'\x89PNG\r\n\x1a\n')
            app.act(self.db,self.path,paco.connect,{'action':'demo','mood':mood})
        self.assertEqual(self.db.execute('SELECT count(DISTINCT mood) FROM notification').fetchone()[0],5)
    def test_red_rage_requires_explicit_urgency_and_long_delay(self):
        now=1000000
        task={'critical':1,'deadline':now-3*86400,'priority':5,'nudges':10,'state':'open'}
        self.assertEqual(planning.presentation(task,now)[0],'rage')
        task['critical']=0
        self.assertNotEqual(planning.presentation(task,now)[0],'rage')
        task['critical']=1;task['deadline']=now-86400
        self.assertEqual(planning.presentation(task,now)[0],'furious')
    def test_setup_completion_persists_without_changing_task_data(self):
        with patch('startup.configure') as configure:
            app.act(self.db,self.path,paco.connect,{'action':'setup_finish','autostart':True})
            configure.assert_called_once_with(True,self.path)
        self.db.close();self.db=paco.connect(self.path)
        self.assertEqual(planning.setting(self.db,'setup_complete'),'yes')
        self.assertEqual(self.db.execute('SELECT count(*) FROM task').fetchone()[0],0)
    def test_failed_startup_setup_does_not_claim_completion(self):
        with patch('startup.configure',side_effect=OSError('failure')):
            with self.assertRaises(OSError):app.act(self.db,self.path,paco.connect,{'action':'setup_finish'})
        self.assertNotEqual(planning.setting(self.db,'setup_complete'),'yes')
    def test_login_config_survives_quiet_quit_and_has_database_guard(self):
        plist=Path(self.tmp.name)/'LaunchAgents/paco.plist'
        with patch('startup.PLIST',plist),patch('startup.sys.platform','darwin'),patch('startup.subprocess.run') as run:
            startup.configure(True,self.path)
            config=plistlib.loads(plist.read_bytes())
            self.assertEqual(config['KeepAlive'],{'SuccessfulExit':False})
            self.assertEqual(config['ProgramArguments'][-2:],['desktop','--login'])
            self.assertIn(str(self.path.resolve()),config['ProgramArguments'])
            self.assertFalse(any('bootout' in call.args[0] for call in run.call_args_list))
            startup.configure(False,self.path)
            self.assertFalse(startup.enabled())
