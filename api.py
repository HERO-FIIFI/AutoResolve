"""Vercel entrypoint for the src-layout application."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from agentictriage.api import app  # noqa: E402

__all__ = ["app"]
