"""User-level login startup without restarting the companion during setup."""
import os
from pathlib import Path
import plistlib
import subprocess
import sys

LABEL = 'com.paco.reminders'
PLIST = Path.home()/'Library/LaunchAgents'/f'{LABEL}.plist'


def enabled():
    return PLIST.exists()


def configure(enable, database):
    if sys.platform != 'darwin':
        raise ValueError('Login startup requires macOS')
    if not enable:
        PLIST.unlink(missing_ok=True)
        return
    PLIST.parent.mkdir(parents=True,exist_ok=True)
    database=Path(database).resolve()
    config={'Label':LABEL,'ProgramArguments':[sys.executable,str(Path(__file__).with_name('paco.py').resolve()),
                '--db',str(database),'desktop','--login'],
            'RunAtLoad':True,'KeepAlive':{'SuccessfulExit':False},'ThrottleInterval':30,
            'WorkingDirectory':str(Path(__file__).parent.resolve()),
            'EnvironmentVariables':{'PATH':os.environ.get('PATH','/usr/bin:/bin:/usr/sbin:/sbin')},
            'StandardErrorPath':str(database.parent/'service.log')}
    temporary=PLIST.with_suffix('.tmp')
    temporary.write_bytes(plistlib.dumps(config));temporary.chmod(0o600);temporary.replace(PLIST)
    # RunAtLoad takes effect at next login. The current companion is already alive.
    subprocess.run(['launchctl','enable',f'gui/{os.getuid()}/{LABEL}'],capture_output=True,check=True)
