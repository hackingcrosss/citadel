---
name: template-xss-review
description: Review Citadel Jinja templates and inline JavaScript for XSS and unsafe rendering. Use when changes touch app/templates, dynamic tables/modals, email or landing page previews, Initial Access pages, user-controlled content, innerHTML, Jinja safe filters, or JSON injection into scripts.
argument-hint: "[template files or base-branch]"
context: fork
allowed-tools: Read, Grep, Glob, Bash(rg *), Bash(git *)
---

# Template XSS Review

Review templates and inline JavaScript for unsafe rendering of user-controlled or provider-controlled data.

## High-Risk Areas

- Initial Access pages: targets, intel, email templates, landing pages, campaigns, FOFA/discoveries.
- Admin/user/company/project pages that render names, notes, scope, ROE, contacts, or descriptions.
- Provider data from DNS, cloud, Docker, NPM, GoPhish, Cobalt Strike, scanner, FOFA, and CDN APIs.
- HTML previews for generated websites, landing pages, and email templates.

## Checklist

1. Search changed templates for:
   - `| safe`
   - `innerHTML`
   - `insertAdjacentHTML`
   - template literals building HTML
   - inline event handlers such as `onclick="..."`
   - Jinja variables inside `<script>` blocks
2. Confirm Jinja variables in JavaScript use `|tojson`, not string interpolation.
3. Confirm dynamic table/modal/card builders escape data before injecting into HTML.
4. Prefer `textContent` for plain text updates.
5. If HTML rendering is intentional, confirm input is trusted, sanitized, sandboxed, or isolated in preview-only context.
6. Confirm generated email/landing-page HTML is not mixed into the app DOM without containment.
7. Confirm URLs placed into `href`, `src`, or fetch calls are validated or encoded.
8. Confirm no user/provider string is inserted into inline JavaScript handlers.

## Acceptable Patterns

Plain text:

```javascript
cell.textContent = item.name || '';
```

JSON from Jinja to JS:

```javascript
const ACTIVE_PROJECT_CODE = {{ active_project.code | tojson if active_project else 'null' }};
```

HTML builder only when every dynamic value is escaped:

```javascript
row.innerHTML = `<td>${esc(item.name)}</td>`;
```

## Common Findings

- `{{ value }}` inside JavaScript strings instead of `{{ value | tojson }}`.
- API data inserted with `innerHTML` without an `esc()` helper.
- `|safe` used for notes, names, scope, FOFA/scanner results, or provider metadata.
- Modal body populated with raw provider error/detail text.
- Generated HTML preview rendered directly in the admin app DOM.

## Output

Lead with findings:

```text
[HIGH] app/templates/ia_targets.html:220
Issue: Target name from API is inserted via innerHTML without escaping.
Fix: Use textContent or escape dynamic values before building HTML.
```

If no issues are found, state whether the review covered only changed files or all templates.
