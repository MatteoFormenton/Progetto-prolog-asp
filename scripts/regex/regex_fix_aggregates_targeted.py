import argparse
import json
import re
from pathlib import Path

"""
Questo script applica una correzione automatica a programmi ASP che contengono aggregati
scritti in forme non compatibili o poco stabili per clingo.

Per ogni riga di un file JSONL legge il campo `asp_program` e normalizza diverse strutture
legate agli aggregati, come `#count`, `#sum`, `#max` e `#min`. In particolare riscrive
uguaglianze del tipo `#count {...} = C` nella forma più stabile `C = #count {...}`,
trasforma alcune choice rule usate come conteggi in veri aggregati `#count`, corregge
forme semplici di `#max` e `#min` con elementi separati da virgola e rimuove direttive
di ottimizzazione inserite erroneamente nel corpo delle regole.

Lo script gestisce anche alcuni costrutti non supportati o problematici, come `#ceil`
e `#prod`, applicando sostituzioni conservative per ridurre errori di parsing o lexer.
Inoltre corregge alcuni casi specifici in cui un aggregato `#sum` viene usato per
rappresentare una differenza assoluta, riscrivendolo come massimo tra due espressioni.

Se il programma contiene `answer(...)` ma non include la direttiva di output, aggiunge
automaticamente `#show answer/1.`. Quando il codice viene modificato, la versione originale
viene salvata nel campo `asp_program_before_aggregate_fix`, mentre `asp_program` viene
aggiornato con la versione corretta. Alla fine produce un nuovo file JSONL e stampa un
riepilogo con il numero di righe elaborate, quelle modificate e gli eventuali programmi
in cui restano ancora `#prod`, `#ceil`, direttive di ottimizzazione o forme `{ ... } = Var`.
"""
VAR_RE = re.compile(r"\b[A-Z_][A-Za-z0-9_]*\b")


def split_top_level(text, sep=","):
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


def split_rules(code):
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


def extract_vars(text):
    return [
        v for v in VAR_RE.findall(text)
        if not v.startswith("_")
    ]


def normalize_aggregate_equality(code):
    for agg in ["count", "sum", "max", "min"]:
        pat = re.compile(
            rf"(#(?:{agg})\s*\{{[^{{}}]*\}})\s*=\s*([A-Z][A-Za-z0-9_]*)",
            re.S,
        )
        code = pat.sub(r"\2 = \1", code)

    return code


def fix_simple_max_min_commas(code):
    code = re.sub(
        r"#max\s*\{\s*([^{}:;,\n]+?)\s*,\s*([^{}:;,\n]+?)\s*\}",
        r"#max {\1; \2}",
        code,
    )
    code = re.sub(
        r"#min\s*\{\s*([^{}:;,\n]+?)\s*,\s*([^{}:;,\n]+?)\s*\}",
        r"#min {\1; \2}",
        code,
    )
    return code


def fix_choice_count_equals(code):

    counter = 0

    atom_choice_re = re.compile(
        r"(?<!#count\s)(?<!#sum\s)(?<!#max\s)(?<!#min\s)"
        r"\{\s*([a-z][A-Za-z0-9_]*\s*\(([^{}]*)\))\s*\}\s*=\s*([A-Z][A-Za-z0-9_]*)",
        re.S,
    )

    def repl(m):
        nonlocal counter

        atom = m.group(1).strip()
        args_text = m.group(2).strip()
        out_var = m.group(3).strip()

        pred_m = re.match(r"([a-z][A-Za-z0-9_]*)\s*\((.*)\)$", atom, re.S)
        if not pred_m:
            return m.group(0)

        pred = pred_m.group(1)
        raw_args = split_top_level(pred_m.group(2), ",")

        fixed_args = []
        tuple_terms = []

        for arg in raw_args:
            arg = arg.strip()

            if arg == "_" or arg.startswith("_"):
                counter += 1
                v = f"AggAnon{counter}"
                fixed_args.append(v)
                tuple_terms.append(v)
            else:
                fixed_args.append(arg)
                if re.match(r"^[A-Z][A-Za-z0-9_]*$", arg):
                    tuple_terms.append(arg)

        fixed_atom = f"{pred}({','.join(fixed_args)})"

        if tuple_terms:
            tuple_part = ",".join(tuple_terms)
        else:
            tuple_part = "1"

        return f"{out_var} = #count {{ {tuple_part} : {fixed_atom} }}"

    return atom_choice_re.sub(repl, code)


def remove_optimizer_inside_body(code):

    lines = code.splitlines()
    new_lines = []

    for line in lines:
        stripped = line.strip()
        if re.fullmatch(r"#(?:minimize|maximize)\s*\{[^{}]*\}\s*,?", stripped):
            continue
        new_lines.append(line)

    return "\n".join(new_lines)


def fix_unsupported_builtin_syntax(code):

    code = re.sub(r"#ceil\s*\(\s*sqrt\s*\(\s*([^)]+?)\s*\)\s*\)", r"\1", code)
    code = re.sub(r"#ceil\s*\(\s*([^)]+?)\s*\)", r"\1", code)


    code = code.replace("#prod", "#sum")

    return code


def fix_bad_aggregate_element_equalities(code):
    code = re.sub(
        r"([A-Z][A-Za-z0-9_]*)\s*=\s*#sum\s*\{\s*([A-Z][A-Za-z0-9_]*)\s*:\s*\2\s*=\s*([^;{}]+?)\s*;\s*\2\s*=\s*([^{}]+?)\s*\}",
        r"\1 = #max {\3; \4}",
        code,
        flags=re.S,
    )

    return code


def normalize_spaces(code):
    code = code.replace("#count{", "#count {")
    code = code.replace("#sum{", "#sum {")
    code = code.replace("#max{", "#max {")
    code = code.replace("#min{", "#min {")
    code = code.replace("#showsig", "#show")
    return code


def fix_code(code):
    old = code or ""
    new = old

    new = normalize_spaces(new)
    new = normalize_aggregate_equality(new)
    new = fix_choice_count_equals(new)
    new = fix_simple_max_min_commas(new)
    new = fix_bad_aggregate_element_equalities(new)
    new = remove_optimizer_inside_body(new)
    new = fix_unsupported_builtin_syntax(new)
    new = normalize_spaces(new)

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

    still_prod = 0
    still_ceil = 0
    still_optimizer = 0
    still_choice_equals = 0

    with args.input.open("r", encoding="utf-8") as f, args.output.open("w", encoding="utf-8") as out:
        for line in f:
            if not line.strip():
                continue

            row = json.loads(line)
            old = row.get("asp_program") or ""
            new, did_change = fix_code(old)

            if did_change:
                row["asp_program_before_aggregate_fix"] = old
                row["aggregate_fix_attempted"] = True
                row["asp_program"] = new
                changed += 1
            else:
                row["aggregate_fix_attempted"] = False

            if "#prod" in new:
                still_prod += 1
            if "#ceil" in new:
                still_ceil += 1
            if "#minimize" in new or "#maximize" in new:
                still_optimizer += 1
            if re.search(r"\{[^{}]*\}\s*=\s*[A-Z][A-Za-z0-9_]*", new, re.S):
                still_choice_equals += 1

            out.write(json.dumps(row, ensure_ascii=False) + "\n")
            total += 1

    print("File creato:", args.output)
    print("Righe:", total)
    print("Modificate:", changed)
    print("Ancora #prod:", still_prod)
    print("Ancora #ceil:", still_ceil)
    print("Ancora optimizer:", still_optimizer)
    print("Ancora { ... } = Var:", still_choice_equals)


if __name__ == "__main__":
    main()
