"""Background loops survive failures; connections use WAL with one-time schema setup."""
from contextlib import closing
import json
import logging
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import app
import discovery
import paco
import workflows


class Loops(unittest.TestCase):
    def test_failing_pass_is_reported_retried_and_cleared(self):
        stop, calls, reports = threading.Event(), [], []
        def step():
            calls.append(1)
            if len(calls) <= 2:
                raise ValueError('private task text')
            if len(calls) == 4:
                stop.set()
        with self.assertLogs('paco', logging.WARNING) as logs:
            app.run_loop('reminders', stop, 0, step, lambda name, error: reports.append((name, error)))
        self.assertEqual(len(calls), 4)
        self.assertEqual([error is None for _, error in reports], [False, False, True])
        self.assertTrue(reports[0][1].startswith('ValueError at test_reliability.py:'))
        self.assertNotIn('private task text', ''.join(logs.output) + str(reports))

    def test_failure_label_never_contains_the_message(self):
        try:
            raise RuntimeError('subject: salary review')
        except RuntimeError as exc:
            label = app.failure_label(exc)
        self.assertTrue(label.startswith('RuntimeError at '))
        self.assertNotIn('salary', label)

    def test_scheduler_keeps_running_after_a_tick_fails_and_settings_show_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'tasks.sqlite3'
            with closing(paco.connect(path)) as db:
                app.initialize(db)
            ticks, seen_error, stop = [], [], threading.Event()
            def tick(db, now, deliver):
                ticks.append(now)
                if len(ticks) == 1:
                    raise RuntimeError('database is locked')
                if len(ticks) == 2:
                    seen_error.extend(r['error'] for r in db.execute("SELECT error FROM sync_status WHERE source='Paco reminders'"))
                if len(ticks) >= 3:
                    stop.set()
            with patch.object(app, 'TICK_INTERVAL', 0.01), patch.object(paco, 'tick', tick), \
                 patch('app.presence.active', return_value=True), \
                 patch.object(discovery, 'sync', lambda db: None), self.assertLogs('paco', logging.WARNING):
                thread = threading.Thread(target=app.worker, args=(path, paco.connect, stop))
                thread.start()
                thread.join(20)
            self.assertFalse(thread.is_alive())
            self.assertGreaterEqual(len(ticks), 3)
            self.assertEqual(len(seen_error), 1)
            self.assertIn('RuntimeError', seen_error[0])
            with closing(paco.connect(path)) as db:
                self.assertIsNone(db.execute("SELECT 1 FROM sync_status WHERE source='Paco reminders'").fetchone())


class Connections(unittest.TestCase):
    def test_wal_and_secure_delete_on_every_connection_schema_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            first, second = Path(tmp) / 'a.sqlite3', Path(tmp) / 'b.sqlite3'
            with patch.object(paco, 'initialize', wraps=paco.initialize) as setup:
                for path in (first, first, first, second):
                    with closing(paco.connect(path)) as db:
                        self.assertEqual(db.execute('PRAGMA journal_mode').fetchone()[0], 'wal')
                        self.assertEqual(db.execute('PRAGMA secure_delete').fetchone()[0], 1)
                        self.assertIsNotNone(db.execute("SELECT 1 FROM sqlite_master WHERE name='meeting_note'").fetchone())
            self.assertEqual(setup.call_count, 2)

    def test_forgetting_text_truncates_the_write_ahead_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'tasks.sqlite3'
            with closing(paco.connect(path)) as db:
                with db:
                    db.execute("INSERT INTO capture_rule VALUES('Notes',1,0)")
                workflows.capture(db, 'Notes', 'Plan', 'confidential plan text ' * 50)
                key = db.execute("SELECT source_key FROM evidence WHERE source='desktop'").fetchone()[0]
                self.assertGreater(Path(str(path) + '-wal').stat().st_size, 0)
                workflows.forget(db, 'desktop', key)
                self.assertEqual(Path(str(path) + '-wal').stat().st_size, 0)
                self.assertIsNone(db.execute("SELECT 1 FROM evidence WHERE source='desktop'").fetchone())


class Settings(unittest.TestCase):
    def test_concurrent_saves_leave_valid_private_config_and_no_temp_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / 'Paco' / 'sources.json'
            with patch.object(discovery, 'CONFIG', config):
                threads = [threading.Thread(target=app.save_settings, args=({'n': n, 'pad': 'x' * 20000},)) for n in range(20)]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join()
                self.assertIn(json.loads(config.read_text())['n'], range(20))
                self.assertEqual(config.stat().st_mode & 0o777, 0o600)
                self.assertEqual([p.name for p in config.parent.iterdir()], ['sources.json'])


if __name__ == '__main__':
    unittest.main()
