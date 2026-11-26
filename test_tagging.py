"""Catalog regressions: ambiguity, corrections, stale responses and source grouping."""
import tempfile
import unittest
from pathlib import Path
import app
import paco
import tagging


class CatalogFixture:

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


class Catalog(CatalogFixture, unittest.TestCase):
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

class UserCategories(CatalogFixture, unittest.TestCase):
    def test_new_category_moves_existing_repository_task(self):
        task=self.task('Prepare customer invoice','https://github.com/acme/product/issues/10')
        tagging.retag(self.db)
        self.assertEqual(tagging.of_task(self.db,task)['name'],'acme/product')
        project=self.project('Finance','invoice')
        self.assertEqual(tagging.of_task(self.db,task)['id'],project)
        tagging.tag(self.db,task,project)
        self.project('Other finance','invoice')
        self.assertEqual(tagging.of_task(self.db,task)['id'],project)

    def test_semantic_category_reconsiders_repository_fallback(self):
        task=self.task('Prepare quarterly numbers','https://github.com/acme/product/issues/11')
        tagging.retag(self.db)
        fallback=tagging.of_task(self.db,task)['id']
        project=self.project('Finance')
        self.assertEqual(tagging.of_task(self.db,task)['id'],fallback)
        calls=[]
        def model(config,system,data,source):
            calls.append(data)
            return {'assignments':[{'id':task,'project':'Finance','confidence':'high','reason':'Quarterly financial reporting'}]},{}
        tagging.retag(self.db,{'provider':'ollama'},model)
        self.assertEqual(tagging.of_task(self.db,task)['id'],project)
        self.assertTrue(calls[0]['projects'][0].get('user_created') in (True,False))

    def test_uncertain_semantic_match_keeps_source_bucket(self):
        task=self.task('Review quarterly numbers','https://github.com/acme/product/issues/12')
        tagging.retag(self.db);fallback=tagging.of_task(self.db,task)['id']
        self.project('Finance')
        def model(*args):
            return {'assignments':[{'id':task,'project':'Finance','confidence':'medium','reason':'Could be financial or product metrics'}]},{}
        tagging.retag(self.db,{'provider':'ollama'},model)
        self.assertEqual(tagging.of_task(self.db,task)['id'],fallback)
        self.assertEqual(tagging.catalog(self.db,task)['suggested']['name'],'Finance')

    def test_description_matches_and_unchanged_edit_does_not_pin_category(self):
        import workspace
        task=workspace.edit_task(self.db,{'changes':{'title':'Send the documents','project':None,'description':'Customer onboarding paperwork'}})['id']
        project=self.project('Onboarding')
        self.assertEqual(tagging.of_task(self.db,task)['id'],project)
        workspace.edit_task(self.db,{'id':task,'changes':{'priority':1,'project':project}})
        self.assertEqual(tagging.of_task(self.db,task)['how'],'rule')
