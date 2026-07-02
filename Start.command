#!/bin/bash
# ============================================================================
#  Start.command — double-click this file to launch the bibliometrics app.
#
#  On first run it sets up a private Python environment and installs the
#  four packages the app needs (about a minute, one time only). After that
#  it just launches — your web browser opens automatically.
#
#  Keep the black Terminal window open while you work. Close it, or press
#  Ctrl+C inside it, to stop the app.
# ============================================================================

cd "$(dirname "$0")" || exit 1

say()  { printf '\n\033[1m%s\033[0m\n' "$1"; }
fail() { printf '\n\033[31mERROR: %s\033[0m\n' "$1"; printf '\nPress Return to close this window.\n'; read -r _; exit 1; }

say "Bibliometrics — starting up in $(basename "$PWD")"

# 1. Find a suitable Python (3.10 or newer) ---------------------------------
PY=""
for cand in python3.13 python3.12 python3.11 python3.10 python3; do
  if command -v "$cand" >/dev/null 2>&1; then
    v=$("$cand" -c 'import sys;print(sys.version_info[0]*100+sys.version_info[1])' 2>/dev/null || echo 0)
    if [ "$v" -ge 310 ]; then PY="$cand"; break; fi
  fi
done
[ -n "$PY" ] || fail "Python 3.10 or newer was not found.
Install it from https://www.python.org/downloads/  (click the big yellow
Download button, run the installer), then double-click this file again."
say "Using $("$PY" --version)"

# 2. Create the private environment (one time) ------------------------------
if [ ! -d ".venv" ]; then
  say "Setting up (one time only)…"
  "$PY" -m venv .venv || fail "Could not create the Python environment."
fi
# shellcheck disable=SC1091
source .venv/bin/activate || fail "Could not activate the Python environment.
Delete the '.venv' folder in this directory and try again."

# 3. Install / update dependencies (only when needed) -----------------------
if [ ! -f ".venv/.installed" ] || [ requirements.txt -nt ".venv/.installed" ]; then
  say "Installing the packages the app needs (one time, ~1 minute)…"
  python -m pip install --quiet --upgrade pip >/dev/null 2>&1
  if python -m pip install --quiet -r requirements.txt; then
    date > ".venv/.installed"
  else
    fail "Could not install the required packages.
Check that you are connected to the internet, then try again."
  fi
fi

# 4. Launch -----------------------------------------------------------------
say "Launching — your browser will open in a moment."
echo   "Leave this window open while you work; close it to stop the app."
python gui.py
say "The app has stopped."
printf '\nPress Return to close this window.\n'; read -r _
