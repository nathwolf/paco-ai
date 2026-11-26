"""Small, independent read-only adapters with account identity and source links.
Each returns a fully materialized snapshot before reconciliation may change tasks.
"""
import json
import urllib.parse
import urllib.request


class Client:
    def __init__(self, base, token, headers=None):
        self.base = base.rstrip('/')
        self.headers = {'Authorization':'Bearer '+token, **(headers or {})}

    def get(self, path, **params):
        url = self.base+path+('?' + urllib.parse.urlencode(params) if params else '')
        request = urllib.request.Request(url,headers=self.headers)
        with urllib.request.urlopen(request,timeout=20) as response:
            return json.load(response)

    def post(self, path, data):
        request = urllib.request.Request(self.base+path,data=json.dumps(data).encode(),headers={**self.headers,'Content-Type':'application/json'})
        with urllib.request.urlopen(request,timeout=20) as response:
            return json.load(response)


GRAPH = 'https://graph.microsoft.com/v1.0'
BASES = {'todoist':'https://api.todoist.com/api/v1','asana':'https://app.asana.com/api/1.0',
         'outlook':GRAPH,'outlook_calendar':GRAPH,'microsoft_todo':GRAPH,'slack':'https://slack.com/api',
         'gitlab':'https://gitlab.com/api/v4','linear':'https://api.linear.app'}


def client_for(provider, base, token):
    # Linear personal API keys are sent as-is; every other service takes a bearer token.
    return Client(base, token, {'Authorization': token} if provider == 'linear' else None)


def graph_pages(client, path, params):
    """Microsoft Graph paging, refusing next links that point anywhere but Graph."""
    while True:
        data = client.get(path, **params)
        yield from data.get('value', [])
        link = data.get('@odata.nextLink')
        if not link:
            return
        parsed = urllib.parse.urlsplit(link)
        if parsed.netloc != 'graph.microsoft.com' or not parsed.path.startswith('/v1.0/'):
            raise ValueError('Unexpected pagination origin')
        path, params = parsed.path[len('/v1.0'):], dict(urllib.parse.parse_qsl(parsed.query))


def identity(provider, client):
    if provider=='todoist':
        return str(client.get('/user')['id'])
    if provider=='asana':
        return str(client.get('/users/me')['data']['gid'])
    if provider in ('outlook','outlook_calendar','microsoft_todo'):
        return client.get('/me')['id']
    if provider=='gitlab':
        return str(client.get('/user')['id'])
    if provider=='linear':
        data=client.post('/graphql',{'query':'{ viewer { id } }'})
        if data.get('errors') or not data.get('data'):
            raise ValueError('Linear authentication failed')
        return data['data']['viewer']['id']
    if provider=='jira':
        return client.get('/myself')['accountId']
    if provider=='slack':
        data=client.post('/auth.test',{})
        if not data.get('ok'):
            raise ValueError('Slack authentication failed')
        return data['team_id']+'/'+data['user_id']
    raise ValueError('Unknown connector')


def configure(provider, token, base=None):
    import keyring
    if provider=='jira':
        parsed=urllib.parse.urlsplit(base or '')
        if parsed.scheme!='https' or not (parsed.hostname or '').endswith('.atlassian.net') or parsed.username:
            raise ValueError('Use your https://workspace.atlassian.net Jira site')
        base=parsed.scheme+'://'+parsed.netloc+'/rest/api/3'
    elif provider=='gitlab' and base:
        parsed=urllib.parse.urlsplit(base)
        if parsed.scheme!='https' or not parsed.hostname or parsed.username:
            raise ValueError('Use your https:// GitLab address, or leave it empty for gitlab.com')
        base=parsed.scheme+'://'+parsed.netloc+'/api/v4'
    else:
        base=BASES[provider]
    client=client_for(provider,base,token)
    account=identity(provider,client)
    keyring.set_password('paco.connector',provider+'/'+account,token)
    return {'account':account,'base':base}


def configured_client(provider, config):
    import keyring
    token=keyring.get_password('paco.connector',provider+'/'+config['account'])
    if not token:
        raise ValueError('Reconnect '+provider)
    return client_for(provider,config['base'],token)


def slack_messages(client, account, now):
    from datetime import datetime,timezone
    if identity('slack',client)!=account:
        raise ValueError('Slack account changed; reconnect')
    user=account.split('/')[1]
    since=datetime.fromtimestamp(now-14*86400,timezone.utc).date().isoformat()
    found={}
    for query in ('to:'+user+' after:'+since,'<@'+user+'> after:'+since):
        page=1
        while True:
            data=client.get('/search.messages',query=query,count=100,page=page,sort='timestamp',sort_dir='asc')
            if not data.get('ok'):
                raise ValueError('Slack search permission missing or rate limited')
            messages=data['messages']
            for message in messages.get('matches',[]):
                if message.get('user')!=user:
                    found[message['permalink']]={'url':message['permalink'],'text':message['text'],
                        'person':message.get('user',''),'at':float(message['ts'])}
            if page>=messages.get('paging',{}).get('pages',1):
                break
            page+=1
    return list(found.values())


