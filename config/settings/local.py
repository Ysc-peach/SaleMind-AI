"""Local development settings."""

from pathlib import Path

import environ


# Load the ignored local .env before importing base settings. ``overwrite=False``
# preserves values supplied by the process environment (for example, CI values).
BASE_DIR = Path(__file__).resolve().parents[2]
environ.Env().read_env(BASE_DIR / ".env", overwrite=False)

from .base import *  # noqa: E402,F401,F403


DEBUG = True
