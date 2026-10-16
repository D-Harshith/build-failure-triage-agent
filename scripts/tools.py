import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOGS = ROOT/ "Dataset"/"LogChunks"/"logs"

MAX_CHARS = 200     # cut very long lines
MAX_MATCHES = 20    # most search results returned at once
MAX_READ = 60       # most lines returned by one read

COLOURS = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")   # terminal colour codes

def load_lines(log):
    text = (LOGS/log).read_text(encoding="utf-8")
    return [COLOURS.sub("", line)[:MAX_CHARS] for line in text.splitlines()]

def search_log(lines, pattern):
    matches = []
    for number, line in enumerate(lines, 1):
        if pattern.lower() in line.lower():
            matches.append(f"{number}: {line}")

    if not matches:
        return f"No lines contain '{pattern}'."
    shown = matches[-MAX_MATCHES:]
    return f"{len(matches)} lines contain '{pattern}'. Showing the last {len(shown)}:\n" + "\n".join(shown)

def read_lines(lines, start, end):
    """Lines start to end, written as '1370: text'. Returns at most MAX_READ lines."""
    if start > len(lines):
        return f"The log has only {len(lines)} lines."
    start = max(start, 1)
    asked_end = min(end, len(lines))
    end = min(asked_end, start + MAX_READ - 1)
    shown = []
    for number in range(start, end + 1):
        shown.append(f"{number}: {lines[number - 1]}")
    if end < asked_end:   # say that we cut it, or the model thinks it has seen everything it asked for
        shown.append(f"(Only lines {start}-{end} shown: the limit is {MAX_READ} lines. Read from line {end + 1} for more.)")
    return "\n".join(shown)
