---
name: frontend-conventions
description: InfraRed frontend conventions — Bootstrap 5 patterns, role gating, modals, toasts, fetch patterns, design tokens. Auto-loaded when editing templates or static files.
user-invocable: false
paths:
  - "app/templates/**/*.html"
  - "app/static/**/*.js"
  - "app/static/**/*.css"
---

# InfraRed Frontend Conventions

Apply these rules when writing or modifying templates and static assets.

## Template Structure

1. **All pages extend `base.html`**:
   ```jinja
   {% extends "base.html" %}
   {% block title %}Page Name - InfraRed{% endblock %}
   {% block content %}
   ...
   {% endblock %}
   ```

2. **No external CSS/JS beyond what `base.html` already loads** (Bootstrap 5.3, Bootstrap Icons 1.11, vis-network for infra_map only). All custom styles go inline in `<style>` within `{% block content %}`.

3. **Page-specific JS goes in a `<script>` block at the bottom** of `{% block content %}`, not in a separate file.

## Role Gating (mandatory for action pages)

4. **Inject role constants at the top of the script block**:
   ```javascript
   const IS_AUDITOR = {{ 'true' if current_user.role == 'auditor' else 'false' }};
   const IS_WHITE_TEAM = {{ 'true' if current_user.role == 'white_team' else 'false' }};
   const IS_READONLY = IS_AUDITOR || IS_WHITE_TEAM;
   const ACTIVE_PROJECT_ID = {{ active_project.id if active_project else 'null' }};
   const ACTIVE_PROJECT_CODE = {{ active_project.code | tojson if active_project else 'null' }};
   ```

5. **Gate all write actions** (create/edit/delete buttons, forms, action columns):
   - JS: `if (!IS_READONLY) { /* render button */ }`
   - Jinja (for header buttons): `{% if current_user.role not in ['auditor', 'white_team'] %}`

6. **Project-scoped tagging** — when rendering resource lists with project tags, include the untag icon only for non-readonly users:
   ```javascript
   (canUntag && !IS_READONLY
     ? '<i class="bi bi-x-circle text-muted" style="cursor:pointer;font-size:0.8rem" onclick="untagResource(...)"></i>'
     : '')
   ```

## Design Tokens

7. **Always use CSS custom properties** from `base.html :root` — never hardcode colors:
   ```
   Primary red:    var(--ir-red)        Background:  var(--ir-bg)
   Surface:        var(--ir-surface)    Surface 2:   var(--ir-surface-2)
   Border:         var(--ir-border)     Border 2:    var(--ir-border-2)
   Text:           var(--ir-text)       Muted:       var(--ir-text-muted)
   Green:          var(--ir-green)      Yellow:      var(--ir-yellow)
   Blue:           var(--ir-blue)       Orange:      var(--ir-orange)
   ```

8. **Card styling** follows this pattern:
   ```css
   .card {
     background: var(--ir-surface);
     border: 1px solid var(--ir-border);
     border-radius: 8px;
   }
   ```

9. **Table styling** — use Bootstrap's `.table` class with dark overrides:
   ```css
   .table { color: var(--ir-text); }
   .table th { color: var(--ir-text-muted); font-weight: 600; border-color: var(--ir-border); }
   .table td { border-color: var(--ir-border); vertical-align: middle; }
   .table-hover tbody tr:hover { background: var(--ir-red-dim); }
   ```

## Fetch Pattern

10. **All API calls use this pattern**:
    ```javascript
    fetch('/api/resource', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload)
    })
    .then(r => r.json())
    .then(data => {
      if (data.error) {
        if (data.upgrade_required) { showUpgradeToast(data.error); return; }
        showToast(data.error, 'danger');
        return;
      }
      // success handling
      showToast('Success message', 'success');
    })
    .catch(err => showToast('Network error', 'danger'));
    ```

11. **Always check `data.upgrade_required`** on error responses — this triggers plan upgrade prompts.

12. **Always check `data.error`** before processing success data.

## Toast Notifications

13. **Use `showToast(message, type)`** — types: `success`, `danger`, `warning`, `info`. This function is defined in `base.html` and available globally.

## Modals

14. **Use Bootstrap 5 modals** with this ID pattern: `#createModal`, `#editModal`, `#detailModal`, `#confirmModal`.
15. **Modal backdrop**: always use `data-bs-backdrop="static"` for forms (prevent accidental close).
16. **Reset form state** when opening modals — clear previous values and validation states.

## Status Badges

17. **Use consistent badge classes** for resource states:
    ```
    Running/Active/Healthy:  badge bg-success
    Stopped/Inactive:        badge bg-secondary
    Pending/Starting:        badge bg-warning text-dark
    Error/Failed/Terminated: badge bg-danger
    ```

## Auto-Refresh

18. **Dashboard and list pages auto-refresh every 30 seconds** using `setInterval`. Always clear interval on page unload.
19. **Preserve user scroll position and selection** across refreshes — store state before refresh, restore after.

## Accessibility Baseline

20. **All interactive elements must have a `title` attribute** or visible label.
21. **Icon-only buttons must have `aria-label`**.
22. **Tables must have `<thead>` with scope attributes**.

## XSS Prevention

23. **Never use `innerHTML` with user-supplied data** — use `textContent` for text, or build DOM elements programmatically.
24. **When building HTML strings for table rows** (common pattern in this codebase), escape dynamic values:
    ```javascript
    function esc(s) { 
      const d = document.createElement('div'); 
      d.textContent = s; 
      return d.innerHTML; 
    }
    ```
    Use `esc()` on any value that came from an API response before inserting into HTML strings.
