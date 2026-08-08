import argparse
import json
import re
from pathlib import Path
"""
Pulisce programmi ASP generati da GPT-OSS in formato JSONL.

Rimuove marker del modello, markdown e testo naturale, normalizza alcuni operatori non
compatibili con clingo e aggiorna `asp_program` con il codice pulito. Se necessario,
aggiunge automaticamente `#show answer/1.`.
"""

def looks_like_asp_line(line: str) -> bool:
    s = line.strip()

    if not s:
        return True

    if s.startswith("#show"):
        return True

    if s.startswith("#const"):
        return True

    if s.startswith("#minimize"):
        return True

    if s.startswith(":-"):
        return True

    if ":-" in s:
        return True

    if re.match(r"^[a-z][A-Za-z0-9_]*\s*\(.*\)\s*\.$", s):
        return True

    if re.match(r"^[a-z][A-Za-z0-9_]*\s*\.$", s):
        return True

    if re.match(r"^[a-z][A-Za-z0-9_]*\s*\([^)]*\.\.[^)]*\)\s*\.$", s):
        return True

    return False


def clean_text(text: str) -> str:
    if not text:
        return ""

    text = text.strip()

    markers = [
        "assistantfinal",
        "<|channel|>final",
        "<|start|>assistant<|channel|>final",
        "final answer:",
        "Final answer:",
    ]

    for marker in markers:
        if marker in text:
            text = text.split(marker)[-1].strip()

    text = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", text)
    text = re.sub(r"\s*```$", "", text)

    if "#show answer/1." in text:
        before, _, _ = text.partition("#show answer/1.")
        text = before.rstrip() + "\n#show answer/1."

    text = text.replace("≠", "!=")
    text = text.replace("≤", "<=")
    text = text.replace("≥", ">=")

    text = text.replace("=<", "<=")
    text = text.replace("=:=", "=")

    raw_lines = text.splitlines()
    cleaned = []

    for line in raw_lines:
        s = line.strip()

        if not s:
            cleaned.append(line)
            continue

        lower = s.lower()

        bad_starts = (
            "analysis",
            "we need",
            "maybe",
            "so we",
            "the problem",
            "this program",
            "return",
            "check:",
            "let",
            "if we",
            "alternative",
            "but ",
            "then ",
            "because",
            "probably",
            "i think",
        )

        if lower.startswith(bad_starts):
            continue

        if s.startswith("```"):
            continue

        if looks_like_asp_line(line):
            cleaned.append(line)

    text = "\n".join(cleaned).strip()

    if "#show answer/1." in text:
        before, _, _ = text.partition("#show answer/1.")
        text = before.rstrip() + "\n#show answer/1."

    if "answer(" in text and "#show answer/1." not in text:
        text = text.rstrip() + "\n#show answer/1."

    return text.strip()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    total = 0
    changed = 0
    empty = 0
    only_show = 0

    with args.input.open("r", encoding="utf-8") as f, args.output.open("w", encoding="utf-8") as out:
        for line in f:
            if not line.strip():
                continue

            row = json.loads(line)
            old = row.get("asp_program", "")
            new = clean_text(old)

            if new != old:
                row["asp_program_before_gptoss_clean_v2"] = old
                row["gptoss_clean_v2_attempted"] = True
                row["asp_program"] = new
                changed += 1
            else:
                row["gptoss_clean_v2_attempted"] = False

            if not new.strip():
                empty += 1

            if new.strip() == "#show answer/1.":
                only_show += 1

            out.write(json.dumps(row, ensure_ascii=False) + "\n")
            total += 1

    print("File creato:", args.output)
    print("Righe:", total)
    print("Modificate:", changed)
    print("Vuote:", empty)
    print("Solo #show:", only_show)


if __name__ == "__main__":
    main()
