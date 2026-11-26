"""Call-outs: Paco judges what you're doing, and gets furious when you're behind and on garbage."""
from contextlib import closing
from datetime import datetime
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import wave
import app
import discovery
import flow
import paco
import slacking

BASE = Path(__file__).parent
NOW = datetime(2026, 11, 25, 11, 0).timestamp()     # a Wednesday, inside default working hours


class FakeModel:
    """Stands in for models.complete; records what Paco sent."""
    def __init__(self, verdict='distraction', label='Instagram Reels', roast='Reels won’t finish the slides.', fail=False):
        self.calls, self.answer, self.fail = [], {'verdict': verdict, 'label': label, 'roast': roast}, fail

    def __call__(self, config, system, data, source):
        self.calls.append({'system': system, 'data': data, 'source': source})
        if self.fail:
            raise ValueError('Model request failed (HTTP 500)')
        return dict(self.answer), {}


class CallOut(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.config = Path(self.tmp.name) / 'sources.json'
        self.patch = patch.object(discovery, 'CONFIG', self.config); self.patch.start()
        self.db = paco.connect(Path(self.tmp.name) / 'db')
        app.initialize(self.db)
        with self.db:
            self.db.executemany('INSERT OR REPLACE INTO preference VALUES(?,?)', [('hours', '9-18'), ('workdays', '0,1,2,3,4')])
        slacking.configure(self.db, {'enabled': True, 'sound': True, 'judge': True, 'behind': 3})
        self.model(['activity', 'chat'])

    def tearDown(self):
        self.db.close(); self.patch.stop(); self.tmp.cleanup()

    def model(self, consent, provider='anthropic'):
        self.config.write_text(json.dumps({'model': {'provider': provider, 'model': 'claude-test', 'allowed_sources': consent}}))

    def late(self, count, critical=0):
        with self.db:
            for i in range(count):
                ident = self.db.execute("INSERT INTO task(title,priority,state,due) VALUES(?,3,'open',?)", (f'Late task {i}', NOW)).lastrowid
                self.db.execute('INSERT INTO urgency VALUES(?,?)', (ident, critical))
                self.db.execute("INSERT INTO details VALUES(?,'',30,?)", (ident, NOW - (i + 1) * 86400))

    def spend(self, seconds, fake=None, step=15, **meta):
        """Stay on one activity: activity checks every 15 s, each followed by the background review."""
        values = {'app': 'Safari', 'bundle': 'com.apple.Safari', 'idle': 3, 'locked': False, **meta}
        start = self.clock = getattr(self, 'clock', NOW)
        for t in range(0, seconds + 1, step):
            flow.sample(self.db, now=start + t, reader=lambda: values)
            slacking.review(self.db, now=start + t, complete=fake or FakeModel(),reader=lambda:values)
        self.clock = start + seconds + step

    def callouts(self):
        return self.db.execute('SELECT * FROM notification WHERE reason=?', (slacking.REASON,)).fetchall()

    def payload(self):
        return app.banner_payload(self.db, self.callouts()[-1], self.clock)

    def test_paco_judges_an_unlisted_site_and_writes_the_roast(self):
        self.late(3)
        fake = FakeModel(label='doom-scrolling Threads', roast='Threads can wait. The slides cannot.')
        self.spend(75, fake, title='Home • Threads')
        value = self.payload()
        self.assertEqual(value['mood'], 'rage')
        self.assertTrue(value['scream'])
        self.assertEqual(value['badges'][:2], [{'text': 'Caught on doom-scrolling Threads', 'tone': 'red'}, {'text': '3 late', 'tone': 'red'}])
        self.assertEqual(value['nudge'], 'Threads can wait. The slides cannot.')
        call = fake.calls[0]
        self.assertEqual(call['source'], 'activity')
        self.assertEqual(call['data']['activity'], {'app': 'Safari', 'bundle': 'com.apple.Safari', 'title': 'Home • Threads'})
        self.assertEqual(call['data']['late_tasks'], ['Late task 2', 'Late task 1', 'Late task 0'])
        self.assertIn('untrusted', call['system'])

    def test_work_is_left_alone_and_each_activity_is_judged_once(self):
        self.late(3)
        fake = FakeModel(verdict='work', label='')
        self.spend(300, fake, title='python - asyncio gather vs wait - Stack Overflow')
        self.assertEqual(self.callouts(), [])
        self.assertEqual(len(fake.calls), 1)          # cached for the rest of the five minutes
    def test_slow_verdict_is_discarded_after_switching_back_to_work(self):
        self.late(3)
        meta={'app':'Safari','bundle':'com.apple.Safari','title':'Reels - Instagram','idle':1,'locked':False}
        for t in (NOW,NOW+30,NOW+60):flow.sample(self.db,t,reader=lambda:meta)
        fake=FakeModel()
        result=slacking.review(self.db,NOW+61,complete=fake,reader=lambda:dict(meta,app='Xcode',bundle='com.apple.dt.Xcode',title='Project'))
        self.assertIsNone(result);self.assertEqual(len(fake.calls),1);self.assertEqual(self.callouts(),[])
    def test_queued_callout_is_cancelled_after_activity_change_or_holiday(self):
        self.late(3,critical=1);self.spend(75,FakeModel(),title='Instagram Reels')
        row=self.callouts()[0]
        self.assertTrue(slacking.delivery_allowed(self.db,row['id'],self.clock-15))
        with self.db:self.db.execute("INSERT OR REPLACE INTO preference VALUES('mode','holiday')")
        self.assertFalse(slacking.delivery_allowed(self.db,row['id'],self.clock-15))
        with self.db:
            self.db.execute("DELETE FROM preference WHERE key='mode'")
            slacking.observe(self.db,{'app':'Safari','bundle':'com.apple.Safari','title':'Python documentation','idle':0,'locked':False},self.clock)
        self.assertFalse(slacking.delivery_allowed(self.db,row['id'],self.clock))
    def test_failed_final_activity_read_cannot_use_old_verdict(self):
        self.late(3)
        meta={'app':'Safari','bundle':'com.apple.Safari','title':'Instagram','idle':1,'locked':False}
        for t in (NOW,NOW+30,NOW+60):flow.sample(self.db,t,reader=lambda:meta)
        def missing():raise OSError('permission unavailable')
        self.assertIsNone(slacking.review(self.db,NOW+61,complete=FakeModel(),reader=missing))
        self.assertEqual(self.callouts(),[])
    def test_cached_verdict_changes_with_work_context_and_model(self):
        self.late(3);late=slacking.behind(self.db,NOW);config=slacking.model_config(self.db);fake=FakeModel()
        slacking.judge(self.db,config,{'app':'Safari'},'same-site',late,NOW,fake)
        late=[dict(r) for r in late];late[0]['title']='Research this site for work'
        slacking.judge(self.db,config,{'app':'Safari'},'same-site',late,NOW+1,fake)
        slacking.judge(self.db,dict(config,model='other'),{'app':'Safari'},'same-site',late,NOW+2,fake)
        self.assertEqual(len(fake.calls),3)
    def test_separate_activity_model_preserves_main_model_and_permissions(self):
        self.config.write_text(json.dumps({'model':{'provider':'codex_cli','model':'','allowed_sources':['chat']},
            'activity_model':{'provider':'private','model':'qwen','endpoint':'http://127.0.0.1:18766/v1','remote_processing':True,'allowed_sources':['activity']}}))
        self.assertEqual(slacking.model_config(self.db)['model'],'qwen')
        data=json.loads(self.config.read_text());data['activity_model']['allowed_sources']=[];self.config.write_text(json.dumps(data))
        self.assertIsNone(slacking.model_config(self.db))

    def test_model_is_not_asked_when_no_call_out_could_happen(self):
        fake = FakeModel()
        self.late(2)                                                       # not behind yet
        self.spend(120, fake, title='Reels • Instagram')
        self.late(3)
        self.spend(120, fake, app='Xcode', bundle='com.apple.dt.Xcode')    # behind, but in a work app
        self.spend(45, fake, title='Funny cats - YouTube')                 # a new activity, under a minute
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO preference VALUES('mode','holiday')")
        self.spend(120, fake, title='Funny cats - YouTube')                # on holiday
        self.assertEqual(fake.calls, [])
        self.assertEqual(self.callouts(), [])

    def test_hosted_model_needs_the_activity_permission(self):
        self.late(3)
        self.model(['chat'])                          # tasks yes, "What I'm doing" no
        fake = FakeModel()
        self.spend(75, fake, title='Some forum I never listed')
        self.assertEqual(fake.calls, [])
        self.assertEqual(self.callouts(), [])
        self.spend(75, fake, title='Reels • Instagram')   # the built-in list still works without a model
        self.assertEqual(fake.calls, [])
        self.assertEqual(self.payload()['badges'][0]['text'], 'Caught on Instagram')

    def test_local_model_needs_no_permission_and_tasks_need_their_own(self):
        self.late(3)
        self.model([], provider='ollama')
        fake = FakeModel()
        self.spend(75, fake, title='Some forum')
        self.assertEqual(len(fake.calls), 1)
        self.model(['activity'])                      # hosted, without the tasks permission
        slacking._VERDICTS.clear()
        with self.db:
            self.db.execute("DELETE FROM preference WHERE key IN ('callout_last','callout_count')")
        fake2 = FakeModel()
        self.spend(75, fake2, title='Another forum')
        self.assertNotIn('late_tasks', fake2.calls[0]['data'])

    def test_lists_games_and_failures(self):
        self.late(3)
        slacking.configure(self.db, {'enabled': True, 'judge': True, 'behind': 3, 'always': 'LinkedIn', 'never': 'YouTube'})
        fake = FakeModel()
        self.spend(75, fake, title='Lecture 4: transformers - YouTube')   # "never" wins, model not asked
        self.assertEqual((fake.calls, self.callouts()), ([], []))
        self.spend(75, fake, title='Feed | LinkedIn')                     # "always" wins, model not asked
        self.assertEqual(fake.calls, [])
        self.assertEqual(self.payload()['badges'][0]['text'], 'Caught on LinkedIn')
        with self.db:
            self.db.execute("DELETE FROM preference WHERE key IN ('callout_last','callout_count')")
        self.spend(75, fake, app='Hades', bundle='com.supergiant.hades', category='public.app-category.action-games')
        self.assertEqual(self.payload()['badges'][0]['text'], 'Caught on Hades')
        with self.db:
            self.db.execute("DELETE FROM preference WHERE key IN ('callout_last','callout_count')")
        broken = FakeModel(fail=True)
        self.spend(75, broken, title='Unknown page')                      # an error is not a verdict
        self.assertEqual(len(self.callouts()), 2)

    def test_model_answers_are_validated(self):
        self.late(3)
        fake = FakeModel(verdict='DISTRACTION!!', label='x' * 300, roast='y' * 500)
        self.spend(75, fake, title='Page')
        self.assertEqual(self.callouts(), [])                              # unknown verdict = unclear
        slacking._VERDICTS.clear()
        fake = FakeModel(label='z' * 300, roast='Get back\n\nto work ' * 20)
        self.spend(75, fake, title='Other page')
        value = self.payload()
        self.assertLessEqual(len(value['badges'][0]['text']), len('Caught on ') + 40)
        self.assertLessEqual(len(value['nudge']), 120)
        self.assertNotIn('\n', value['nudge'])

    def test_titles_are_never_stored(self):
        self.late(3)
        self.spend(75, FakeModel(), title='Instagram — private message from Sam')
        dump = '\n'.join(self.db.iterdump())
        self.assertNotIn('private message', dump)
        self.assertNotIn('Sam', dump)

    def test_every_protection_still_wins(self):
        self.late(5, critical=1)
        cases = {
            'paused': lambda: self.db.execute("INSERT OR REPLACE INTO preference VALUES('mode','paused')"),
            'meeting': lambda: self.db.execute('INSERT INTO busy VALUES(?,?)', (NOW - 60, NOW + 7200)),
            'after hours': lambda: self.db.execute("INSERT OR REPLACE INTO preference VALUES('hours','9-10')"),
        }
        for name, setup in cases.items():
            with self.subTest(name):
                with self.db:
                    setup()
                fake = FakeModel()
                self.spend(90, fake, title='Reels • Instagram')
                self.assertEqual((fake.calls, self.callouts()), ([], []), name)
                with self.db:
                    self.db.execute("DELETE FROM preference WHERE key='mode'")
                    self.db.execute("INSERT OR REPLACE INTO preference VALUES('hours','9-18')")
                    self.db.execute('DELETE FROM busy')
        fake = FakeModel()
        self.spend(90, fake, title='Reels • Instagram', idle=600)                # away from the keyboard
        self.assertEqual(self.callouts(), [])

    def test_rate_limited_and_capped(self):
        self.late(3)
        self.spend(40 * 60, FakeModel(), step=60, app='TikTok')
        self.assertEqual(len(self.callouts()), 3)     # at about 1, 16 and 31 minutes

    def test_on_by_default_and_purged_after_a_day(self):
        with tempfile.TemporaryDirectory() as tmp, closing(paco.connect(Path(tmp) / 'db')) as db:
            self.assertTrue(slacking.enabled(db))
        self.late(3)
        self.spend(75, FakeModel(), title='Reels • Instagram')
        self.assertEqual(len(self.callouts()), 1)
        slacking.purge(self.db, self.clock + 86400)
        self.assertEqual(self.callouts(), [])
        self.assertIsNone(self.db.execute('SELECT 1 FROM callout').fetchone())

    def test_status_explains_what_judging_needs(self):
        self.assertTrue(slacking.status(self.db)['judge_ready'])
        self.model(['chat'])
        self.assertIn('What I’m doing', slacking.status(self.db)['judge_state'])
        self.config.unlink()
        self.assertIn('Connect a model', slacking.status(self.db)['judge_state'])

    def test_preview_and_sound_off(self):
        slacking.configure(self.db, {'enabled': True, 'sound': False, 'judge': True, 'behind': 3})
        ident = slacking.preview(self.db, NOW)
        value = app.banner_payload(self.db, self.db.execute('SELECT * FROM notification WHERE id=?', (ident,)).fetchone())
        self.assertFalse(value['scream'])
        self.assertEqual(value['badges'][-1], {'text': 'Preview', 'tone': 'gray'})

    def test_scream_file_is_short_and_not_full_scale(self):
        with wave.open(str(BASE / 'assets/sounds/paco-screech.wav')) as w:
            seconds = w.getnframes() / w.getframerate()
            frames = w.readframes(w.getnframes())
        peak = max(abs(int.from_bytes(frames[i:i + 2], 'little', signed=True)) for i in range(0, len(frames), 2))
        self.assertLess(seconds, 2.0)                       # short: loud, not sustained
        self.assertGreater(peak / 32767, 0.85)              # loud: about −1 dBFS
        self.assertLess(peak / 32767, 0.95)                 # never clipped flat at full scale
        samples = [int.from_bytes(frames[i:i + 2], 'little', signed=True) for i in range(0, len(frames), 2)]
        crossings = sum(1 for a, b in zip(samples, samples[1:]) if (a < 0) != (b < 0))
        self.assertGreater(crossings / 2 / seconds, 2000)  # high pitched: well above 2 kHz on average


if __name__ == '__main__':
    unittest.main()
