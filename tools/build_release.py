"""Build a clean universal Mac pilot installer, never including personal state."""
from pathlib import Path
import hashlib
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from build_app import build, VERSION


def main():
    output = ROOT/'dist'
    staging = ROOT/'build/release'/f'Paco-{VERSION}'
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    for path in ROOT.glob('*.py'):
        if not path.name.startswith(('test_', 'eval_')):
            shutil.copy2(path, staging/path.name)
    for name in ('web', 'native', 'assets', 'extensions', 'examples'):
        shutil.copytree(ROOT/name, staging/name,
                        ignore=shutil.ignore_patterns('__pycache__', '.DS_Store'))
    for name in ('Install Paco.command', 'requirements.txt', 'requirements-meetings.txt',
                 'README.md', 'QUICKSTART.md', 'CONNECT.md', 'COMPANY.md', 'TEAM-SETUP.md'):
        shutil.copy2(ROOT/name, staging/name)
    (staging/'Install Paco.command').chmod(0o755)
    build(ROOT, python='/usr/bin/false', destination=staging/'prebuilt/Paco.app', universal=True)
    # No paths from the builder's Mac belong in a distributed template.
    import plistlib
    plist = staging/'prebuilt/Paco.app/Contents/Info.plist'
    info = plistlib.loads(plist.read_bytes())
    info['PacoScript'] = '/not-installed/paco.py'
    plist.write_bytes(plistlib.dumps(info))
    subprocess.run(['codesign', '--force', '--deep', '--sign', '-', str(plist.parents[1])], check=True)
    subprocess.run(['bash', str(staging/'Install Paco.command'), '--check'], check=True)
    output.mkdir(exist_ok=True)
    archive = output/f'Paco-{VERSION}-macOS.zip'
    if archive.exists():
        archive.unlink()
    subprocess.run(['ditto', '-c', '-k', '--keepParent', '--norsrc', str(staging), str(archive)], check=True)
    (output/'SHA256SUMS.txt').write_text(hashlib.sha256(archive.read_bytes()).hexdigest()+'  '+archive.name+'\n')
    print(archive)


if __name__ == '__main__':
    main()
