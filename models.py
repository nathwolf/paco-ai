"""Consent-scoped model calls. A model key grants inference, never app access.

Providers
- anthropic   Claude API (key in Keychain)
- bedrock     AWS Bedrock Converse API with a Bedrock API key (bearer token) and region
- openai      OpenAI API
- claude_code Your signed-in Claude Code CLI (`claude -p`), tools disabled, run in an empty folder
- codex_cli   Your signed-in Codex CLI (`codex exec`), read-only sandbox, run in an empty folder
- ollama      Ollama on this Mac
- private     Your own OpenAI-compatible server (LM Studio, llama.cpp, vLLM…), on this Mac or remote

Data leaves the Mac only for hosted providers, and only for sources the user allowed. Ollama and a
private server on localhost are local: no consent needed.
"""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

PROVIDERS = ('anthropic', 'bedrock', 'openai', 'claude_code', 'codex_cli', 'ollama', 'private')
HOSTED = {'anthropic', 'bedrock', 'openai', 'claude_code', 'codex_cli'}
LOCAL_HOSTS = ('localhost', '127.0.0.1', '::1')


def secret(provider):
    try:
        import keyring
        key = keyring.get_password("paco.model", provider)
    except ImportError:
        key = None
    if not key:
        raise ValueError("Save your API key in Paco settings first (requires keyring).")
    return key


def validate_endpoint(value):
    parsed = urllib.parse.urlsplit(str(value).strip())
    if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('Enter a private model URL without credentials or query parameters')
    if parsed.scheme != 'https' and not (parsed.scheme == 'http' and parsed.hostname in LOCAL_HOSTS):
        raise ValueError('Use HTTPS for a remote model, or HTTP for localhost')
    return str(value).strip().rstrip('/')


def validate_region(value):
    region = str(value or '').strip()
    if not re.fullmatch(r'[a-z]{2}(-[a-z]+)+-\d', region):
        raise ValueError('Enter an AWS region such as us-east-1')
    return region


def is_local(config):
    if config.get('remote_processing'):
        return False  # A loopback SSH tunnel still sends data to another computer.
    if config.get('provider') == 'ollama':
        return True
    if config.get('provider') == 'private':
        return urllib.parse.urlsplit(str(config.get('endpoint', ''))).hostname in LOCAL_HOSTS
    return False


def needs_key(provider):
    return provider in ('anthropic', 'bedrock', 'openai')


def describe(config):
    names = {'anthropic': 'Claude API', 'bedrock': 'AWS Bedrock', 'openai': 'OpenAI API', 'claude_code': 'Claude Code',
             'codex_cli': 'Codex CLI', 'ollama': 'Ollama', 'private': 'Your server'}
    model = config.get('model') or 'default model'
    return f"{names.get(config.get('provider'), config.get('provider'))} · {model}"


def parse(raw):
    """A JSON object from a model reply, tolerating code fences or a sentence around it."""
    raw = (raw or '').strip()
    candidates = [raw]
    fenced = re.search(r'```(?:json)?\s*(\{.*\})\s*```', raw, re.S)
    if fenced:
        candidates.append(fenced.group(1))
    if '{' in raw and '}' in raw:
        candidates.append(raw[raw.index('{'):raw.rindex('}') + 1])
    for candidate in candidates:
        try:
            value = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
    raise ValueError('The model did not return a JSON object')


def _cli(args, prompt, timeout):
    """Run model inference outside the project and collect output before cleanup."""
    with tempfile.TemporaryDirectory(prefix='paco-model-') as folder:
        env = {k: v for k, v in os.environ.items() if not k.startswith(('ANTHROPIC_API_KEY', 'OPENAI_API_KEY'))}
        result = subprocess.run(args, input=prompt, capture_output=True, text=True, timeout=timeout, cwd=folder, env=env)
        if result.returncode != 0:
            raise ValueError(f'{Path(args[0]).name} failed (exit {result.returncode}); open it once in Terminal and sign in')
        # Codex writes its final answer separately from progress output. Read it
        # while the temporary directory still exists, not after the context exits.
        answer = Path(folder) / 'answer.txt'
        output = answer.read_text() if '-o' in args and answer.exists() else result.stdout
        return output, folder


