import argparse
import json
import re
from pathlib import Path

"""
Questo script applica una correzione automatica a programmi ASP salvati in formato JSONL.

Per ogni riga del file di input legge il campo `asp_program`, individua eventuali costrutti
condizionali del tipo if-then-else espressi con `->` e `;`, e prova a riscriverli come più
regole ASP separate. Durante la trasformazione gestisce la separazione delle regole, delle
condizioni e degli elementi del body rispettando parentesi, liste, insiemi e stringhe.

Lo script applica anche alcune correzioni meccaniche aggiuntive, come la sostituzione di
piccoli valori epsilon o decimali non gestiti da clingo e la normalizzazione di `#showsig`
in `#show`. Se il programma contiene `answer(...)`, aggiunge inoltre la direttiva
`#show answer/1.` quando assente.

Per ogni esempio modificato salva il programma originale nel campo
`asp_program_before_if_then_else_fix`, aggiorna `asp_program` con la versione corretta e
indica se il tentativo di correzione è stato applicato. Alla fine produce un nuovo file
JSONL e stampa un riepilogo con il numero totale di righe elaborate, quelle modificate e
quelle che contengono ancora il simbolo `->`.
"""
def split_rules(code: str):
    rules = []
    cur = []
    in_str = False
    esc = False

    for i, ch in enumerate(code):
        cur.append(ch)

        if ch == '"' and not esc:
            in_str = not in_str

        esc = (ch == "\\" and not esc)
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


def split_top_level(text: str, sep: str):
    parts = []
    cur = []
    depth_par = 0
    depth_brack = 0
    depth_brace = 0
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
            elif ch == "[":
                depth_brack += 1
            elif ch == "]":
                depth_brack -= 1
            elif ch == "{":
                depth_brace += 1
            elif ch == "}":
                depth_brace -= 1
            elif ch == sep and depth_par == 0 and depth_brack == 0 and depth_brace == 0:
                parts.append("".join(cur).strip())
                cur = []
                esc = False
                continue

        cur.append(ch)

        esc = (ch == "\\" and not esc)
        if ch != "\\":
            esc = False

    last = "".join(cur).strip()
    if last:
        parts.append(last)

    return parts


def find_top_level_arrow(text: str):
    depth_par = 0
    depth_brack = 0
    depth_brace = 0
    in_str = False
    esc = False
    i = 0

    while i < len(text) - 1:
        ch = text[i]

        if ch == '"' and not esc:
            in_str = not in_str

        if not in_str:
            if ch == "(":
                depth_par += 1
            elif ch == ")":
                depth_par -= 1
            elif ch == "[":
                depth_brack += 1
            elif ch == "]":
                depth_brack -= 1
            elif ch == "{":
                depth_brace += 1
            elif ch == "}":
                depth_brace -= 1
            elif (
                ch == "-"
                and text[i + 1] == ">"
                and depth_par == 0
                and depth_brack == 0
                and depth_brace == 0
            ):
                return i

        esc = (ch == "\\" and not esc)
        if ch != "\\":
            esc = False

        i += 1

    return -1


def strip_outer_parens(text: str):
    s = text.strip()

    if not (s.startswith("(") and s.endswith(")")):
        return s

    depth = 0
    in_str = False
    esc = False

    for i, ch in enumerate(s):
        if ch == '"' and not esc:
            in_str = not in_str

        if not in_str:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0 and i != len(s) - 1:
                    return s

        esc = (ch == "\\" and not esc)
        if ch != "\\":
            esc = False

    return s[1:-1].strip()


def invert_simple_condition(cond: str):
    if cond is None:
        return None

    c = cond.strip()

    m = re.match(r"^(.+?)\s*(<=|>=|!=|=|<|>)\s*(.+)$", c)
    if not m:
        return None

    left = m.group(1).strip()
    op = m.group(2)
    right = m.group(3).strip()

    inv = {
        "<": ">=",
        "<=": ">",
        ">": "<=",
        ">=": "<",
        "=": "!=",
        "!=": "=",
    }[op]

    return f"{left} {inv} {right}"


