import argparse
import json
import re
from pathlib import Path
"""
Questo script applica una correzione regex di base a programmi ASP salvati in formato
JSONL, con l'obiettivo di rimuovere o normalizzare costrutti che possono produrre errori
di sintassi durante la validazione con clingo.

Per ogni riga del file di input legge il campo `asp_program`, rimuove eventuali blocchi
markdown, elimina testo successivo alla direttiva `#show answer/1.` e normalizza diversi
operatori provenienti da Prolog o da formati non compatibili con clingo, come `=<`,
`=:=`, `=\=`, `\+`, `//` e alcuni simboli Unicode. Inoltre converte float interi come
`1.0` in interi, semplifica confronti con soglie numeriche molto piccole e normalizza
alcuni atomi racchiusi tra apici singoli.

Se il programma contiene `answer(...)` ma non dichiara la direttiva di output, viene
aggiunto automaticamente `#show answer/1.`. Quando una riga viene modificata, lo script
salva il programma originale nel campo `asp_program_before_syntax_regexfix`, aggiorna
`asp_program` con la versione corretta e registra che il tentativo di correzione è stato
applicato. Alla fine produce un nuovo file JSONL e stampa un riepilogo con il numero di
righe elaborate e modificate.
"""

def fix_code(code: str) -> str:
    if not code:
        return code

    original = code

    code = code.replace("```asp", "")
    code = code.replace("```prolog", "")
    code = code.replace("```", "")

    if "#show answer/1." in code:
        before, _, _ = code.partition("#show answer/1.")
        code = before.rstrip() + "\n#show answer/1."

    code = code.replace("=<", "<=")
    code = code.replace("=:=", "=")
    code = code.replace(" =\\= ", " != ")
    code = code.replace("\\+", "not ")

    code = code.replace("//", "/")

    code = code.replace("≤", "<=")
    code = code.replace("≥", ">=")
    code = code.replace("≠", "!=")

    code = re.sub(r"\b(-?\d+)\.0\b", r"\1", code)

    code = re.sub(r"\b([A-Z][A-Za-z0-9_]*)\s*<\s*0\.0+\d+\b", r"\1 = 0", code)
    code = re.sub(r"\b([A-Z][A-Za-z0-9_]*)\s*<\s*1e-\d+\b", r"\1 = 0", code)
    code = re.sub(r"\b([A-Z][A-Za-z0-9_]*)\s*<=\s*0\.0+\d+\b", r"\1 = 0", code)

    def single_quote_atom(m):
        value = m.group(1)
        if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", value):
            return value.lower()
        return '"' + value + '"'

    code = re.sub(r"'([^']+)'", single_quote_atom, code)

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
            old = row.get("asp_program") or ""
            new = fix_code(old)

            if new != old:
                row["asp_program_before_syntax_regexfix"] = old
                row["syntax_regexfix_attempted"] = True
                row["asp_program"] = new
                changed += 1
            else:
                row["syntax_regexfix_attempted"] = False

            out.write(json.dumps(row, ensure_ascii=False) + "\n")
            total += 1

    print("File creato:", args.output)
    print("Righe:", total)
    print("Modificate:", changed)


if __name__ == "__main__":
    main()
