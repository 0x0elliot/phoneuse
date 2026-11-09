#!/usr/bin/env bash
# Build the macOS port and link it onto PATH.
set -euo pipefail
cd "$(dirname "$0")"

command -v swift >/dev/null || {
  echo "swift not found. Install Xcode or the Command Line Tools: xcode-select --install" >&2
  exit 1
}

swift build -c release

BIN="$PWD/.build/release/phoneuse-mac"
mkdir -p "$HOME/.local/bin"
ln -sf "$BIN" "$HOME/.local/bin/phoneuse-mac"

echo "linked $HOME/.local/bin/phoneuse-mac"
case ":$PATH:" in
  *":$HOME/.local/bin:"*) ;;
  *) echo "note: $HOME/.local/bin is not on your PATH" ;;
esac

echo
echo "Next: open iPhone Mirroring and pair your phone, then grant Screen Recording"
echo "and Accessibility to this terminal in System Settings > Privacy & Security."
echo
"$HOME/.local/bin/phoneuse-mac" status || true
