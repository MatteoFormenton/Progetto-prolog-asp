import argparse
import json
import re
from pathlib import Path

"""
Questo script applica una correzione automatica a programmi ASP che contengono liste in
stile Prolog, convertendole in una rappresentazione esplicita basata su `cons/2` e `nil`.

Per ogni riga di un file JSONL legge il campo `asp_program` e cerca espressioni tra
parentesi quadre, comprese liste semplici, liste annidate e liste con coda esplicita del
tipo `[H|T]` o `[A,B|T]`. La trasformazione riscrive queste strutture in forma funzionale,
ad esempio convertendo una lista in una catena di `cons(...)` terminata da `nil`, evitando
di modificare contenuti che si trovano dentro stringhe.

Lo script applica anche alcune correzioni sintattiche aggiuntive osservate nei programmi
di questo gruppo, come la normalizzazione di `#showsig`, la conversione di codici carattere
in stile Prolog e la sostituzione di espressioni `X in S` con `member(X,S)`. Se il programma
contiene `answer(...)` ma non include la direttiva di output, aggiunge automaticamente
`#show answer/1.`.

Quando il codice viene modificato, la versione originale viene salvata nel campo
`asp_program_before_prolog_list_fix`, mentre `asp_program` viene aggiornato con la versione
corretta. Alla fine produce un nuovo file JSONL e stampa un riepilogo con il numero di
righe elaborate, quelle modificate e gli eventuali programmi che contengono ancora parentesi
quadre o il simbolo `|`.
"""
def is_quote_toggle(text, i, in_string):

    if text[i] != '"':
        return False
    if in_string:
        return True
    if i > 0 and text[i - 1].isdigit():
        return False
    return True


def split_top_level(text, sep=","):
    parts = []
    cur = []
    depth_par = 0
    depth_brack = 0
    depth_brace = 0
    in_string = False
    esc = False

    for i, ch in enumerate(text):
        if ch == '"' and not esc and is_quote_toggle(text, i, in_string):
            in_string = not in_string

        if not in_string:
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
                ch == sep
                and depth_par == 0
                and depth_brack == 0
                and depth_brace == 0
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


def find_top_level_pipe(text):
    depth_par = 0
    depth_brack = 0
    depth_brace = 0
    in_string = False
    esc = False

    for i, ch in enumerate(text):
        if ch == '"' and not esc and is_quote_toggle(text, i, in_string):
            in_string = not in_string

        if not in_string:
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
                ch == "|"
                and depth_par == 0
                and depth_brack == 0
                and depth_brace == 0
            ):
                return i

        esc = ch == "\\" and not esc
        if ch != "\\":
            esc = False

    return -1


def build_cons(items, tail="nil"):
    result = tail.strip()

    for item in reversed(items):
        item = item.strip()
        if not item:
            continue
        result = f"cons({item},{result})"

    return result


def replace_prolog_lists(text):
    out = []
    i = 0
    in_string = False
    esc = False

    while i < len(text):
        ch = text[i]

        if ch == '"' and not esc and is_quote_toggle(text, i, in_string):
            in_string = not in_string
            out.append(ch)
            i += 1
            esc = False
            continue

        if ch == "[" and not in_string:
            depth = 1
            j = i + 1
            in_string_2 = False
            esc_2 = False

            while j < len(text):
                ch2 = text[j]

                if ch2 == '"' and not esc_2 and is_quote_toggle(text, j, in_string_2):
                    in_string_2 = not in_string_2
                elif not in_string_2:
                    if ch2 == "[":
                        depth += 1
                    elif ch2 == "]":
                        depth -= 1
                        if depth == 0:
                            break

                esc_2 = ch2 == "\\" and not esc_2
                if ch2 != "\\":
                    esc_2 = False

                j += 1

            if j >= len(text):
                out.append(ch)
                i += 1
                continue

            inner = text[i + 1:j].strip()

            if not inner:
                replacement = "nil"
            else:
                pipe_pos = find_top_level_pipe(inner)

                if pipe_pos >= 0:
                    left = inner[:pipe_pos].strip()
                    tail = inner[pipe_pos + 1:].strip()

                    left_items = [
                        replace_prolog_lists(x)
                        for x in split_top_level(left, ",")
                        if x.strip()
                    ]

                    tail = replace_prolog_lists(tail)
                    replacement = build_cons(left_items, tail)
                else:
                    items = [
                        replace_prolog_lists(x)
                        for x in split_top_level(inner, ",")
                        if x.strip()
                    ]

                    replacement = build_cons(items, "nil")

            out.append(replacement)
            i = j + 1
            continue

        out.append(ch)

        esc = ch == "\\" and not esc
        if ch != "\\":
            esc = False

        i += 1

    return "".join(out)


def cleanup_extra_syntax(code):
    code = code.replace("#showsig", "#show")

    code = re.sub(r'0"([0-9])', lambda m: str(ord(m.group(1))), code)
    code = re.sub(r'"([0-9])"', lambda m: str(ord(m.group(1))), code)

    code = re.sub(
        r"\b([A-Za-z_][A-Za-z0-9_]*)\s+in\s+([A-Za-z_][A-Za-z0-9_]*)",
        r"member(\1,\2)",
        code,
    )

    return code


def fix_code(code):
    old = code or ""
    new = replace_prolog_lists(old)
    new = cleanup_extra_syntax(new)

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
    still_brackets = 0
    still_pipe = 0

    with args.input.open("r", encoding="utf-8") as f, args.output.open("w", encoding="utf-8") as out:
        for line in f:
            if not line.strip():
                continue

            row = json.loads(line)
            old = row.get("asp_program") or ""
            new, did_change = fix_code(old)

            if did_change:
                row["asp_program_before_prolog_list_fix"] = old
                row["prolog_list_to_cons_fix_attempted"] = True
                row["asp_program"] = new
                changed += 1
            else:
                row["prolog_list_to_cons_fix_attempted"] = False

            if "[" in new or "]" in new:
                still_brackets += 1
            if "|" in new:
                still_pipe += 1

            out.write(json.dumps(row, ensure_ascii=False) + "\n")
            total += 1

    print("File creato:", args.output)
    print("Righe:", total)
    print("Modificate:", changed)
    print("Ancora con []:", still_brackets)
    print("Ancora con |:", still_pipe)


if __name__ == "__main__":
    main()
