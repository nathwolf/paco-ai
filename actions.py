"""Publish an explicitly reviewed comment to a discovered GitHub issue."""
import json
import re
import subprocess
import uuid


def draft(db, task, body):
    if not body.strip():
        raise ValueError("empty comment")
    row = db.execute("SELECT key FROM discovered WHERE source='github' AND task_id=?", (task,)).fetchone()
    if not row:
        raise ValueError("choose a discovered GitHub task")
    match = re.fullmatch(r"https://github\.com/([\w.-]+)/([\w.-]+)/(?:issues|pull)/(\d+)", row[0])
    if not match:
        raise ValueError("unsupported issue URL")
    target = "repos/{}/{}/issues/{}/comments".format(*match.groups())
    key = uuid.uuid4().hex
    with db:
        db.execute("INSERT INTO outgoing VALUES(?,?,?,'draft',NULL)", (key,target,body))
    return key


def publish(db, key, gh, login, ask=input):
    row = db.execute("SELECT target,body,status,receipt FROM outgoing WHERE id=?", (key,)).fetchone()
    if not row:
        raise ValueError("unknown draft")
    target, body, status, receipt = row
    if status == "sent":
        return receipt
    who = subprocess.check_output([gh,"api","user","--jq",".login"], text=True, timeout=20).strip()
    if who != login:
        raise ValueError("GitHub account changed")
    marker = "<!-- paco:" + key + " -->"
    if status == "pending":
        results = subprocess.check_output([gh,"api","--paginate",target,"--jq",
                                          ".[] | [.body,.html_url,.user.login] | @json"],
                                         text=True, timeout=60)
        for line in results.splitlines():
            text, url, author = json.loads(line)
            if marker in text and author == login:
                with db:
                    db.execute("UPDATE outgoing SET status='sent',receipt=? WHERE id=?", (url,key))
                return url
        raise ValueError("delivery unconfirmed; inspect the issue before creating another draft")
    if ask(f"Post as {login} to {target}?\n{body}\nType POST to confirm: ") != "POST":
        return "Draft retained"
    with db:
        if db.execute("UPDATE outgoing SET status='pending' WHERE id=? AND status='draft'", (key,)).rowcount != 1:
            raise ValueError("another publish is in progress")
    payload = json.dumps({"body":body + "\n\n" + marker})
    reply = subprocess.check_output([gh,"api","--method","POST",target,"--input","-"],
                                    input=payload, text=True, timeout=30)
    url = json.loads(reply)["html_url"]
    with db:
        db.execute("UPDATE outgoing SET status='sent',receipt=? WHERE id=?", (url,key))
    return url
