---
name: sec-review
description: Deep security review of branch changes against develop. Checks OWASP Top 10, auth bypasses, credential leaks, XSS, SQLi, and Citadel-specific patterns.
argument-hint: "[base-branch]"
context: fork
allowed-tools: Bash(git *), Read, Grep, Glob
---

# Security Review

Review all code changes on the current branch for security vulnerabilities.

## Context

- Current branch: !`git branch --show-current`
- Diff stats: !`git diff origin/develop --stat`

If the user provided a base branch argument, use that instead of `develop` for all git diff commands below.

## Full diff

!`git diff origin/develop`

## Review Checklist

Analyze every changed file against these categories. Skip categories that don't apply to a given file.

### 1. Authentication & Authorization
- [ ] Every new route has `@login_required`
- [ ] Admin routes have `@admin_required`
- [ ] Project-scoped routes have `@project_member_required(write=True/False)`
- [ ] Feature-gated routes have `@feature_required('feature_name')`
- [ ] No direct object access without ownership/membership check
- [ ] No privilege escalation paths (e.g., operator modifying admin-only fields)

### 2. Injection
- [ ] No string formatting in SQL queries (must use SQLAlchemy ORM or bound params)
- [ ] No `eval()`, `exec()`, `os.system()`, or unsanitized `subprocess` calls
- [ ] No shell=True in subprocess calls with user input
- [ ] No f-string or .format() in shell commands

### 3. XSS (Templates)
- [ ] No `| safe` filter on user-supplied data in Jinja
- [ ] No `innerHTML` assignment with unescaped API data in JS
- [ ] HTML string builders use an `esc()` function for dynamic values
- [ ] No inline event handlers with unescaped data (`onclick="fn('${userInput}')"`)

### 4. Credential Handling
- [ ] No plaintext secrets in code, configs, or comments
- [ ] All credential reads go through `credential_service.get_credential()`
- [ ] No credentials logged at any level
- [ ] No credentials returned in API responses (unless explicitly a credential endpoint)
- [ ] No hardcoded API keys, tokens, or passwords

### 5. Input Validation
- [ ] API endpoints validate `request.get_json()` is not None
- [ ] Type/length/format validation on all user inputs
- [ ] Hostname inputs validated against RFC-1123 regex
- [ ] File uploads validated (extension, MIME, size) if applicable
- [ ] URL/redirect targets validated (no open redirects)

### 6. Data Exposure
- [ ] No stack traces or internal errors leaked in API responses
- [ ] Error responses use generic messages, not exception details
- [ ] No database model objects returned directly (must use `.to_dict()`)
- [ ] No sensitive fields (password_hash, encrypted_*) in serialized output

### 7. CSRF / Session
- [ ] State-changing operations use POST/PUT/DELETE (not GET)
- [ ] No session fixation vectors

### 8. Citadel-Specific
- [ ] Multi-account label validated against `get_account_labels(provider)`
- [ ] Celery tasks don't access `current_user` or `request` context
- [ ] Plan/feature checks can't be bypassed by direct API calls
- [ ] Domain checkout ownership respected in mutations

## Output Format

For each finding:
```
[CRITICAL|HIGH|MEDIUM|LOW|INFO] file_path:line_number
Issue: One-line description
Evidence: The vulnerable code snippet
Fix: Specific remediation recommendation
```

Group findings by severity. End with a summary count: `X critical, Y high, Z medium, W low, V info`.

If no issues found, state: "No security issues found in the reviewed changes."
