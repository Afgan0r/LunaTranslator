---
name: lunatranslator-tests
description: Write or review tests and verify LunaTranslator behavior, coverage, regression, and recovery. Use for «проверь тесты LunaTranslator» and related project verification, not skill or memory evaluations.
---

# LunaTranslator tests

## Establish the evidence

Read root `AGENTS.md`, `docs/agent-memory.md`, `docs/engineering/contract.md`,
and `docs/engineering/verification.md`. Follow the memory contract and
authority boundaries. Read `docs/grisaia-openai.md` for Grisaia, deployment,
or recovery. Use `lunatranslator-integrations` when a changed boundary needs
host or cross-language evidence.

Fix the comparison base and behavior under test. Derive expected outcomes from
an independent contract, example, or property; exercise observable results,
including meaningful boundary and failure/recovery cases. Use synthetic
dialogue. Bug fixes require TDD: run the regression and observe the original
failure before implementing the fix, then observe it pass. For other work,
prefer TDD where useful. If reproduction is unavailable, report
awaiting verification unless an exact exception is approved. Investigate
before changing a failing expectation. Review removed or weakened assertions,
fixtures, exclusions, and discovery.

## Verify and report

Resolve affected modules through the engineering contract's ownership scope.
There is no mandatory coverage percentage or metric-exception process. Report
only actual measurements. Test changed behavior, significant boundaries/failures
and the requested scenario with independent expectations; choose methods for
their concrete risks. Unchanged coverage debt does not block a task. Preserve
separately agreed acceptance checks. For upstream updates, run existing regression
tests without requiring migration of unchanged custom modules.

Request intermediate test review only for complex scenarios, disputed expectations
or substantial test changes, using the review skill's configured role. Within
TDD, complete that conditional review before implementation. The final primary
reviewer always reviews test meaning, deletions, expectations and discovery.

Run the existing checks declared by `.githooks/pre-push` once, plus any
additional affected checks in `docs/engineering/verification.md` that
the hook does not cover.
Distinguish synthetic tests from actual
Qt, embedded runtime, native, game, API, and deployment evidence. Record
commands, results, source identity, missing checks, and their effect on
acceptance. Mutation, fuzz, and benchmark campaigns require explicit scope and
budget approval.
Apply the contract's Upstream update acceptance before requiring live game/API
checks. Those checks are excluded during updates even when integration changed;
report the exclusion without claiming live behavior passed.
