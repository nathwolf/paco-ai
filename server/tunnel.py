"""Supervise a provisional Cloudflare URL and keep OAuth discovery on that origin."""
import argparse
import os
from pathlib import Path
import re
import signal
import subprocess
import sys


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--binary',required=True);parser.add_argument('--address-file',required=True);args=parser.parse_args()
    os.umask(0o077)
    child=subprocess.Popen([args.binary,'tunnel','--no-autoupdate','--url','http://127.0.0.1:8765'],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
    def stop(*_):
        child.terminate()
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    address=None
    try:
        for line in child.stdout:
            match=re.search(r'https://[a-z0-9-]+\.trycloudflare\.com\b',line)
            if match and match[0]!=address:
                address=match[0];path=Path(args.address_file);tmp=path.with_suffix('.new')
                tmp.write_text(address+'\n');tmp.chmod(0o600);tmp.replace(path)
                subprocess.run(['systemctl','--user','restart','paco-company.service'],check=True)
                print('Paco temporary HTTPS address: '+address,flush=True)
            elif ' ERR ' in line:print(line.strip(),flush=True)
        return child.wait() or 1
    finally:
        if child.poll() is None:child.terminate();child.wait(timeout=15)


if __name__=='__main__':sys.exit(main())
