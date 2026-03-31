---
name: pr-ready
description: Pre-PR quality gate — security scan, code hygiene, migration check, and draft PR description.
disable-model-invocation: true
argument-hint: "[base-branch]"
context: fork
allowed-tools: Bash(git *), Read, Grep, Glob
---

# PR Readiness Check

Validate the current branch is ready for a pull request against `$ARGUMENTS` (default: `develop`).

## Context

- Current branch: !`git branch --show-current`
- Commits on branch: !`git log origin/develop..HEAD --oneline`
- Changed files: !`git diff origin/develop --name-only`
- Diff stats: !`git diff origin/develop --stat`

If the user provided a base branch argument, use that instead of `develop` for all git diff/log commands.

## Checks

### 1. Code Hygiene
- [ ] No `console.log` in JS (unless in a debug utility)
- [ ] No `print()` in Python (unless in a migration/CLI script)
- [ ] No `debugger` statements in JS
- [ ] No `import pdb` or `breakpoint()` in Python
- [ ] No `TODO` or `FIXME` comments introduced in this branch
- [ ] No commented-out code blocks added

Search for these in the diff only (not the entire codebase).

### 2. Security Quick Scan
- [ ] No hardcoded secrets, API keys, tokens, or passwords in diff
- [ ] No `.env` file changes staged
- [ ] No `| safe` on user data in new Jinja code
- [ ] No `innerHTML` with unescaped data in new JS code
- [ ] All new routes have `@login_required`
- [ ] All new API mutations check authorization

### 3. Schema & Migration
- [ ] If any model file changed (`app/models/*.py`), check if a `migrate_*.py` script exists for the change
- [ ] If a migration exists, verify it has the idempotency check (column/table existence guard)

### 4. Frontend Consistency (if templates changed)
- [ ] New templates have role gating constants (IS_AUDITOR, IS_WHITE_TEAM, IS_READONLY)
- [ ] New write actions are gated with `!IS_READONLY`
- [ ] Design tokens used (no hardcoded colors)
- [ ] Fetch calls have error handling

### 5. Commit Quality
- [ ] Commit messages are descriptive (not "fix", "update", "wip")
- [ ] No unrelated changes mixed into commits
- [ ] No large binary files committed

## Output

```
## PR Readiness Report

### Status: READY | NOT READY

### Checks
- [x] Code hygiene: clean
- [ ] Security: 2 issues found
  - [HIGH] app/api/foo.py:42 — missing @login_required
  - [LOW] app/templates/bar.html:100 — innerHTML without esc()
- [x] Migrations: not needed
- [x] Frontend: consistent
- [x] Commits: clean

### Suggested PR Title
<short title based on commits>

### Suggested PR Body
## Summary
- <bullet points from commit analysis>

## Test plan
- [ ] <suggested test steps>
```
