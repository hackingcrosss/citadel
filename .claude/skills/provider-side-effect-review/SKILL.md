---
name: provider-side-effect-review
description: Review Citadel external provider mutations for wrong-account use, unsafe side effects, missing cleanup, weak error handling, non-idempotency, secret leakage, and missing audit logs. Use for AWS, Azure, Hetzner, Cloudflare, Azure DNS, CDN, Docker, NPM, Mailgun, GoPhish, Cobalt Strike, scanner, FOFA, or website deployment changes.
argument-hint: "[provider files or base-branch]"
context: fork
allowed-tools: Read, Grep, Glob, Bash(rg *), Bash(git *)
---

# Provider Side-Effect Review

Review code that changes external systems.

## What Counts As A Side Effect

- Creating, updating, deleting, starting, stopping, rebooting, or terminating cloud resources.
- DNS/SSL/security rule changes.
- NPM proxy host/certificate/redirection changes.
- Mailgun domain/SMTP changes.
- GoPhish profile/template/group/page/campaign changes.
- Cobalt Strike listener changes.
- Docker container lifecycle changes.
- CDN distribution create/update/disable/delete.
- Website/landing page deploy or teardown.
- External scanner/FOFA job triggers.

## Checklist

1. Confirm the provider account `label` is accepted, validated, and passed through every service call.
2. Confirm credentials are read only through `credential_service`.
3. Confirm state-changing endpoints require auth, write permission, project scoping, and feature gates where applicable.
4. Confirm external mutations are not performed on GET requests.
5. Confirm idempotency:
   - Does retrying create duplicates?
   - Can the code detect existing resources?
   - Is cleanup possible after partial failure?
6. Confirm provider IDs are persisted locally when future cleanup or sync needs them.
7. Confirm error handling returns user-safe messages and logs useful non-secret context.
8. Confirm audit logging exists for successful sensitive mutations.
9. Confirm secrets are not logged, returned, or stored in task metadata.
10. Confirm destructive actions require explicit target IDs and do not operate on broad filters accidentally.

## High-Risk Patterns

- Dropping `label` and silently using `default`.
- Creating DNS/NPM/CDN resources in multiple systems without rollback notes or stored IDs.
- Retrying a create task without checking existing provider state.
- Returning raw provider exception bodies to the frontend.
- Deleting resources based only on display name.
- Mutating resources before project authorization is checked.

## Output

Lead with findings:

```text
[HIGH] app/services/cdn_service.py:123
Issue: Create task can duplicate distributions on retry.
Fix: Store provider request/resource ID before retry or look up by deterministic comment/name.
```

If no issues are found, state what providers/files were reviewed and whether live provider behavior was not tested.
