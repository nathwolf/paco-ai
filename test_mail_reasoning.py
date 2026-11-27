import base64
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import Mock

import mail_reasoning as mail
from paco import connect


def message(mid, text, sent=False):
    return {"id":mid, "internalDate":mid, "labelIds":["SENT"] if sent else [],
            "payload":{"headers":[], "mimeType":"text/plain",
                       "body":{"data":base64.urlsafe_b64encode(text.encode()).decode()}}}


class MailTest(unittest.TestCase):
    def test_routine_account_actions_are_skipped_without_losing_real_work(self):
        with tempfile.TemporaryDirectory() as folder, closing(connect(Path(folder)/'db')) as db:
            mail.initialize(db)
            quote='Verify your email. Sign and return the proposal by Friday.'
            thread=dict(id='mixed',historyId='1',messages=[message('1',quote)])
            titles=['Verify your email to activate your Inocrowd registration',
                    'Confirmar el correo de registro para activar la cuenta de Global66',
                    'Verify your email address to complete Dropbox signup',
                    'Activate your account', 'Vérifier votre adresse e-mail',
                    'Sign in to your new account', 'Sign the proposal']
            predict=Mock(return_value={'actions':[dict(kind='add',title=t,message='1',quote=quote) for t in titles]})
            mail.analyze(db,thread,{},'user',predict)
            self.assertEqual([r[0] for r in db.execute('SELECT title FROM task')],['Sign the proposal'])
            self.assertFalse(mail.analyze(db,thread,{},'user',predict))

    def test_real_short_actions_are_not_filtered_as_account_noise(self):
        import mail_noise
        for title in ('Sign the offer letter','Confirm the meeting with Marcos',
                      'Verify the invoice total','Fix email verification in the app',
                      'Review suspicious sign-in activity','Submit the visa application',
                      'Renovar el permiso de residencia'):
            with self.subTest(title=title):self.assertFalse(mail_noise.routine_account_action(title))

    def test_long_generated_title_keeps_full_details_in_notes(self):
        with tempfile.TemporaryDirectory() as folder, closing(connect(Path(folder)/'db')) as db:
            mail.initialize(db)
            title='Follow up with the project coordinator about the outstanding confirmation and contact the partner only after approval to schedule the December meeting'
            thread=dict(id='long',historyId='1',messages=[message('1',title)])
            predict=Mock(return_value={'actions':[dict(kind='add',title=title,description='Only contact the partner after approval.',message='1',quote=title)]})
            mail.analyze(db,thread,{},'user',predict)
            self.assertLessEqual(len(db.execute('SELECT title FROM task').fetchone()[0]),90)
            notes=db.execute('SELECT description FROM task_extra').fetchone()[0]
            self.assertIn(title,notes)
            self.assertIn('Only contact the partner after approval.',notes)

    def test_shortened_labels_do_not_merge_distinct_obligations(self):
        import attention
        with tempfile.TemporaryDirectory() as folder, closing(connect(Path(folder)/'db')) as db:
            mail.initialize(db)
            prefix='Prepare the complete project documentation requested by the coordinator for the upcoming assessment of '
            titles=[prefix+'the GPU implementation',prefix+'the separate CPU implementation']
            thread=dict(id='distinct',historyId='1',messages=[message(str(i+1),t) for i,t in enumerate(titles)])
            predict=Mock(return_value={'actions':[dict(kind='add',title=t,message=str(i+1),quote=t) for i,t in enumerate(titles)]})
            mail.analyze(db,thread,{},'user',predict)
            attention.reconcile_duplicates(db)
            self.assertEqual([r[0] for r in db.execute('SELECT status FROM task_attention')],['suggested','suggested'])

    def test_thread_replay_resolution_and_invalid_evidence(self):
        with tempfile.TemporaryDirectory() as folder, closing(connect(Path(folder)/"db")) as db:
            mail.initialize(db)
            thread = dict(id="a", historyId="1", messages=[message("1", "We need your signature.\n> Old request")])
            add = dict(kind="add", title="Sign proposal", message="1", quote="your signature")
            predict = Mock(return_value={"actions":[add]})
            run = lambda: mail.analyze(db, thread, {}, "user", predict)
            self.assertTrue(run())
            self.assertNotIn("Old request", predict.call_args.args[1]["messages"][0]["text"])
            self.assertFalse(run())
            predict.assert_called_once()
            thread.update(historyId="2")
            thread["messages"].append(message("2", "Signed and returned.", True))
            close = dict(kind="close", task=1, message="2", quote="Signed and returned.")
            predict.return_value = {"actions":[close, dict(add, quote="invented")]}
            with self.assertRaises(ValueError):
                run()
            self.assertEqual(db.execute("SELECT state FROM task").fetchone()[0], "open")
            predict.return_value = {"actions":[close]}
            self.assertTrue(run())
            self.assertEqual(db.execute("SELECT state FROM task").fetchone()[0], "open")
            self.assertEqual(db.execute("SELECT outcome FROM source_event").fetchone()[0], "suggested_completion")
