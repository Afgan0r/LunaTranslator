---
name: lunatranslator-conventions
description: Implement, refactor, or debug LunaTranslator Python, Qt, native code, and tools. Use for project code changes, including «исправь код LunaTranslator»; not generic translation prose or unrelated projects.
---

# LunaTranslator conventions

## Load and establish scope

Read root `AGENTS.md`, `docs/agent-memory.md`, `docs/engineering/contract.md`,
and `docs/engineering/verification.md` before substantive work. Follow the
memory contract and applicable authority boundaries. Read
`docs/grisaia-openai.md` when Grisaia, deployment, or recovery is involved.
Use `lunatranslator-integrations` for affected integration boundaries and
`lunatranslator-tests` for behavioral verification.

Establish the requested behavior, fixed comparison base, source identity,
allowed effects, and applicable checks. Inspect the smallest relevant
neighboring source and tests for existing patterns. Preserve unrelated
changes. For a defect, state expected and observed behavior and a causal
hypothesis; check it before editing and retain evidence and uncertainty for
review.

## Implement and verify

Apply the engineering contract's responsibilities, dependency directions,
protected behavior, diagnostics, and fast workflow to the changed scope. Keep
game-specific identity and capture rules within their adapters. Resolve
ordinary implementation choices from current evidence; obtain owner approval
for new obligations, policies, exceptions, or changed protected behavior.

Run the existing checks declared by `.githooks/pre-push` once, plus any
additional affected checks in `docs/engineering/verification.md` that
the hook does not cover. Use `lunatranslator-review` for substantive
completion. Separate code checks from native builds, deployment,
and observed live behavior. Missing mandatory checks or real-boundary evidence
leave acceptance awaiting verification or an exact owner-approved exception;
existing adoption gaps are not evidence of compliance.
