#!/bin/zsh
set -eu
cd "${0:A:h}"
for interpreter in .venv/bin/python /opt/homebrew/bin/python3.11 /opt/homebrew/bin/python3 /usr/local/bin/python3 /usr/bin/python3; do
  if [[ -x "$interpreter" ]] && "$interpreter" -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; then
    exec "$interpreter" paco.py desktop "$@"
  fi
done
print 'Paco needs Python 3.11 or newer. Install it and reopen this launcher.'
read -r
