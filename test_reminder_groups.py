import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock

import app
import paco
import planning
import reminder_groups as groups
import task_relationships as rel
import workspace


class GroupDelivery(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db=paco.connect(Path(tmp.name)/'tasks')
        self.addCleanup(self.db.close)
        app.initialize(self.db)
        self.now=time.time()
        self.config={'provider':'codex_cli','allowed_sources':['chat']}
        with self.db:
            for k,v in [('hours','0-24'),('workdays','0,1,2,3,4,5,6')]:
                self.db.execute('INSERT OR REPLACE INTO preference VALUES(?,?)',(k,v))
        self.tasks=[workspace.edit_task(self.db,{'changes':{'title':title}})['id'] for title in
                    ('Check workshop return flight','Request workshop travel letter','Finish workshop travel form')]
        with self.db:self.db.execute('UPDATE task SET due=?',(self.now-10,))
        tasks=rel.snapshot(self.db,self.config)
        self.result={'merges':[],'groups':[dict(confidence='high',label='Workshop travel paperwork',
                     tasks=self.tasks,quotes=[{'task':t['id'],'quote':t['title']} for t in tasks])]}
        self.model=Mock(return_value=(self.result,{}))
        rel.reconcile(self.db,self.config,self.model)

    def test_one_banner_independent_completion_and_urgent_bypass(self):
        paco.tick(self.db,self.now,lambda msg:app.enqueue(self.db,self.now,msg))
        note=self.db.execute('SELECT * FROM notification').fetchone()
        self.assertEqual(note['reason'],groups.REASON)
        self.assertEqual(groups.current(self.db,note['id'],self.now),self.tasks)
        self.db.execute('UPDATE notification SET shown=?',(self.now,))
        self.assertIsNone(planning.next_reminder(self.db,self.now+3600))
        self.db.execute("UPDATE task SET state='done' WHERE id=?",(self.tasks[0],))
        self.assertEqual(groups.current(self.db,note['id'],self.now),self.tasks[1:])
        self.db.execute('INSERT INTO urgency VALUES(?,1)',(self.tasks[1],))
        self.assertEqual(planning.next_reminder(self.db,self.now+3600)['id'],self.tasks[1])

    def test_snooze_and_negative_feedback(self):
        with self.db:self.db.execute('UPDATE task SET due=? WHERE id=?',(self.now+800,self.tasks[0]))
        paco.tick(self.db,self.now,lambda msg:app.enqueue(self.db,self.now,msg))
        note=self.db.execute('SELECT id FROM notification').fetchone()[0]
        self.assertEqual(groups.members(self.db,note),self.tasks[1:])
        groups.split(self.db,note)
        rel.reconcile(self.db,self.config,self.model)
        self.assertEqual(self.db.execute('SELECT count(*) FROM reminder_member').fetchone()[0],0)
        self.assertEqual(len(self.model.call_args.args[2]['keep_separate_examples']),1)
