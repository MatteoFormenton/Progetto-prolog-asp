"""
Funzione dello script:
- lettura ogni esempio dal dataset pulito
- salvataggio in un file .pl il programma prolog
- esecuzione query prolog usando SWI-Prolog tramite subprocess
- confronto tra l'output e il campo answer del dataet pulito
- salvataggio del risultato 
"""

from __future__ import annotations
import argparse
import json
import shutil
import subprocess
import tempfile
import re
from fractions import Fraction
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
INPUT_FILE = PROJECT_ROOT / "data" / "prolog_clean.jsonl"
OUTPUT_FILE = PROJECT_ROOT / "data" / "prolog_checked.jsonl"
REPORT_FILE = PROJECT_ROOT / "outputs" / "prolog_validation_report.txt"


def prepare_output_files(output_file: Path, report_file: Path) -> None:
    # creo i file di output se non esistono
    output_file.touch(exist_ok=True)
    report_file.touch(exist_ok=True)


def normalize_text(value: str) -> str:
    """Normalizza una stringa togliendo spazi inutili e a capo."""
    return " ".join(str(value).strip().split())

def stderr_has_real_error(stderr: str) -> bool:
    """Controllo se strerr continene errori"""

    text = stderr.strip()

    if not text:
         return False
    
    if "Timeout" in text:
        return True
    
    for line in text.splitlines():
        line=line.strip()

        if not line:
            continue

        if line.startswith("Warning:"):
            continue
        
        if line.startswith("ERROR:"):
            return True

        return True

    return False 

def fraction_to_string(value: Fraction) -> str:
    """Converte una frazione in una forma standard."""
    if value.denominator == 1:
        return str(value.numerator)

    return f"{value.numerator}/{value.denominator}"   


def try_parse_fraction(value: str) -> Fraction | None:
    """Prova a convertire vari formati di frazione in un oggetto Fraction."""
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
    """ Confronta l'output di Prolog e la risposta dopo aver normalizzato il testo, 
    in modo da riconoscere uguali risposte scritte in formati diversi."""
    text = normalize_text(value)

    fraction_value = try_parse_fraction(text)

    if fraction_value is not None:
        return fraction_to_string(fraction_value)

    text = text.replace("\\{", "{")
    text = text.replace("\\}", "}")

    if re.fullmatch(r"[A-Za-z](,[A-Za-z])+", text):
        return text.replace(",", "")

    return text

def query_to_goal(prolog_query: str) -> str:
    """Conversione della uery salvata in un goal eseguibile da SWI-Prolog"""

    query = prolog_query.strip()

    if query.endswith("."):
        query = query[:-1].strip()

    return f"once(({query})), halt."


def run_prolog_program(prolog_program: str, prolog_query: str, timeout_seconds: int,) -> tuple [str, str]:
    
    """Esecuzione di un programma prolog tramite subprocess"""
    goal = query_to_goal(prolog_query)

    with tempfile.TemporaryDirectory() as temp_dir:
        program_path = Path(temp_dir) / "program.pl"
        program_path.write_text(prolog_program, encoding="utf-8")

        command = [
            "swipl",
            "-q",
            "-s",
            str(program_path),
            "-g",
            goal,
        ]

        completed_process = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )

    return completed_process.stdout, completed_process.stderr


def check_dataset( input_file: Path, output_file: Path, report_file: Path, limit: int | None, timeout_seconds: int,):
    """ Esegue il controllo sul dataset pulito. """
    if not input_file.exists():
        raise FileNotFoundError(f"File non trovato: {input_file}")

    # Qui vengono creati i file se non esistono.
    # Le cartelle data/ e outputs/ devono gia' esistere.
    prepare_output_files(output_file, report_file)

    if shutil.which("swipl") is None:
        raise RuntimeError(
            "SWI-Prolog non e' installato o il comando 'swipl' non e' nel PATH."
        )

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
                    stdout, stderr = run_prolog_program(
                        prolog_program=row["prolog_program"],
                        prolog_query=row["prolog_query"],
                        timeout_seconds=timeout_seconds,
                    )
                except subprocess.TimeoutExpired:
                    stdout = ""
                    stderr = "Timeout: il programma Prolog ha impiegato troppo tempo."

                prolog_output = normalize_text(stdout)
                
                prolog_output_normalized = normalize_for_compare(stdout)
                expected_answer_normalized = normalize_for_compare(row["answer"])
                
                has_error = stderr_has_real_error(stderr)
                
                is_correct = (
                    not has_error
                    and prolog_output_normalized == expected_answer_normalized)

                if is_correct:
                    correct += 1
                elif has_error:
                    errors += 1
                else:
                    wrong += 1

                checked_row = {
                    **row,
                    "prolog_output": prolog_output,
                    "prolog_output_normalized": prolog_output_normalized,
                    "answer_normalized": expected_answer_normalized,
                    "prolog_is_correct": is_correct,
                    "prolog_error": stderr.strip(),
                }

                output_handle.write(json.dumps(checked_row, ensure_ascii=False) + "\n")

    report = (
        "Prolog validation report\n"
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
    """
    Legge gli argomenti da terminale.
    """
    parser = argparse.ArgumentParser(
        description="Esegue i programmi Prolog puliti e confronta il risultato con answer."
    )

    parser.add_argument(
        "--input",
        type=Path,
        default=INPUT_FILE,
        help="Dataset pulito da leggere. Default: data/prolog_clean.jsonl",
    )

    parser.add_argument(
        "--output",
        type=Path,
        default=OUTPUT_FILE,
        help="File JSONL con i risultati del controllo. Default: data/prolog_checked.jsonl",
    )

    parser.add_argument(
        "--report",
        type=Path,
        default=REPORT_FILE,
        help="Report testuale. Default: outputs/prolog_validation_report.txt",
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Numero massimo di esempi da controllare. Utile per una prova veloce.",
    )

    parser.add_argument(
        "--timeout",
        type=int,
        default=10,
        help="Secondi massimi per ogni programma Prolog. Default: 10.",
    )

    return parser.parse_args()

def main () :
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