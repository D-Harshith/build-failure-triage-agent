import argparse
import json
import time
from pathlib import Path

import ollama
import pandas as pd
from pydantic import BaseModel

from tools import load_lines, read_lines, search_log

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "Dataset"
RESULTS = ROOT / "results"

MODEL = "qwen3:8b"
MAX_STEPS = 8      # most rounds of tool calls before we ask for the answer anyway
MAX_ANSWER = 50    # longest answer we accept, in lines (same as baseline.py)
TAIL = 150         # only used to record in_tail, so the two result files can be compared
OPTIONS = {"temperature": 0, "num_ctx": 16384}   # same as baseline.py
start_time = time.perf_counter()
print("Start time", start_time)
SYSTEM = f"""You are a CI build-failure triage assistant. A build failed. Find the block of lines in its log that explains why: the error message with its details, such as the failing test and its assertion, the compiler error, or the failing command's output.
Do not answer with the generic closing lines such as "The command ... exited with 1" or "Done. Your build exited with 1".

You cannot see the log. Use the tools to look at it:
- search_log(pattern): find lines that contain a word or phrase
- read_lines(start, end): read a part of the log

The explanation is often near the end of the log, but not always. A good way to work: read the last 60 lines, then search for words such as "error", "failed", "exception" or the name of the failing command, then read around the best match to see where the error block starts and ends.

When you have found the block, stop calling tools and say its first and last line number. The block must be at most {MAX_ANSWER} lines."""

# what the model is told about each tool: its name, what it does, and which arguments it takes
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_log",
            "description": "Find the lines of the log that contain a word or phrase. Upper and lower case are ignored. Returns line numbers with the text.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "the word or phrase to look for, for example 'error'"},
                },
                "required": ["pattern"]
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_lines",
            "description": "Read lines start to end of the log (at most 60 lines at once).",
            "parameters": {
                "type": "object",
                "properties": {
                    "start": {"type": "integer", "description": "first line number"},
                    "end": {"type": "integer", "description": "last line number"},
                },
                "required": ["start", "end"]
            },
        },
    },
]


class Answer(BaseModel):
    start_line: int
    end_line: int


def run_tool(lines, name, arguments):
    """Run the tool the model asked for and return its text result."""
    try:
        if name == "search_log":
            return search_log(lines, str(arguments["pattern"]))
        if name == "read_lines":
            return read_lines(lines, int(arguments["start"]), int(arguments["end"]))
        return f"Unknown tool '{name}'."
    except Exception as error:   # the model sent bad arguments: tell it, don't crash
        return f"Bad arguments: {error}"


def solve(case):
    """The agent loop for one log. Returns the answer, the list of tool calls, and the prompt size."""
    lines = load_lines(case["log"])
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": f"The log has {len(lines)} lines. Find the lines that explain why the build failed."},
    ]
    trace = []
    for step in range(MAX_STEPS):
        resp = ollama.chat(model=MODEL, messages=messages, tools=TOOLS, think=False, options=OPTIONS)
        message = resp["message"]
        messages.append(message)         # keep what the model said in the conversation
        if not message.tool_calls:       # no tool call means the model has finished looking
            break
        for call in message.tool_calls:
            name = call.function.name
            arguments = dict(call.function.arguments)
            result = run_tool(lines, name, arguments)
            messages.append({"role": "tool", "tool_name": name, "content": result})   # give the result back to the model
            trace.append({"tool": name, "arguments": arguments})

    # one last call without tools, forced into {"start_line": ..., "end_line": ...} like the baseline
    messages.append({"role": "user", "content": "Give your final answer: the first and last line number of the block."})
    resp = ollama.chat(model=MODEL, messages=messages, format=Answer.model_json_schema(), think=False, options=OPTIONS)
    answer = Answer.model_validate_json(resp["message"]["content"])
    return answer, trace, resp["prompt_eval_count"]


def is_hit(case, answer):
    """Correct when the answer overlaps the labelled lines and is not too long (same as baseline.py)."""
    length = answer.end_line - answer.start_line + 1
    overlap = answer.start_line <= case["end_line"] and answer.end_line >= case["start_line"]
    return bool(overlap and 1 <= length <= MAX_ANSWER)


parser = argparse.ArgumentParser()
parser.add_argument("split", choices=["dev", "eval"])
parser.add_argument("--limit", type=int, help="run only N cases (smoke test)")
args = parser.parse_args()

cases = pd.read_json(DATA / f"{args.split}.jsonl", lines=True)
cases = cases.sample(frac=1, random_state=42)   # same order as baseline.py
if args.limit:
    cases = cases.head(args.limit)

solve(cases.iloc[-1])   # warm-up: the first call loads the model, so don't time it

rows = []
for n, (_, case) in enumerate(cases.iterrows(), 1):
    start = time.perf_counter()
    answer, trace, prompt_tokens = solve(case)
    seconds = time.perf_counter() - start
    rows.append({
        "log": case["log"],
        "repo": case["repo"],
        "start_line": case["start_line"],
        "end_line": case["end_line"],
        "predicted_start": answer.start_line,
        "predicted_end": answer.end_line,
        "hit": is_hit(case, answer),
        "in_tail": bool(case["end_line"] > case["log_lines"] - TAIL),
        "steps": len(trace),                 # how many tool calls the model made
        "prompt_tokens": prompt_tokens,
        "seconds": round(seconds, 2),
        "trace": json.dumps(trace),          # every tool call, in order, so you can replay what the model did
    })
    if n % 10 == 0:
        print(f"{n}/{len(cases)} done")

df = pd.DataFrame(rows)
RESULTS.mkdir(exist_ok=True)
name = f"agent_{args.split}" + ("_smoke" if args.limit else "")
df.to_csv(RESULTS / f"{name}.csv", index=False)

summary = {
    "variant": "agent",
    "split": args.split,
    "cases": len(df),
    "hit_rate": round(float(df["hit"].mean()), 3),
    "answer_in_tail": round(float(df["in_tail"].mean()), 3),
    "steps_per_case": round(float(df["steps"].mean()), 1),
    "seconds_per_case": round(float(df["seconds"].mean()), 2),
    "max_prompt_tokens": int(df["prompt_tokens"].max()),   # must stay below num_ctx, or the conversation was cut
}
(RESULTS / f"{name}_summary.json").write_text(json.dumps(summary, indent=2))
end_time = time.perf_counter()
print(json.dumps(summary, indent=2))
elapsed_time = end_time - start_time
print(f"Execution time: {elapsed_time:.6f} seconds")