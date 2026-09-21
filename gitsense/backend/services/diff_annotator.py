"""
Annotates a single-file diff chunk with the NEW file's actual line
numbers, computed deterministically from the @@ hunk header — so the
LLM only has to read off a line number, never calculate one.
"""

import re


def annotate_diff_with_line_numbers(diff_chunk: str) -> str:
    lines = diff_chunk.splitlines()
    output = []
    new_line_num = None

    for line in lines:
        hunk_match = re.match(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@", line)
        if hunk_match:
            new_line_num = int(hunk_match.group(2))
            output.append(line)
            continue

        if line.startswith("diff --git") or line.startswith("index ") or \
           line.startswith("---") or line.startswith("+++"):
            output.append(line)
            continue

        if new_line_num is None:
            output.append(line)
            continue

        if line.startswith("+"):
            output.append(f"[L{new_line_num}] {line}")
            new_line_num += 1
        elif line.startswith("-"):
            output.append(f"[removed]  {line}")
            # removed lines don't consume a new-file line number
        else:
            output.append(f"[L{new_line_num}] {line}")
            new_line_num += 1

    return "\n".join(output)
