"""Interface contracts: safe page redirects, banner wording, served assets and well-formed pages."""
from contextlib import closing
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request
import app
import paco
import planning

BASE = Path(__file__).parent


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class Server(unittest.TestCase):
    def setUp(self):
        self.presence = patch('app.presence.active', return_value=True)
        self.presence.start(); self.addCleanup(self.presence.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'db'
        with closing(paco.connect(self.path)) as db:
            app.initialize(db)
        self.server, self.token = app.make_server(self.path, paco.connect)
        self.base = 'http://127.0.0.1:' + str(self.server.server_port)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(); self.tmp.cleanup()

    def location(self, query):
        opener = urllib.request.build_opener(NoRedirect)
        with self.assertRaises(urllib.error.HTTPError) as err:
            opener.open(self.base + '/?' + query, timeout=3)
        self.assertEqual(err.exception.code, 303)
        return err.exception.headers['Location']

    def test_sign_in_redirects_only_to_paco_pages(self):
        self.assertEqual(self.location('token=' + self.token), '/')
        for page in ('/', '/meetings', '/advanced', '/controls', '/#sessions'):
            self.assertEqual(self.location(f'token={self.token}&next={urllib.request.quote(page, safe="")}'), page)
        for hostile in ('https://evil.test/', '//evil.test', '/api/state', 'javascript:alert(1)'):
            self.assertEqual(self.location(f'token={self.token}&next={urllib.request.quote(hostile)}'), '/')

    def test_banner_carries_labels_and_plan_destination(self):
        now = time.time()
        with closing(paco.connect(self.path)) as db, db:
            db.execute("INSERT INTO notification(task,message,mood,reason,created) VALUES(NULL,'Your plan has 2 work blocks. First: A','friendly','Your daily plan',?)", (now,))
        request = urllib.request.Request(self.base + '/api/banner', headers={'Authorization': 'Bearer ' + self.token})
        value = json.load(urllib.request.urlopen(request, timeout=3))
        self.assertEqual(value['open'], '/advanced')
        self.assertEqual(value['labels']['show_plan'], 'Show plan')
        self.assertEqual(set(value['labels']), set(app.BANNER_LABELS['es']))

    def test_every_page_asset_is_served(self):
        opener = urllib.request.build_opener()
        opener.addheaders = [('Authorization', 'Bearer ' + self.token)]
        for page in ('setup.html', 'meetings.html', 'index.html'):
            for asset in re.findall(r'src="(/assets/[^"]+)"', (BASE / 'web' / page).read_text()):
                with opener.open(self.base + asset, timeout=3) as response:
                    self.assertEqual(response.status, 200, asset)
                    self.assertLess(len(response.read()), 400_000, asset + ' should be a small display copy')


class Wording(unittest.TestCase):
    def task(self, **values):
        return {'critical': 0, 'deadline': None, 'priority': 3, 'nudges': 0, 'state': 'open', 'minutes': None, **values}

    def test_headlines_say_why_now_and_fit_the_banner(self):
        now = 1_800_000_000
        cases = [
            (self.task(critical=1, deadline=now - 2 * 86400, minutes=180), 'Urgent · 2 days late'),
            (self.task(deadline=now + 5 * 3600, minutes=45), 'Due in 5 h · ~45 min'),
            (self.task(minutes=15), 'Next up · ~15 min'),
            (self.task(), 'Next up'),
            (self.task(state='focus'), 'Focus check-in'),
        ]
        for task, expected in cases:
            heading = planning.presentation(task, now)[1]
            self.assertEqual(heading, expected)
            self.assertLessEqual(len(heading), 24)
        self.assertEqual(planning.presentation(cases[0][0], now, spanish=True)[1], 'Urgente · 2 días tarde')
        self.assertEqual(planning.presentation(cases[0][0], now)[0], 'furious')  # moods unchanged

    def test_spanish_preference_translates_banner_labels(self):
        with tempfile.TemporaryDirectory() as tmp, closing(paco.connect(Path(tmp) / 'db')) as db:
            app.initialize(db)
            with db:
                db.execute("INSERT OR REPLACE INTO preference VALUES('language','es')")
                db.execute("INSERT INTO notification(task,message,mood,reason,created) VALUES(NULL,'x','friendly','Tu plan de hoy',0)")
            row = db.execute('SELECT * FROM notification').fetchone()
            value = app.banner_payload(db, row)
        self.assertEqual(value['labels']['done'], 'Hecho')
        self.assertEqual(value['open'], '/advanced')


class BannerContent(unittest.TestCase):
    def test_banner_splits_title_from_nudge_and_computes_fresh_chips(self):
        now = time.time()
        with tempfile.TemporaryDirectory() as tmp, closing(paco.connect(Path(tmp) / 'db')) as db:
            app.initialize(db)
            with db:
                db.execute("INSERT INTO task(id,title,priority,state,due) VALUES(1,'Prepare Q4 slides',3,'open',0)")
                db.execute('INSERT INTO urgency VALUES(1,1)')
                db.execute("INSERT INTO details VALUES(1,'',180,?)", (now - 2 * 86400,))
                db.execute("INSERT INTO notification(task,message,mood,reason,created) VALUES(1,'Come on. Take the first step: Prepare Q4 slides','furious','old',?)", (now - 86400,))
            value = app.banner_payload(db, db.execute('SELECT * FROM notification').fetchone(), now)
        self.assertEqual(value['title'], 'Prepare Q4 slides')
        self.assertEqual(value['nudge'], 'Come on. Take the first step')
        self.assertEqual(value['badges'], [{'text': 'Urgent', 'tone': 'red'}, {'text': '2 days late', 'tone': 'red'}, {'text': '~180 min', 'tone': 'gray'}])

    def test_chip_tones_follow_meaning(self):
        now = 1_800_000_000
        task = lambda **v: {'critical': 0, 'deadline': None, 'state': 'open', 'minutes': None, **v}
        self.assertEqual(planning.badges(task(deadline=now + 3600), now)[0], ('Due in 1 h', 'orange'))
        self.assertEqual(planning.badges(task(deadline=now + 3 * 86400), now)[0], ('Due in 3 days', 'green'))
        self.assertEqual(planning.badges(task(state='focus'), now)[0], ('Focus check-in', 'blue'))
        self.assertEqual(planning.badges(task(), now), [('Next up', 'green')])


class Pages(unittest.TestCase):
    def test_pages_have_no_malformed_end_tags_and_options_are_complete(self):
        class Options(HTMLParser):
            def __init__(self):
                super().__init__(); self.selects = {}; self.current = None
            def handle_starttag(self, tag, attrs):
                attrs = dict(attrs)
                if tag == 'select':
                    self.current = attrs.get('name') or attrs.get('id'); self.selects[self.current] = []
                elif tag == 'option' and self.current:
                    self.selects[self.current].append(attrs.get('value'))
            def handle_endtag(self, tag):
                if tag == 'select':
                    self.current = None
        pages = {}
        for page in ('setup.html', 'meetings.html', 'index.html'):
            text = (BASE / 'web' / page).read_text()
            self.assertIsNone(re.search(r'</\w+\s+[^>]+>', text), page + ' has an end tag with attributes')
            self.assertEqual(text.count('<option'), text.count('</option>'), page)
            parser = Options(); parser.feed(text); pages[page] = parser.selects
        self.assertIn('en', pages['meetings.html']['language'])
        self.assertIn('anthropic', pages['meetings.html']['provider'])
        self.assertIn('claude', pages['index.html']['talk-target'])


if __name__ == '__main__':
    unittest.main()
