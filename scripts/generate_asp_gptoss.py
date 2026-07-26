"""
Genera programmi ASP a partire dai programmi Prolog validi usando gpt-oss.

Input:
    data/prolog_for_asp.jsonl

Output:
    data/asp_generated_gptoss20b.jsonl

Nota:
    Il modello gpt-oss viene caricato dalla cache locale.
    Prima deve essere scaricato dal login node con snapshot_download.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer


PROJECT_ROOT = Path(__file__).resolve().parents[1]

INPUT_FILE = PROJECT_ROOT / "data" / "prolog_for_asp.jsonl"
OUTPUT_FILE = PROJECT_ROOT / "data" / "asp_generated_gptoss20b.jsonl"
PROMPT_FILE = PROJECT_ROOT / "prompts" / "prolog_to_asp_prompt.txt"

DEFAULT_MODEL = "openai/gpt-oss-20b"


def read_prompt_template(prompt_file: Path) -> str:
    if not prompt_file.exists():
        raise FileNotFoundError(f"File prompt non trovato: {prompt_file}")

    return prompt_file.read_text(encoding="utf-8")


def build_prompt(template: str, row: dict) -> str:
    return template.format(
        input=row["input"],
        prolog_program=row["prolog_program"],
        prolog_query=row["prolog_query"],
        answer=row["answer"],
    )


def clean_llm_output(text: str) -> str:
    cleaned = text.strip()

    # gpt-oss / Harmony può emettere canali tipo:
    # analysis...
    # assistantfinal...
    # final...
    # Teniamo solo la parte finale, cioè il codice ASP.
    markers = [
        "assistantfinal",
        "assistant final",
        "<|channel|>final",
        "final",
    ]

    lower_cleaned = cleaned.lower()

    best_pos = -1
    best_marker = None

    for marker in markers:
        pos = lower_cleaned.rfind(marker)
        if pos > best_pos:
            best_pos = pos
            best_marker = marker

    if best_pos != -1 and best_marker is not None:
        cleaned = cleaned[best_pos + len(best_marker):].strip()

    # Rimuove eventuali fence markdown
    cleaned = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)

    # Se il modello continua a scrivere spiegazioni, prova a partire
    # dalla prima riga che sembra ASP.
    asp_start_patterns = [
        r"^[a-z][a-zA-Z0-9_]*\(",
        r"^#show",
        r"^#const",
        r"^:-",
        r"^[a-z][a-zA-Z0-9_]*\.",
    ]

    lines = cleaned.splitlines()
    start_index = None

    for i, line in enumerate(lines):
        stripped = line.strip()
        if any(re.match(pattern, stripped) for pattern in asp_start_patterns):
            start_index = i
            break

    if start_index is not None:
        cleaned = "\n".join(lines[start_index:]).strip()

    # Taglia via eventuale testo dopo il codice, se compare.
    stop_markers = [
        "analysis",
        "assistant",
        "user",
        "explanation",
        "check safety",
        "thus final",
    ]

    lines = cleaned.splitlines()
    kept_lines = []

    for line in lines:
        stripped_lower = line.strip().lower()
        if kept_lines and any(stripped_lower.startswith(marker) for marker in stop_markers):
            break
        kept_lines.append(line)

    cleaned = "\n".join(kept_lines).strip()

    # Piccola normalizzazione da sintassi Prolog/Python a clingo.
    cleaned = cleaned.replace("//", "/")

    # Taglia tutto dopo #show answer/1.
    # Così eventuali spiegazioni successive non finiscono nel file ASP.
    lines = cleaned.splitlines()
    final_lines = []

    for line in lines:
        final_lines.append(line)
        if line.strip() == "#show answer/1.":
            break

    cleaned = "\n".join(final_lines).strip()

    # Se non contiene il marker finale richiesto, probabilmente è rimasto solo analysis.
    if "#show answer/1." not in cleaned:
        return ""

    return cleaned

def load_model(model_name: str):
    """
    Carica tokenizer e modello dalla cache locale.

    local_files_only=True evita che il nodo GPU provi ad andare su internet.
    """
    tokenizer = AutoTokenizer.from_pretrained(
        model_name,
        local_files_only=True,
        trust_remote_code=True,
    )

    model = AutoModelForCausalLM.from_pretrained(
        model_name,
        torch_dtype="auto",
        device_map="auto",
        local_files_only=True,
        trust_remote_code=True,
    )

    model.eval()

    print(f"CUDA disponibile: {torch.cuda.is_available()}", flush=True)
    print(f"Dispositivo modello: {next(model.parameters()).device}", flush=True)

    return tokenizer, model


def generate_asp_program(
    tokenizer,
    model,
    prompt: str,
    max_new_tokens: int,
) -> str:
    """
    Genera codice ASP usando il formato chat del tokenizer.

    Per gpt-oss, il chat template di Transformers applica il formato Harmony.
    """
    messages = [
        {
            "role": "system",
            "content": (
                "You are an expert in Answer Set Programming for clingo. "
                "Return only valid clingo ASP code. "
                "Do not write explanations. "
                "Do not use Markdown. "
                "Do not use code fences. "
                "Never output Prolog syntax. "
                "The final result must be represented using answer/1. "
                "The program must end with #show answer/1."
            ),
        },
        {
            "role": "user",
            "content": prompt,
        },
    ]

    text = tokenizer.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=True,
    )

    device = next(model.parameters()).device

    inputs = tokenizer(
        [text],
        return_tensors="pt",
    ).to(device)

    with torch.inference_mode():
        generated_ids = model.generate(
            **inputs,
            max_new_tokens=max_new_tokens,
            do_sample=False,
            pad_token_id=tokenizer.eos_token_id,
        )

    generated_ids = [
        output_ids[len(input_ids):]
        for input_ids, output_ids in zip(inputs.input_ids, generated_ids)
    ]

    output_text = tokenizer.batch_decode(
        generated_ids,
        skip_special_tokens=True,
    )[0]

    return clean_llm_output(output_text)


def count_input_rows(input_file: Path, limit: int | None) -> int:
    count = 0

    with input_file.open("r", encoding="utf-8") as file:
        for line in file:
            if not line.strip():
                continue

            count += 1

            if limit is not None and count >= limit:
                break

    return count


def generate_dataset(
    input_file: Path,
    output_file: Path,
    prompt_file: Path,
    model_name: str,
    limit: int | None,
    max_new_tokens: int,
) -> None:
    if not input_file.exists():
        raise FileNotFoundError(f"File input non trovato: {input_file}")

    output_file.parent.mkdir(parents=True, exist_ok=True)

    total_examples = count_input_rows(input_file, limit)

    print(f"Esempi da generare: {total_examples}", flush=True)
    print(f"Modello: {model_name}", flush=True)
    print(f"Output: {output_file}", flush=True)

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
                output_handle.flush()

                total += 1
                print(f"[{total}/{total_examples}] Test generato", flush=True)

    print(f"File creato: {output_file}", flush=True)
    print(f"Test generati: {total}", flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Genera codice ASP usando gpt-oss."
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
        help="File JSONL di output. Default: data/asp_generated_gptoss20b.jsonl",
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
        default=768,
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
