#!/usr/bin/env python3
"""Package-relative entry point; credentials are not used by the graph server."""
import os
import sys
from pathlib import Path

for name in ("OPENAI_API_KEY", "CODEX_API_KEY"):
    os.environ.pop(name, None)
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from arv.server import main

if __name__ == "__main__":
    main()
