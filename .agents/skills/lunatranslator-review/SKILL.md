---
name: lunatranslator-review
description: Independently review LunaTranslator changes and historical risks, including «проверь изменения LunaTranslator» and substantive task completion. Excludes unrelated project code and skill or memory evaluations.
---

# LunaTranslator review

## Fix the review surface

Read root `AGENTS.md`, `docs/agent-memory.md`, `docs/engineering/contract.md`,
and `docs/engineering/verification.md`. Read `docs/grisaia-openai.md` when
Grisaia, deployment, or recovery is affected. Apply `lunatranslator-tests` and
`lunatranslator-integrations` to their relevant scopes. Establish the original
task, fixed base, reviewed source identity, complete diff, allowed effects,
and mandatory evidence. If requirements are missing, retrieve the original
task; withhold the requirements verdict until sufficient evidence exists. A
sufficient original task does not need an additional specification.
Classify the reviewed code through the engineering contract's ownership scope.
Do not demand whole-file compliance for small upstream patches or coverage/size
migration of unchanged custom modules during updates. Use its Upstream update
acceptance when assessing build, deployment, startup, UI and excluded live checks.

## Independent discovery

Dispatch one independent read-only primary reviewer in a fresh context:
`gpt-6.1-sol` / `high`. Give each applicable reviewer the
full task, fixed base, source identity, exact applicable source/reference
list, scope, and evidence requirements, without the other's endorsed findings.
If the runtime cannot provide the required reviewers, report the missing
review and withhold acceptance. The main agent owns live state and mutations.

The primary reviews the whole task: requirements, code, tests, contracts,
architecture/dependencies, performance/resource growth, diagnostics, affected
boundaries and actual evidence against the fixed identity. Review the fast
contract without importing additional strict gates or using a bug-only scan.

Use `gpt-6.1-sol` / `low` for intermediate test review only when scenarios are
complex, expectations are disputed, or test changes are substantial. Within
TDD, perform that conditional review before implementing the specified behavior.

Dispatch a separate `gpt-6-luna` / `high` historical reviewer only for a concrete
question: an unexplained restriction, possible repeated defect, or behavior
whose preservation needs history. It investigates relevant Git
history, available pull-request discussions, and moved logic for regressions
or lost decisions; report inaccessible history or discussions as evidence
gaps. The primary attempts to confirm or disprove each historical candidate
and labels it confirmed, suspected, rejected, or a gap, with evidence. A
separate verifier, mandatory fanout or closing saturation assignment is not
required. Do not substitute a different model/effort for unavailable required
review; report it incomplete. The routing in this section is canonical.

## Recheck and decide

After fixes, reuse the assignments to review affected behavior, dependencies,
tests, and the actual changed scope against the resulting identity. Report
findings with concrete evidence and impact, review coverage, remaining
uncertainty, and required checks. Accept only when the requested scenario,
mandatory evidence, and risk boundary in the engineering contract pass.
Disclose noncritical limitations with their effects; missing mandatory
evidence is not a passing review.
