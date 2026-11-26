import base64
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import Mock

import mail_reasoning as mail
from paco import connect


def message(mid, text, sent=False):
    return {"id":mid, "internalDate":mid, "labelIds":["SENT"] if sent else [],
            "payload":{"headers":[], "mimeType":"text/plain",
                       "body":{"data":base64.urlsafe_b64encode(text.encode()).decode()}}}


class MailTest(unittest.TestCase):
    def test_thread_replay_resolution_and_invalid_evidence(self):
        with tempfile.TemporaryDirectory() as folder, closing(connect(Path(folder)/"db")) as db:
            mail.initialize(db)
            thread = dict(id="a", historyId="1", messages=[message("1", "We need your signature.\n> Old request")])
            add = dict(kind="add", title="Sign proposal", message="1", quote="your signature")
            predict = Mock(return_value={"actions":[add]})
            run = lambda: mail.analyze(db, thread, {}, "user", predict)
            self.assertTrue(run())
            self.assertNotIn("Old request", predict.call_args.args[1]["messages"][0]["text"])
            self.assertFalse(run())
            predict.assert_called_once()
            thread.update(historyId="2")
            thread["messages"].append(message("2", "Signed and returned.", True))
            close = dict(kind="close", task=1, message="2", quote="Signed and returned.")
            predict.return_value = {"actions":[close, dict(add, quote="invented")]}
            with self.assertRaises(ValueError):
                run()
            self.assertEqual(db.execute("SELECT state FROM task").fetchone()[0], "open")
            predict.return_value = {"actions":[close]}
            self.assertTrue(run())
            self.assertEqual(db.execute("SELECT state FROM task").fetchone()[0], "open")
            self.assertEqual(db.execute("SELECT outcome FROM source_event").fetchone()[0], "suggested_completion")
