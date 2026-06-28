"""
Funzione dello script:
- lettura ogni esempio dal dataset pulito
- salvataggio in un file .pl il programma prolog
- esecuzione query prolog usando SWI-Prolog tramite subprocess
- confronto tra l'output e il campo answer del dataet pulito
- salvataggio del risultato 
"""

from __future__ import annotations
import json
import argparse
import shutil
import subprocess
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
INPUT_FILE = PROJECT_ROOT / "data" / "prolog_clean.jsonl"
OUTPUT_FILE = PROJECT_ROOT / "data" / "prolog_checked.jsonl"
REPORT_FILE = PROJECT_ROOT / "outputs" / "prolog_validation_report.txt"


def normalize_text(value:str) -> str:
    """Normalizzazioen della stringa da confrontare, tolgo spazi e a capo, sequenza di +spazi in 1 spazio"""
    return " ".join(str(value).strip().split())


def query_to_goal(prolog_query: str) -> str:
    """
    Conversione della uery salvata in un goal eseguibile da SWI-Prolog
    """

    query = prolog_query.strip()

    if query.endswith("."):
        query = query[:-1].strip()

    return f"once(({query})), halt."



def run_prolog_program(
        prolog_program: str,
        prolog_query: str,
        timeout_seconds: int,
) -> tuple [str, str]:
    
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

def check_dataset (
            input_file: Path,
    output_file: Path,
    report_file: Path,
    limit: int | None,
    timeout_seconds: int,
): 
    """Esegue il controllo sul dataset pulito"""
    if shutil.which("swipl") is None: 
        raise RuntimeError(
            "SWI-Prolog non è installato o il comando swipl non è nel PATH"
        )
    
    if not input_file.exists():
        raise FileNotFoundError (f"File non trovato {input_file}")
    
    output_file.parent.mkdir(parents=True, exist_ok=True)
    report_file.parent.mkdir(parents=True, exist_ok=True)

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
                total+=1

                try:
                    stdout, stderr = run_prolog_program(
                        row["prolog_program"],
                        row["prolog_query"],
                        timeout_seconds,
                    )
                except subprocess.TimeoutExpired:
                    stdout = ""
                    stderr = "Timeout: programma prolog ha impiegato troppo tempo"
                
                prolog_output = normalize_text(stdout)
                expected_answer = normalize_text(row["answer"])

                is_correct = stderr.strip() == "" and prolog_output == expected_answer

                if is_correct:
                    correct += 1
                elif stderr.strip():
                    errors += 1
                else:
                    wrong += 1
                
                checked_row = {
                    **row,
                    "prolog_output": prolog_output,
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
        """Lege gli argomenti da terminale
        
        per prova python3 scripts/check_prolog.py --limit 20
        """

        parser = argparse.ArgumentParser(description="esecuzione programmi prolog")

        parser.add_argument("--input", type=Path, default=INPUT_FILE, help="Dataset da leggere")
        parser.add_argument("--output", type=Path, default=OUTPUT_FILE, help="File json con i risultati")
        parser.add_argument("--report", type=Path, default=REPORT_FILE, help="Report testuale")
        parser.add_argument("--limit", type=int, default=None, help="numero di dati da controllare1")
        parser.add_argument("--timeout", type=int, default=10, help="Secondi massimi per prolog")
        return parser.parse_args()
    

    if __name__ == "__main":
        args = parse_args(
        check_dataset(
            input_file=args.input,
            output_file=args.output,
            report_file=args.report,
            limit=args.limit,
            timeout_seconds=args.timeout,                
            )
        )

