#!/bin/bash
# Internal pilot installer. No sudo, Homebrew, or Xcode required by recipients.
set -euo pipefail
cd "$(dirname "$0")"
trap 'echo "Installation stopped. The error above explains why."; if [ -t 0 ]; then read -r -p "Press Return to close."; fi' ERR
test "$(uname -s)" = Darwin || { echo 'Paco requires macOS 14.2 or newer.'; exit 1; }
version=$(sw_vers -productVersion)
major=${version%%.*}; rest=${version#*.}; minor=${rest%%.*}
if (( major < 14 || (major == 14 && minor < 2) )); then echo 'Paco requires macOS 14.2 or newer.'; exit 1; fi
arch=$(uname -m)
if [ "$(sysctl -n hw.optional.arm64 2>/dev/null || true)" = 1 ]; then arch=arm64; fi
case "$arch" in
  arm64) target=aarch64; checksum=89ce773f5eb6f072ceea3a30d86258ecd5d02ea0f8e87fda0b940b9067aebf81;;
  x86_64) target=x86_64; checksum=0ed706ae7467b9e6e3df827c2fb4043d6022aa8fa9f5cd9fb4b436ef4eb06ecf;;
  *) echo "Unsupported Mac architecture: $arch"; exit 1;;
esac
if [ "${1:-}" = --check ]; then
  /usr/bin/codesign --verify --deep --strict prebuilt/Paco.app
  echo "Ready to install on macOS $version ($arch)."
  exit 0
fi
runtime="$HOME/Library/Application Support/Paco/python/3.11.18-20261124-$arch"
python="$runtime/bin/python3"
if [ ! -x "$python" ]; then
  echo 'Downloading Paco’s private Python runtime…'
  temporary=$(mktemp -d)
  trap 'rm -rf "$temporary"' EXIT
  url="https://github.com/astral-sh/python-build-standalone/releases/download/20261124/cpython-3.11.18%2B20261124-$target-apple-darwin-install_only.tar.gz"
  /usr/bin/curl --fail --location --retry 3 --proto '=https' --tlsv1.2 "$url" -o "$temporary/python.tar.gz"
  printf '%s  %s\n' "$checksum" "$temporary/python.tar.gz" | /usr/bin/shasum -a 256 -c -
  /usr/bin/tar -xzf "$temporary/python.tar.gz" -C "$temporary"
  mkdir -p "$(dirname "$runtime")"
  mv "$temporary/python" "$runtime"
fi
if [ "${1:-}" = --prepare-runtime ]; then "$python" --version; exit 0; fi
echo 'Installing Paco and local meeting transcription dependencies…'
"$python" paco.py install
echo 'Paco is installed. Click the parrot in your menu bar to finish setup.'
if [ -t 0 ]; then read -r -p 'Press Return to close this installer.'; fi
