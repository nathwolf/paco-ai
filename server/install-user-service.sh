#!/bin/sh
# Run from the deployed source directory as the unprivileged service owner.
set -eu
base=${1:?Usage: sh server/install-user-service.sh https://hostname OR temporary}
root=$(pwd)
case "$root" in *' '*) echo 'Use an installation path without spaces'; exit 1;; esac
case "$base" in https://*) address_args="--base $base";; temporary) address_args="--base-file $root/data/public-url";; *) echo 'HTTPS base URL or temporary required'; exit 1;; esac
umask 077
mkdir -p "$root/data" "$HOME/.config/systemd/user"
chmod 700 "$root/data"
python3 -m venv "$root/.venv"
deps=server/requirements.txt
if [ -f server/requirements.lock ]; then deps=server/requirements.lock; fi
"$root/.venv/bin/python" -m pip install --disable-pip-version-check -r "$deps"
cat > "$HOME/.config/systemd/user/paco-company.service" <<EOF
[Unit]
Description=Paco internal company task service
After=network-online.target
StartLimitIntervalSec=0
[Service]
Type=simple
WorkingDirectory=$root
ExecStart=$root/.venv/bin/python -m server.main --db $root/data/paco.sqlite3 $address_args
Restart=always
RestartSec=5
UMask=0077
NoNewPrivileges=yes
MemoryMax=512M
TasksMax=64
[Install]
WantedBy=default.target
EOF
cat > "$HOME/.config/systemd/user/paco-maintenance.service" <<EOF
[Unit]
Description=Paco task database backup and token cleanup
[Service]
Type=oneshot
WorkingDirectory=$root
ExecStart=$root/.venv/bin/python -m server.admin --db $root/data/paco.sqlite3 maintenance
UMask=0077
NoNewPrivileges=yes
EOF
cat > "$HOME/.config/systemd/user/paco-maintenance.timer" <<EOF
[Unit]
Description=Daily Paco maintenance
[Timer]
OnCalendar=daily
Persistent=true
RandomizedDelaySec=15m
[Install]
WantedBy=timers.target
EOF
if [ "$base" = temporary ]; then
  test -x "$HOME/bin/cloudflared" || { echo 'Install official cloudflared at ~/bin/cloudflared first'; exit 1; }
  cat > "$HOME/.config/systemd/user/paco-tunnel.service" <<EOF
[Unit]
Description=Paco provisional Cloudflare HTTPS tunnel
After=network-online.target
[Service]
Type=simple
WorkingDirectory=$root
ExecStart=$root/.venv/bin/python -m server.tunnel --binary $HOME/bin/cloudflared --address-file $root/data/public-url
Restart=always
RestartSec=15
UMask=0077
NoNewPrivileges=yes
MemoryMax=256M
[Install]
WantedBy=default.target
EOF
fi
cat > "$HOME/.config/systemd/user/paco-health.service" <<EOF
[Unit]
Description=Check Paco and recover an unresponsive task service
[Service]
Type=oneshot
WorkingDirectory=$root
ExecStart=$root/.venv/bin/python -m server.healthcheck
UMask=0077
NoNewPrivileges=yes
EOF
cat > "$HOME/.config/systemd/user/paco-health.timer" <<EOF
[Unit]
Description=Check Paco every two minutes
[Timer]
OnBootSec=2min
OnUnitActiveSec=2min
[Install]
WantedBy=timers.target
EOF
systemctl --user daemon-reload
systemctl --user enable --now paco-company.service paco-maintenance.timer paco-health.timer
if [ "$base" = temporary ]; then systemctl --user enable --now paco-tunnel.service; fi
systemctl --user restart paco-company.service
systemctl --user start paco-maintenance.service
