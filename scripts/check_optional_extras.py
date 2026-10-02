"""Run the test suite as if the optional extras were not installed.

`pyproject.toml` declares opencv and smolagents as optional, and
`pytest.importorskip` is what makes that true at test time. The trouble is that
a skip is silent: if an import at module scope in `src/` ever starts pulling
OpenCV in, the full suite still passes, and the only person who finds out is
whoever installed without the extras.

CI has a job for this. This script is the same check locally, without having to
uninstall anything:

    python scripts/check_optional_extras.py

It blocks the imports with a meta-path finder rather than touching the
environment, so it cannot leave your working install in a different state than
it found it.
"""
from __future__ import annotations

import os
import pathlib
import subprocess
import sys
import tempfile

BLOCKED = ("cv2", "smolagents")

SITECUSTOMIZE = '''
import sys

BLOCKED = {blocked!r}


class _Block:
    """Refuse the optional imports, as if they were never installed."""

    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in BLOCKED:
            raise ImportError("No module named %r" % name.split(".")[0])
        return None


sys.meta_path.insert(0, _Block())
'''


def main() -> int:
    with tempfile.TemporaryDirectory() as temporary:
        (pathlib.Path(temporary) / "sitecustomize.py").write_text(
            SITECUSTOMIZE.format(blocked=BLOCKED), encoding="utf-8"
        )

        environment = dict(os.environ)
        # Prepended, so a PYTHONPATH already in use keeps working.
        existing = environment.get("PYTHONPATH", "")
        environment["PYTHONPATH"] = (
            f"{temporary}{os.pathsep}{existing}" if existing else temporary
        )

        print(f"running the suite with {', '.join(BLOCKED)} blocked\n")
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-rs", *sys.argv[1:]],
            env=environment,
            check=False,
        )

    if result.returncode == 0:
        print("\nthe optional extras really are optional")
    else:
        print("\nsomething in src/ needs an optional dependency at import time")
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
