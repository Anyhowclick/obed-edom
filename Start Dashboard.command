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

venv_stale() {
  local py="$1" pyver dirs
  dirs=("$VENV"/lib/python*)
  pyver="$("$py" -c 'import sys; print("python%d.%d" % sys.version_info[:2])')"
  [[ ${#dirs[@]} -eq 1 && -d "${dirs[0]}" && "$(basename "${dirs[0]}")" == "$pyver" ]] && return 1
  return 0
}

find_python() {
  local skip_venv="${1:-}" c
  for c in "$VENV/bin/python" python3.13 python3.12 python3.11 python3.10 python3; do
    [[ -n "$skip_venv" && "$c" == "$VENV/bin/python" ]] && continue
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
  local skip_venv="${1:-}" py
  if py="$(find_python "$skip_venv")"; then
    say "Using Python: $py ($("$py" -V))"
    printf '%s\n' "$py"
    return 0
  fi

  if command -v brew >/dev/null 2>&1; then
    say "Python $MIN_PY or newer was not found. Installing with Homebrew…"
    brew install python
    if py="$(find_python "$skip_venv")"; then
      printf '%s\n' "$py"
      return 0
    fi
  fi

  say "Python $MIN_PY or newer was not found, and Homebrew is not required."
  if ensure_uv; then
    say "Installing Python $MIN_PY with uv…"
    uv python install 3.12
    py="$(uv python find 3.12)"
    read -r py <<<"$py"
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

git_with_timeout() {
  local secs="$1" waited=0
  shift
  "$@" >/dev/null 2>&1 &
  local pid=$!
  disown "$pid" 2>/dev/null
  while kill -0 "$pid" 2>/dev/null; do
    if (( waited >= secs )); then
      kill -TERM -"$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null
      sleep 2
      kill -KILL -"$pid" 2>/dev/null || kill -KILL "$pid" 2>/dev/null
      wait "$pid" 2>/dev/null
      return 124
    fi
    sleep 1
    waited=$((waited + 1))
  done
  wait "$pid"
}

if command -v git >/dev/null 2>&1 && git -C "$ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  # -0 prompt / batch-mode ssh stop a private repo from hanging the window on a login prompt;
  # the low-speed options give up on a stalled transfer, and git_with_timeout bounds a stuck connect too
  export GIT_TERMINAL_PROMPT=0
  export GIT_SSH_COMMAND="ssh -oBatchMode=yes"
  git_with_timeout 10 git -C "$ROOT" -c http.lowSpeedLimit=1000 -c http.lowSpeedTime=10 fetch --prune || true
  branch="$(git -C "$ROOT" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")"
  if [[ "$branch" == "HEAD" ]]; then
    echo "Not updating: this copy isn't on a branch (a detached checkout)."
  elif [[ "$branch" != "main" ]]; then
    echo "Not updating: you're on branch $branch, not main."
  elif [[ -n "$(git -C "$ROOT" status --porcelain --untracked-files=no 2>/dev/null)" ]]; then
    echo "Not updating: you have your own changes here."
  elif git_with_timeout 10 git -C "$ROOT" -c http.lowSpeedLimit=1000 -c http.lowSpeedTime=10 -c merge.overwriteIgnore=false pull --ff-only; then
    echo "Updated to the latest version."
  else
    echo "Couldn't check for updates just now — carrying on with the version you have."
  fi
fi

if [[ ! -x "$VENV/bin/python" ]] || ! version_ok "$VENV/bin/python" || venv_stale "$VENV/bin/python" || ! "$VENV/bin/python" -m pip --version >/dev/null 2>&1; then
  echo "Creating a private Python folder in this project (once)…"
  if [[ -e "$VENV" ]]; then
    rm -rf "$VENV" 2>/dev/null || mv "$VENV" "$VENV-old-$(date +%s)" 2>/dev/null || fail "Could not remove or move aside the old .venv folder. Please delete the .venv folder next to this file yourself, then run this again."
  fi
  # rebuilding, so the interpreter must come from outside the venv we just removed
  PY="$(pick_python skip_venv)" || fail "Could not find or install Python $MIN_PY+. Connect to the internet and try again, or install Python from https://www.python.org/downloads/macos/"
  export PATH="$HOME/.local/bin:$PATH"
  # --seed, or uv leaves the new folder without pip
  if command -v uv >/dev/null 2>&1; then
    uv venv "$VENV" --python "$PY" --seed || fail "Could not create the private Python folder with uv. Try deleting the .venv folder next to this file and running this again."
  else
    "$PY" -m venv "$VENV" || fail "Could not create the private Python folder. Try deleting the .venv folder next to this file and running this again."
  fi
fi

echo "Installing Obed-Edom into that folder…"
"$VENV/bin/python" -m pip install -q --upgrade pip || fail "Could not update pip in the private Python folder. Try deleting the .venv folder next to this file and running this again."
"$VENV/bin/python" -m pip install -q -e "$ROOT" || fail "Could not install Obed-Edom into the private Python folder. Try deleting the .venv folder next to this file and running this again."

if ! "$VENV/bin/python" -c 'import obed_edom' >/dev/null 2>&1; then
  echo "The first install attempt didn't take. Trying again…"
  export PATH="$HOME/.local/bin:$PATH"
  if command -v uv >/dev/null 2>&1; then
    uv pip install --python "$VENV/bin/python" --reinstall -e "$ROOT" || true
  else
    "$VENV/bin/python" -m pip install --force-reinstall --no-deps -e "$ROOT" || true
  fi
  if ! "$VENV/bin/python" -c 'import obed_edom' >/dev/null 2>&1; then
    fail "Obed-Edom could not be installed into its private Python folder. Try deleting the .venv folder next to this file and running this again."
  fi
fi

if [[ ! -f "$ROOT/dashboard/dist/index.html" ]]; then
  fail "The dashboard files are missing (dashboard/dist). Re-clone the folder, or ask whoever maintains this project to rebuild the UI."
fi

echo
echo "Opening the dashboard in your browser…"
echo "If nothing opens, go to: http://127.0.0.1:8765/"
echo
exec "$VENV/bin/python" -m obed_edom dashboard
