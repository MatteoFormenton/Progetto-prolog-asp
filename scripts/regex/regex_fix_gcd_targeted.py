import argparse
import json
import re
from pathlib import Path
"""
Questo script applica una correzione mirata a programmi ASP che contengono predicati
relativi al massimo comune divisore, come `gcd/3` o varianti con nome simile.

Per ogni riga di un file JSONL legge il campo `asp_program`, normalizza alcuni operatori
non compatibili con clingo e individua le chiamate a predicati `gcd` con tre argomenti.
Le eventuali definizioni originali di questi predicati vengono rimosse e sostituite con
un template ASP controllato, basato su un dominio numerico limitato tramite `gcd_bound/1`
e su un predicato ausiliario `gcd_abs_val/2` per gestire valori assoluti e numeri negativi.

Lo script gestisce anche chiamate del tipo `gcd(abs(...), ..., ...)`, introducendo variabili
ausiliarie e condizioni aggiuntive nel body della regola. Il bound numerico viene stimato
a partire dalle costanti presenti nel programma e può essere configurato tramite argomenti
da riga di comando, in modo da evitare grounding eccessivamente grandi.

Quando il programma viene modificato, la versione originale viene salvata nel campo
`asp_program_before_gcd_fix`, mentre `asp_program` viene aggiornato con la versione corretta.
Alla fine produce un nuovo file JSONL e stampa un riepilogo con il numero di righe elaborate,
quelle modificate, i programmi in cui è stato aggiunto il template `gcd`, le regole originali
rimosse e gli eventuali casi in cui restano ancora chiamate `gcd(abs(...), ...)`.
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


def find_matching_paren(text, open_pos):
    depth = 0
    in_str = False
    esc = False

    for i in range(open_pos, len(text)):
        ch = text[i]

        if ch == '"' and not esc:
            in_str = not in_str

        if not in_str:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    return i

        esc = ch == "\\" and not esc
        if ch != "\\":
            esc = False

    return -1


def parse_call(text):
    s = text.strip()
    m = re.match(r"^([A-Za-z_#][A-Za-z0-9_#]*)\s*\(", s)

    if not m:
        return None

    name = m.group(1)
    open_pos = m.end() - 1
    close_pos = find_matching_paren(s, open_pos)

    if close_pos != len(s) - 1:
        return None

    args = split_top_level(s[open_pos + 1:close_pos], ",")

    return name, args


def iter_gcd_calls(code):
    for m in re.finditer(r"\b(gcd[A-Za-z0-9_]*)\s*\(", code):
        name = m.group(1)
        open_pos = m.end() - 1
        close_pos = find_matching_paren(code, open_pos)

        if close_pos < 0:
            continue

        args = split_top_level(code[open_pos + 1:close_pos], ",")

        if len(args) == 3:
            yield name, args


def is_gcd3_head(rule):
    head = rule.split(":-", 1)[0].strip()
    parsed = parse_call(head)

    if not parsed:
        return False

    name, args = parsed

    return name.startswith("gcd") and len(args) == 3


def is_abs_call(text):
    s = text.strip()

    if s.startswith("#abs("):
        open_pos = s.find("(")
        close_pos = find_matching_paren(s, open_pos)
        if close_pos == len(s) - 1:
            return s[open_pos + 1:close_pos].strip()

    if s.startswith("abs("):
        open_pos = s.find("(")
        close_pos = find_matching_paren(s, open_pos)
        if close_pos == len(s) - 1:
            return s[open_pos + 1:close_pos].strip()

    return None


def transform_gcd_abs_calls_in_body(rule):
    if ":-" not in rule:
        return rule

    head, body = rule.split(":-", 1)

    body = body.strip()
    if body.endswith("."):
        body = body[:-1].strip()

    items = split_top_level(body, ",")
    new_items = []
    aux_id = 0

    for item in items:
        parsed = parse_call(item)

        if parsed and parsed[0].startswith("gcd") and len(parsed[1]) == 3:
            name, args = parsed
            fixed_args = []

            for pos, arg in enumerate(args):
                if pos < 2:
                    inner = is_abs_call(arg)

                    if inner is not None:
                        aux_id += 1
                        aux = f"GcdAbsAux{aux_id}"
                        new_items.append(f"gcd_abs_val({inner}, {aux})")
                        fixed_args.append(aux)
                    else:
                        fixed_args.append(arg.strip())
                else:
                    fixed_args.append(arg.strip())

            new_items.append(f"{name}({fixed_args[0]}, {fixed_args[1]}, {fixed_args[2]})")
        else:
            new_items.append(item.strip())

    new_body = ",\n    ".join(x for x in new_items if x)

    return head.rstrip() + " :-\n    " + new_body + "."


def rough_bound(code, default_bound, max_bound, multiplier):
    nums = []

    for m in re.finditer(r"-?\d+", code):
        try:
            nums.append(abs(int(m.group(0))))
        except Exception:
            pass

    mx = max(nums) if nums else default_bound
    bound = max(default_bound, mx * multiplier)
    bound = min(bound, max_bound)
    bound = max(10, bound)

    return int(bound)


def cleanup(code):
    code = code.replace("#showsig", "#show")
    code = code.replace("//", "/")
    code = code.replace("=:=", "=")
    code = code.replace("=\\=", "!=")
    code = code.replace("=<", "<=")

    code = re.sub(r"\bdiv\b", "/", code)

    code = re.sub(
        r"\b([A-Za-z0-9_()]+)\s+mod\s+([A-Za-z0-9_()]+)\b",
        r"\1 \\ \2",
        code,
    )

    code = code.replace("\\(", "mod(")

    return code


def gcd_templates(predicates, bound):
    lines = []

    lines.append(f"gcd_bound(0..{bound}).")
    lines.append(f"gcd_bound(-{bound}..-1).")
    lines.append("")
    lines.append("gcd_abs_val(X,X) :- gcd_bound(X), X >= 0.")
    lines.append("gcd_abs_val(X,Y) :- gcd_bound(X), X < 0, Y = -X.")
    lines.append("")

    for pred in sorted(predicates):
        lines.append(f"{pred}(A,0,G) :- gcd_bound(A), gcd_abs_val(A,G).")
        lines.append(
            f"{pred}(A,B,G) :- "
            f"gcd_bound(A), gcd_bound(B), B != 0, "
            f"gcd_abs_val(B,BB), R = A \\ BB, {pred}(BB,R,G)."
        )
        lines.append("")

    return "\n".join(lines).strip()


def fix_code(code, default_bound, max_bound, multiplier):
    old = code or ""
    new = cleanup(old)

    predicates = {
        name
        for name, args in iter_gcd_calls(new)
        if len(args) == 3
    }

    if not predicates:
        return new.strip(), new.strip() != old.strip(), 0, 0

    bound = rough_bound(new, default_bound, max_bound, multiplier)

    rules = split_rules(new)
    kept = []

    removed_gcd_rules = 0

    for rule in rules:
        if is_gcd3_head(rule):
            removed_gcd_rules += 1
            continue

        kept.append(transform_gcd_abs_calls_in_body(rule))

    template = gcd_templates(predicates, bound)
    fixed = template + "\n\n" + "\n\n".join(kept)

    if "answer(" in fixed and "#show answer/1." not in fixed:
        fixed = fixed.rstrip() + "\n#show answer/1."

    return fixed.strip(), fixed.strip() != old.strip(), len(predicates), removed_gcd_rules


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--default-bound", type=int, default=120)
    parser.add_argument("--max-bound", type=int, default=250)
    parser.add_argument("--multiplier", type=int, default=2)
    args = parser.parse_args()

    total = 0
    changed = 0
    with_gcd_template = 0
    removed_rules = 0

    still_gcd_head_rules = 0
    still_abs_gcd_calls = 0

    with args.input.open("r", encoding="utf-8") as f, args.output.open("w", encoding="utf-8") as out:
        for line in f:
            if not line.strip():
                continue

            row = json.loads(line)
            old = row.get("asp_program") or ""

            new, did_change, pred_count, removed = fix_code(
                old,
                args.default_bound,
                args.max_bound,
                args.multiplier,
            )

            if did_change:
                row["asp_program_before_gcd_fix"] = old
                row["gcd_targeted_fix_attempted"] = True
                row["gcd_targeted_max_bound"] = args.max_bound
                row["asp_program"] = new
                changed += 1
            else:
                row["gcd_targeted_fix_attempted"] = False

            if pred_count:
                with_gcd_template += 1

            removed_rules += removed

            for rule in split_rules(new):
                if is_gcd3_head(rule):
                    pass

            if re.search(r"\bgcd[A-Za-z0-9_]*\s*\(\s*(?:#?abs)\s*\(", new):
                still_abs_gcd_calls += 1

            out.write(json.dumps(row, ensure_ascii=False) + "\n")
            total += 1

    print("File creato:", args.output)
    print("Righe:", total)
    print("Modificate:", changed)
    print("Con template gcd:", with_gcd_template)
    print("Regole gcd originali rimosse:", removed_rules)
    print("Ancora gcd(abs(...), ...):", still_abs_gcd_calls)
    print("Default bound:", args.default_bound)
    print("Max bound:", args.max_bound)


if __name__ == "__main__":
    main()
