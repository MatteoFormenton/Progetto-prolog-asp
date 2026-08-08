import argparse
import json
import re
from pathlib import Path

"""
Questo script applica una correzione automatica a programmi ASP che contengono funzioni
matematiche o operatori non direttamente supportati da clingo.

Per ogni riga di un file JSONL legge il campo `asp_program`, normalizza alcune forme
sintattiche non compatibili con ASP e riscrive l'uso di funzioni come `sqrt`, `abs`,
`round`, `#ceil` e alcune funzioni trigonometriche. Le chiamate a `sqrt(...)` e `abs(...)`
vengono sostituite con variabili ausiliarie e con predicati di supporto, rispettivamente
`isqrt/2` e `abs_val/2`, aggiunti automaticamente al programma quando necessari.

Lo script separa le regole ASP rispettando stringhe, intervalli numerici e parentesi,
trasforma solo gli elementi del body delle regole e mantiene invariati i fatti semplici.
Calcola inoltre un bound numerico approssimativo a partire dalle costanti presenti nel
programma, così da limitare i domini usati dai predicati ausiliari ed evitare grounding
eccessivamente grandi.

Se il programma viene modificato, la versione originale viene salvata nel campo
`asp_program_before_math_functions_fix`, mentre `asp_program` viene aggiornato con il
codice trasformato. Alla fine produce un nuovo file JSONL e stampa un riepilogo con il
numero di righe elaborate, quelle modificate, i programmi che usano helper matematici e
gli eventuali casi in cui restano ancora funzioni non riscritte.
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


def find_call(text, names):
    best = None

    for name in names:
        start = 0
        while True:
            pos = text.find(name + "(", start)
            if pos < 0:
                break

            if pos > 0 and re.match(r"[A-Za-z0-9_#]", text[pos - 1]):
                start = pos + 1
                continue

            open_pos = pos + len(name)
            depth = 0
            in_str = False
            esc = False

            for j in range(open_pos, len(text)):
                ch = text[j]

                if ch == '"' and not esc:
                    in_str = not in_str

                if not in_str:
                    if ch == "(":
                        depth += 1
                    elif ch == ")":
                        depth -= 1
                        if depth == 0:
                            if best is None or pos < best[0]:
                                best = (pos, j + 1, name, text[open_pos + 1:j].strip())
                            break

                esc = ch == "\\" and not esc
                if ch != "\\":
                    esc = False

            start = pos + 1

    return best


def rough_bound(code):
    nums = []

    for m in re.finditer(r"-?\d+", code):
        try:
            nums.append(abs(int(m.group(0))))
        except Exception:
            pass

    mx = max(nums) if nums else 100

    b = max(100, mx * 2)

    b = min(b, 10000)

    return b


def transform_item_functions(item, aux_counter):
    """
    Sostituisce funzioni non supportate dentro un singolo item:
      sqrt(E)  -> Aux, con isqrt(E, Aux)
      abs(E)   -> Aux, con abs_val(E, Aux)
      #abs(E)  -> Aux, con abs_val(E, Aux)
      round(E) -> E
      #ceil(E) -> E
      sin/cos/acos -> 0, solo per togliere lexer/syntax error.
    """
    pre_items = []
    text = item

    text = text.replace("#abs(", "abs(")

    for fname in ["round", "#ceil"]:
        while True:
            call = find_call(text, [fname])
            if not call:
                break
            start, end, name, arg = call
            text = text[:start] + "(" + arg + ")" + text[end:]

    while True:
        call = find_call(text, ["sqrt", "abs"])
        if not call:
            break

        start, end, name, arg = call
        aux_counter[0] += 1

        if name == "sqrt":
            aux = f"MathSqrtAux{aux_counter[0]}"
            pre_items.append(f"isqrt({arg}, {aux})")
        else:
            aux = f"MathAbsAux{aux_counter[0]}"
            pre_items.append(f"abs_val({arg}, {aux})")

        text = text[:start] + aux + text[end:]

    for fname in ["#sin", "#cos", "sin", "cos", "tan", "acos", "asin", "atan"]:
        while True:
            call = find_call(text, [fname])
            if not call:
                break
            start, end, name, arg = call
            text = text[:start] + "0" + text[end:]

    return pre_items + [text.strip()], aux_counter


def transform_rule(rule):
    if ":-" not in rule:
        return rule

    head, body = rule.split(":-", 1)

    body = body.strip()
    if body.endswith("."):
        body = body[:-1].strip()

    items = split_top_level(body, ",")
    new_items = []
    aux_counter = [0]

    for item in items:
        item = item.strip()

        if not item:
            continue

        transformed, aux_counter = transform_item_functions(item, aux_counter)
        new_items.extend(x for x in transformed if x.strip())

    new_body = ",\n    ".join(new_items)

    return head.rstrip() + " :-\n    " + new_body + "."


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

    return code


def add_helpers(code, bound):
    needs_sqrt = "isqrt(" in code
    needs_abs = "abs_val(" in code

    helpers = []

    if needs_sqrt:
        helpers.append(f"sqrt_bound(0..{bound}).")
        helpers.append("isqrt(N,R) :- sqrt_bound(R), N = R * R.")

    if needs_abs:
        helpers.append(f"abs_bound(-{bound}..{bound}).")
        helpers.append("abs_val(X,X) :- abs_bound(X), X >= 0.")
        helpers.append("abs_val(X,Y) :- abs_bound(X), X < 0, Y = -X.")

    if not helpers:
        return code

    return "\n".join(helpers) + "\n\n" + code


def fix_code(code):
    old = code or ""
    new = cleanup(old)

    b = rough_bound(new)

    rules = split_rules(new)
    fixed_rules = []

    for rule in rules:
        fixed_rules.append(transform_rule(rule))

    new = "\n\n".join(fixed_rules)
    new = add_helpers(new, b)

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
    still_sqrt_func = 0
    still_abs_func = 0
    still_round_func = 0
    still_hash_trig = 0
    has_helpers = 0

    with args.input.open("r", encoding="utf-8") as f, args.output.open("w", encoding="utf-8") as out:
        for line in f:
            if not line.strip():
                continue

            row = json.loads(line)
            old = row.get("asp_program") or ""
            new, did_change = fix_code(old)

            if did_change:
                row["asp_program_before_math_functions_fix"] = old
                row["math_functions_fix_attempted"] = True
                row["asp_program"] = new
                changed += 1
            else:
                row["math_functions_fix_attempted"] = False

            if re.search(r"=\s*sqrt\s*\(", new):
                still_sqrt_func += 1
            if re.search(r"=\s*abs\s*\(", new) or "#abs(" in new:
                still_abs_func += 1
            if re.search(r"round\s*\(", new):
                still_round_func += 1
            if "#sin" in new or "#cos" in new:
                still_hash_trig += 1
            if "isqrt(" in new or "abs_val(" in new:
                has_helpers += 1

            out.write(json.dumps(row, ensure_ascii=False) + "\n")
            total += 1

    print("File creato:", args.output)
    print("Righe:", total)
    print("Modificate:", changed)
    print("Con helper isqrt/abs_val:", has_helpers)
    print("Ancora '= sqrt(...)':", still_sqrt_func)
    print("Ancora '= abs(...)' o #abs:", still_abs_func)
    print("Ancora round(...):", still_round_func)
    print("Ancora #sin/#cos:", still_hash_trig)


if __name__ == "__main__":
    main()
