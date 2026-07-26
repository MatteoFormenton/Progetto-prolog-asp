import argparse
import json
from pathlib import Path

import torch

from generate_asp import load_model, clean_llm_output


REPAIR_SYSTEM_PROMPT = """You repair invalid clingo ASP programs translated from Prolog.

Return only valid clingo ASP code.

Rules:
- Output only ASP code, no explanations, no markdown.
- The final result must be derived by answer/1.
- Never put answer(X) in the body of a rule.
- Do not use solve/0 as the main result.
- Wrong: solve :- value(X), answer(X).
- Correct: answer(X) :- value(X).

- Do not use Prolog lists: [1,2,3], [], [H|T].
- Encode lists using ASP facts such as item(1). item(2). item(3).

- Do not use Prolog if-then-else: (Cond -> A ; B).
- Do not use unsupported floating point syntax such as 1e-8.
- Do not use sqrt/1 unless it is explicitly encoded as integer facts.
- Do not invent symbolic function-like constants such as sqrt_4_plus_sqrt(I).
- Do not use intpow, round, is, =:=, =<, or Prolog arithmetic syntax.
- In clingo use <= instead of =<.
- In clingo use = for equality constraints, not =:=.
- Do not write global assignments like A = 1. as standalone statements.
- Encode constants as facts, for example a(1). or const_a(1).

- Do not use choice rules unless necessary.
- Avoid syntax like 1 { X : Condition }.
- Prefer simple deterministic rules with answer/1 in the head.

- Do not use not with a tuple/conjunction like:
  not (expr(A,B,S2), S2 < S).
- Instead define a helper predicate:
  smaller(S) :- expr(...,S), expr(...,S2), S2 < S.
  smallest(S) :- expr(...,S), not smaller(S).

- For sums over finite sets, prefer #sum aggregates.
- Example:
  sum_values(S) :- S = #sum { K : value(K) }.

- Every variable appearing only in arithmetic must have a finite domain predicate.
- If S is used in S*S = Target, add a domain such as s(0..1000), s(S).
- Use finite integer domains and integer arithmetic.

- Every variable must be safe.
- Every variable must appear in a positive body atom before arithmetic/comparisons.
- Every predicate must have consistent arity everywhere.
- Preserve the logic of the Prolog program.
- The expected answer is given only to verify correctness.
- Do not cheat by outputting only answer(Expected). unless the original Prolog program is truly a direct fact.

The program must end with exactly:
#show answer/1.
Stop immediately after #show answer/1.
"""


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


def generate_repair(tokenizer, model, row: dict, max_new_tokens: int) -> str:
    messages = [
        {"role": "system", "content": REPAIR_SYSTEM_PROMPT},
        {"role": "user", "content": build_user_prompt(row)},
    ]

    prompt = tokenizer.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=True,
    )

    device = next(model.parameters()).device

    inputs = tokenizer(prompt, return_tensors="pt")
    inputs = {k: v.to(device) for k, v in inputs.items()}

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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="data/asp_checked.jsonl")
    parser.add_argument("--output", default="data/asp_repaired.jsonl")
    parser.add_argument("--model", default="Qwen/Qwen2.5-14B-Instruct")
    parser.add_argument("--max-new-tokens", type=int, default=768)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)

    rows = []
    with input_path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))

    failed_indices = [
        i for i, row in enumerate(rows)
        if not row.get("asp_is_correct", False)
    ]

    if args.limit is not None:
        failed_indices = failed_indices[:args.limit]

    print(f"Esempi totali: {len(rows)}")
    print(f"Esempi da riparare: {len(failed_indices)}")
    print(f"Modello: {args.model}")

    tokenizer, model = load_model(args.model)
    model.eval()

    for pos, idx in enumerate(failed_indices, 1):
        row = rows[idx]
        old_asp = row.get("asp_program", "")

        print(f"[{pos}/{len(failed_indices)}] Repair esempio {idx + 1}")

        repaired_asp = generate_repair(
            tokenizer=tokenizer,
            model=model,
            row=row,
            max_new_tokens=args.max_new_tokens,
        )

        row["asp_program_before_repair"] = old_asp
        row["asp_error_before_repair"] = row.get("asp_error", "")
        row["asp_error_type_before_repair"] = row.get("asp_error_type", "")
        row["repair_attempted"] = True
        row["asp_program"] = repaired_asp

    with output_path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(f"File creato: {output_path}")


if __name__ == "__main__":
    main()
