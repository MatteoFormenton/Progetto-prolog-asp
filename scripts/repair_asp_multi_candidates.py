import argparse
import json
from pathlib import Path

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

"""
Genera più candidati ASP per ogni esempio di un file JSONL usando un modello Hugging Face.

Per ogni riga costruisce un prompt con problema, programma Prolog, query, risposta attesa,
programma ASP corrente ed eventuali errori di clingo. Il modello produce più versioni
candidate del programma ASP, salvate nel file di output insieme a id del candidato, seed
usato e parametri di generazione.
"""


def read_prompt(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()


def build_prompt(template: str, row: dict) -> str:
    return f"""{template}

Original problem text:
{row.get("input", "")}

Original Prolog program:
{row.get("prolog_program", "")}

Original Prolog query:
{row.get("prolog_query", "")}

Expected answer:
{row.get("answer", "")}

Current ASP program:
{row.get("asp_program", "")}

Current clingo error type:
{row.get("asp_error_type", "")}

Current clingo error:
{row.get("asp_error", "")}

Current clingo output:
{row.get("asp_output", "")}
"""


def load_model(model_name: str):
    tokenizer = AutoTokenizer.from_pretrained(model_name)

    model = AutoModelForCausalLM.from_pretrained(
        model_name,
        torch_dtype="auto",
        device_map="auto",
    )

    if tokenizer.pad_token_id is None:
        tokenizer.pad_token_id = tokenizer.eos_token_id

    return tokenizer, model


def generate_one(tokenizer, model, prompt: str, max_new_tokens: int, temperature: float, top_p: float):
    messages = [
        {
            "role": "system",
            "content": (
                "You output only final valid clingo ASP code. "
                "Do not include analysis, explanations, markdown, or natural language."
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

    inputs = tokenizer([text], return_tensors="pt").to(model.device)

    with torch.no_grad():
        output_ids = model.generate(
            **inputs,
            max_new_tokens=max_new_tokens,
            do_sample=True,
            temperature=temperature,
            top_p=top_p,
            pad_token_id=tokenizer.pad_token_id,
        )

    generated = output_ids[0][inputs.input_ids.shape[-1]:]
    return tokenizer.decode(generated, skip_special_tokens=True).strip()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--prompt", required=True, type=Path)
    parser.add_argument("--model", required=True)
    parser.add_argument("--candidates", type=int, default=5)
    parser.add_argument("--max-new-tokens", type=int, default=1024)
    parser.add_argument("--temperature", type=float, default=0.7)
    parser.add_argument("--top-p", type=float, default=0.9)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    rows = [
        json.loads(line)
        for line in args.input.open("r", encoding="utf-8")
        if line.strip()
    ]

    if args.limit is not None:
        rows = rows[:args.limit]

    template = read_prompt(args.prompt)

    print("Esempi:", len(rows), flush=True)
    print("Candidati per esempio:", args.candidates, flush=True)
    print("Modello:", args.model, flush=True)

    tokenizer, model = load_model(args.model)

    args.output.parent.mkdir(parents=True, exist_ok=True)

    total_written = 0

    with args.output.open("w", encoding="utf-8") as out:
        for row_index, row in enumerate(rows, start=1):
            prompt = build_prompt(template, row)

            for candidate_id in range(args.candidates):
                seed = 100000 + row_index * 100 + candidate_id
                torch.manual_seed(seed)
                if torch.cuda.is_available():
                    torch.cuda.manual_seed_all(seed)

                asp_program = generate_one(
                    tokenizer=tokenizer,
                    model=model,
                    prompt=prompt,
                    max_new_tokens=args.max_new_tokens,
                    temperature=args.temperature,
                    top_p=args.top_p,
                )

                output_row = dict(row)
                output_row["asp_program"] = asp_program
                output_row["candidate_id"] = candidate_id
                output_row["candidate_seed"] = seed
                output_row["multi_candidate_model"] = args.model
                output_row["multi_candidate_temperature"] = args.temperature
                output_row["multi_candidate_top_p"] = args.top_p

                out.write(json.dumps(output_row, ensure_ascii=False) + "\n")
                out.flush()

                total_written += 1

            print(f"[{row_index}/{len(rows)}] generati {args.candidates} candidati", flush=True)

    print("File creato:", args.output, flush=True)
    print("Candidati totali:", total_written, flush=True)


if __name__ == "__main__":
    main()
