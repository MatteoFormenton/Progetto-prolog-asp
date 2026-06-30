from __future__ import annotations

import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
INPUT_FILE = PROJECT_ROOT / "data" / "asp_checked.jsonl"


def main() -> None:
    if not INPUT_FILE.exists():
        raise FileNotFoundError(f"File non trovato: {INPUT_FILE}")

    failures = 0

    with INPUT_FILE.open("r", encoding="utf-8") as input_file:
        for line in input_file:
            if not line.strip():
                continue

            row = json.loads(line)

            if row.get("asp_is_correct") is True:
                continue

            failures += 1

            print("=" * 80)
            print(f"ID: {row.get('id')}")
            print()
            print("INPUT:")
            print(row.get("input", "")[:500])
            print()
            print("ANSWER ATTESA:")
            print(repr(row.get("answer", "")))
            print()
            print("OUTPUT ASP:")
            print(repr(row.get("asp_output", "")))
            print()
            print("ERRORE ASP / CLINGO:")
            print(row.get("asp_error", "")[:1500])
            print()
            print("ASP PROGRAM:")
            print(row.get("asp_program", "")[:2500])
            print()

    print("=" * 80)
    print(f"Totale esempi ASP non corretti: {failures}")


if __name__ == "__main__":
    main()