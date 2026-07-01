"""Crea il dataset finale richiesto dalla consegna."""

from __future__ import annotations

import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]

INPUT_FILE = PROJECT_ROOT / "data" / "asp_checked.jsonl"
OUTPUT_FILE = PROJECT_ROOT / "data" / "final_dataset.jsonl"
REPORT_FILE = PROJECT_ROOT / "outputs" / "final_dataset_report.txt"


FINAL_FIELDS = [
    "input",
    "prolog_program",
    "prolog_query",
    "asp_program",
]


def main() -> None:
    if not INPUT_FILE.exists():
        raise FileNotFoundError(f"File non trovato: {INPUT_FILE}")

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)

    total = 0
    included = 0
    discarded = 0

    with INPUT_FILE.open("r", encoding="utf-8") as input_file:
        with OUTPUT_FILE.open("w", encoding="utf-8") as output_file:
            for line in input_file:
                if not line.strip():
                    continue

                total += 1
                row = json.loads(line)

                if row.get("asp_is_correct") is not True:
                    discarded += 1
                    continue

                final_row = {
                    field: row.get(field, "")
                    for field in FINAL_FIELDS
                }

                output_file.write(json.dumps(final_row, ensure_ascii=False) + "\n")
                included += 1

    report = (
        "Final dataset report\n"
        f"Input file: {INPUT_FILE}\n"
        f"Output file: {OUTPUT_FILE}\n"
        f"Total checked examples: {total}\n"
        f"Included valid examples: {included}\n"
        f"Discarded invalid examples: {discarded}\n"
        "\n"
        "Final JSONL fields:\n"
        "- input\n"
        "- prolog_program\n"
        "- prolog_query\n"
        "- asp_program\n"
    )

    REPORT_FILE.write_text(report, encoding="utf-8")

    print(report)


if __name__ == "__main__":
    main()
