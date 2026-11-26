"""Local administrator CLI. No public account creation or password reset endpoint."""
import argparse
import getpass
import os
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from server.store import Store,PASSWORDS


def main():
    os.umask(0o077)
    parser=argparse.ArgumentParser()
    parser.add_argument('--db',required=True)
    parser.add_argument('command',choices=['create-user','reset-password','disable-user','revoke-sessions','list-users','maintenance'])
    parser.add_argument('username',nargs='?')
    parser.add_argument('--password-stdin',action='store_true')
    parser.add_argument('--backups')
    args=parser.parse_args();store=Store(args.db)
    if args.command=='maintenance':
        store.prune();print('Backup:',store.backup(args.backups or str(Path(args.db).parent/'backups')));return
    if args.command=='list-users':
        with store.db() as db:
            for row in db.execute('SELECT username,active FROM users ORDER BY username'):print(row['username'],'active' if row['active'] else 'disabled')
        return
    if not args.username:parser.error('username is required')
    if args.command in ('create-user','reset-password'):
        password=sys.stdin.readline().rstrip('\r\n') if args.password_stdin else getpass.getpass('Password: ')
        if len(password)<8:parser.error('Use at least eight characters')
        if args.command=='create-user':store.create_user(args.username,password);print('User created');return
    with store.db() as db:
        user=db.execute('SELECT id FROM users WHERE username=?',(args.username,)).fetchone()
        if not user:parser.error('User not found')
        if args.command=='reset-password':db.execute('UPDATE users SET password_hash=? WHERE id=?',(PASSWORDS.hash(password),user['id']))
        if args.command=='disable-user':db.execute('UPDATE users SET active=0 WHERE id=?',(user['id'],))
        # Sessions carry the subject inside their private JSON payload.
        db.execute("DELETE FROM tokens WHERE json_extract(payload,'$.subject')=?",(user['id'],))
        db.execute("DELETE FROM oauth_codes WHERE json_extract(payload,'$.subject')=?",(user['id'],))
    print('Account updated; existing sessions revoked')


if __name__=='__main__':main()
