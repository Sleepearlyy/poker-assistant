"""Bundled resources are read-only; installed apps save per-user data."""
import os
import sys
from pathlib import Path

def roots():
    if getattr(sys, "frozen", False):
        bundle = Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
        home = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "PokerScreenReader"
        home.mkdir(parents=True, exist_ok=True)
        return bundle, home
    here = Path(__file__).resolve().parent
    return here, here

ROOT, DATA = roots()
