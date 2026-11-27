"""Run the installed package's unittest checks with inherited network guards."""
import os
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
environment = dict(os.environ)
environment.pop("POLYGON_API_KEY", None)
environment["PYTHONPATH"] = str(root / "tests/offline_guard")
result = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
                        cwd=root, env=environment)
raise SystemExit(result.returncode)
