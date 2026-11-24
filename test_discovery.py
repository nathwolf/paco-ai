import sqlite3
import tempfile
import unittest
from pathlib import Path
from contextlib import closing

from discovery import reconcile
from paco import connect


class DiscoveryTest(unittest.TestCase):
    def test_refresh_preserves_snooze_and_closes_removed_assignment(self):
        with tempfile.TemporaryDirectory() as folder, closing(connect(Path(folder)/"db")) as db:
            rows = [("issue1", "Send proposal", 100)]
            reconcile(db, "github", rows, 100)
            db.execute("UPDATE task SET due=900")
            reconcile(db, "github", rows, 200)
            self.assertEqual(db.execute("SELECT due FROM task").fetchall()[0][0], 900)
            self.assertEqual(db.execute("SELECT count(*) FROM task").fetchone()[0], 1)
            reconcile(db, "github", [], 300)
            self.assertEqual(db.execute("SELECT state FROM task").fetchone()[0], "done")
