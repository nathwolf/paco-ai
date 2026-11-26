"""Persistent OAuth provider for the official MCP SDK; no password-based OAuth grant."""
import hashlib
import html
import json
import secrets
import time
from urllib.parse import urlsplit,urlencode
from mcp.server.auth.provider import AuthorizationCode,RefreshToken,AccessToken,TokenError,AuthorizeError,RegistrationError,construct_redirect_uri
from mcp.shared.auth import OAuthClientInformationFull,OAuthToken
from starlette.responses import HTMLResponse,RedirectResponse,JSONResponse

SCOPES=['tasks.read','tasks.write','offline_access']
def digest(value):return hashlib.sha256(value.encode()).hexdigest()

class Auth:
    def __init__(self,store,base):self.store=store;self.base=base.rstrip('/');self.resource=self.base+'/mcp'
    async def get_client(self,client_id):
        with self.store.db() as db:r=db.execute('SELECT payload FROM oauth_clients WHERE id=?',(client_id,)).fetchone()
        return OAuthClientInformationFull.model_validate_json(r[0]) if r else None
    async def register_client(self,client_info):
        if not self.store.limit('registration',100,3600):raise RegistrationError('invalid_client_metadata','Registration limit reached')
        for uri in client_info.redirect_uris:
            p=urlsplit(str(uri))
            if p.fragment or p.username or p.password or not p.hostname or (p.scheme!='https' and not(p.scheme=='http' and p.hostname in ('localhost','127.0.0.1','::1'))):
                raise RegistrationError('invalid_redirect_uri','Use HTTPS or localhost callbacks')
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT count(*) FROM oauth_clients').fetchone()[0]>=500:raise RegistrationError('invalid_client_metadata','Client limit reached; contact the administrator')
            db.execute('INSERT INTO oauth_clients VALUES(?,?,?)',(client_info.client_id,client_info.model_dump_json(),time.time()))
    async def authorize(self,client,params):
        if not self.store.limit('authorization',300,3600):raise AuthorizeError('temporarily_unavailable','Authorization limit reached; try again later')
        if params.resource not in (None,self.resource):raise AuthorizeError('invalid_request','Incorrect resource')
        if not params.code_challenge:raise AuthorizeError('invalid_request','PKCE is required')
        txn=secrets.token_urlsafe(32)
        value={'client_id':client.client_id,'client_name':client.client_name or 'MCP client','params':params.model_dump(mode='json')}
        with self.store.db() as db:db.execute('INSERT INTO oauth_pending VALUES(?,?,?)',(txn,json.dumps(value),time.time()+600))
        return self.base+'/login?'+urlencode({'transaction':txn})
    async def load_authorization_code(self,client,authorization_code):
        with self.store.db() as db:r=db.execute('SELECT payload FROM oauth_codes WHERE hash=? AND expires>?',(digest(authorization_code),time.time())).fetchone()
        if not r:return None
        value=json.loads(r[0]);value['code']=authorization_code
        return AuthorizationCode(**value) if value['client_id']==client.client_id else None
    def issue(self,db,owner,client,scopes,resource=None,family=None,device=False):
        family=family or secrets.token_urlsafe(24);now=int(time.time());ttl=30*86400 if device else 3600
        access=secrets.token_urlsafe(40);refresh=secrets.token_urlsafe(40)
        common=dict(client_id=client,scopes=scopes,resource=resource or self.resource,subject=owner)
        a=dict(common,expires_at=now+ttl);r=dict(common,expires_at=now+30*86400)
        db.execute('INSERT INTO tokens VALUES(?,?,?,?,?)',(digest(access),'access',json.dumps(a),family,a['expires_at']))
        if not device:db.execute('INSERT INTO tokens VALUES(?,?,?,?,?)',(digest(refresh),'refresh',json.dumps(r),family,r['expires_at']))
        return OAuthToken(access_token=access,token_type='Bearer',expires_in=ttl,scope=' '.join(scopes),refresh_token=None if device else refresh)
    async def exchange_authorization_code(self,client,authorization_code):
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('DELETE FROM oauth_codes WHERE hash=? AND expires>?',(digest(authorization_code.code),time.time())).rowcount!=1:raise TokenError('invalid_grant','Code already used or expired')
            if not self.store.active(authorization_code.subject):raise TokenError('invalid_grant','Account unavailable')
            return self.issue(db,authorization_code.subject,client.client_id,authorization_code.scopes,authorization_code.resource)
    async def load_refresh_token(self,client,refresh_token):
        value=self.load(refresh_token,'refresh')
        return RefreshToken(token=refresh_token,**value) if value and value['client_id']==client.client_id else None
    async def exchange_refresh_token(self,client,refresh_token,scopes):
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute("SELECT family FROM tokens WHERE hash=? AND kind='refresh' AND expires>?",(digest(refresh_token.token),time.time())).fetchone()
            if not row or not set(scopes)<=set(refresh_token.scopes):raise TokenError('invalid_grant','Refresh expired or already used')
            if not self.store.active(refresh_token.subject):raise TokenError('invalid_grant','Account unavailable')
            db.execute('DELETE FROM tokens WHERE family=?',(row['family'],))
            return self.issue(db,refresh_token.subject,client.client_id,scopes,refresh_token.resource,row['family'])
    def load(self,token,kind):
        with self.store.db() as db:r=db.execute('SELECT payload FROM tokens WHERE hash=? AND kind=? AND expires>?',(digest(token),kind,time.time())).fetchone()
        value=json.loads(r[0]) if r else None
        return value if value and self.store.active(value['subject']) else None
    async def load_access_token(self,token):
        value=self.load(token,'access')
        return AccessToken(token=token,**value) if value else None
    async def revoke_token(self,token):
        with self.store.db() as db:
            row=db.execute('SELECT family FROM tokens WHERE hash=?',(digest(token.token),)).fetchone()
            if row:db.execute('DELETE FROM tokens WHERE family=?',(row['family'],))
    async def login(self,request):
        txn=request.query_params.get('transaction','')
        with self.store.db() as db:row=db.execute('SELECT payload FROM oauth_pending WHERE id=? AND expires>?',(txn,time.time())).fetchone()
        if not row:return HTMLResponse('This sign-in request expired. Reconnect Paco from ChatGPT.',status_code=400)
        value=json.loads(row[0])
        if request.method=='POST':
            form=await request.form();csrf=str(form.get('csrf',''))
            if request.headers.get('origin')!=self.base or not csrf or not secrets.compare_digest(request.cookies.get('paco_csrf',''),csrf) or digest(csrf)!=value.get('csrf'):
                return HTMLResponse('Invalid sign-in session. Reopen the connection.',status_code=403)
            if not self.store.limit('login:'+str(form.get('username','')).casefold(),10) or not self.store.limit('login-global',100):return HTMLResponse('Too many attempts. Try again in 15 minutes.',status_code=429)
            user=self.store.authenticate(str(form.get('username',''))[:80],str(form.get('password',''))[:512])
            if not user:return HTMLResponse('Sign-in failed. Go back and try again.',status_code=401)
            params=value['params'];code=secrets.token_urlsafe(40)
            record=dict(client_id=value['client_id'],scopes=params.get('scopes') or SCOPES,expires_at=time.time()+120,
                        code_challenge=params['code_challenge'],redirect_uri=params['redirect_uri'],
                        redirect_uri_provided_explicitly=params['redirect_uri_provided_explicitly'],resource=self.resource,subject=user['id'])
            with self.store.db() as db:
                if db.execute('DELETE FROM oauth_pending WHERE id=? AND expires>?',(txn,time.time())).rowcount!=1:return HTMLResponse('Sign-in already completed.',status_code=400)
                db.execute('INSERT INTO oauth_codes VALUES(?,?,?)',(digest(code),json.dumps(record),record['expires_at']))
            response=RedirectResponse(construct_redirect_uri(params['redirect_uri'],code=code,state=params.get('state')),status_code=303)
            response.delete_cookie('paco_csrf');return response
        csrf=secrets.token_urlsafe(32);value['csrf']=digest(csrf)
        with self.store.db() as db:db.execute('UPDATE oauth_pending SET payload=? WHERE id=?',(json.dumps(value),txn))
        client=html.escape(value['client_name']);scopes=html.escape(', '.join(value['params'].get('scopes') or SCOPES))
        response=HTMLResponse(f'''<!doctype html><html><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Connect Paco</title>
        <style>:root{{color-scheme:light dark}}body{{font:16px system-ui;max-width:420px;margin:12vh auto;padding:24px}}input,button{{box-sizing:border-box;width:100%;padding:12px;margin:8px 0}}button{{background:#376b55;color:white;border:0;border-radius:8px}}</style>
        <h1>Connect Paco</h1><p>Company accounts only. No public registration.</p><p>Allow <strong>{client}</strong> to access your task account: {scopes}.</p><p>Meeting transcripts and activity history are not available through this connection.</p>
        <form method="post"><input type="hidden" name="csrf" value="{csrf}"><label>Username<input name="username" autocomplete="username" required maxlength="80"></label><label>Password<input name="password" type="password" autocomplete="current-password" required maxlength="512"></label><button>Sign in and connect</button></form></html>''')
        response.set_cookie('paco_csrf',csrf,secure=True,httponly=True,samesite='lax',max_age=600)
        return response
