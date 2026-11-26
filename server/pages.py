"""Small, script-free account pages sharing Paco's light/dark visual language."""
import html
from pathlib import Path

STYLE = (Path(__file__).parent/'static/sign-in.css').read_text()


def page(title, body):
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark">
<title>{html.escape(title)} · Paco</title><style>{STYLE}</style></head>
<body><main class="card" aria-labelledby="page-title">
<header class="brand"><img src="/assets/paco.webp" width="56" height="56" alt="">
<span>Paco</span></header>{body}</main></body></html>'''


def sign_in(client, scopes, csrf):
    permissions=[]
    if 'tasks.read' in scopes:permissions.append('View your tasks and projects')
    if 'tasks.write' in scopes:permissions.append('Create and update your tasks')
    if 'offline_access' in scopes:permissions.append('Stay connected between visits')
    access=''.join('<li><span aria-hidden="true">✓</span>'+text+'</li>' for text in permissions)
    return page('Connect',f'''
<h1 id="page-title">Connect with Paco</h1>
<p class="intro">Sign in to connect your Paco tasks with <strong>{html.escape(client)}</strong>.</p>
<div class="access"><p class="eyebrow">This connection can</p><ul>{access}</ul></div>
<form method="post">
<input type="hidden" name="csrf" value="{html.escape(csrf,quote=True)}">
<label for="username">Username</label>
<input id="username" name="username" autocomplete="username" autocapitalize="none" spellcheck="false" required maxlength="80" placeholder="Your Paco username">
<label for="password">Password</label>
<input id="password" name="password" type="password" autocomplete="current-password" required maxlength="512" placeholder="Your password">
<button type="submit">Sign in and connect <span aria-hidden="true">↗</span></button>
</form>
<p class="privacy">Meeting transcripts and activity history stay off this connection.</p>
<p class="account-help">Need an account? Ask your team’s Paco administrator.</p>''')


def message(title, detail, retry=None):
    action=(f'<a class="button" href="{html.escape(retry,quote=True)}">Try signing in again <span aria-hidden="true">↗</span></a>' if retry else '')
    return page(title,f'<h1 id="page-title">{html.escape(title)}</h1><p class="intro">{html.escape(detail)}</p>{action}')
