"""Golden-set evaluation for natural-language commands.

    uv run python -m evals.run_evals            # offline heuristic parser (free, deterministic; CI gate)
    uv run python -m evals.run_evals --claude   # also score Claude (needs ANTHROPIC_API_KEY; costs a few cents)

Scores each engine on: action accuracy, attendees (exact set), duration, date window, time of day,
and full-case exact match over the fields each case specifies. Writes evals/reports/latest.md.
Exit code 1 if offline action accuracy < 0.90 (regression gate).
Every AI failure found in user testing should be added here as a new case (docs/05).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

from app.ai import heuristic
from app.ai.schemas import ParsedCommand
from app.models import Person
from app.seed.generator import PEOPLE

HERE = Path(__file__).parent
TODAY = date(2026, 11, 25)  # fixed reference date (Wednesday) so the golden set never drifts
FIELDS = ("action", "attendees", "duration", "window", "time_of_day")


def load_cases() -> list[dict[str, Any]]:
    return [json.loads(line) for line in (HERE / "golden_commands.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]


def _people() -> list[Person]:
    return [Person(**{**p, "email": f"{p['id']}@example.com"}) for p in PEOPLE]


def _canon(names: list[str], people: list[Person]) -> list[str]:
    out = []
    for n in names:
        low = n.lower()
        match = next((p.name for p in people if low in (p.name.lower(), p.first_name.lower())), n)
        out.append(match)
    return sorted(out)


def compare(case: dict[str, Any], p: ParsedCommand, people: list[Person]) -> dict[str, bool]:
    got = {
        "action": p.action,
        "attendees": _canon(p.attendees, people),
        "duration": p.duration_minutes if p.action != "block_focus" else (int(p.focus_hours * 60) if p.focus_hours else p.duration_minutes),
        "window": [p.window.start_date, p.window.end_date] if p.window else None,
        "time_of_day": p.time_of_day,
    }
    res: dict[str, bool] = {}
    for f in FIELDS:
        if f not in case:
            continue
        expected = sorted(case[f]) if f == "attendees" else case[f]
        res[f] = got[f] == expected
    return res


def score(engine: str, parse_fn: Any, cases: list[dict[str, Any]], people: list[Person]) -> dict[str, Any]:
    totals: dict[str, list[int]] = {f: [0, 0] for f in FIELDS}
    exact = 0
    failures = []
    for case in cases:
        try:
            parsed = parse_fn(case["text"])
            res = compare(case, parsed, people)
        except Exception as e:  # count crashes as failures, keep going
            res = {f: False for f in FIELDS if f in case}
            parsed = None
            failures.append({"id": case["id"], "text": case["text"], "error": str(e)})
        for f, ok in res.items():
            totals[f][0] += int(ok)
            totals[f][1] += 1
        if all(res.values()):
            exact += 1
        elif parsed is not None:
            failures.append({"id": case["id"], "text": case["text"], "wrong": [f for f, ok in res.items() if not ok],
                             "got": parsed.model_dump(exclude_none=True)})
    acc = {f: (round(c / n, 3) if n else None) for f, (c, n) in totals.items()}
    return {"engine": engine, "n": len(cases), "exact_match": round(exact / len(cases), 3), "field_accuracy": acc,
            "support": {f: n for f, (_, n) in totals.items()}, "failures": failures}


def report(results: list[dict[str, Any]]) -> str:
    lines = ["# NL command evaluation", "", f"Reference date: {TODAY} (Wednesday). Golden set: `evals/golden_commands.jsonl`.", ""]
    lines.append("| Engine | Cases | Exact match | " + " | ".join(FIELDS) + " |")
    lines.append("|---|---|---|" + "---|" * len(FIELDS))
    for r in results:
        cells = [f"{r['field_accuracy'][f]:.0%} (n={r['support'][f]})" if r["field_accuracy"][f] is not None else "-" for f in FIELDS]
        lines.append(f"| {r['engine']} | {r['n']} | {r['exact_match']:.0%} | " + " | ".join(cells) + " |")
    for r in results:
        lines += ["", f"## Failures - {r['engine']} ({len(r['failures'])})", ""]
        for f in r["failures"]:
            lines.append(f"- `{f['id']}` “{f['text']}” → wrong: {', '.join(f.get('wrong', ['error']))}")
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--claude", action="store_true", help="also evaluate Claude (requires credentials)")
    ap.add_argument("--gemini", action="store_true", help="also evaluate Gemini (requires GEMINI_API_KEY)")
    args = ap.parse_args()
    cases = load_cases()
    people = _people()
    results = [score("offline-heuristic", lambda t: heuristic.parse(t, TODAY, people, "maya"), cases, people)]
    if args.claude:
        from app.ai.gateway import ClaudeGateway
        from app.config import get_settings
        from app.services.assistant import PARSE_SYSTEM

        gw = ClaudeGateway(get_settings())
        if not gw.available:
            print("Claude not configured (set ANTHROPIC_API_KEY); skipping.")
        else:
            names = ", ".join(sorted(p.first_name for p in people if p.id != "maya"))

            def claude_parse(text: str) -> ParsedCommand:
                prompt = f"now: {TODAY}T09:00 (Wednesday), user time zone: America/Los_Angeles\ncolleagues (first names): {names}\n<request>{text}</request>"
                return gw.structured(system=PARSE_SYSTEM, prompt=prompt, schema=ParsedCommand, effort="low")[0]

            results.append(score(f"claude ({gw.settings.model})", claude_parse, cases, people))
    if args.gemini:
        from app.ai.gateway import GeminiGateway
        from app.config import get_settings
        from app.services.assistant import PARSE_SYSTEM

        gem = GeminiGateway(get_settings())
        if not gem.available:
            print("Gemini not configured (set GEMINI_API_KEY); skipping.")
        else:
            gnames = ", ".join(sorted(p.first_name for p in people if p.id != "maya"))

            def gemini_parse(text: str) -> ParsedCommand:
                prompt = f"now: {TODAY}T09:00 (Wednesday), user time zone: America/Los_Angeles\ncolleagues (first names): {gnames}\n<request>{text}</request>"
                return gem.structured(system=PARSE_SYSTEM, prompt=prompt, schema=ParsedCommand, effort="low", timeout_s=20)[0]

            results.append(score(f"gemini ({gem.settings.gemini_fast_model})", gemini_parse, cases, people))
    out = report(results)
    (HERE / "reports").mkdir(exist_ok=True)
    (HERE / "reports" / "latest.md").write_text(out, encoding="utf-8")
    for r in results:
        print(f"{r['engine']}: exact={r['exact_match']:.0%} " + " ".join(
            f"{f}={r['field_accuracy'][f]:.0%}" for f in FIELDS if r["field_accuracy"][f] is not None))
    offline = results[0]["field_accuracy"]["action"] or 0
    if offline < 0.90:
        print(f"FAIL: offline action accuracy {offline:.0%} < 90%")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
