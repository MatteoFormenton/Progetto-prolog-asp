"""
Script per visualizzare più facilmente quali esempi sono
problematici e capire dove il programma Prolog sbaglia.
"""

from __future__ import annotations
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
INPUT_FILE = PROJECT_ROOT / "data" / "prolog_checked.jsonl"


def main ():

    """
    Leggo il file con i risultati Prolog e stampo solo gli esempi
    che non sono stati classificati come corretti.
    """
    if not INPUT_FILE.exists():
        raise FileNotFoundError(f"File non trovato: {INPUT_FILE}")
    
    failures = 0 

    with INPUT_FILE.open("r", encoding="utf-8") as input_file:
        for line in input_file:
            if not line.strip():
                continue

            row = json.loads(line)

            if row.get("prolog_is_correct") is True:
                continue

            failures += 1

            # Stampo tutte le informazioni utili per capire il problema.
            print("=" * 80)
            print(f"ID: {row.get('id')}")
            print()
            print("INPUT:")
            print(row.get("input", "")[:500])
            print()
            print("PROLOG QUERY:")
            print(row.get("prolog_query", ""))
            print()
            print("ANSWER ATTESA:")
            print(repr(row.get("answer", "")))
            print()
            print("OUTPUT PROLOG:")
            print(repr(row.get("prolog_output", "")))
            print()
            print("ERRORE PROLOG:")
            print(row.get("prolog_error", "")[:1000])
            print()            


    print("=" * 80)
    print(f"Totale esempi non corretti: {failures}")


if __name__ == "__main__":
    main()            