"""Every model provider: request shape, consent before any key or network, and readable failures."""
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import app
import models


class Response(io.BytesIO):
    pass


def transport_returning(body, seen):
    def transport(request, timeout):
        seen.append({'url': request.full_url, 'headers': dict(request.header_items()), 'body': json.loads(request.data)})
        return Response(json.dumps(body).encode())
    return transport


class Providers(unittest.TestCase):
    def test_real_cli_answer_survives_temporary_directory_cleanup(self):
        import sys
        output, folder = models._cli([sys.executable, '-c',
            'from pathlib import Path; Path("answer.txt").write_text(\'{"ok":true}\'); print("progress")',
            '-o', 'answer.txt'], 'synthetic test', 10)
        self.assertEqual(models.parse(output), {'ok': True})
        self.assertFalse(Path(folder).exists())

    def test_bedrock_converse_with_api_key(self):
        seen = []
        body = {'output': {'message': {'content': [{'text': '{"answer":"ok"}'}]}}, 'usage': {'inputTokens': 9}}
        config = {'provider': 'bedrock', 'model': 'us.anthropic.claude-sonnet-5-5-v1:0', 'region': 'eu-west-1', 'allowed_sources': ['chat']}
        with patch('models.secret', return_value='bedrock-key'):
            value, metrics = models.complete(config, 'system', {'q': 1}, 'chat', transport_returning(body, seen))
        self.assertEqual(value, {'answer': 'ok'})
        self.assertEqual(seen[0]['url'], 'https://bedrock-runtime.eu-west-1.amazonaws.com/model/us.anthropic.claude-sonnet-5-5-v1%3A0/converse')
        self.assertEqual(seen[0]['headers']['Authorization'], 'Bearer bedrock-key')
        self.assertEqual(seen[0]['body']['messages'][0]['content'][0]['text'], '{"q": 1}')
        self.assertIn('system', seen[0]['body']['system'][0]['text'])
        with self.assertRaises(ValueError):
            models.validate_region('eu-west-1/../evil')

    def test_claude_code_runs_without_tools_in_an_empty_folder(self):
        calls = []
        def runner(args, prompt, timeout):
            calls.append((args, prompt))
            return json.dumps({'type': 'result', 'result': 'Sure: {"verdict":"work"}', 'is_error': False, 'usage': {'output_tokens': 4}}), '/tmp/x'
        config = {'provider': 'claude_code', 'model': '', 'allowed_sources': ['activity']}
        with patch('shutil.which', return_value='/usr/local/bin/claude'):
            value, _ = models.complete(config, 'Judge this', {'app': 'Safari'}, 'activity', runner=runner)
        self.assertEqual(value, {'verdict': 'work'})
        args, prompt = calls[0]
        self.assertEqual(args[:5], ['/usr/local/bin/claude', '-p', '--output-format', 'json', '--tools'])
        self.assertEqual(args[5], '')            # tools disabled
        self.assertIn('untrusted data', prompt)
        self.assertNotIn('--model', args)       # blank means the CLI's default

    def test_codex_reads_the_final_message_in_a_read_only_sandbox(self):
        def runner(args, prompt, timeout):
            folder = Path(self.tmp)
            (folder / 'answer.txt').write_text('```json\n{"ok": true}\n```')
            self.args = args
            return 'progress…', str(folder)
        import tempfile
        with tempfile.TemporaryDirectory() as self.tmp, patch('shutil.which', return_value='/opt/bin/codex'):
            value, _ = models.complete({'provider': 'codex_cli', 'model': 'gpt-5', 'allowed_sources': ['chat']}, 's', {}, 'chat', runner=runner)
        self.assertEqual(value, {'ok': True})
        self.assertIn('read-only', self.args)
        self.assertEqual(self.args[-3:], ['-m', 'gpt-5', '-'])

    def test_local_servers_need_no_consent_but_remote_ones_do(self):
        seen = []
        body = {'choices': [{'message': {'content': '{"ok": true}'}}]}
        local = {'provider': 'private', 'model': 'llama', 'endpoint': 'http://localhost:1234/v1'}
        with patch('models.secret', side_effect=ValueError('no key')):
            models.complete(local, 's', {}, 'gmail', transport_returning(body, seen))
        self.assertEqual(seen[0]['url'], 'http://localhost:1234/v1/chat/completions')
        self.assertTrue(models.is_local({'provider': 'ollama'}))
        remote = dict(local, endpoint='https://gpu.example/v1')
        for config in (remote, {'provider': 'claude_code'}, {'provider': 'codex_cli'}, {'provider': 'bedrock', 'model': 'm', 'region': 'us-east-1'}):
            with patch('models.secret') as key, self.assertRaises(ValueError):
                models.complete(config, 's', {}, 'gmail')
            key.assert_not_called()

    def test_unreachable_model_is_a_readable_error(self):
        import urllib.error
        def down(request, timeout):
            raise urllib.error.URLError('Connection refused')
        with self.assertRaisesRegex(ValueError, 'Could not reach the model'):
            models.complete({'provider': 'ollama', 'model': 'qwen3'}, 's', {}, 'chat', down)

    def test_connection_test_sends_no_personal_data(self):
        seen = []
        body = {'choices': [{'message': {'content': '{"ok": true}'}}]}
        metrics = models.test({'provider': 'ollama', 'model': 'qwen3', 'allowed_sources': []}, transport_returning(body, seen))
        self.assertEqual(seen[0]['body']['messages'][1]['content'], '{"ping": "pong"}')
        self.assertIn('latency', metrics)
    def test_private_tunnel_requires_consent_and_can_use_prompt_json(self):
        seen=[];config={'provider':'private','model':'qwen','endpoint':'http://127.0.0.1:18766/v1','remote_processing':True,'json_mode':False,'max_tokens':256}
        self.assertFalse(models.is_local(config))
        with self.assertRaises(ValueError):models.complete(config,'s',{},'activity')
        body={'choices':[{'message':{'content':'{"verdict":"work"}'}}]}
        with patch('models.secret',side_effect=ValueError('no key')):
            value,_=models.complete(dict(config,allowed_sources=['activity']),'s',{},'activity',transport_returning(body,seen))
        self.assertEqual(value['verdict'],'work');self.assertNotIn('response_format',seen[0]['body']);self.assertEqual(seen[0]['body']['max_tokens'],256)

    def test_settings_validation(self):
        with patch('keyring.set_password') as store:
            chosen = app.model_settings({'provider': 'bedrock', 'model': 'm', 'region': 'us-east-1', 'key': ' k '}, ['chat'])
        self.assertEqual(chosen, {'provider': 'bedrock', 'model': 'm', 'allowed_sources': ['chat'], 'region': 'us-east-1'})
        store.assert_called_once_with('paco.model', 'bedrock', 'k')
        for bad in ({'provider': 'gemini', 'model': 'x'}, {'provider': 'anthropic', 'model': ''},
                    {'provider': 'private', 'model': 'x', 'endpoint': 'http://remote.example/v1'}, {'provider': 'bedrock', 'model': 'm'}):
            with self.assertRaises(ValueError):
                app.model_settings(bad, [])
        with patch('shutil.which', return_value=None), self.assertRaisesRegex(ValueError, 'not installed'):
            app.model_settings({'provider': 'claude_code'}, [])

    def test_parse_tolerates_prose_and_fences(self):
        self.assertEqual(models.parse('Here you go:\n```json\n{"a": 1}\n```'), {'a': 1})
        self.assertEqual(models.parse('Result: {"a": {"b": 2}} done'), {'a': {'b': 2}})
        with self.assertRaises(ValueError):
            models.parse('no json here')


if __name__ == '__main__':
    unittest.main()
