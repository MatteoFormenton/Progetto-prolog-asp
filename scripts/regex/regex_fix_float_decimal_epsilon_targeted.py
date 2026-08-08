import argparse
import json
import re
from pathlib import Path

"""
Questo script applica una correzione automatica a programmi ASP che contengono valori
decimali, notazione scientifica, confronti con epsilon e alcune funzioni aritmetiche non
direttamente compatibili con clingo.

Per ogni riga di un file JSONL legge il campo `asp_program`, rimuove eventuale testo
naturale presente prima del codice ASP e normalizza diversi operatori provenienti da Prolog
o da formati non accettati da clingo, come `//`, `div`, `mod`, `=\=`, `=:=`, `=<` e
`#showsig`. Le soglie numeriche molto piccole usate nei confronti vengono trasformate in
uguaglianze a zero, mentre i valori decimali e in notazione scientifica vengono convertiti
in interi tramite arrotondamento.

Lo script semplifica anche alcune forme di arrotondamento, come `round(...)`, `#floor(...)`
e `int(... + 0.5)`, trasformandole in assegnazioni più semplici. Inoltre, quando trova
assegnazioni del tipo `X = abs(E)` all'interno del body di una regola, espande la regola
in due casi distinti: uno per `E >= 0` e uno per `E < 0`.

Se il programma contiene `answer(...)` ma non include la direttiva di output, aggiunge
automaticamente `#show answer/1.`. Quando il codice viene modificato, la versione originale
viene salvata nel campo `asp_program_before_float_decimal_fix`, mentre `asp_program` viene
aggiornato con la versione corretta. Alla fine produce un nuovo file JSONL e stampa un
riepilogo con il numero di righe elaborate, quelle modificate e gli eventuali programmi in
cui restano ancora decimali, notazione scientifica, funzioni di arrotondamento, `#floor` o
`abs(...)`.
"""

SCI_RE = re.compile(r"\b\d+(?:\.\d+)?e-?\d+\b", re.I)
DEC_RE = re.compile(r"\b\d+\.\d+\b")


def split_rules(code: str):
    rules = []
    cur = []
    in_str = False
    esc = False

    for i, ch in enumerate(code):
        cur.append(ch)

        if ch == '"' and not esc:
            in_str = not in_str

        esc = ch == "\\" and not esc
        if ch != "\\":
            esc = False

        if ch == "." and not in_str:
            prev = code[i - 1] if i > 0 else ""
            nxt = code[i + 1] if i + 1 < len(code) else ""

            if prev == "." or nxt == ".":
                continue
            if prev.isdigit() and nxt.isdigit():
                continue

            rules.append("".join(cur).strip())
            cur = []

    rest = "".join(cur).strip()
    if rest:
        rules.append(rest)

    return [r for r in rules if r.strip()]


def split_top_level(text: str, sep=","):
    parts = []
    cur = []
    depth_par = 0
    depth_brace = 0
    depth_brack = 0
    in_str = False
    esc = False

    for ch in text:
        if ch == '"' and not esc:
            in_str = not in_str

        if not in_str:
            if ch == "(":
                depth_par += 1
            elif ch == ")":
                depth_par -= 1
            elif ch == "{":
                depth_brace += 1
            elif ch == "}":
                depth_brace -= 1
            elif ch == "[":
                depth_brack += 1
            elif ch == "]":
                depth_brack -= 1
            elif (
                ch == sep
                and depth_par == 0
                and depth_brace == 0
                and depth_brack == 0
            ):
                parts.append("".join(cur).strip())
                cur = []
                esc = False
                continue

        cur.append(ch)

        esc = ch == "\\" and not esc
        if ch != "\\":
            esc = False

    last = "".join(cur).strip()
    if last or parts:
        parts.append(last)

    return parts


def decimal_to_int_token(match):
    s = match.group(0)

    try:
        x = float(s)
    except Exception:
        return s

    return str(int(round(x)))


def sci_to_int_token(match):
    s = match.group(0)

    try:
        x = float(s)
    except Exception:
        return s

    return str(int(round(x)))


def fix_small_epsilon_comparisons(code):
    eps = r"(?:0\.0+\d+|1e-\d+|1E-\d+)"

    code = re.sub(
        rf"\b([A-Z][A-Za-z0-9_]*)\s*<\s*{eps}",
        r"\1 = 0",
        code,
    )

    code = re.sub(
        rf"\b([A-Z][A-Za-z0-9_]*)\s*<=\s*{eps}",
        r"\1 = 0",
        code,
    )

    return code


