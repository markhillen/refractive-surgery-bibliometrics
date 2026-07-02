"""
check_deps.py — Verify required third-party packages are installed.
====================================================================
Called at startup by main.py and gui.py so that a fresh checkout fails
with one clear, actionable message rather than a ModuleNotFoundError
partway through a run.

Standard-library modules (urllib, json, csv, sqlite3, etc.) are assumed
present and are not checked here.
"""

import sys

# package import-name → pip install-name (usually identical)
REQUIRED = {
    "numpy":      "numpy",
    "matplotlib": "matplotlib",
    "networkx":   "networkx",
    "openpyxl":   "openpyxl",
}

OPTIONAL = {
    "pyvis": "pyvis",   # interactive HTML network only
}


def check(verbose: bool = True) -> list[str]:
    """Return a list of missing REQUIRED pip package names (empty if all present)."""
    missing = []
    for mod, pip_name in REQUIRED.items():
        try:
            __import__(mod)
        except ImportError:
            missing.append(pip_name)

    if missing and verbose:
        exe = sys.executable
        print("=" * 64)
        print("  Missing required packages:", ", ".join(missing))
        print("  Install them with:")
        print(f"    {exe} -m pip install {' '.join(missing)}")
        print("  (add --break-system-packages if not using a virtualenv)")
        print("  Or install everything at once:")
        print(f"    {exe} -m pip install -r requirements.txt")
        print("=" * 64)

    return missing


def check_optional() -> list[str]:
    """Return list of missing OPTIONAL packages (no output)."""
    missing = []
    for mod, pip_name in OPTIONAL.items():
        try:
            __import__(mod)
        except ImportError:
            missing.append(pip_name)
    return missing


if __name__ == "__main__":
    miss = check()
    if miss:
        sys.exit(1)
    print("All required packages present.")
    opt = check_optional()
    if opt:
        print("Optional packages not installed:", ", ".join(opt))