def parse_conditional_item(item: str):
    inner = strip_outer_parens(item)

    if "->" not in inner:
        return None

    raw_branches = split_top_level(inner, ";")
    branches = []
    previous_simple_conds = []

    for raw in raw_branches:
        pos = find_top_level_arrow(raw)

        if pos >= 0:
            cond_text = raw[:pos].strip()
            action_text = raw[pos + 2:].strip()

            conds = split_top_level(cond_text, ",")
            actions = split_top_level(action_text, ",")

            prefix_inverses = []
            for pc in previous_simple_conds:
                inv = invert_simple_condition(pc)
                if inv:
                    prefix_inverses.append(inv)

            branches.append(prefix_inverses + conds + actions)

            if len(conds) == 1 and invert_simple_condition(conds[0]):
                previous_simple_conds.append(conds[0])
            else:
                previous_simple_conds.append(None)

        else:
            actions = split_top_level(raw, ",")

            prefix_inverses = []
            for pc in previous_simple_conds:
                inv = invert_simple_condition(pc)
                if inv:
                    prefix_inverses.append(inv)

            branches.append(prefix_inverses + actions)

    if len(branches) < 2:
        return None

    return branches


def expand_rule_once(rule: str):
    if ":-" not in rule or "->" not in rule:
        return [rule]

    head, body = rule.split(":-", 1)

    body = body.strip()
    if body.endswith("."):
        body = body[:-1].strip()

    items = split_top_level(body, ",")

    for idx, item in enumerate(items):
        if "->" not in item:
            continue

        branches = parse_conditional_item(item)
        if not branches:
            continue

        new_rules = []

        for branch_items in branches:
            new_items = items[:idx] + branch_items + items[idx + 1:]
            new_body = ",\n    ".join(x.strip() for x in new_items if x.strip())

            new_rules.append(head.rstrip() + " :-\n    " + new_body + ".")

        return new_rules

    return [rule]


def expand_rule(rule: str):
    pending = [rule]

    for _ in range(5):
        next_rules = []
        changed = False

        for r in pending:
            expanded = expand_rule_once(r)
            next_rules.extend(expanded)

            if len(expanded) != 1 or expanded[0] != r:
                changed = True

        pending = next_rules

        if not changed:
            break

    return pending


def cleanup_code(code: str):

    replacements = {
        "1e-12": "0",
        "1e-9": "0",
        "1e-6": "0",
        "1e-3": "0",
        "0.0001": "0",
        "0.001": "0",
    }

    for old, new in replacements.items():
        code = code.replace(old, new)

    code = code.replace("#showsig", "#show")

    return code


def fix_code(code: str):
    if not code:
        return code, False

    original = code
    code = cleanup_code(code)

    rules = split_rules(code)

    out_rules = []

    for rule in rules:
        expanded = expand_rule(rule)
        out_rules.extend(expanded)

    fixed = "\n\n".join(out_rules)

    if "answer(" in fixed and "#show answer/1." not in fixed:
        fixed = fixed.rstrip() + "\n#show answer/1."

    fixed = fixed.strip()

    return fixed, fixed != original.strip()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    total = 0
    changed = 0
    still_arrow = 0

    with args.input.open("r", encoding="utf-8") as f, args.output.open("w", encoding="utf-8") as out:
        for line in f:
            if not line.strip():
                continue

            row = json.loads(line)
            old = row.get("asp_program") or ""

            new, did_change = fix_code(old)

            if did_change:
                row["asp_program_before_if_then_else_fix"] = old
                row["if_then_else_fix_attempted"] = True
                row["asp_program"] = new
                changed += 1
            else:
                row["if_then_else_fix_attempted"] = False

            if "->" in new:
                still_arrow += 1

            out.write(json.dumps(row, ensure_ascii=False) + "\n")
            total += 1

    print("File creato:", args.output)
    print("Righe:", total)
    print("Modificate:", changed)
    print("Ancora con ->:", still_arrow)


if __name__ == "__main__":
    main()
