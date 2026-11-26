"""Catalog regressions: ambiguity, corrections, stale responses and source grouping."""
import tempfile
import unittest
from pathlib import Path
import app
import paco
import tagging


class Catalog(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = paco.connect(Path(self.tmp.name)/'db')
        app.initialize(self.db)
        self.db.execute('CREATE TABLE IF NOT EXISTS discovered(source TEXT,key TEXT,task_id INTEGER,scheduled REAL,PRIMARY KEY(source,key))')

    def tearDown(self):
        self.db.close(); self.tmp.cleanup()

    def task(self, title, url=None):
        with self.db:
            ident = self.db.execute("INSERT INTO task(title,priority,state,due) VALUES(?,3,'open',0)", (title,)).lastrowid
            if url:self.db.execute('INSERT INTO discovered VALUES(?,?,?,0)', ('github',url,ident))
        return ident

    def project(self, name, hints='', area=''):
        return tagging.save_project(self.db,dict(name=name,hints=hints,area=area))

    def test_ambiguous_and_partial_words_are_not_confident_tags(self):
        self.project('Mobile', 'app')
        self.project('Client One', '@client.com')
        self.project('Client Two', '@client.com')
        a=self.task('Review application');b=self.task('Message ana@client.com');c=self.task('Message ana@client.com.evil')
        tagging.retag(self.db)
        for task in (a,b,c):self.assertIsNone(tagging.of_task(self.db,task))
        self.assertIn('Conflicting',tagging.catalog(self.db,b)['reason'])

    def test_narrow_hint_refines_broad_but_independent_clues_conflict(self):
        self.project('Client', 'github.com/acme/')
        specific=self.project('Website', 'github.com/acme/site/')
        a=self.task('Fix login','https://github.com/acme/site/issues/1')
        tagging.retag(self.db)
        self.assertEqual(tagging.of_task(self.db,a)['id'],specific)
        other=self.project('Billing','invoice')
        b=self.task('Fix invoice','https://github.com/acme/site/issues/2')
        tagging.retag(self.db)
        self.assertIsNone(tagging.of_task(self.db,b))

    def test_source_catalog_is_created_and_deleted_catalog_stays_deleted(self):
        a=self.task('Fix crash','https://github.com/acme/mobile/issues/1')
        tagging.retag(self.db)
        project=tagging.of_task(self.db,a)
        self.assertEqual(project['name'],'acme/mobile')
        tagging.delete_project(self.db,project['id']);tagging.retag(self.db)
        self.assertEqual(tagging.projects(self.db),[])

    def test_manual_correction_teaches_same_repo_and_explicit_none_wins(self):
        p=self.project('Client work',area='Consulting')
        a=self.task('Fix crash','https://github.com/acme/mobile/issues/1')
        b=self.task('Tune startup','https://github.com/acme/mobile/issues/2')
        tagging.tag(self.db,a,p)
        self.assertEqual(tagging.of_task(self.db,b)['how'],'learned')
        tagging.tag(self.db,b,None)
        tagging.retag(self.db)
        self.assertIsNone(tagging.of_task(self.db,b))
        c=self.task('Update icon','https://github.com/acme/mobile/issues/3')
        tagging.retag(self.db)
        self.assertIsNone(tagging.of_task(self.db,c))

    def test_changed_task_is_reclassified_but_manual_selection_is_preserved(self):
        a=self.project('Client A','alpha');b=self.project('Client B','bravo')
        t=self.task('alpha proposal');tagging.retag(self.db)
        self.assertEqual(tagging.of_task(self.db,t)['id'],a)
        with self.db:self.db.execute('UPDATE task SET title=? WHERE id=?',('bravo launch',t))
        tagging.retag(self.db);self.assertEqual(tagging.of_task(self.db,t)['id'],b)
        tagging.tag(self.db,t,a);tagging.retag(self.db)
        self.assertEqual(tagging.of_task(self.db,t)['id'],a)

    def test_model_uncertainty_is_reviewable_and_not_repeated(self):
        p=self.project('Marketing site',area='Marketing');t=self.task('Write launch copy');calls=[]
        def model(*args):
            calls.append(1)
            return {'assignments':[{'id':t,'project':'Marketing site','confidence':'medium','reason':'Possible launch work'}]},{}
        config={'provider':'ollama','model':'fixture'}
        tagging.retag(self.db,config,model);tagging.retag(self.db,config,model)
        self.assertEqual(len(calls),1)
        self.assertIsNone(tagging.of_task(self.db,t))
        self.assertEqual(tagging.catalog(self.db,t)['suggested']['id'],p)

    def test_slow_model_cannot_overwrite_manual_correction(self):
        a=self.project('Alpha');b=self.project('Bravo');t=self.task('Draft release')
        def model(*args):
            tagging.tag(self.db,t,b)
            return {'assignments':[{'id':t,'project':'Alpha','confidence':'high'}]},{}
        tagging.retag(self.db,{'provider':'ollama'},model)
        self.assertEqual(tagging.of_task(self.db,t)['id'],b)
        self.assertEqual(tagging.of_task(self.db,t)['how'],'manual')

    def test_model_areas_fill_only_automatic_projects_and_respect_user_edits(self):
        t=self.task('Fix GPU memory leak','https://github.com/acme/runtime/issues/1')
        calls=[]
        def model(config,system,data,source):
            calls.append(data)
            return {'areas':[{'id':data['projects'][0]['id'],'area':'Engineering','confidence':'high','reason':'GPU code changes'}]},{}
        tagging.retag(self.db,{'provider':'ollama'},model)
        project=tagging.of_task(self.db,t)
        self.assertEqual(project['area'],'Engineering')
        original=tagging.projects(self.db)[0]
        tagging.save_project(self.db,dict(original,area='Research'))
        tagging.retag(self.db,{'provider':'ollama'},model)
        self.assertEqual(tagging.of_task(self.db,t)['area'],'Research')
        self.assertEqual(len(calls),1)

    def test_permission_blocks_model_and_invalid_responses_do_not_crash(self):
        self.project('Client');t=self.task('Write a note')
        def forbidden(*args):raise AssertionError('should not call')
        tagging.retag(self.db,{'provider':'codex_cli','allowed_sources':[]},forbidden)
        tagging.retag(self.db,{'provider':'ollama'},lambda *args:({'assignments':'bad'},{}))
        self.assertIsNone(tagging.of_task(self.db,t))

if __name__=='__main__':unittest.main()
