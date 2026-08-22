#!/bin/bash
# Double-click this in Finder after cloning. Homebrew and Node are not required.
set -euo pipefail

cd "$(dirname "$0")"
ROOT="$(pwd)"
VENV="$ROOT/.venv"
MIN_PY="3.10"

keep_open() {
  echo
  echo "Press Return to close this window."
  read -r _
}

fail() {
  echo
  echo "Something went wrong: $*"
  keep_open
  exit 1
}

say() {
  echo "$@" >&2
}

version_ok() {
  "$1" -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" 2>/dev/null
}

find_python() {
  local c
  for c in "$VENV/bin/python" python3.13 python3.12 python3.11 python3.10 python3; do
    if command -v "$c" >/dev/null 2>&1 && version_ok "$c"; then
      command -v "$c"
      return 0
    fi
  done
  return 1
}

ensure_uv() {
  if command -v uv >/dev/null 2>&1; then
    return 0
  fi
  export PATH="$HOME/.local/bin:$PATH"
  if command -v uv >/dev/null 2>&1; then
    return 0
  fi
  say "Installing a small helper (uv) so Python can be set up without Homebrew…"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
  command -v uv >/dev/null 2>&1
}

pick_python() {
  local py
  if py="$(find_python)"; then
    say "Using Python: $py ($("$py" -V))"
    printf '%s\n' "$py"
    return 0
  fi

  if command -v brew >/dev/null 2>&1; then
    say "Python $MIN_PY or newer was not found. Installing with Homebrew…"
    brew install python
    if py="$(find_python)"; then
      printf '%s\n' "$py"
      return 0
    fi
  fi

  say "Python $MIN_PY or newer was not found, and Homebrew is not required."
  if ensure_uv; then
    say "Installing Python $MIN_PY with uv…"
    uv python install 3.12
    py="$(uv python find 3.12)"
    printf '%s\n' "$py"
    return 0
  fi

  return 1
}

echo "========================================"
echo "  Obed-Edom — starting the dashboard"
echo "========================================"
echo
echo "Leave this window open while you work."
echo "Keynote must already be installed on this Mac."
echo

if [[ "$(uname -s)" != "Darwin" ]]; then
  fail "This tool only runs on a Mac (it drives Keynote)."
fi

if ! command -v curl >/dev/null 2>&1; then
  fail "curl is missing. Install Apple’s Command Line Tools when prompted, then try again."
fi

PY="$(pick_python)" || fail "Could not find or install Python $MIN_PY+. Connect to the internet and try again, or install Python from https://www.python.org/downloads/macos/"

if [[ ! -x "$VENV/bin/python" ]] || ! version_ok "$VENV/bin/python"; then
  echo "Creating a private Python folder in this project (once)…"
  export PATH="$HOME/.local/bin:$PATH"
  if command -v uv >/dev/null 2>&1; then
    uv venv "$VENV" --python "$PY"
  else
    "$PY" -m venv "$VENV"
  fi
fi

echo "Installing Obed-Edom into that folder…"
"$VENV/bin/python" -m pip install -q --upgrade pip
"$VENV/bin/python" -m pip install -q -e "$ROOT"

if [[ ! -f "$ROOT/dashboard/dist/index.html" ]]; then
  fail "The dashboard files are missing (dashboard/dist). Re-clone the folder, or ask whoever maintains this project to rebuild the UI."
fi

echo
echo "Opening the dashboard in your browser…"
echo "If nothing opens, go to: http://127.0.0.1:8765/"
echo
exec "$VENV/bin/python" -m obed_edom dashboard
