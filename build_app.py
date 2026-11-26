"""Build the local macOS shell with Apple's installed command-line tools."""
from pathlib import Path
import plistlib
import subprocess
import sys
import tempfile
import shutil

VERSION = '0.6.2'


def install_prebuilt(template, root, python, destination):
    """Relocate a release shell without requiring Xcode on the recipient's Mac."""
    template, destination = Path(template), Path(destination)
    info = plistlib.loads((template/'Contents/Info.plist').read_bytes())
    if info.get('CFBundleIdentifier') != 'com.paco.desktop':
        raise ValueError('Not a Paco release bundle')
    subprocess.run(['codesign', '--verify', '--deep', '--strict', str(template)], check=True)
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(template, destination)
    info.update(PacoPython=str(python), PacoScript=str(Path(root)/'paco.py'))
    (destination/'Contents/Info.plist').write_bytes(plistlib.dumps(info))
    subprocess.run(['codesign', '--force', '--deep', '--sign', '-', str(destination)], check=True, capture_output=True)
    return destination


def build(root=None, python=None, destination=None, universal=False):
    root = Path(root or Path(__file__).resolve().parent)
    bundle = (Path(destination) if destination else root/'build/Paco.app')/'Contents'
    (bundle/'MacOS').mkdir(parents=True,exist_ok=True)
    (bundle/'Resources').mkdir(parents=True,exist_ok=True)
    # Package the existing Paco artwork at every Finder/Launchpad icon size.
    with tempfile.TemporaryDirectory() as temporary:
        iconset=Path(temporary)/'Paco.iconset';iconset.mkdir()
        for size in (16,32,128,256,512):
            for scale in (1,2):
                name=f'icon_{size}x{size}'+('@2x' if scale==2 else '')+'.png'
                subprocess.run(['sips','-z',str(size*scale),str(size*scale),
                                str(root/'assets/icons/paco-friendly-v1.png'),'--out',str(iconset/name)],
                               check=True,capture_output=True)
        subprocess.run(['iconutil','-c','icns',str(iconset),'-o',str(bundle/'Resources/Paco.icns')],check=True)
    architectures = ['-arch','arm64','-arch','x86_64'] if universal else []
    subprocess.run(['xcrun','clang',*architectures,'-mmacosx-version-min=14.2','-fobjc-arc','-fmodules',str(root/'native/Paco.m'),str(root/'native/AppleSources.m'),str(root/'native/Capture.m'),str(root/'native/MeetingCapture.m'),str(root/'native/MeetingSpeakers.m'),'-o',str(bundle/'MacOS/Paco'),
                    '-framework','Cocoa','-framework','WebKit','-framework','Carbon','-framework','EventKit','-framework','AVFoundation','-framework','ScreenCaptureKit','-framework','CoreMedia'],check=True)
    (bundle/'Info.plist').write_bytes(plistlib.dumps({
        'CFBundleIdentifier':'com.paco.desktop','CFBundleName':'Paco','CFBundleExecutable':'Paco',
        'CFBundleVersion':'10','CFBundleShortVersionString':VERSION,'LSMinimumSystemVersion':'14.2','LSUIElement':True,
        'CFBundlePackageType':'APPL','CFBundleDisplayName':'Paco','CFBundleIconFile':'Paco.icns',
        'PacoPython':str(python or sys.executable),'PacoScript':str(root/'paco.py'),
        'NSMicrophoneUsageDescription':'Paco transcribes meeting speech locally. Audio is never saved.',
        'NSScreenCaptureUsageDescription':'Paco captures meeting audio. No screen images or audio recordings are saved.',
        'NSAudioCaptureUsageDescription':'Paco transcribes meeting audio locally without saving recordings.',
        'NSCalendarsFullAccessUsageDescription':'Paco reads calendar timing to protect meetings and plan work.',
        'NSRemindersFullAccessUsageDescription':'Paco reads your reminders when you connect Apple Reminders.',
        'NSCalendarsUsageDescription':'Paco reads calendar timing to plan work.',
        'NSRemindersUsageDescription':'Paco reads reminders you connect.',
        'NSHighResolutionCapable':True,'NSAppTransportSecurity':{'NSAllowsLocalNetworking':True}}))
    subprocess.run(['codesign','--force','--deep','--sign','-',str(bundle.parent)],check=True,capture_output=True)
    return bundle.parent

if __name__=='__main__':
    print(build())
