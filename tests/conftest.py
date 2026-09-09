"""pytest configuration: make the repo root importable so tests can do
`from cotd_parser import ...` and `import elo_engine` without installing."""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)
