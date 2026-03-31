---
name: explore-feature
description: Map all files related to a feature and return a concise summary. Keeps heavy exploration out of main context.
argument-hint: "<feature-name>"
context: fork
allowed-tools: Read, Grep, Glob
---

# Feature Explorer

Map all code related to the feature: **$ARGUMENTS**

## Search Strategy

1. **Identify keywords** — derive 3-5 search terms from the feature name (e.g., "c2 deployments" → `cobaltstrike`, `listener`, `orchestration`, `teardown`, `c2`)

2. **Find all related files** by searching:
   - `app/api/` — API endpoint modules
   - `app/services/` — Business logic
   - `app/models/` — Database models
   - `app/templates/` — Frontend templates
   - `app/tasks/` — Celery async tasks
   - `app/utils/` — Utility modules
   - `app/routes.py` — Page routes
   - Migration scripts (`migrate_*.py`)

3. **For each file found**, extract:
   - File path and line count
   - Key functions/classes/routes defined
   - Dependencies on other project files
   - External API calls (Cloudflare, AWS, Mailgun, etc.)

4. **Map the data flow**: API endpoint → service function → model → external API

## Output Format

```
## Feature: $ARGUMENTS

### Files
| File | Role | Key Functions | Lines |
|------|------|---------------|-------|
| ...  | ...  | ...           | ...   |

### Data Flow
[endpoint] → [service function] → [model/external API]

### Database Tables
- table_name: relevant columns

### Frontend
- Template: template_name.html
- Key JS functions: func1(), func2()
- API calls made: GET /api/..., POST /api/...

### Dependencies
- External: [cloudflare, aws, etc.]
- Internal: [credential_service, plan_service, etc.]
```

Keep the output under 150 lines. Focus on structure, not implementation details.
