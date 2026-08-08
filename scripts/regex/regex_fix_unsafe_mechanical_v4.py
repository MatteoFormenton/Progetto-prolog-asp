import argparse
import json
import re
from pathlib import Path

"""
Questo script applica una correzione meccanica a programmi ASP che producono errori di
variabili unsafe durante la validazione con clingo.

Per ogni riga di un file JSONL legge il programma ASP dal campo `asp_program` e analizza
il messaggio di errore contenuto in `asp_error` per individuare le variabili segnalate
come unsafe. A partire dal codice ASP costruisce poi un predicato ausiliario `safe_num/1`,
ricavando eventuali domini numerici già presenti nel programma e aggiungendo un intervallo
di fallback limitato.

La trasformazione rende sicure le variabili non vincolate aggiungendo condizioni
`safe_num(...)` nei body delle regole, corregge fatti con variabili nella testa,
sostituisce gli underscore anonimi presenti negli head con variabili esplicite e gestisce
un caso ricorrente legato al pattern `exists_smaller`, trasformandolo in una forma più
sicura per ASP.

Se il programma viene modificato, lo script conserva la versione originale nel campo
`asp_program_before_unsafe_mechanical_v4`, aggiorna `asp_program` con la versione corretta
e registra le variabili unsafe individuate. Alla fine produce un nuovo file JSONL e stampa
un riepilogo con il numero totale di righe elaborate e il numero di programmi modificati.
"""

VAR_RE = re.compile(r"\b[A-Z][A-Za-z0-9_]*\b")


def extract_unsafe_vars(err: str):
    vars_ = []
    for v in re.findall(r"note:\s+'([^']+)'\s+is unsafe", err or ""):
        if v.startswith("#"):
            continue
        if v not in vars_:
            vars_.append(v)
    return vars_


def collect_numeric_unary_domains(code: str):
    preds = set()

    for line in code.splitlines():
        s = line.strip()
        if not s or s.startswith("#") or ":-" in s:
            continue

        m = re.match(r"^([a-z][A-Za-z0-9_]*)\((-?\d+)\.\.(-?\d+)\)\.$", s)
        if m:
            preds.add(m.group(1))
            continue

        m = re.match(r"^([a-z][A-Za-z0-9_]*)\((-?\d+)\)\.$", s)
        if m:
            preds.add(m.group(1))
            continue

    return sorted(preds)


def build_safe_num_block(code: str):
    preds = collect_numeric_unary_domains(code)

    lines = []

    for p in preds:
        if p == "safe_num":
            continue
        lines.append(f"safe_num(V) :- {p}(V).")

    lines.append("safe_num(-200..200).")

    block = "\n".join(lines)

    if "safe_num(" in code:
        return code

    return block + "\n\n" + code


def split_rules(code: str):
    rules = []
    cur = []

    for line in code.splitlines():
        cur.append(line)
        if line.strip().endswith("."):
            rules.append("\n".join(cur))
            cur = []

    if cur:
        rules.append("\n".join(cur))

    return rules


def normalize_anonymous_head(rule: str):
    """
    pow(_,0,1). is unsafe.
    Convert _ in heads to real variables Anon1, Anon2.
    """
    if ":-" in rule:
        head, body = rule.split(":-", 1)
        suffix = ":-" + body
    else:
        head = rule
        suffix = ""

    counter = 0

    def repl(m):
        nonlocal counter
        text = m.group(0)
        parts = text[text.find("(")+1:-1].split(",")
        new_parts = []

        for p in parts:
            q = p.strip()
            if q == "_":
                counter += 1
                new_parts.append(f"Anon{counter}")
            else:
                new_parts.append(q)

        return text[:text.find("(")+1] + ",".join(new_parts) + ")"

    new_head = re.sub(r"\b[a-z][A-Za-z0-9_]*\([^()]*\)", repl, head)

    return new_head + suffix


def vars_in_rule(rule: str):
    return sorted(set(VAR_RE.findall(rule)))


