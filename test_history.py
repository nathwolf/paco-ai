import sqlite3
import unittest
from unittest.mock import Mock
from history_sync import update


class History(unittest.TestCase):
    def test_resumable_work_and_atomic_cursor(self):
        db = sqlite3.connect(":memory:")
        self.addCleanup(db.close)
        get = Mock(return_value={"threads":[{"id":"old"}]})
        update(db,get,"owner","10")
        update(db,get,"owner","10")
        get.assert_called_once()
        get.side_effect = [{"nextPageToken":"2","history":[{"messages":[{"threadId":"new"}]}]}, IOError()]
        with self.assertRaises(IOError):
            update(db,get,"owner","11")
        self.assertEqual(db.execute("SELECT version FROM gmail_cursor").fetchone()[0],"10")
        get.side_effect = [{"history":[{"messages":[{"threadId":"new"},{"threadId":"new"}]}]}]
        update(db,get,"owner","11")
        self.assertEqual(db.execute("SELECT count(*) FROM gmail_work").fetchone()[0],2)
