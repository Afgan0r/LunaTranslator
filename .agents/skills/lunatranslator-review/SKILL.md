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

## Independent discovery

Dispatch two read-only reviewers in fresh independent contexts: primary
`gpt-6.1-sol` / `high`, and historical `gpt-6-luna` / `high`. Give each the
full task, fixed base, source identity, exact applicable source/reference
list, scope, and evidence requirements, without the other's endorsed findings.
If the runtime cannot provide the required reviewers, report the missing
review and withhold acceptance. The main agent owns live state and mutations.

The primary reviews requirements, code, tests, contracts, and actual evidence
against the fixed identity. The historical reviewer investigates relevant Git
history, available pull-request discussions, and moved logic for regressions
or lost decisions; report inaccessible history or discussions as evidence
gaps. The primary attempts to confirm or disprove each historical candidate
and labels it confirmed, suspected, rejected, or a gap, with evidence. A
separate verifier or further fanout is not required by fast mode.

## Recheck and decide

After fixes, reuse the assignments to review affected behavior, dependencies,
tests, and the actual changed scope against the resulting identity. Report
findings with concrete evidence and impact, review coverage, remaining
uncertainty, and required checks. Accept only when the requested scenario,
mandatory evidence, and risk boundary in the engineering contract pass.
Disclose noncritical limitations with their effects; missing mandatory
evidence is not a passing review.