def vars_in_positive_atoms(body: str):
    safe = set()

    for m in re.finditer(r"\b([a-z][A-Za-z0-9_]*)\(([^()]*)\)", body):
        start = m.start()
        prefix = body[max(0, start - 6):start].lower()
        if "not" in prefix:
            continue

        args = [x.strip() for x in m.group(2).split(",")]
        for a in args:
            if re.fullmatch(r"[A-Z][A-Za-z0-9_]*", a):
                safe.add(a)

    return safe


def fix_unique_exists_smaller(code: str):
    """
    Pattern comune:
      unique_ks(K) :- valid_k(_, _, K), not exists_smaller(K, K2).
      exists_smaller(K, K2) :- valid_k(_,_,K), valid_k(_,_,K2), K2 < K.

    K2 in negazione è unsafe. Trasformiamo exists_smaller/2 in exists_smaller/1.
    """
    lines = code.splitlines()
    out = []

    for line in lines:
        s = line.strip()

        m = re.match(r"^(unique_[A-Za-z0-9_]*\(([^()]+)\)\s*:-\s*.*),\s*not\s+exists_smaller\(\s*([^,\s]+)\s*,\s*[^()]+\)\.$", s)
        if m:
            out.append(line.replace(re.search(r",\s*not\s+exists_smaller\([^()]+\)\.", line).group(0), f", not exists_smaller({m.group(3)})."))
            continue

        m = re.match(r"^exists_smaller\(\s*([^,\s]+)\s*,\s*([^,\s]+)\s*\)\s*:-\s*(.*)\.$", s)
        if m:
            k = m.group(1)
            body = m.group(3)
            out.append(f"exists_smaller({k}) :- {body}.")
            continue

        out.append(line)

    return "\n".join(out)


def fix_rule(rule: str, unsafe_vars):
    rule = normalize_anonymous_head(rule)

    stripped = rule.strip()

    if not stripped or stripped.startswith("#"):
        return rule

    if ":-" not in rule:
        vars_ = vars_in_rule(rule)
        if not vars_:
            return rule

        body = ", ".join(f"safe_num({v})" for v in vars_)
        return stripped[:-1] + f" :- {body}."

    head, body = rule.split(":-", 1)
    body_clean = body.strip()
    if body_clean.endswith("."):
        body_clean = body_clean[:-1].strip()

    already_safe = vars_in_positive_atoms(body_clean)

    additions = []

    for v in unsafe_vars:
        if v not in rule:
            continue
        if v in already_safe:
            continue
        add = f"safe_num({v})"
        if add not in body_clean and add not in additions:
            additions.append(add)

    if not additions:
        return rule

    new_body = ",\n    ".join(additions + [body_clean])
    return head.rstrip() + " :-\n    " + new_body + "."


def fix_code(code: str, unsafe_vars):
    if not code:
        return code

    code = build_safe_num_block(code)
    code = fix_unique_exists_smaller(code)

    rules = split_rules(code)
    fixed_rules = [fix_rule(r, unsafe_vars) for r in rules]

    fixed = "\n".join(fixed_rules)

    if "answer(" in fixed and "#show answer/1." not in fixed:
        fixed = fixed.rstrip() + "\n#show answer/1."

    return fixed.strip()


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
            unsafe_vars = extract_unsafe_vars(row.get("asp_error") or "")

            new = fix_code(old, unsafe_vars)

            if new != old:
                row["asp_program_before_unsafe_mechanical_v4"] = old
                row["unsafe_mechanical_v4_attempted"] = True
                row["unsafe_mechanical_v4_vars"] = unsafe_vars
                row["asp_program"] = new
                changed += 1
            else:
                row["unsafe_mechanical_v4_attempted"] = False
                row["unsafe_mechanical_v4_vars"] = unsafe_vars

            out.write(json.dumps(row, ensure_ascii=False) + "\n")
            total += 1

    print("File creato:", args.output)
    print("Righe:", total)
    print("Modificate:", changed)


if __name__ == "__main__":
    main()