def snapshot(provider, client, account, now):
    rows = []
    if provider == 'todoist':
        who = client.get('/user')
        if str(who['id']) != account:
            raise ValueError('Account changed; reconnect Todoist')
        cursor = None
        while True:
            data = client.get('/tasks',**({'cursor':cursor} if cursor else {}))
            rows.extend((t.get('url','https://app.todoist.com/app/task/'+str(t['id'])),t['content'],now) for t in data['results'])
            cursor = data.get('next_cursor')
            if not cursor:
                break
    elif provider == 'asana':
        who = client.get('/users/me',opt_fields='gid,workspaces.gid')['data']
        if str(who['gid']) != account:
            raise ValueError('Account changed; reconnect Asana')
        for workspace in who.get('workspaces',[]):
            offset = None
            while True:
                params = {'assignee':account,'workspace':workspace['gid'],'completed_since':'now','opt_fields':'name,permalink_url,completed','limit':100}
                if offset:
                    params['offset'] = offset
                data = client.get('/tasks',**params)
                rows.extend((t['permalink_url'],t['name'],now) for t in data['data'] if not t.get('completed'))
                offset = (data.get('next_page') or {}).get('offset')
                if not offset:
                    break
    elif provider == 'outlook':
        who = client.get('/me')
        if who['id'] != account:
            raise ValueError('Account changed; reconnect Outlook')
        # Explicitly flagged messages only; a message alone is not an obligation.
        path = '/me/messages'
        params = {'$filter':"flag/flagStatus eq 'flagged'",'$select':'id,subject,webLink','$top':100}
        while True:
            data = client.get(path,**params)
            rows.extend((m['webLink'],m['subject'],now) for m in data['value'])
            link = data.get('@odata.nextLink')
            if not link:
                break
            parsed = urllib.parse.urlsplit(link)
            if parsed.netloc != 'graph.microsoft.com' or not parsed.path.startswith('/v1.0/'):
                raise ValueError('Unexpected pagination origin')
            path,params = parsed.path[len('/v1.0'):],dict(urllib.parse.parse_qsl(parsed.query))
    elif provider=='jira':
        if identity('jira',client)!=account:
            raise ValueError('Jira account changed; reconnect')
        cursor=None
        while True:
            params={'jql':'assignee = currentUser() AND statusCategory != Done','fields':'summary','maxResults':100}
            if cursor:
                params['nextPageToken']=cursor
            data=client.get('/search/jql',**params)
            site=client.base.split('/rest/')[0]
            rows.extend((site+'/browse/'+i['key'],i['key']+' '+i['fields']['summary'],now) for i in data['issues'])
            cursor=data.get('nextPageToken')
            if not cursor:
                break
    elif provider=='gitlab':
        if identity('gitlab',client)!=account:
            raise ValueError('GitLab account changed; reconnect')
        for path,params,prefix in (('/issues',{'scope':'assigned_to_me','state':'opened'},''),
                                   ('/merge_requests',{'reviewer_id':account,'state':'opened','scope':'all'},'Review: ')):
            page=1
            while True:
                items=client.get(path,per_page=100,page=page,**params)
                rows.extend((i['web_url'],prefix+i['title'],now) for i in items)
                if len(items)<100:
                    break
                page+=1
    elif provider=='linear':
        import projects
        if identity('linear',client)!=account:
            raise ValueError('Linear account changed; reconnect')
        cursor=None
        while True:
            data=client.post('/graphql',{'query':projects.LINEAR,'variables':{'after':cursor}})
            if data.get('errors'):
                raise ValueError('Linear query failed')
            page=data['data']['viewer']['assignedIssues']
            rows.extend((i['url'],i['identifier']+' '+i['title'],now) for i in page['nodes'] if i['state']['type'] not in ('completed','canceled'))
            if not page['pageInfo']['hasNextPage']:
                break
            cursor=page['pageInfo']['endCursor']
    elif provider=='microsoft_todo':
        if client.get('/me')['id']!=account:
            raise ValueError('Account changed; reconnect Microsoft To Do')
        for group in graph_pages(client,'/me/todo/lists',{'$select':'id,displayName'}):
            for task in graph_pages(client,'/me/todo/lists/'+urllib.parse.quote(group['id'],safe='')+'/tasks',{'$filter':"status ne 'completed'",'$select':'id,title'}):
                rows.append(('https://to-do.office.com/tasks/id/'+urllib.parse.quote(task['id'],safe='')+'/details',task['title'],now))
    else:
        raise ValueError('Unsupported read-only adapter')
    return rows


def outlook_events(client, account, now):
    """Outlook Calendar for the next seven days: meeting protection, join links and preparation reminders."""
    from datetime import datetime, timezone
    if client.get('/me')['id']!=account:
        raise ValueError('Account changed; reconnect Outlook Calendar')
    stamp=lambda t: datetime.fromtimestamp(t,timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    def parse(value):
        text=value['dateTime'].split('.')[0]
        return datetime.fromisoformat(text).replace(tzinfo=timezone.utc).timestamp()
    params={'startDateTime':stamp(now),'endDateTime':stamp(now+7*86400),'$top':100,
            '$select':'id,subject,start,end,showAs,isCancelled,isAllDay,onlineMeeting,webLink,attendees,responseStatus'}
    original=client.headers
    client.headers={**original,'Prefer':'outlook.timezone="UTC"'}
    try:
        events=[]
        for e in graph_pages(client,'/me/calendarView',params):
            if e.get('isCancelled') or e.get('isAllDay') or (e.get('responseStatus') or {}).get('response')=='declined':
                continue
            events.append({'id':e['id'],'title':e.get('subject') or 'Meeting','start':parse(e['start']),'end':parse(e['end']),
                           'url':(e.get('onlineMeeting') or {}).get('joinUrl') or e.get('webLink',''),
                           'busy':e.get('showAs') not in ('free','workingElsewhere'),
                           'attendees':[(a.get('emailAddress') or {}).get('address','') for a in e.get('attendees',[])]})
        return events
    finally:
        client.headers=original
