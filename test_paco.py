import tempfile
import unittest
from pathlib import Path
from contextlib import closing
from unittest.mock import patch

import paco


class ReminderTest(unittest.TestCase):
    def test_lifecycle_across_restarts(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "db"
            def command(*args):
                with patch("paco.time.time", return_value=100):
                    paco.main(["--db", str(path), *args])
            messages = []
            def tick(now):
                with closing(paco.connect(path)) as db:
                    paco.tick(db, now, messages.append)
            command("add", "Review proposal")
            tick(100)
            tick(101)
            self.assertEqual(len(messages), 1)
            command("snooze", "1", "5")
            tick(399)
            self.assertEqual(len(messages), 1)
            tick(400)
            tick(1300)
            self.assertIn("Still waiting", messages[-1])
            command("start", "1", "25")
            tick(1599)
            self.assertEqual(len(messages), 3)
            tick(1600)
            self.assertIn("Focus check-in", messages[-1])
            command("block", "1")
            tick(3000)
            self.assertEqual(len(messages), 4)
            command("resume", "1")
            tick(3001)
            self.assertEqual(len(messages), 4)  # Rolling allowance is temporarily full.
            tick(10901)  # Morning notifications no longer suppress later work.
            command("done", "1")
            tick(99999)
            self.assertEqual(len(messages), 5)
