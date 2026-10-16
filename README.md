# Build-failure triage agent

Can a small local LLM find *why* a CI build failed better by searching the log with tools than by reading only the end of the log?

**Result:** on 60 repos it was never tuned on, the tool-using agent tied the simple baseline: **83/180 vs 85/180 hits, McNemar p = 0.88**, at 1.9× the time per log. The agent finds errors the baseline cannot see (6 vs 0), but it is less precise on errors that are already in the last 150 lines (77 vs 85). On the 20 repos used for tuning, the agent had looked clearly better (113/199 vs 94/199, p = 0.003). That gain did not carry over to new repos.

## Task and data

- **Data:** [LogChunks](https://zenodo.org/records/3632351) (Brandt et al., MSR 2020): 797 failed Travis CI logs from 80 GitHub repos in 29 languages. Each log has a hand-labelled *chunk*: the lines that explain the failure.
- **Task:** given a failed log, return the first and last line number of the block that explains the failure.
- **Logs are long:** across the 379 logs in the two sets, the median log is 1,492 lines and the longest is 38,940, so the whole log does not fit in the model's context.
- **Finding the labelled lines:** the dataset gives the chunk text, not line numbers. `scripts/explore_labels.ipynb` finds each chunk in its log after stripping everything except letters and digits. A plain text search finds only 528 of the 797 chunks because of terminal escape codes; the stripped search finds all 797.

## Split: by repo, frozen before any tuning

Logs from the same repo are near-copies, so the split is by repo, not by log (`random_state=42`):

| set | repos | logs | used for |
|---|---|---|---|
| `Dataset/dev.jsonl` | 20 | 199 (all of their logs) | building and tuning the agent |
| `Dataset/eval.jsonl` | the other 60 | 180 (3 per repo) | one final run of the frozen agent |

## The two systems

Both use the same model and settings: `qwen3:8b` (Q4_K_M) in Ollama 0.30.8, temperature 0, 16,384-token context, thinking off, running on an Apple M5 MacBook with 16 GB. Colour codes are removed, lines are cut to 200 characters, every line is shown as `1370: text`, and the final answer is forced into JSON `{"start_line", "end_line"}` with a schema.

- **Baseline** (`scripts/baseline.py`): one call that sees the last 150 lines of the log.
- **Agent** (`scripts/agent.py`, `scripts/tools.py`): the model starts with only the number of lines in the log. It has two tools:
  - `search_log(pattern)`: case-insensitive search; returns the last 20 matching lines with their line numbers.
  - `read_lines(start, end)`: returns at most 60 lines, and says so when it had to cut the range.

  It may make up to 8 rounds of tool calls, then gives a final JSON answer. Every tool call is saved in the `trace` column of the results.

**Scoring:** a *hit* means the answer overlaps the labelled lines and is 1–50 lines long. Agent and baseline answer the same logs, so they are compared with an exact McNemar test on the logs where only one of them is right.

## Results

| set | system | hits | only this system right | McNemar p | answer above the last 150 lines | answer in the last 150 lines | seconds per log |
|---|---|---|---|---|---|---|---|
| dev (tuned on) | baseline | 94/199 (47.2%) | 10 | | 0/68 | 94/131 | 16.4 |
| dev (tuned on) | agent v2 | **113/199 (56.8%)** | 29 | 0.003 | 12/68 | 101/131 | 29.0 |
| **eval (unseen)** | baseline | **85/180 (47.2%)** | 22 | | 0/54 | 85/126 | 14.2 |
| **eval (unseen)** | agent v2 | **83/180 (46.1%)** | 20 | **0.88** | 6/54 | 77/126 | 27.0 |

- With 180 logs, a hit rate can move by about ±7 points by chance alone.
- The agent averaged 3.5 tool calls per eval log. Its largest prompt was 15,700 tokens, under the 16,384 limit.

### What happened while tuning on dev

| version | change | dev hits | only agent right / only baseline right |
|---|---|---|---|
| v1 | first agent | 96/199 | 28 / 26 (p = 0.89) |
| v2 | fixed a typo in the tool schema (`typn` → `type`); `read_lines` says when it cuts a range | 113/199 | 29 / 10 (p = 0.003) |

- **The typo mattered:** with the broken `read_lines` schema, all 199 v1 runs began with `search_log("error")`, and 142 stopped after one search and one read. With the fixed schema, 170 of 199 runs began by reading the end of the log.
- **The silent cut mattered too:** in v1, 59 of 299 reads asked for more than 60 lines and were cut without the model being told. Example: the model asked for lines 3000–3318, got 3000–3059, and never saw the answer at 3249.
- **Two more ideas were each tried on 16 dev logs and rejected:**
  - A prompt hint ("the end is often only a summary; search for 'fail'") won 1 of 8 earlier misses and lost 3 of 8 earlier hits.
  - Merging repeated lines in search results won 0 of 8 and lost 2 of 8.

### Why the dev gain did not hold

- Of the +19 net gain on dev, 16 came from just 3 repos; shellcheck alone gave +8 and git gave −6.
- Because logs within a repo are near-copies, dev is really about 20 independent samples, not 199. A version that suits those 20 repos need not suit others. The 60 unseen eval repos showed it does not.

## Failure modes (eval)

1. **Off by a few lines.** In 10 of its 22 eval losses, the agent was shown the labelled lines but answered just next to them (git-extras: answer 863–865, agent 867). The baseline sees all 150 lines at once and gets the edges right.
2. **Stops after the end of the log.** 35 of 180 runs read only the end of the log and then answered, even when the error was further up.
3. **Chooses the summary over the error.** Example from dev, RxJava: the agent answered line 1511 (`11072 tests completed, 1 failed`) instead of line 1171 (`publishNoLeak FAILED` plus the assertion).
4. **Wanders.** 24 eval runs used all 8 rounds of tool calls; only 5 of them were hits.

## One replayed trace: an eval win the baseline could not get

`Elixir/elixir-lang@elixir/failed/572202401.log`: 963 lines; the labelled answer is lines 713–715. The baseline answered 932–935, because 713 is not in its last 150 lines.

```text
read_lines(903, 963)   -> 903: Compiled lib/elixir/lib/code.ex ...            (end of the log: no error)
search_log("error")    -> 11 lines contain 'error'. Showing the last 11: ...
read_lines(713, 728)   -> 713: ** (CompileError) (for doctest at) lib/list.ex:102: undefined function i/1
answer: 713-717        -> hit (3 tool calls, 33 s)
```

## Next idea (not yet run)

- **Hybrid:** give the agent the same last 150 lines as the baseline in its first message, and keep the tools for searching further up. The aim is to keep the baseline's precision near the end and add the agent's reach.
- It would be tuned on dev and then tested on a *fresh* sample: 3 unused logs from each of the 60 eval repos (418 are left). The current eval set has now been used, so it cannot be reused.

## How to run

```bash
uv venv --python 3.12 && source .venv/bin/activate
uv pip install pandas ollama pydantic ipykernel
ollama pull qwen3:8b
ollama serve                      # leave running in a second terminal
```

- Download LogChunks from [Zenodo](https://zenodo.org/records/3632351) and unzip it to `Dataset/LogChunks/`.
- `Dataset/dev.jsonl` and `eval.jsonl` are the frozen split, made by `scripts/explore_labels.ipynb`.

```bash
cd scripts
python baseline.py dev --limit 20   # quick check; writes results/baseline_dev_smoke.csv
python baseline.py dev              # about 1 hour
python agent.py dev                 # about 1.5 hours
```

- Open `scripts/compare.ipynb` and set `SPLIT = "dev"` or `"eval"`. It shows the agreement table, the McNemar test, hits split by where the answer is, and time and tokens per log.

## Files

| path | what it is |
|---|---|
| `scripts/explore_labels.ipynb` | loads the labels, finds each chunk's line numbers, makes the frozen split |
| `scripts/baseline.py` | baseline: one call on the last 150 lines |
| `scripts/tools.py` | `load_lines`, `search_log`, `read_lines` |
| `scripts/agent.py` | the agent loop, with tool schemas and a trace of every call |
| `scripts/compare.ipynb` | agent vs baseline: agreement table, McNemar test, breakdowns |
| `results/` | one CSV row per log, plus a summary JSON for each run (`agent_dev_v1`, `agent_dev_v2`, `*_eval`) |
