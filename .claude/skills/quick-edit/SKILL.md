---
name: quick-edit
description: Fast, low-overhead edits for small well-defined changes. Skips deep analysis — just does the edit.
argument-hint: "<instruction>"
effort: low
allowed-tools: Read, Edit, Glob, Grep
---

# Quick Edit

Perform this change with minimal overhead: **$ARGUMENTS**

## Rules
- Do NOT explore the codebase broadly — only read files directly relevant to the edit.
- Do NOT add comments, docstrings, or type annotations beyond what's needed for the change.
- Do NOT refactor surrounding code.
- Do NOT add error handling unless the edit specifically requires it.
- Make the smallest diff possible that correctly implements the request.
- If the instruction is ambiguous, make the most likely interpretation and state your assumption in one sentence.
