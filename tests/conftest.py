"""
Shared test set-up. pytest loads this before any test module.

* SDL's "dummy" drivers let the GUI tests draw into memory - no window opens
  (and CI machines have no screen).
* JACKC_GUI=off so a Jack compiler installed on this machine is never launched.
"""

import os
from pathlib import Path

import pytest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
os.environ["JACKC_GUI"] = "off"

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures() -> Path:
    return FIXTURES
