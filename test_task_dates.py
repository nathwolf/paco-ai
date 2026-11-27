import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
import app
import discovery
import mail_reasoning
import paco
from task_dates import timestamp
from test_mail_reasoning import message


class TaskDates(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name)/'db'
        self.db = paco.connect(self.path)
        self.addCleanup(self.db.close)
        app.initialize(self.db)

    def deadline(self, task):
        row = self.db.execute('SELECT deadline FROM details WHERE task=?',(task,)).fetchone()
        return row[0] if row else None

    def test_chat_add_keeps_fields_through_sync(self):
        import company_sync
        task = app.act(self.db,self.path,paco.connect,dict(action='add',title='Send plan',
            deadline='2026-12-03',description='Include cost',tags=['admin'],estimate_minutes=45))['id']
        app.act(self.db,self.path,paco.connect,dict(action='estimate',id=task,minutes=55))
        wire = company_sync.local_data(self.db,'task',task)
        self.assertEqual((wire['description'],wire['tags'],wire['estimate_minutes'],wire['deadline']),
                         ('Include cost',['admin'],55,timestamp('2026-12-03')))

    def test_source_date_moves_and_preserves_personal_edit(self):
        def refresh(day):
            discovery.reconcile(self.db,'tasks',[('key','Send plan',100,day)],100)
        refresh(400)
        refresh(800)
        self.assertEqual(self.deadline(1),800)
        self.db.execute('UPDATE details SET deadline=600 WHERE task=1')
        refresh(900)
        self.assertEqual(self.deadline(1),600)

    def test_later_mail_fills_only_with_timing_evidence(self):
        mail_reasoning.initialize(self.db)
        thread=dict(id='abc',historyId='1',messages=[message('1','Please send the plan.')])
        add=dict(kind='add',title='Send plan',message='1',quote='send the plan',
                 deadline='2026-12-03',deadline_quote='invented')
        def apply(action):
            mail_reasoning.analyze(self.db,thread,{},'me',Mock(return_value={'actions':[action]}))
        apply(add)
        self.assertIsNone(self.deadline(1))
        thread.update(historyId='2')
        thread['messages'].append(message('2','Please send it by December 3.'))
        apply(dict(kind='date',task=1,message='2',quote='send it by December 3',
                   deadline='2026-12-03',deadline_quote='by December 3'))
        self.assertEqual(self.deadline(1),timestamp('2026-12-03'))
