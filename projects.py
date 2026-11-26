"""Read-only project context and assigned Linear issues."""
from pathlib import Path
import subprocess

LINEAR = """query Assigned($after: String) {
  viewer { id assignedIssues(first: 50, after: $after) {
    nodes { id identifier title url state { type } }
    pageInfo { hasNextPage endCursor }
  } }
}"""


def linear_rows(token, now):
    import requests
    cursor = None
    while True:
        response = requests.post("https://api.linear.app/graphql", timeout=20,
                                 headers={"Authorization":token},
                                 json={"query":LINEAR, "variables":{"after":cursor}})
        response.raise_for_status()
        data = response.json()
        if data.get("errors"):
            raise ValueError("Linear query failed")
        page = data["data"]["viewer"]["assignedIssues"]
        for issue in page["nodes"]:
            if issue["state"]["type"] not in ("completed", "canceled"):
                yield issue["url"], issue["identifier"] + " " + issue["title"], now
        if not page["pageInfo"]["hasNextPage"]:
            return
        cursor = page["pageInfo"]["endCursor"]


def track(db, path):
    path = str(Path(path).expanduser().resolve())
    subprocess.run(["git", "-C", path, "rev-parse", "--show-toplevel"],
                   check=True, stdout=subprocess.DEVNULL, timeout=5)
    with db:
        db.execute("INSERT OR IGNORE INTO repository VALUES(?)", (path,))


def activity(db):
    for (path,) in db.execute("SELECT path FROM repository"):
        try:
            log = subprocess.check_output(["git","-C",path,"log","-1","--format=%h %as %s"],
                                          text=True, timeout=5).strip()
            yield {"source":path, "latest_commit":log}
        except (OSError, subprocess.SubprocessError):
            yield {"source":path, "status":"unavailable"}
    for row in db.execute("SELECT title,url,modified FROM drive_context ORDER BY modified DESC LIMIT 20"):
        yield dict(row)


def drive(session, db):
    response = session.get("https://www.googleapis.com/drive/v3/files", timeout=20,
                           params={"q":"trashed=false", "orderBy":"modifiedTime desc",
                                   "pageSize":20, "fields":"files(id,name,webViewLink,modifiedTime)"})
    response.raise_for_status()
    files = response.json()["files"]
    with db:
        db.execute("DELETE FROM drive_context")
        db.executemany("INSERT INTO drive_context VALUES(?,?,?,?)",
                       [(f["id"], f["name"], f.get("webViewLink"), f["modifiedTime"]) for f in files])
