"""Stdio bridge to the company MCP using this Mac's existing Keychain sign-in.

Supports MCP hosts such as Codex and Claude Desktop without storing a bearer
token in their configuration. Only the remote task tools are exposed.
"""
import json
from pathlib import Path
import sqlite3
import sys
import urllib.error
import urllib.request
import company_sync


def credentials():
    import keyring
    path=Path.home()/'Library/Application Support/Paco/tasks.sqlite3'
    with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True) as db:
        account=company_sync.setting(db,'account')
    if not account:raise ValueError('Connect your company account in Paco Settings first')
    token=keyring.get_password('paco.company',account['url']+'|'+account['user'])
    if not token:raise ValueError('Reconnect your company account in Paco Settings')
    return account['url'],token


def forward(message,connection=credentials):
    from urllib.parse import urlsplit
    base,token=connection();u=urlsplit(base)
    if u.scheme!='https' or not u.hostname or u.username or u.password or u.query or u.fragment:raise ValueError('Invalid company HTTPS address')
    req=urllib.request.Request(base.rstrip('/')+'/mcp',json.dumps(message).encode(),headers={
        'Authorization':'Bearer '+token,'Content-Type':'application/json','Accept':'application/json, text/event-stream',
        'MCP-Protocol-Version':'2025-11-25'})
    try:
        with urllib.request.build_opener(company_sync.NoRedirect).open(req,timeout=60) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code==401:raise ValueError('Company sign-in expired; reconnect in Paco Settings') from None
        raise ValueError('Company MCP returned HTTP '+str(exc.code)) from None
    except (OSError,ValueError):raise ValueError('Company MCP unavailable; check Paco Settings and the server address') from None


def serve(stdin=None,stdout=None,dispatch=forward):
    stdin,stdout=stdin or sys.stdin,stdout or sys.stdout
    for line in stdin:
        message=None
        try:
            if len(line)>256*1024:raise ValueError('Request too large')
            message=json.loads(line)
            if not isinstance(message,dict) or message.get('jsonrpc')!='2.0':raise ValueError('Invalid MCP request')
            if 'id' not in message:continue  # Stateless service: client notifications need no forwarding.
            reply=dispatch(message)
        except Exception as exc:
            reply={'jsonrpc':'2.0','id':message.get('id') if isinstance(message,dict) else None,
                   'error':{'code':-32603,'message':str(exc) if isinstance(exc,ValueError) else 'Paco connection failed'}}
        stdout.write(json.dumps(reply)+'\n');stdout.flush()


if __name__=='__main__':serve()
