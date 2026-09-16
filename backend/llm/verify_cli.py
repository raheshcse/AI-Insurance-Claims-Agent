"""Prove — or disprove — that a real LLM call is happening.

    python -m llm.verify_cli                # one narration through the configured provider
    python -m llm.verify_cli --provider gemini
    python -m llm.verify_cli --json

Why this exists: `LLM_PROVIDER=gemini` means a provider was *selected*, not that
a request reached Google. Every provider in this project falls back to
deterministic text when its key is missing or its endpoint is unreachable, and
that fallback is designed to be invisible to the workflow — which is right for
a claims system and useless when you are trying to confirm the integration.

So this makes one narration call and reports what actually happened:

    configured      is a key present?  (presence only — only the API can judge it)
    degraded        did the fallback write this, or did the model?
    provider/model  what answered
    latency         a real network round trip is not sub-millisecond
    text            the prose itself, which reads nothing like the stub's

EXIT CODES
    0   a live model answered            (degraded=False)
    1   the fallback answered            (no key, unreachable, blocked, empty)
    2   the CLI could not run            (bad arguments)

Exit 1 is not a crash. It is the honest answer to "did a real call happen?" when
the answer is no, and it is what CI would check.

**The API key is never printed**, in any mode. This reports whether a key is
present and how many characters it has; nothing more. A verification tool that
echoes the credential it is verifying is a liability, not a diagnostic.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any

from bootstrap import DOTENV_PATH, load_project_env, mask_secret
from llm.base import NarrationRequest
from llm.factory import get_llm_provider
from llm.gemini_provider import API_KEY_ENV

EXIT_LIVE = 0
EXIT_FALLBACK = 1
EXIT_UNUSABLE = 2

# The same shape an agent sends: facts already determined, prose requested.
# Nothing here is a claim decision and nothing is read back by any rule.
SAMPLE = NarrationRequest(
    purpose="claim intake summary for a claims employee",
    facts={
        "headline": "Storm damage claim covering Roof, Ceiling",
        "points": [
            "2 damaged item(s) reported across 2 area(s).",
            "Photographs supplied.",
            "Loss reported 1 day(s) after it occurred.",
        ],
        "caveat": "Synthetic demonstration data. Not a real claim.",
    },
    max_words=60,
)


def _key_state(provider_name: str) -> dict[str, Any]:
    """Whether a key is configured. Never the key itself.

    `masked` shows the last four characters only -- enough to tell two keys
    apart when you are looking at the wrong one, not enough to use.
    """
    env_var = API_KEY_ENV if provider_name == "gemini" else "OPENAI_API_KEY"
    raw = os.environ.get(env_var, "")
    return {
        "env_var": env_var,
        "configured": bool(raw),
        "length": len(raw),  # a length is not a credential; a prefix would be
        "masked": mask_secret(raw),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m llm.verify_cli",
        description="Make one narration call and report whether a live model answered.",
    )
    parser.add_argument(
        "--provider",
        default=None,
        help="Override LLM_PROVIDER for this check (e.g. gemini, stub, openai).",
    )
    parser.add_argument("--json", action="store_true", help="Machine-readable output")
    args = parser.parse_args(argv)

    dotenv_loaded = load_project_env()
    provider = get_llm_provider(args.provider)
    key = _key_state(provider.name)

    started = time.perf_counter()
    result = provider.narrate(SAMPLE)
    elapsed_ms = round((time.perf_counter() - started) * 1000, 1)

    live = not result.degraded and provider.name != "stub"

    payload = {
        "provider": result.provider,
        "model": result.model,
        "degraded": result.degraded,
        "degraded_reason": result.degraded_reason,
        "live_model_answered": live,
        "latency_ms": elapsed_ms,
        "api_key": key,
        "dotenv_path": str(DOTENV_PATH),
        "dotenv_present": DOTENV_PATH.is_file(),
        "llm_provider_env": os.environ.get("LLM_PROVIDER"),
        "endpoint": getattr(provider, "endpoint", None),
        "narration": result.text,
    }

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return EXIT_LIVE if live else EXIT_FALLBACK

    print()
    print("LLM PROVIDER CHECK")
    print("-" * 18)
    print(
        f"  .env              {DOTENV_PATH}"
        + ("" if DOTENV_PATH.is_file() else "   (NOT FOUND)")
    )
    print(f"  LLM_PROVIDER      {os.environ.get('LLM_PROVIDER') or '(not set -> stub)'}")
    print(f"  provider          {result.provider}")
    print(f"  model             {result.model or '(none — deterministic stub)'}")
    if payload["endpoint"]:
        print(f"  endpoint          {payload['endpoint']}")
    print(
        f"  {key['env_var']:<17} "
        + (
            f"configured: true  {key['masked']}  ({key['length']} chars)"
            if key["configured"]
            else "configured: false"
        )
    )
    print(f"  round trip        {elapsed_ms} ms")
    print()

    if live:
        print("  RESULT            LIVE — a real model produced this text.")
    elif provider.name == "stub":
        print("  RESULT            STUB — no provider configured, no call was made.")
        print("                    This is the default and is not an error.")
    else:
        print("  RESULT            FALLBACK — the provider was selected but did not")
        print("                    answer. The deterministic stub wrote this text and")
        print("                    the analysis result will report llm_degraded=true.")
        if result.degraded_reason:
            print(f"                    Reason code: {result.degraded_reason}")
        if not key["configured"]:
            print(f"                    Cause: {key['env_var']} is not set.")
            if not DOTENV_PATH.is_file():
                print("                    There is also no .env file at the path above.")
        else:
            print("                    Cause: the endpoint was unreachable, refused the")
            print("                    key, or returned nothing usable. Run the backend")
            print("                    and read the claims.llm log line for the class.")

    print()
    print("  narration")
    for line in _wrap(result.text, 72):
        print(f"    {line}")
    print()
    print("  Narration is prose only. No claim decision depends on it, whichever")
    print("  way this check comes out.")
    print()

    return EXIT_LIVE if live else EXIT_FALLBACK


def _wrap(text: str, width: int) -> list[str]:
    words, lines, current = text.split(), [], ""
    for word in words:
        if len(current) + len(word) + 1 > width:
            lines.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    if current:
        lines.append(current)
    return lines or [""]


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 - a diagnostic must not traceback
        print(f"Could not run the check: {exc.__class__.__name__}", file=sys.stderr)
        raise SystemExit(EXIT_UNUSABLE) from exc
