import unittest
import tempfile
from unittest.mock import Mock, patch
from pathlib import Path
from contextlib import closing
import subprocess

from paco import connect
from projects import drive, activity, track


class Projects(unittest.TestCase):
    def test_real_git_and_drive_snapshot_failure(self):
        with tempfile.TemporaryDirectory() as tmp, closing(connect(Path(tmp)/"db")) as db:
            repo = Path(tmp)/"repo"
            subprocess.run(["git","init","-q",repo],check=True)
            subprocess.run(["git","-C",repo,"-c","user.name=Test","-c","user.email=test@example.org",
                            "commit","-q","--allow-empty","-m","Pilot scope"],check=True)
            track(db,repo)
            session = Mock()
            session.get.return_value.json.return_value = {"files":[
                {"id":"d","name":"Spec","modifiedTime":"2026-01-01"}]}
            drive(session,db)
            session.get.side_effect = IOError("offline")
            with self.assertRaises(IOError):
                drive(session,db)
            result = list(activity(db))
            self.assertIn("Pilot scope",result[0]["latest_commit"])
            self.assertEqual(result[1]["title"],"Spec")
