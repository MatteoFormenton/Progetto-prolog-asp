import argparse
import json
from pathlib import Path

import torch

from generate_asp import load_model, clean_llm_output


PROJECT_ROOT = Path(__file__).resolve().parents[1]
INPUT_FILE = PROJECT_ROOT / "data" / "asp_checked.jsonl"
OUTPUT_FILE = PROJECT_ROOT / "data" / "asp_repaired.jsonl"
PROMPT_FILE = PROJECT_ROOT / "prompts" / "repair_asp_prompt.txt"

DEFAULT_MODEL = "Qwen/Qwen2.5-32B-Instruct"


def read_prompt_template(prompt_file: Path) -> str:
    """
    Leggo il prompt di repair da file, come in generate_asp.py.
    """
    if not prompt_file.exists():
        raise FileNotFoundError(f"File prompt non trovato: {prompt_file}")

    return prompt_file.read_text(encoding="utf-8")


def build_user_prompt(row: dict) -> str:
    return f"""Repair this ASP program.

Problem text:
{row.get("input", "")}

Original Prolog program:
{row.get("prolog_program", "")}

Original Prolog query:
{row.get("prolog_query", "")}

Expected answer:
{row.get("answer", "")}

Current incorrect ASP program:
{row.get("asp_program", "")}

Clingo error/output:
{row.get("asp_error", "")}
{row.get("asp_output", "")}

Return the repaired clingo ASP program only.
"""


def generate_repair(
    tokenizer,
    model,
    repair_system_prompt: str,
    row: dict,
    max_new_tokens: int,
) -> str:
    messages = [
        {"role": "system", "content": repair_system_prompt},
        {"role": "user", "content": build_user_prompt(row)},
    ]

    prompt = tokenizer.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=True,
    )

    device = next(model.parameters()).device

    inputs = tokenizer(prompt, return_tensors="pt")
    inputs = {key: value.to(device) for key, value in inputs.items()}

    with torch.no_grad():
        outputs = model.generate(
            **inputs,
            max_new_tokens=max_new_tokens,
            do_sample=False,
            pad_token_id=tokenizer.eos_token_id,
        )

    generated_ids = outputs[0][inputs["input_ids"].shape[-1]:]
    text = tokenizer.decode(generated_ids, skip_special_tokens=True)

    return clean_llm_output(text)


def repair_dataset(
    input_file: Path,
    output_file: Path,
    prompt_file: Path,
    model_name: str,
    limit: int | None,
    max_new_tokens: int,
):
    """
    Legge il file validato da check_asp.py e ripara gli ASP non corretti.
    """

    if not input_file.exists():
        raise FileNotFoundError(f"File input non trovato: {input_file}")

    repair_system_prompt = read_prompt_template(prompt_file)

    rows = []
    with input_file.open("r", encoding="utf-8") as input_handle:
        for line in input_handle:
            if line.strip():
                rows.append(json.loads(line))

    failed_indices = [
        index
        for index, row in enumerate(rows)
        if not row.get("asp_is_correct", False)
    ]

    if limit is not None:
        failed_indices = failed_indices[:limit]

    print(f"Esempi totali: {len(rows)}", flush=True)
    print(f"Esempi da riparare: {len(failed_indices)}", flush=True)
    print(f"Modello: {model_name}", flush=True)
    print(f"Prompt: {prompt_file}", flush=True)

    tokenizer, model = load_model(model_name)
    model.eval()

    for position, index in enumerate(failed_indices, start=1):
        row = rows[index]
        old_asp = row.get("asp_program", "")

        print(
            f"[{position}/{len(failed_indices)}] Repair esempio {index + 1}",
            flush=True,
        )

        repaired_asp = generate_repair(
            tokenizer=tokenizer,
            model=model,
            repair_system_prompt=repair_system_prompt,
            row=row,
            max_new_tokens=max_new_tokens,
        )

        row["asp_program_before_repair"] = old_asp
        row["asp_error_before_repair"] = row.get("asp_error", "")
        row["asp_error_type_before_repair"] = row.get("asp_error_type", "")
        row["repair_attempted"] = True
        row["asp_program"] = repaired_asp

    output_file.parent.mkdir(parents=True, exist_ok=True)

    with output_file.open("w", encoding="utf-8") as output_handle:
        for row in rows:
            output_handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(f"File creato: {output_file}", flush=True)


def parse_args() -> argparse.Namespace:
    """
    Legge gli argomenti da terminale.
    """
    parser = argparse.ArgumentParser(
        description="Ripara programmi ASP non validi usando un modello LLM."
    )

    parser.add_argument(
        "--input",
        type=Path,
        default=INPUT_FILE,
        help="File JSONL di input. Default: data/asp_checked.jsonl",
    )

    parser.add_argument(
        "--output",
        type=Path,
        default=OUTPUT_FILE,
        help="File JSONL di output. Default: data/asp_repaired.jsonl",
    )

    parser.add_argument(
        "--prompt",
        type=Path,
        default=PROMPT_FILE,
        help="File prompt. Default: prompts/repair_asp_prompt.txt",
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
        help="Numero massimo di esempi falliti da riparare.",
    )

    parser.add_argument(
        "--max-new-tokens",
        type=int,
        default=768,
        help="Numero massimo di token generati per ogni repair.",
    )

    return parser.parse_args()


def main():
    args = parse_args()

    repair_dataset(
        input_file=args.input,
        output_file=args.output,
        prompt_file=args.prompt,
        model_name=args.model,
        limit=args.limit,
        max_new_tokens=args.max_new_tokens,
    )


if __name__ == "__main__":
    main()