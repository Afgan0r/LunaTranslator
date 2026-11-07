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
dialogue. For a defect, demonstrate the regression fails on the original
defect and passes with the fix; if reproduction is unavailable, report
awaiting verification unless an exact exception is approved. Investigate
before changing a failing expectation. Review removed or weakened assertions,
fixtures, exclusions, and discovery.

## Measure and report

Apply the full owned-code denominator and 100% target for every applicable
counter, including tests and scripts, as defined in the engineering contract.
Inventory unimported files and relevant runtimes. An unsupported metric needs
an exact code/metric/runtime exception and alternative evidence; never present
an alternative as measured coverage. Incremental adoption does not approve
exclusions.

Run the existing checks declared by `.githooks/pre-push` once, plus any
additional affected checks in `docs/engineering/verification.md` that
the hook does not cover.
Distinguish synthetic tests from actual
Qt, embedded runtime, native, game, API, and deployment evidence. Record
commands, results, source identity, missing checks, and their effect on
acceptance. Mutation, fuzz, and benchmark campaigns require explicit scope and
budget approval.
