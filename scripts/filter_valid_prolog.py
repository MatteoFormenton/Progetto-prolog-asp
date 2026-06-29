"""
Filtro i prolog validi 
"""

from __future__ import annotations
import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
INPUT_FILE = PROJECT_ROOT / "data" / "prolog_checked.jsonl"
OUTPUT_FILE = PROJECT_ROOT / "data" / "prolog_for_asp.jsonl"

def main():
    if not INPUT_FILE.exists():
        raise FileNotFoundError(f"File non trovato {INPUT_FILE}")
    

    total_rows = 0
    valid_rows = 0
    discarded_rows = 0

    with INPUT_FILE.open("r", encoding="utf-8") as input_file:
        with OUTPUT_FILE.open("w", encoding="utf-8") as output_file:
            for line in input_file:
                if not line.strip():
                    continue

                total_rows += 1
                row = json.loads(line)

                if row.get("prolog_is_correct") is not True:
                    discarded_rows += 1
                    continue

                clean_row = {
                    "id": row.get("id"),
                    "input": row["input"],
                    "prolog_program": row["prolog_program"],
                    "prolog_query": row["prolog_query"],
                    "answer": row["answer"],
                }

                output_file.write(json.dumps(clean_row, ensure_ascii=False) + "\n")
                valid_rows += 1
    print(f"File letto: {INPUT_FILE}")
    print(f"File creato: {OUTPUT_FILE}")
    print(f"Righe totali: {total_rows}")
    print(f"Righe valide: {valid_rows}")
    print(f"Righe scartate: {discarded_rows}")

if __name__ == "__main__":
    main()