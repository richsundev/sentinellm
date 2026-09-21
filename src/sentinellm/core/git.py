"""Git metadata helper, shared by anything that stamps a git commit onto a
persisted record (experiment runs, the demo seed script)."""

from __future__ import annotations

import subprocess
from functools import lru_cache
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]


@lru_cache
def get_git_commit() -> str:
    """Cached: the checked-out commit can't change under a running process,
    and this is called from async request paths (experiment runs) where a
    fresh blocking `git` subprocess each time stalls the event loop."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return "unknown"
