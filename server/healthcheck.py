"""Systemd timer probe: recover a stuck server without logging user data."""
import json
import subprocess
import time
import urllib.request


def healthy():
    try:
        with urllib.request.urlopen('http://127.0.0.1:8765/health', timeout=10) as response:
            data = json.load(response)
            return response.status == 200 and data.get('ok') is True and data.get('service') == 'paco'
    except (OSError, ValueError):
        return False


def main():
    if healthy():
        return
    time.sleep(5)
    if not healthy():
        print('Paco health check failed twice; restarting the company service.', flush=True)
        subprocess.run(['systemctl', '--user', 'restart', 'paco-company.service'], check=True)


if __name__ == '__main__':
    main()
