from contextlib import closing
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import actions
from discovery import reconcile
from paco import connect, tick
import planning
import attention, tagging


class Workday(unittest.TestCase):
    def test_rescheduling_meetings_focus_and_learning(self):
        with tempfile.TemporaryDirectory() as tmp, closing(connect(Path(tmp)/"db")) as db:
            reconcile(db,"github",[("issue","Scope pilot",0),("other","Inbox",0)],0)
            attention.decision(db,1,'accept');attention.decision(db,2,'accept')
            db.execute("INSERT INTO preference VALUES('goal','paid pilot')")
            db.execute("INSERT INTO details VALUES(1,'paid pilot',30,NULL)")
            db.execute("INSERT INTO busy VALUES(600,1200)")
            self.assertEqual(planning.ranked(db,0).fetchone()["title"], "Inbox")
            db.execute("UPDATE busy SET start=2700,end=3700")
            self.assertEqual(planning.ranked(db,0).fetchone()["title"], "Scope pilot")
            self.assertEqual(planning.reason_to_wait(db,3000),"Meeting in progress")
            db.execute("UPDATE task SET state='focus',due=200 WHERE id=2")
            self.assertEqual(planning.reason_to_wait(db,100),"Focus session in progress")
            db.executemany("INSERT INTO intervention VALUES(1,'snooze',?)", [(1,),(2,)])
            db.commit()
            alerts = []
            tick(db,4000,alerts.append)
            tick(db,4060,alerts.append)
            self.assertIn("five-minute",alerts[-1])
            self.assertTrue(planning.review(db,4100))

    def test_approved_write_and_receipt_replay(self):
        with tempfile.TemporaryDirectory() as tmp, closing(connect(Path(tmp)/"db")) as db:
            tagging.save_project(db,{'name':'Example','hints':'github.com/example/repo/'})
            reconcile(db,"github",[("https://github.com/example/repo/issues/1","Review",0)],0)
            draft = actions.draft(db,1,"Looks good")
            with patch("subprocess.check_output",side_effect=["me","me",'{"html_url":"receipt"}']) as call:
                self.assertEqual(actions.publish(db,draft,"gh","me",lambda _: "no"),"Draft retained")
                self.assertEqual(actions.publish(db,draft,"gh","me",lambda _: "POST"),"receipt")
                self.assertEqual(actions.publish(db,draft,"gh","me"),"receipt")
                self.assertEqual(call.call_count,3)

    def test_dependency_cycle_and_release(self):
        with tempfile.TemporaryDirectory() as tmp, closing(connect(Path(tmp)/"db")) as db:
            reconcile(db,"github",[("a","Deliver",0),("b","Prepare",0)],0)
            attention.decision(db,1,'accept');attention.decision(db,2,'accept')
            planning.add_dependency(db,1,2)
            self.assertEqual([r["id"] for r in planning.ranked(db,0)],[2])
            with self.assertRaises(ValueError):
                planning.add_dependency(db,2,1)
            db.execute("UPDATE task SET state='done' WHERE id=2")
            self.assertEqual([r["id"] for r in planning.ranked(db,0)],[1])
