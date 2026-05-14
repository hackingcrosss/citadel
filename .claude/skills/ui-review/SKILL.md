---
name: ui-review
description: Audit an Citadel template for accessibility, responsive design, role gating, XSS, and visual consistency.
argument-hint: "<template-name>"
context: fork
allowed-tools: Read, Grep, Glob
---

# UI Review

Audit the template `app/templates/$ARGUMENTS` for frontend quality issues.

If `$ARGUMENTS` does not end in `.html`, append `.html`. If the file doesn't exist, search `app/templates/` for a close match.

## Review Categories

### 1. Role Gating Compliance
- Verify the JS role constants are present at the top of the script block:
  `IS_AUDITOR`, `IS_WHITE_TEAM`, `IS_READONLY`, `ACTIVE_PROJECT_ID`, `ACTIVE_PROJECT_CODE`
- Verify ALL write actions (create/edit/delete buttons, form submits) are gated with `!IS_READONLY`
- Verify header-level action buttons use Jinja gating: `{% if current_user.role not in ['auditor', 'white_team'] %}`
- Flag any write action that is NOT gated

### 2. XSS Prevention
- Flag any `innerHTML` assignment with unescaped dynamic data
- Check for an `esc()` helper function if HTML strings are built dynamically
- Flag any `| safe` Jinja filter on user-controlled data
- Flag inline event handlers with string interpolation

### 3. Design Token Compliance
- Flag any hardcoded colors (hex values like `#1f2937`, `rgb(...)`) that should use `var(--ir-*)` tokens
- Exception: colors inside SVG icons or third-party widget overrides are acceptable
- Check card/table/badge patterns match the conventions in `base.html`

### 4. Accessibility
- Check all `<img>` tags have `alt` attributes
- Check icon-only buttons have `aria-label`
- Check tables have `<thead>` with `<th>` elements
- Check form inputs have associated `<label>` elements or `aria-label`
- Check modals have `aria-labelledby` pointing to their title
- Check color contrast: text on `var(--ir-surface)` background should use `var(--ir-text)` not `var(--ir-text-dim)`

### 5. Responsive Design
- Check for Bootstrap grid usage (`col-md-*`, `col-lg-*`) on layout sections
- Flag fixed-width elements that would break on mobile (`width: 800px` etc.)
- Check tables have `table-responsive` wrapper
- Check modals use appropriate sizing (`modal-lg`, `modal-xl`) for their content

### 6. Fetch Error Handling
- Every `fetch()` call must have a `.catch()` handler
- Every response must check `data.error` before processing success
- Every error response must check `data.upgrade_required` for plan gating
- Flag any `fetch()` without error handling

### 7. Consistency with Other Templates
- Compare patterns against `base.html` and 2-3 sibling templates
- Flag deviations in: modal structure, toast usage, badge classes, table styling, button styling

## Output Format

For each finding:
```
[CRITICAL|HIGH|MEDIUM|LOW] Line N — Category
Issue: Description
Fix: Specific recommendation
```

End with a summary: `X issues (Y critical, Z high, ...)`
