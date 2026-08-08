import argparse
import json
import re
from pathlib import Path

"""
Questo script applica una correzione regex minimale e conservativa a programmi ASP
salvati in formato JSONL, con l'obiettivo di rimuovere residui non compatibili con clingo
senza modificare in modo aggressivo la logica del programma.

Per ogni riga del file di input legge il campo `asp_program`, rimuove eventuali delimitatori
markdown, normalizza alcuni operatori Prolog in forme accettate da clingo e taglia il
contenuto successivo alla direttiva `#show answer/1.` quando presente. Durante la pulizia
elimina anche righe tipiche di programmi Prolog non utili in ASP, come `halt.`, chiamate
a `solve`, `write(...)` e `writeln(...)`.

Se il programma contiene `answer(...)` ma non include la direttiva di output, aggiunge
automaticamente `#show answer/1.`. Quando il codice viene modificato, lo script conserva
la versione originale nel campo `asp_program_before_regex_fix_safe`, aggiorna `asp_program`
con la versione corretta e registra che il tentativo di correzione è stato applicato.
Alla fine produce un nuovo file JSONL e stampa un riepilogo con il numero totale di righe
elaborate e modificate.
"""
def fix_asp(code: str) -> str:
    if not code:
        return code

    code = code.strip()

    code = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", code)
    code = re.sub(r"\s*```$", "", code)

    code = code.replace("=<", "<=")
    code = code.replace("=:=", "=")

    if "#show answer/1." in code:
        before, _, _ = code.partition("#show answer/1.")
        code = before.rstrip() + "\n#show answer/1."

    lines = []
    for line in code.splitlines():
        stripped = line.strip()

        if stripped == "halt.":
            continue

        if re.match(r"^:-\s*solve\s*,\s*halt\s*\.\s*$", stripped):
            continue

        if re.match(r"^write\s*\(.*\)\s*\.\s*$", stripped):
            continue

        if re.match(r"^writeln\s*\(.*\)\s*\.\s*$", stripped):
            continue

        if stripped.startswith("```"):
            continue

        lines.append(line)

    code = "\n".join(lines).strip()

    if "answer(" in code and "#show answer/1." not in code:
        code = code.rstrip() + "\n#show answer/1."

    return code.strip()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    total = 0
    changed = 0

    with args.input.open("r", encoding="utf-8") as f, args.output.open("w", encoding="utf-8") as out:
        for line in f:
            if not line.strip():
                continue

            row = json.loads(line)
            old = row.get("asp_program", "")
            new = fix_asp(old)

            if new != old:
                row["asp_program_before_regex_fix_safe"] = old
                row["regex_fix_safe_attempted"] = True
                row["asp_program"] = new
                changed += 1
            else:
                row["regex_fix_safe_attempted"] = False

            out.write(json.dumps(row, ensure_ascii=False) + "\n")
            total += 1

    print("File creato:", args.output)
    print("Righe:", total)
    print("Modificate:", changed)


if __name__ == "__main__":
    main()
