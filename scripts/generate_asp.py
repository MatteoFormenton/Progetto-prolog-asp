"""
Leggo ogni Prolog valido, costruisco un prompt così llm genera codice asp
salvo il risultato in un file json"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

#import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

PROJECT_ROOT = Path(__file__).resolve().parents[1]
INPUT_FILE = PROJECT_ROOT / "data" / "prolog_for_asp.jsonl"
OUTPUT_FILE = PROJECT_ROOT / "data" / "asp_generated.jsonl"
PROMPT_FILE = PROJECT_ROOT / "prompts" / "prolog_to_asp_prompt.txt"

DEFAULT_MODEL = "Qwen/Qwen2.5-3B-Instruct"


def read_prompt_template(prompt_file: Path) -> str:
    if not prompt_file.exists():
        raise FileNotFoundError(f"File prompt non trovato: {prompt_file}")

    return prompt_file.read_text(encoding="utf-8")

def build_prompt(template: str, row: dict) -> str:
    """Inserisce i dati dentro il template del prompt."""
    return template.format(
        input=row["input"],
        prolog_program=row["prolog_program"],
        prolog_query=row["prolog_query"],
        answer=row["answer"],
    )

def clean_llm_output(text: str) -> str:
    cleaned = text.strip()

    cleaned = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)

    return cleaned.strip()

def load_model(model_name: str):
    tokenizer = AutoTokenizer.from_pretrained(model_name)

    model = AutoModelForCausalLM.from_pretrained(model_name, torch_dtype="auto", device_map="auto", )

    return tokenizer, model

def generate_asp_program( tokenizer, model, prompt: str, max_new_tokens: int,) -> str:
    """Genera il programma ASP usando il modello scelto."""

    messages = [
        {
            "role": "user",
            "content": prompt,
        }
    ]

    # Usa il formato chat del modello instruct.
    text = tokenizer.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=True,
    )

    inputs = tokenizer([text], return_tensors="pt").to(model.device)

    generated_ids = model.generate(
        **inputs,
        max_new_tokens=max_new_tokens,
        do_sample=False,
    )

    # Tolgo dal risultato i token del prompt, lasciando solo la risposta generata.
    generated_ids = [
        output_ids[len(input_ids):]
        for input_ids, output_ids in zip(inputs.input_ids, generated_ids)
    ]

    output_text = tokenizer.batch_decode(
        generated_ids,
        skip_special_tokens=True,
    )[0]

    return clean_llm_output(output_text)

def generate_dataset(input_file: Path, output_file: Path, prompt_file: Path, model_name: str, limit: int | None, max_new_tokens: int,):
    """Legge il dataset validato e genera il codice ASP."""

    if not input_file.exists():
        raise FileNotFoundError(f"File input non trovato: {input_file}")

    prompt_template = read_prompt_template(prompt_file)

    tokenizer, model = load_model(model_name)

    total = 0

    with input_file.open("r", encoding="utf-8") as input_handle:
        with output_file.open("w", encoding="utf-8") as output_handle:
            for line in input_handle:
                if not line.strip():
                    continue

                if limit is not None and total >= limit:
                    break

                row = json.loads(line)
                prompt = build_prompt(prompt_template, row)

                asp_program = generate_asp_program(
                    tokenizer=tokenizer,
                    model=model,
                    prompt=prompt,
                    max_new_tokens=max_new_tokens,
                )

                output_row = {
                    "id": row.get("id"),
                    "input": row["input"],
                    "prolog_program": row["prolog_program"],
                    "prolog_query": row["prolog_query"],
                    "answer": row["answer"],
                    "asp_program": asp_program,
                }

                output_handle.write(
                    json.dumps(output_row, ensure_ascii=False) + "\n"
                )

                total += 1
                print(f"Test generato: {total}")

    print(f"File creato: {output_file}")
    print(f"Test generati: {total}")


def parse_args() -> argparse.Namespace:
    """Legge gli argomenti da terminale."""
    parser = argparse.ArgumentParser(
        description="Genera codice ASP a partire da programmi Prolog validi."
    )

    parser.add_argument(
        "--input",
        type=Path,
        default=INPUT_FILE,
        help="File JSONL di input. Default: data/prolog_for_asp.jsonl",
    )

    parser.add_argument(
        "--output",
        type=Path,
        default=OUTPUT_FILE,
        help="File JSONL di output. Default: data/asp_generated.jsonl",
    )

    parser.add_argument(
        "--prompt",
        type=Path,
        default=PROMPT_FILE,
        help="File prompt. Default: prompts/prolog_to_asp_prompt.txt",
    )

    parser.add_argument(
        "--model",
        type=str,
        default=DEFAULT_MODEL,
        help=f"Modello HuggingFace da usare. Default: {DEFAULT_MODEL}",
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Numero massimo di test da generare.",
    )

    parser.add_argument(
        "--max-new-tokens",
        type=int,
        default=512,
        help="Numero massimo di token generati per ogni test.",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    generate_dataset(
        input_file=args.input,
        output_file=args.output,
        prompt_file=args.prompt,
        model_name=args.model,
        limit=args.limit,
        max_new_tokens=args.max_new_tokens,
    )


if __name__ == "__main__":
    main()
