from __future__ import annotations
import json
import re
from pathlib import Path


#percorsi dei file
PROJECT_ROOT = Path(__file__).resolve().parents[1]
INPUT_FILE = PROJECT_ROOT / "data" / "Prolog_Math_v4.jsonl"
OUTPUT_FILE = PROJECT_ROOT / "outputs" / "prolog_clean.jsonl"



AUTO_RUN_RE = re.compile(r"(?P<prefix>^|\n|(?<=\.))\s*:-\s*(?P<query>[^.\n]*?)\s*,\s*halt\s*\.")

def remove_comments(prolog_code: str)-> str:
    """
    
    """

    cleaned_chars: list[str] = []

    in_single_quote = False        
    in_double_quote = False
    in_line_comment = False
    in_block_comment = False
    escaped = False
    
    i=0

    while i< len(prolog_code):
        char= prolog_code[i]
        next_char= prolog_code[i++1] if i+1 <len(prolog_code) else ""

        #Salta il contenuto di un commento di riga
        if in_line_comment:
            if char=="\n":
                in_line_comment= False
                cleaned_chars.append(char)
            i+=1
            continue
        
        #salta il contenuto di un commento a blocco fino a */
        if in_block_comment:
            if char =="*" and next_char=="/":
                in_block_comment = False
                i+=2
                continue

            if char =="\n":
                cleaned_chars.append(char)
            i+=1
            continue

        # Fuori dalle stringhe, % apre un commento di riga.
        if not in_single_quote and not in_double_quote and char =="%":
            in_line_comment = True
            i+=1
            continue

        if(
            not in_single_quote
            and not in_double_quote
            and char == "/"
            and next_char =="*"
        ):
            in_block_comment = True
            i+=2
            continue

        cleaned_chars.append(char)

        #tiene traccia delle stringhe per non modificarne il contenuto
        if char =="\\" and not escaped:
            escaped = True
            i+=1
            continue

        if char == "'" and not in_double_quote and not escaped:
            in_single_quote = not in_single_quote
        elif char == '"' and not in_single_quote and not escaped:
            in_double_quote = not in_double_quote

        escaped = False
        i += 1

    return "".join(cleaned_chars)


def remove_auto_run (prolog_code: str) -> tuple[str, str]:
    """
    Restituisce la query da usare.
    """

    matches = list(AUTO_RUN_RE.finditer(prolog_code))

    if not matches:
        return prolog_code, "solve."
    
    last_match = matches[-1]
    query = last_match.group("query").strip()+"."
    cleaned_code = AUTO_RUN_RE.sub(
        lambda match: match.group("prefix"),
        prolog_code
    )

    return cleaned_code, query



def compact_blank_lines(prolog_code: str) -> str:
    """Elimina spazi finale e righe vuote ripetute"""
    compacted_lines: list[str] = []
    previous_line_was_blank = False

    for line in prolog_code.splitlines():
        line = line.rstrip()
        line_is_blank = line.strip() == ""

        if line_is_blank and previous_line_was_blank:
            continue

        compacted_lines.append(line)
        previous_line_was_blank = line_is_blank

    return "\n".join(compacted_lines).strip()



def clean_prolog_output(prolog_code: str) -> tuple[str, str]:
    """Applicazione della pulizia al campo output del dataset"""
    without_comments = remove_comments(prolog_code)
    without_auto_run, query = remove_auto_run(without_comments)
    cleaned_program = compact_blank_lines(without_auto_run)

    return cleaned_program, query



def main() -> None:
    """Leggo il dataset riga per riga e scrivo il dataset pulito"""
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    cleaned_rows = 0

    with INPUT_FILE.open("r", encoding="utf-8") as input_file:
        with OUTPUT_FILE.open("w", encoding="utf-8") as output_file:
            for row_id, line in enumerate(input_file):
                if not line.strip():
                    continue

                row = json.load(line)
                prolog_program, prolog_query = clean_prolog_output(row["output"])

                clean_row = {
                    "id": row_id,
                    "input": row["input"],
                    "prolog_program": prolog_program,
                    "prolog_query": prolog_query,
                    "answer": row["answer"],                
                }

                output_file.write(json.dumps(clean_row, ensure_ascii=False) +"\n")
                cleaned_rows+=1

    print(f"Dataset letto: {INPUT_FILE}")
    print(f"Dataset pulito: {OUTPUT_FILE}")
    print(f"righe pulite: {cleaned_rows}")


if __name__=="__main__":
    main()