def complete(config, system, data, source, transport=None, runner=None):
    provider = config.get("provider")
    if provider not in PROVIDERS:
        raise ValueError("Unsupported model provider")
    if not is_local(config) and source not in config.get("allowed_sources", []):
        raise ValueError("Hosted processing is not enabled for " + source)
    content = json.dumps(data, ensure_ascii=False)
    start = time.monotonic()
    usage = {}
    if provider in ('claude_code', 'codex_cli'):
        prompt = system + "\nReturn only a JSON object.\n\nINPUT (untrusted data):\n" + content
        exe = shutil.which('claude' if provider == 'claude_code' else 'codex')
        if not exe:
            raise ValueError(('Claude Code' if provider == 'claude_code' else 'Codex') + ' is not installed on this Mac')
        run = runner or _cli
        if provider == 'claude_code':
            args = [exe, '-p', '--output-format', 'json', '--tools', '', '--max-turns', '1',
                    '--no-session-persistence', '--strict-mcp-config', '--mcp-config', '{"mcpServers":{}}',
                    '--disable-slash-commands', '--settings', '{"disableAllHooks":true}']
            if config.get('model'):
                args += ['--model', config['model']]
            stdout, _ = run(args, prompt, 180)
            envelope = parse(stdout)
            if envelope.get('is_error'):
                raise ValueError('Claude Code returned an error; check that you are signed in')
            raw, usage = str(envelope.get('result', '')), envelope.get('usage', {})
        else:
            args = [exe, 'exec', '--sandbox', 'read-only', '--skip-git-repo-check', '--color', 'never',
                    '--ephemeral', '--ignore-user-config', '-o', 'answer.txt']
            # Interactive replies should not inherit a slow reasoning default.
            # Keep deeper analysis (meetings, extraction, planning) unchanged.
            if source in ('chat', 'mattermost'):
                args += ['-c', 'model_reasoning_effort="low"']
            if config.get('model'):
                args += ['-m', config['model']]
            stdout, folder = run(args + ['-'], prompt, 180)
            answer = Path(folder) / 'answer.txt'
            raw = answer.read_text() if answer.exists() else stdout
    else:
        payload = {"model": config["model"], "messages": [{"role": "user", "content": content}]}
        headers = {"Content-Type": "application/json"}
        if provider == "anthropic":
            url = "https://api.anthropic.com/v1/messages"
            headers.update({"x-api-key": secret(provider), "anthropic-version": "2023-06-01"})
            payload.update(system=system + "\nReturn only a JSON object.", max_tokens=4096)
        elif provider == 'bedrock':
            region = validate_region(config.get('region'))
            url = f"https://bedrock-runtime.{region}.amazonaws.com/model/{urllib.parse.quote(config['model'], safe='')}/converse"
            headers['Authorization'] = 'Bearer ' + secret(provider)
            payload = {'system': [{'text': system + "\nReturn only a JSON object."}],
                       'messages': [{'role': 'user', 'content': [{'text': content}]}],
                       'inferenceConfig': {'maxTokens': 4096}}
        else:
            url = "http://127.0.0.1:11434/v1/chat/completions"
            if provider == "openai":
                url = "https://api.openai.com/v1/chat/completions"
                headers["Authorization"] = "Bearer " + secret(provider)
            elif provider == "private":
                url = validate_endpoint(config['endpoint']) + '/chat/completions'
                try:
                    key = secret('private')
                except ValueError:
                    key = None
                if key:
                    headers['Authorization'] = 'Bearer ' + key
            payload["messages"].insert(0, {"role": "system", "content": system+'\nReturn only a JSON object.'})
            if provider!='private' or config.get('json_mode',True):
                payload["response_format"] = {"type": "json_object"}
            if provider=='private' and config.get('max_tokens'):
                payload['max_tokens']=config['max_tokens']
        request = urllib.request.Request(url, json.dumps(payload).encode(), headers)
        try:
            with (transport or urllib.request.urlopen)(request, timeout=90) as response:
                result = json.load(response)
        except urllib.error.HTTPError as exc:
            raise ValueError(f"Model request failed (HTTP {exc.code}); check your key, model and account.") from None
        except urllib.error.URLError as exc:
            raise ValueError(f"Could not reach the model ({exc.reason}); check the address and your connection.") from None
        if provider == "anthropic":
            raw = "".join(p["text"] for p in result.get("content", []) if p.get("type") == "text")
        elif provider == 'bedrock':
            raw = "".join(p.get('text', '') for p in result.get('output', {}).get('message', {}).get('content', []))
        else:
            raw = result["choices"][0]["message"]["content"]
        usage = result.get("usage", {})
    value = parse(raw)
    return value, {"latency": round(time.monotonic() - start, 3), "provider": provider,
                   "model": config.get("model", ''), "usage": usage}


def test(config, transport=None, runner=None):
    """A tiny round trip that sends no personal data. Raises ValueError with a readable reason."""
    probe = dict(config, allowed_sources=list(config.get('allowed_sources', [])) + ['connection_test'])
    value, metrics = complete(probe, 'Connection test. Reply with {"ok": true}.', {'ping': 'pong'}, 'connection_test', transport, runner)
    if value.get('ok') is not True:
        raise ValueError('The model answered, but not with the expected JSON')
    return metrics