def fix_round_floor_int(code):

    code = re.sub(
        r"\b([A-Z][A-Za-z0-9_]*)\s*=\s*#floor\s*\(\s*([A-Z][A-Za-z0-9_]*)\s*\+\s*0\.5\s*\)",
        r"\1 = \2",
        code,
    )


    code = re.sub(
        r"\b([A-Z][A-Za-z0-9_]*)\s*=\s*int\s*\(\s*([A-Z][A-Za-z0-9_]*)\s*\+\s*0\.5\s*\)",
        r"\1 = \2",
        code,
    )


    code = re.sub(
        r"\b([A-Z][A-Za-z0-9_]*)\s*=\s*round\s*\(\s*([A-Z][A-Za-z0-9_]*)\s*\)",
        r"\1 = \2",
        code,
    )

    code = re.sub(
        r"\b([A-Z][A-Za-z0-9_]*)\s*=\s*#floor\s*\(\s*([A-Z][A-Za-z0-9_]*)\s*\)",
        r"\1 = \2",
        code,
    )

    return code


def fix_ops(code):
    code = code.replace("//", "/")
    code = re.sub(r"\bdiv\b", "/", code)
    code = re.sub(r"\bmod\b", r"\\", code)
    code = code.replace("=\\=", "!=")
    code = code.replace("=:=", "=")
    code = code.replace("=<", "<=")
    code = code.replace("#showsig", "#show")
    return code


def fix_decimal_tokens(code):
    code = SCI_RE.sub(sci_to_int_token, code)
    code = DEC_RE.sub(decimal_to_int_token, code)
    return code


def expand_abs_assignment_rule(rule):
    if ":-" not in rule or "abs(" not in rule:
        return [rule]

    head, body = rule.split(":-", 1)

    body = body.strip()
    if body.endswith("."):
        body = body[:-1].strip()

    items = split_top_level(body, ",")

    for i, item in enumerate(items):
        m = re.match(r"^([A-Z][A-Za-z0-9_]*)\s*=\s*abs\s*\((.+)\)$", item.strip())
        if not m:
            continue

        var = m.group(1)
        expr = m.group(2).strip()

        items_pos = items[:i] + [f"{expr} >= 0", f"{var} = {expr}"] + items[i + 1:]
        items_neg = items[:i] + [f"{expr} < 0", f"{var} = -({expr})"] + items[i + 1:]

        body_pos = ",\n    ".join(x.strip() for x in items_pos if x.strip())
        body_neg = ",\n    ".join(x.strip() for x in items_neg if x.strip())

        return [
            head.rstrip() + " :-\n    " + body_pos + ".",
            head.rstrip() + " :-\n    " + body_neg + ".",
        ]

    return [rule]


def expand_abs_assignments(code):
    rules = split_rules(code)
    out = []

    for rule in rules:
        out.extend(expand_abs_assignment_rule(rule))

    return "\n\n".join(out)


def remove_dirty_natural_language_prefix(code):
    lines = code.splitlines()

    for i, line in enumerate(lines):
        s = line.strip()

        if not s:
            continue

        if re.match(r"^[a-z][a-zA-Z0-9_]*\s*\(", s):
            return "\n".join(lines[i:])

        if s.startswith("#show"):
            return "\n".join(lines[i:])

    return code


def fix_code(code):
    old = code or ""
    new = old

    new = remove_dirty_natural_language_prefix(new)
    new = fix_small_epsilon_comparisons(new)
    new = fix_round_floor_int(new)
    new = fix_ops(new)
    new = expand_abs_assignments(new)
    new = fix_decimal_tokens(new)

    if "answer(" in new and "#show answer/1." not in new:
        new = new.rstrip() + "\n#show answer/1."

    return new.strip(), new.strip() != old.strip()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    total = 0
    changed = 0
    still_decimal = 0
    still_sci = 0
    still_round_func = 0
    still_floor = 0
    still_abs_func = 0

    with args.input.open("r", encoding="utf-8") as f, args.output.open("w", encoding="utf-8") as out:
        for line in f:
            if not line.strip():
                continue

            row = json.loads(line)
            old = row.get("asp_program") or ""
            new, did_change = fix_code(old)

            if did_change:
                row["asp_program_before_float_decimal_fix"] = old
                row["float_decimal_epsilon_fix_attempted"] = True
                row["asp_program"] = new
                changed += 1
            else:
                row["float_decimal_epsilon_fix_attempted"] = False

            if DEC_RE.search(new):
                still_decimal += 1
            if SCI_RE.search(new):
                still_sci += 1
            if re.search(r"=\s*round\s*\(", new):
                still_round_func += 1
            if "#floor" in new:
                still_floor += 1
            if "abs(" in new:
                still_abs_func += 1

            out.write(json.dumps(row, ensure_ascii=False) + "\n")
            total += 1

    print("File creato:", args.output)
    print("Righe:", total)
    print("Modificate:", changed)
    print("Ancora decimal:", still_decimal)
    print("Ancora scientific:", still_sci)
    print("Ancora = round(...):", still_round_func)
    print("Ancora #floor:", still_floor)
    print("Ancora abs(...):", still_abs_func)


if __name__ == "__main__":
    main()
