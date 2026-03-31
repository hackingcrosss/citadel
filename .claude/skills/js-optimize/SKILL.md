---
name: js-optimize
description: Analyze a template's inline JavaScript for dead code, redundant DOM queries, missing error handling, and deduplication opportunities.
argument-hint: "<template-name>"
context: fork
allowed-tools: Read, Grep, Glob
---

# JavaScript Optimization Review

Analyze the `<script>` block in `app/templates/$ARGUMENTS` for optimization opportunities.

If `$ARGUMENTS` does not end in `.html`, append `.html`.

## Analysis Steps

### 1. Dead Code Detection
- Find functions defined but never called within the template
- Find variables assigned but never read
- Find event listeners bound to elements that don't exist in the HTML
- Find code paths behind conditions that can never be true (e.g., `if (false)`)

### 2. Redundant DOM Queries
- Flag repeated `document.getElementById()` or `document.querySelector()` calls for the same selector — should be cached in a variable
- Flag DOM queries inside loops or frequently-called functions (like table renderers)
- Flag `querySelectorAll` results that are iterated multiple times

### 3. Fetch Pattern Issues
- Flag `fetch()` calls missing `.catch()` error handler
- Flag `fetch()` calls not checking `data.error` in the response
- Flag `fetch()` calls not checking `data.upgrade_required`
- Flag duplicate fetch calls to the same endpoint that could be consolidated
- Flag fetch calls in loops that could be batched into a single API call

### 4. Performance
- Flag large HTML string concatenation in loops — suggest `DocumentFragment` or array `.join('')`
- Flag `setInterval` without corresponding cleanup
- Flag expensive operations (DOM manipulation, large array operations) inside scroll/resize handlers without debouncing

### 5. Deduplication Opportunities
Search other templates (`app/templates/*.html`) for similar patterns:
- Nearly identical fetch+render functions
- Duplicated modal handling logic
- Duplicated table rendering functions
- Duplicated toast/notification patterns
Report which functions appear in 3+ templates and could be extracted to a shared JS file.

## Output Format

For each finding:
```
[DEAD_CODE|REDUNDANT|FETCH|PERF|DEDUP] Line N
Issue: Description
Fix: Specific code suggestion
Savings: Estimated lines/bytes saved or performance impact
```

End with: `Total: X findings (Y actionable, Z informational)`
