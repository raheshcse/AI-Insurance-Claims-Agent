"""The audit CLI. Real checks, real exit codes.

    python -m governance.audit_cli verify     was the ledger tampered with?
    python -m governance.audit_cli audit      does it describe a governed process?
    python -m governance.audit_cli certify    issue a VerbaCertificate, or refuse
    python -m governance.audit_cli summary    what actually happened, in numbers

=============================================================================
TWO DIFFERENT QUESTIONS, AND WHY BOTH ARE RUN

`verify_integrity()` re-walks the hash chain and answers "has anyone edited
these records?". `audit()` runs the framework's five checks and answers "do
these records describe a governed process?".

They are independent. A ledger can be perfectly intact and describe a process
with a terminal state nobody ever resolved; it can also pass every structural
check while having been rewritten. Reporting one as though it answered the
other is the single easiest way to produce a governance claim that is false, so
this CLI always reports both and `certify` requires both.
=============================================================================

EXIT CODES
    0   the requested check passed
    1   the requested check failed
    2   the CLI could not run (no ledger, bad arguments)

Non-zero on failure is the point: an audit that only prints is an audit nobody
notices. This is what CI would run.

A NOTE ON CHECK 1 (`no_monitoring_gaps`). vsl-core deliberately has no default
gap threshold -- required monitoring cadence varies by drift class -- and
passing None *skips* the check while reporting it as passed. This CLI therefore
reports it as NOT ASSERTED unless `--max-monitor-gap-seconds` is given, rather
than letting a skipped check read as a passed one.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from vsl_core.ledger import (
    DRIFT_DETECTED_KEY,
    VERIFICATION_RESULT_KEY,
    LedgerEntryType,
    VerificationResult,
)

from governance.ledger import LEDGER_PATH, build_ledger
from governance.policy import (
    ALL_INVARIANTS,
    AUTOMATION_CONFIDENCE,
    CLAIMS_SPECIFICATION,
    DECISION_THRESHOLD,
    effective_confidence_floor,
)

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_UNUSABLE = 2



# ---------------------------------------------------------------------------
# Output helpers. Plain text by default, JSON when a machine is reading.
# ---------------------------------------------------------------------------


def _emit(payload: dict[str, Any], lines: list[str], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        for line in lines:
            print(line)


def _rule(title: str) -> str:
    return f"\n{title}\n{'-' * len(title)}"


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def cmd_verify(ledger: Any, args: argparse.Namespace) -> int:
    intact = ledger.verify_integrity()
    checkpoint = ledger.current_checkpoint()
    entries = list(ledger.store.all_entries())

    payload = {
        "command": "verify",
        "ledger": str(args.ledger),
        "entries": len(entries),
        "integrity_verified": intact,
        "checkpoint": (
            {
                "sequence": checkpoint.sequence,
                "entry_hash": checkpoint.entry_hash,
            }
            if checkpoint
            else None
        ),
    }

    lines = [
        _rule("LEDGER INTEGRITY"),
        f"  ledger            {args.ledger}",
        f"  entries           {len(entries)}",
        f"  hash chain        {'INTACT' if intact else 'BROKEN'}",
    ]
    if checkpoint:
        lines.append(f"  tip               #{checkpoint.sequence} {checkpoint.entry_hash[:16]}...")
        lines.append(
            "  (the tip is the one value an external witness would need to anchor "
            "this chain over time; nothing here transmits it anywhere)"
        )
    if not intact:
        lines.append(
            "\n  The hash chain does not verify. Records have been edited, "
            "reordered or removed. Nothing derived from this ledger can be relied on."
        )

    _emit(payload, lines, as_json=args.json)
    return EXIT_OK if intact else EXIT_FAILED


def cmd_audit(ledger: Any, args: argparse.Namespace) -> int:
    report = ledger.audit(max_monitor_gap_seconds=args.max_monitor_gap_seconds)
    intact = ledger.verify_integrity()
    gap_asserted = args.max_monitor_gap_seconds is not None

    failed = list(report.checks_failed)
    passed = [
        c
        for c in report.checks_passed
        if gap_asserted or c != "no_monitoring_gaps"
    ]
    not_asserted = (
        []
        if gap_asserted
        else [c for c in report.checks_passed if c == "no_monitoring_gaps"]
    )

    payload = {
        "command": "audit",
        "ledger": str(args.ledger),
        "integrity_verified": intact,
        "checks_passed": passed,
        "checks_failed": failed,
        "checks_not_asserted": not_asserted,
        "violations": {k: list(v) for k, v in report.violations.items()},
        "all_passed": report.all_passed,
    }

    lines = [_rule("GOVERNANCE AUDIT")]
    lines.append(f"  ledger            {args.ledger}")
    lines.append(f"  hash chain        {'INTACT' if intact else 'BROKEN'}")
    lines.append("")
    for check in passed:
        lines.append(f"  PASS   {check}")
    for check in not_asserted:
        lines.append(
            f"  N/A    {check}  (no --max-monitor-gap-seconds given; "
            "the framework skips this check rather than testing it)"
        )
    for check in failed:
        lines.append(f"  FAIL   {check}")
        for entry_id in report.violations.get(check, []):
            lines.append(f"           {entry_id}")

    if "terminal_has_human_authorised_transition" in failed:
        lines.append(
            "\n  An open terminal state is an audit failure BY DESIGN. It means "
            "automation was suspended on a claim and no person has authorised "
            "resuming it. The exit code is non-zero and should be: the ledger is "
            "telling the truth about unfinished governance, not misbehaving."
        )

    if not intact:
        lines.append(
            "\n  Integrity failed. The structural checks above describe records "
            "that cannot be trusted to be the records that were written."
        )

    _emit(payload, lines, as_json=args.json)
    return EXIT_OK if (report.all_passed and intact) else EXIT_FAILED


def cmd_certify(ledger: Any, args: argparse.Namespace) -> int:
    intact = ledger.verify_integrity()
    certificate = ledger.issue_certificate(
        max_monitor_gap_seconds=args.max_monitor_gap_seconds
    )

    # vsl-core refuses to mint a certificate for a failed audit. It does not
    # check integrity, so this does: a certificate over an edited ledger would
    # be exactly the false assurance the whole exercise exists to prevent.
    if certificate is not None and not intact:
        certificate = None
        refusal = "the hash chain does not verify"
    else:
        refusal = "the audit did not fully pass"

    payload: dict[str, Any] = {
        "command": "certify",
        "ledger": str(args.ledger),
        "integrity_verified": intact,
        "certificate_issued": certificate is not None,
    }

    if certificate is None:
        lines = [
            _rule("CERTIFICATION REFUSED"),
            f"  No VerbaCertificate was issued because {refusal}.",
            "  Run `audit` for the failing checks. Nothing here fabricates a",
            "  certificate for a ledger that did not earn one.",
        ]
        _emit(payload, lines, as_json=args.json)
        return EXIT_FAILED

    payload["certificate"] = {
        "issued_at": certificate.issued_at,
        "period_start": certificate.period_start,
        "period_end": certificate.period_end,
        "entries_covered": certificate.entries_covered,
        "checks_passed": list(certificate.audit_report.checks_passed),
    }
    lines = [
        _rule("VERBA CERTIFICATE ISSUED"),
        f"  entries covered   {certificate.entries_covered}",
        f"  checks passed     {', '.join(certificate.audit_report.checks_passed)}",
        f"  hash chain        {'INTACT' if intact else 'BROKEN'}",
        "",
        "  This certifies that the recorded process is structurally governed.",
        "  It does NOT certify that any claim decision was correct.",
    ]
    _emit(payload, lines, as_json=args.json)
    return EXIT_OK


def cmd_summary(ledger: Any, args: argparse.Namespace) -> int:
    entries = list(ledger.store.all_entries())
    by_type = Counter(e.entry_type.value for e in entries)

    denials = [
        e
        for e in entries
        if e.entry_type is LedgerEntryType.PRE_NODE and e.payload.get("denied")
    ]
    insufficient = [
        e
        for e in entries
        if e.entry_type is LedgerEntryType.VERIFICATION
        and e.payload.get(VERIFICATION_RESULT_KEY)
        == VerificationResult.INSUFFICIENT.value
    ]
    terminals = [e for e in entries if e.entry_type is LedgerEntryType.TERMINAL]
    transitions = {
        e.payload.get("claim_id")
        for e in entries
        if e.entry_type is LedgerEntryType.HUMAN_AUTHORISED_TRANSITION
    }
    drift = [
        e
        for e in entries
        if e.entry_type is LedgerEntryType.MONITOR and e.payload.get(DRIFT_DETECTED_KEY)
    ]
    open_terminals = [
        e for e in terminals if e.payload.get("claim_id") not in transitions
    ]
    claims = {e.payload.get("claim_id") for e in entries if e.payload.get("claim_id")}
    invariants = Counter(
        e.payload.get("invariant") for e in terminals if e.payload.get("invariant")
    )

    payload = {
        "command": "summary",
        "ledger": str(args.ledger),
        "specification": f"{CLAIMS_SPECIFICATION.name} v{CLAIMS_SPECIFICATION.version}",
        "decision_threshold": DECISION_THRESHOLD,
        "effective_confidence_floor": round(effective_confidence_floor(), 4),
        "pre_node": AUTOMATION_CONFIDENCE.name,
        "assurance_level": AUTOMATION_CONFIDENCE.assurance_level.value,
        "invariants": [i.name for i in ALL_INVARIANTS],
        "entries": len(entries),
        "entries_by_type": dict(by_type),
        "claims_seen": len(claims),
        "drift_flagged_monitors": len(drift),
        "pre_node_denials": len(denials),
        "invariant_violations": len(insufficient),
        "terminal_states": len(terminals),
        "terminal_states_open": len(open_terminals),
        "human_authorised_transitions": len(transitions),
        "invariants_violated": dict(invariants),
    }

    lines = [
        _rule("GOVERNANCE SUMMARY"),
        f"  specification        {payload['specification']}",
        f"  assurance            {payload['assurance_level']}  "
        "(derived from F1/F2, not asserted -- output-layer control)",
        f"  decision boundary    {DECISION_THRESHOLD}",
        f"  confidence floor     {payload['effective_confidence_floor']}  "
        "(derived: gamma >= 1.1 at that boundary)",
        "",
        f"  claims seen          {len(claims)}",
        f"  ledger entries       {len(entries)}",
    ]
    for entry_type, count in sorted(by_type.items()):
        lines.append(f"    {entry_type:<34} {count}")
    lines += [
        "",
        f"  drift-flagged monitors        {len(drift)}",
        f"  PreNode denials (soft gate)   {len(denials)}",
        f"  Invariant violations (hard)   {len(insufficient)}",
        f"  terminal states entered       {len(terminals)}",
        f"  terminal states still open    {len(open_terminals)}",
        f"  human-authorised transitions  {len(transitions)}",
    ]
    if invariants:
        lines.append("")
        for name, count in invariants.most_common():
            lines.append(f"  violated: {name:<34} {count}")

    _emit(payload, lines, as_json=args.json)
    return EXIT_OK


def cmd_conformance(ledger: Any, args: argparse.Namespace) -> int:
    """Run vsl-core's own adapter conformance suite against the adapter in use.

    There is no `x-verba scan` command: neither `super-semantics-vsl` nor
    `vsl-langgraph` ships a console entry point or a static-analysis module, and
    inventing a "static Γ" figure to fill the gap would be a fabricated number.
    `run_conformance_suite` is the mechanical check the framework does provide,
    and it checks a different thing: that the adapter compiling our gates obeys
    the VSL adapter contract.

    Runtime Gamma -- what `governance.policy.confidence_gamma` computes per claim
    -- is a separate quantity and is reported by `summary`, not here.
    """
    from vsl_core.conformance.suite import run_conformance_suite
    from vsl_langgraph import LangGraphAdapter

    failures = run_conformance_suite(LangGraphAdapter())

    payload = {
        "command": "conformance",
        "adapter": "vsl_langgraph.LangGraphAdapter",
        "conformant": not failures,
        "failures": list(failures),
        "note": (
            "Adapter contract conformance only. It says nothing about whether "
            "this application's ledger describes a governed process -- that is "
            "`audit` -- and nothing about runtime Gamma."
        ),
    }

    lines = [
        _rule("ADAPTER CONFORMANCE"),
        "  adapter           vsl_langgraph.LangGraphAdapter",
        f"  result            {'CONFORMANT' if not failures else 'NON-CONFORMANT'}",
    ]
    for failure in failures:
        lines.append(f"    {failure}")
    lines.append("")
    lines.append("  Checks the adapter contract only. Not the ledger, not Gamma.")

    _emit(payload, lines, as_json=args.json)
    return EXIT_OK if not failures else EXIT_FAILED


COMMANDS = {
    "verify": cmd_verify,
    "audit": cmd_audit,
    "certify": cmd_certify,
    "conformance": cmd_conformance,
    "summary": cmd_summary,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m governance.audit_cli",
        description="Audit the X-Verba/VSL governance ledger.",
    )
    parser.add_argument("command", choices=sorted(COMMANDS))
    parser.add_argument(
        "--ledger",
        default=os.environ.get("VSL_LEDGER_PATH", str(LEDGER_PATH)),
        help="Path to the ledger (default: VSL_LEDGER_PATH or data/ledger.jsonl)",
    )
    parser.add_argument(
        "--max-monitor-gap-seconds",
        type=float,
        default=None,
        help=(
            "Longest acceptable gap between MONITOR entries. Omitted, the "
            "framework SKIPS check 1 and this CLI reports it as not asserted "
            "rather than passed."
        ),
    )
    parser.add_argument("--json", action="store_true", help="Machine-readable output")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    path = Path(args.ledger)

    if not path.exists():
        print(
            f"No ledger at {path}. Nothing has been governed yet, which is not "
            "the same as everything having passed.",
            file=sys.stderr,
        )
        return EXIT_UNUSABLE

    try:
        ledger = build_ledger(path)
        entry_count = sum(1 for _ in ledger.store.all_entries())
    except Exception as exc:  # noqa: BLE001 - the CLI must not traceback at an auditor
        print(f"Could not open the ledger at {path}: {exc}", file=sys.stderr)
        return EXIT_UNUSABLE

    # An empty ledger passes every structural check vacuously. Certifying it
    # would produce a certificate that means nothing, so it is refused here
    # rather than issued and explained away in a footnote.
    if entry_count == 0 and args.command in {"audit", "certify"}:
        print(
            f"The ledger at {path} is empty. An empty ledger satisfies every "
            "check vacuously; it is not evidence of governance. Run the "
            "workflow first.",
            file=sys.stderr,
        )
        return EXIT_UNUSABLE

    return COMMANDS[args.command](ledger, args)


if __name__ == "__main__":
    raise SystemExit(main())
