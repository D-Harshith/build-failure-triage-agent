import argparse
import json
import re
import time
from pathlib import Path

import ollama
import pandas as pd
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "Dataset"
LOGS = DATA / "LogChunks" / "logs"
RESULTS = ROOT / "results"

MODEL = "qwen3:8b"
TAIL = 150         # how many lines from the end of the log the model sees
MAX_CHARS = 200    # cut very long lines
MAX_ANSWER = 50    # longest answer we accept, in lines

SYSTEM = f"""You are a CI build-failure triage assistant. You get the last lines of a failed build log. Every line starts with its line number.

Find the block of lines that explains why the build failed: the error message with its details, such as the failing test and its assertion, the compiler error, or the failing command's output.
Do not answer with the generic closing lines such as "The command ... exited with 1" or "Done. Your build exited with 1".

Reply with the first and last line number of that block. The block must be at most {MAX_ANSWER} lines."""

COLOURS = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")   # terminal colour codes


class Answer(BaseModel):
    start_line: int
    end_line: int


def numbered_tail(case):
    """The last TAIL lines of the log, each written as '1370: text'."""
    lines = (LOGS / case["log"]).read_text(encoding="utf-8").splitlines()
    first = max(len(lines) - TAIL, 0)
    shown = []
    for number, line in enumerate(lines[first:], first + 1):
        shown.append(f"{number}: {COLOURS.sub('', line)[:MAX_CHARS]}")
    return "\n".join(shown)


def ask(case):
    return ollama.chat(
        model=MODEL,
        format=Answer.model_json_schema(),   # force the reply to be {"start_line": ..., "end_line": ...}
        think=False,
        options={"temperature": 0, "num_ctx": 16384},   # room for 16,384 tokens; the default is too small for 150 log lines
        messages=[
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": numbered_tail(case)},
        ],
    )


def is_hit(case, answer):
    """Correct when the answer overlaps the labelled lines and is not too long."""
    length = answer.end_line - answer.start_line + 1
    overlap = answer.start_line <= case["end_line"] and answer.end_line >= case["start_line"]
    return bool(overlap and 1 <= length <= MAX_ANSWER)


parser = argparse.ArgumentParser()
parser.add_argument("split", choices=["dev", "eval"])
parser.add_argument("--limit", type=int, help="run only N cases (smoke test)")
args = parser.parse_args()

cases = pd.read_json(DATA / f"{args.split}.jsonl", lines=True)
cases = cases.sample(frac=1, random_state=42)   # the file is sorted by repo; mix it so --limit sees many repos
if args.limit:
    cases = cases.head(args.limit)

ask(cases.iloc[-1])   # warm-up: the first call loads the model, so don't time it

rows = []
for n, (_, case) in enumerate(cases.iterrows(), 1):
    start = time.perf_counter()
    resp = ask(case)
    seconds = time.perf_counter() - start
    answer = Answer.model_validate_json(resp["message"]["content"])
    rows.append({
        "log": case["log"],
        "repo": case["repo"],
        "start_line": case["start_line"],
        "end_line": case["end_line"],
        "predicted_start": answer.start_line,
        "predicted_end": answer.end_line,
        "hit": is_hit(case, answer),
        "in_tail": bool(case["end_line"] > case["log_lines"] - TAIL),   # was the answer inside the lines the model saw?
        "prompt_tokens": resp["prompt_eval_count"],
        "seconds": round(seconds, 2),
    })
    if n % 10 == 0:
        print(f"{n}/{len(cases)} done")

df = pd.DataFrame(rows)
RESULTS.mkdir(exist_ok=True)
name = f"baseline_{args.split}" + ("_smoke" if args.limit else "")
df.to_csv(RESULTS / f"{name}.csv", index=False)

summary = {
    "variant": "baseline",
    "split": args.split,
    "cases": len(df),
    "hit_rate": round(float(df["hit"].mean()), 3),
    "answer_in_tail": round(float(df["in_tail"].mean()), 3),
    "seconds_per_case": round(float(df["seconds"].mean()), 2),
    "max_prompt_tokens": int(df["prompt_tokens"].max()),   # must stay below num_ctx, or the log was cut
}
(RESULTS / f"{name}_summary.json").write_text(json.dumps(summary, indent=2))
print(json.dumps(summary, indent=2))