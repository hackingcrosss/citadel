---
name: dep-audit
description: Audit Python dependencies in requirements.txt for known CVEs and outdated packages.
disable-model-invocation: true
context: fork
allowed-tools: Bash(pip *), Bash(pip-audit *), Bash(python3 *), Read, Grep
---

# Dependency Audit

Audit the project's Python dependencies for security vulnerabilities and staleness.

## Steps

1. Read `requirements.txt` and note all pinned versions.

2. Run `pip-audit -r requirements.txt --format=json 2>/dev/null || pip-audit -r requirements.txt 2>/dev/null` to check for known CVEs.
   - If pip-audit is not installed, run `pip install pip-audit` first, then retry.

3. For each vulnerability found, report:
   - Package name and installed version
   - CVE ID and severity
   - Fixed version (if available)
   - Whether upgrading would break compatibility (check major version jumps)

4. Check for packages with no pinned version (missing `==x.y.z`) — flag as a supply-chain risk.

5. Check for any package that is 2+ major versions behind latest.

## Output Format

```
## Vulnerabilities Found
| Package | Version | CVE | Severity | Fix Version |
|---------|---------|-----|----------|-------------|
| ...     | ...     | ... | ...      | ...         |

## Unpinned Packages (supply-chain risk)
- package_name (currently resolves to x.y.z)

## Recommended Updates
- package==old → package==new (reason)

## Summary
X vulnerabilities, Y unpinned packages, Z major-version-behind packages
```
