"""Load `.env` into the process environment. Once, early, before anything reads it.

=============================================================================
THE BUG THIS FIXES

`python-dotenv` was listed in requirements.txt from Phase 1 and **never called**.
Every module in this project reads configuration with `os.environ.get(...)`:

    llm/factory.py        os.environ.get("LLM_PROVIDER")
    llm/gemini_provider.py os.environ.get("GEMINI_API_KEY")
    governance/policy.py  os.environ.get("DECISION_THRESHOLD")
    app/config.py         os.environ.get("CORS_ALLOWED_ORIGINS")

None of that reaches a `.env` file on its own. `os.environ` contains what the
shell exported, and nothing else. So a correct `.env` containing

    LLM_PROVIDER=gemini
    GEMINI_API_KEY=...

was simply invisible: `LLM_PROVIDER` resolved to None, the factory fell through
to its `stub` default, and the UI honestly reported `provider: stub`.

The failure mode is nasty precisely because nothing is broken. There is no
error, no warning and no stack trace -- the default is a *legitimate*
configuration, so the system reports a true fact about a state you did not
intend. That is the whole reason `verify_cli` exists and why the factory now
warns when Gemini is selected without a key.
=============================================================================

WHY A SEPARATE MODULE

It has no dependencies on `app`, `llm` or `governance`, so any of them can call
it without an import cycle or a layering inversion. Three entry points do:

    app/main.py        the FastAPI application
    llm/factory.py     provider selection, wherever it is reached from
    llm/verify_cli.py  the diagnostic

PRECEDENCE: a real environment variable always wins over `.env`
(`override=False`). `LLM_PROVIDER=stub python -m ...` must still work for a
one-off run, and CI must not be silently reconfigured by a developer's file.

THE KEY: this module loads `.env`; it never reads, logs or returns a value from
it. Nothing here prints configuration.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger("claims.config")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DOTENV_PATH = PROJECT_ROOT / ".env"

_loaded = False


def load_project_env(*, force: bool = False) -> bool:
    """Load the project's `.env` if present. Idempotent. Returns whether it loaded.

    A missing `.env` is not an error: every setting in this project has a
    working default, which is what lets the POC run with no configuration at
    all. It is only a problem when you *meant* to configure something, which is
    what `python -m llm.verify_cli` is for.
    """
    global _loaded
    if _loaded and not force:
        return False

    _loaded = True

    if not DOTENV_PATH.is_file():
        logger.debug("No .env at %s; using defaults and the shell environment.", DOTENV_PATH)
        return False

    try:
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover - dotenv is a declared dependency
        logger.warning(
            "python-dotenv is not installed, so %s was not loaded. "
            "Run: pip install -r requirements.txt",
            DOTENV_PATH.name,
        )
        return False

    # override=False: an exported variable beats the file. Never the reverse.
    load_dotenv(DOTENV_PATH, override=False)
    logger.info("Loaded configuration from %s", DOTENV_PATH.name)
    return True


def mask_secret(value: str | None, *, keep: int = 4) -> str:
    """Render a secret for a diagnostic: `****abcd`, or `(not set)`.

    The last few characters are enough to tell two keys apart when you are
    looking at the wrong one. They are not enough to use. Nothing in this
    project ever renders more than this.
    """
    if not value:
        return "(not set)"
    tail = value[-keep:] if len(value) > keep else ""
    return f"****{tail}"
