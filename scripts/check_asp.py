"""
leggo ogni ASP generato, lo salva temporaneamente in un file. Eseguo clingo tramite subprocess,estraggo answer e
confronto il risultato con il campo answer salvandone poi il risultato.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from fractions import Fraction
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]

INPUT_FILE = PROJECT_ROOT / "data" / "asp_generated.jsonl"
OUTPUT_FILE = PROJECT_ROOT / "data" / "asp_checked.jsonl"
REPORT_FILE = PROJECT_ROOT / "outputs" / "asp_validation_report.txt"


def prepare_output_files(output_file: Path, report_file: Path) -> None:
    """ Crea solo i file se non esistono."""
    output_file.touch(exist_ok=True)
    report_file.touch(exist_ok=True)


def normalize_text(value: str) -> str:

    return " ".join(str(value).strip().split())


def fraction_to_string(value: Fraction) -> str:

    if value.denominator == 1:
        return str(value.numerator)

    return f"{value.numerator}/{value.denominator}"


def try_parse_fraction(value: str) -> Fraction | None:

    text = normalize_text(value)
    text = text.replace(" ", "")
    text = text.replace("$", "")

    match = re.fullmatch(r"([+-]?)\\frac\{([+-]?\d+)\}\{([+-]?\d+)\}", text)
    if match:
        sign, numerator, denominator = match.groups()
        result = Fraction(int(numerator), int(denominator))
        if sign == "-":
            result = -result
        return result

    match = re.fullmatch(r"([+-]?)\\frac(\d)(\d+)", text)
    if match:
        sign, numerator, denominator = match.groups()
        result = Fraction(int(numerator), int(denominator))
        if sign == "-":
            result = -result
        return result

    match = re.fullmatch(r"frac\(([+-]?\d+),([+-]?\d+)\)", text)
    if match:
        numerator, denominator = match.groups()
        return Fraction(int(numerator), int(denominator))

    if re.fullmatch(r"[+-]?\d+(\.\d+)?", text):
        return Fraction(text)

    return None


def normalize_for_compare(value: str) -> str:

    text = normalize_text(value)

    fraction_value = try_parse_fraction(text)

    if fraction_value is not None:
        return fraction_to_string(fraction_value)

    text = text.replace("\\{", "{")
    text = text.replace("\\}", "}")

    if re.fullmatch(r"[A-Za-z](,[A-Za-z])+", text):
        return text.replace(",", "")

    return text


def run_clingo_program(asp_program: str, timeout_seconds: int) -> tuple[str, str]:

    with tempfile.TemporaryDirectory() as temp_dir:
        program_path = Path(temp_dir) / "program.lp"
        program_path.write_text(asp_program, encoding="utf-8")

        command = [
            sys.executable,
            "-m",
            "clingo",
            str(program_path),
            "--outf=2",
        ]

        completed_process = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )

    return completed_process.stdout, completed_process.stderr


def extract_answer_values(clingo_stdout: str) -> list[str]:

    try:
        data = json.loads(clingo_stdout)
    except json.JSONDecodeError:
        return []

    answers: list[str] = []

    for call in data.get("Call", []):
        for witness in call.get("Witnesses", []):
            for atom in witness.get("Value", []):
                if not atom.startswith("answer("):
                    continue

                value = atom[len("answer("):-1]

                if value.startswith('"') and value.endswith('"'):
                    value = value[1:-1]

                answers.append(value)

    return answers


def answers_to_string(values: list[str]) -> str:

    if not values:
        return ""

    if len(values) == 1:
        return values[0]

    return ",".join(sorted(values))

def classify_asp_error(stderr: str) -> str:
    """
    Classifica il tipo di errore prodotto da clingo.
    """
    text = stderr.lower()

    if not text.strip():
        return ""

    if "timeout" in text:
        return "timeout"

    if "syntax error" in text or "parsing failed" in text:
        return "syntax_error"

    if "unsafe variables" in text or "unsafe" in text:
        return "unsafe_variables"

    if "grounding stopped" in text:
        return "grounding_error"

    return "clingo_error"


def check_dataset( input_file: Path, output_file: Path, report_file: Path, limit: int | None, timeout_seconds: int,):

    if not input_file.exists():
        raise FileNotFoundError(f"File non trovato: {input_file}")

    prepare_output_files(output_file, report_file)

    total = 0
    correct = 0
    wrong = 0
    errors = 0

    with input_file.open("r", encoding="utf-8") as input_handle:
        with output_file.open("w", encoding="utf-8") as output_handle:
            for line in input_handle:
                if not line.strip():
                    continue

                if limit is not None and total >= limit:
                    break

                row = json.loads(line)
                total += 1

                try:
                    stdout, stderr = run_clingo_program(
                        asp_program=row["asp_program"],
                        timeout_seconds=timeout_seconds,
                    )
                except subprocess.TimeoutExpired:
                    stdout = ""
                    stderr = "Timeout: clingo ha impiegato troppo tempo."

                asp_answers = extract_answer_values(stdout)
                asp_output = answers_to_string(asp_answers)

                asp_output_normalized = normalize_for_compare(asp_output)
                expected_answer_normalized = normalize_for_compare(row["answer"])

                has_error = stderr.strip() != ""

                asp_error_type = classify_asp_error(stderr)

                is_correct = (
                    not has_error
                    and asp_output_normalized == expected_answer_normalized
                )

                if is_correct:
                    correct += 1
                elif has_error:
                    errors += 1
                else:
                    wrong += 1

                checked_row = {
                    **row,
                    "asp_output": asp_output,
                    "asp_output_normalized": asp_output_normalized,
                    "answer_normalized": expected_answer_normalized,
                    "asp_is_correct": is_correct,
                    "asp_error": stderr.strip(),
                    "asp_error_type": asp_error_type,
                    }

                output_handle.write(json.dumps(checked_row, ensure_ascii=False) + "\n")

    report = (
        "ASP validation report\n"
        f"Total examples: {total}\n"
        f"Correct: {correct}\n"
        f"Wrong answer: {wrong}\n"
        f"Errors/timeouts: {errors}\n"
    )

    report_file.write_text(report, encoding="utf-8")

    print(report)
    print(f"File creato: {output_file}")
    print(f"Report creato: {report_file}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Esegue i programmi ASP con clingo e confronta answer."
    )

    parser.add_argument(
        "--input",
        type=Path,
        default=INPUT_FILE,
        help="File ASP generato",
    )

    parser.add_argument(
        "--output",
        type=Path,
        default=OUTPUT_FILE,
        help="File ASP controllato",
    )

    parser.add_argument(
        "--report",
        type=Path,
        default=REPORT_FILE,
        help="Report testuale",
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Numero massimo di esempi da controllare.",
    )

    parser.add_argument(
        "--timeout",
        type=int,
        default=10,
        help="Timeout per clingo",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    check_dataset(
        input_file=args.input,
        output_file=args.output,
        report_file=args.report,
        limit=args.limit,
        timeout_seconds=args.timeout,
    )


if __name__ == "__main__":
    main()