# Engineering contract

## Scope and authority

Apply this contract to implementation, testing, diagnosis, review, and integration
work in this personal fork. Read the root `AGENTS.md` and the complete
`docs/agent-memory.md` first. The memory contract owns its lifecycle; this
document grants no memory, credential, game, deployment, or publication authority.

Development uses **fast** mode with incremental adoption. Required user behavior
and protected state determine acceptance. Existing code is not automatically
compliant, and old code is not automatically excluded. Record unmet requirements
and exact owner-approved exceptions in the task's existing evidence. Do not
describe partial migration as whole-project compliance.

Use [verification](verification.md) to distinguish executable baseline checks
from migration work. Skills and repository instructions are canonical here;
ordinary tasks do not need the author's private standards or profiles.

## Fast workflow

1. Establish the requested behavior, fixed comparison base, current source
   identity, allowed effects, and applicable checks. Preserve unrelated edits.
2. For a defect, state expected versus observed behavior and a causal hypothesis.
   Check it with the smallest adequate reproduction or inspection before fixing.
   Give the reviewer the hypothesis, observation, result, and remaining uncertainty.
3. Use TDD when practical. Preserve original-defect evidence: a regression test
   fails on the original defect and passes with the fix. Unavailable reproduction
   remains awaiting verification unless the owner approves an exact exception.
4. Run inexpensive applicable checks before longer tests/builds. Run the
   canonical local gate before completion and push. Complete required real-host
   checks separately; a passing local gate does not replace them.
5. Obtain independent combined code/test review and separate historical-risk
   discovery as defined by `lunatranslator-review`. After fixes, the primary
   reviewer checks the fixes, affected behavior, dependencies, tests, and evidence.
6. Accept only when the requested scenario works, mandatory evidence is complete
   and passing on the current result, and effects stay within the agreed risk
   boundary. Disclose other confirmed noncritical limitations with their effects.

Track one active wall clock across investigation, implementation, builds, tests,
agent work/waiting, review, and fixes; exclude waiting for the owner. At 20 minutes,
stop new work, report results and remaining obstacles, and ask whether to reduce
scope or continue. Wait for an explicit decision. Subtasks and agents do not reset
the clock. Leave time to stop running operations safely.

Mutation tests, fuzz campaigns, and benchmarks require a concrete owner request
or separate approval of their need, scope, and budget. Ordinary behavioral,
property, failure/recovery, coverage, and required integration checks retain
their obligations. Do not run skill or memory evaluations; `AGENTS.md` owns that
restriction. Structural validation and substantive review remain applicable.

## Responsibilities and dependencies

<!-- markdownlint-disable MD013 -->

| Boundary | Responsibility and allowed direction |
| --- | --- |
| `translator/grisaia/prompt.py` | Pure message construction and archived-run semantics; no UI, persistence, or transport effects |
| `translator/grisaia/engine.py` | Journal, ordering, history, run boundaries, duplicate policy, worker ownership and recovery; no Qt or deployment dependency |
| `translator/grisaia/transport.py` | Configuration, guarded egress, credential access, request and response handling; may consume the engine's error contract, never UI/adapters |
| `extensions/grisaia/selfbuild.py` | Luna/Qt adapter, packet validation, worker lifecycle and publication; consumes core and transport |
| Existing Luna bridge sites | Optional integration before the ordinary queue, lifecycle forwarding and translator replacement; preserve unrelated translators |
| `GrisaiaWindowState.h` | Pure occurrence/presentation state and packet construction, independent of Win32 and Python |
| `GrisaiaWindows.h` and `CatSystem.cpp` | Game-specific executable/instruction guards, host-thread reads and hook attachment |
| `tools/deploy_grisaia.py` | Canonical deployment bridge list, manifest, digests, backups and refusal of independent modifications |
| Other tools and launcher | Explicit controls, extraction, patch lifecycle or runtime startup; consume existing contracts rather than duplicate them |

<!-- markdownlint-enable MD013 -->

Review dependency edges even when a static tool cannot resolve dynamic forwarding
or cross-language calls. Such edges need producer/consumer fixtures and required
real-boundary evidence. A graph or successful import alone does not prove them.

Carry suitable invariants in types and preserve them through construction and
updates, so consumers can use established guarantees without repeating checks.
For external or changing conditions, state the guarantee's actual boundary and
lifetime.

Keep cohesive responsibilities and hide decisions callers need not know. Extract
helpers when an existing responsibility warrants them; no hypothetical second
consumer is required. Avoid splitting files while retaining the same coupling.
Choose mechanisms from this Python/Qt/C++ application, without adding a framework
or rewriting inherited software solely to match a language preference.

Owned source, tests, and service scripts have a 500-physical-line limit after the
canonical formatter, counting comments and blanks. Generated output, verified
third-party code, documentation and data are distinct categories; generators and
mixed authored files remain owned. Over-limit code needs cohesive decomposition
or an exact approved exception. Do not compress lines, delete useful behavior or
change formatting to evade the limit. Current formatting and enforcement gaps
are listed in [verification](verification.md).

## Behavior and recovery

Preserve upstream capabilities outside the requested change. The Grisaia durable
queue contract applies to that integration, not every upstream translator.
For other games, establish their own engine and executable evidence.

- Validate external input at its actual boundary: supported forms, semantic
  constraints, malformed-input behavior, and resource bounds.
- Give persistent state one owner. Define commit/publication boundaries, partial
  failures, compatibility, cancellation, and recovery before changing them.
- Define duplicate recognition, retry ownership and limits for repeated work;
  define ordering, stale-result handling and bounded pending work for concurrency.
- Preserve Grisaia's committed originals/translations, full history, FIFO queue,
  immutable prompt and manual run markers. An uncertain API outcome requires
  manual retry; no automatic provider/model substitution or silent shortening.
- Keep network calls outside journal locks. Publish only results still belonging
  to the active translator/window. A replacement worker cannot publish stale work.
- Define units, valid ranges, precision and rounding for changed calculations.
- Review algorithmic cost, memory, request counts and unbounded growth. Do not
  claim an unmeasured performance improvement.

An ordinary application error or a disclosed noncritical defect can be tolerated
within the requested scenario's agreed boundary. Loss of protected history,
secret disclosure, unauthorized requests, or unsafe replacement of deployed files
is outside that boundary. Keep the existing safe-stop/manual-recovery behavior;
new retry, continuation, destructive recovery, or changed persistence semantics
needs an owner decision, not an inference from fast mode.

## Tests and evidence

Test observable outcomes and independently established expectations, including
meaningful boundaries and failures. Assertions about mocked wiring alone do not
establish behavior. Before changing a failing expectation, determine whether the
implementation, expectation, or agreed behavior is wrong. Review weakened/deleted
tests, fixtures, exclusions and discovery as well as new assertions.

The target is 100% of every applicable coverage metric over all owned executable
code, including adapters, error paths, tests and scripts. Inventory files that
tests never import, target/runtime combinations, lines/statements, functions,
branches and other supported counters. A default coverage report is insufficient.
Unsupported measurement requires an exact code/metric/runtime exception with
mandatory alternative evidence; never label alternatives as measured 100%.
Incremental adoption does not itself approve exclusions or lower this target.

Use implementation-independent properties when meaningful input/action domains
exist. Changes to persistent state, cancellation, repeated work or external
systems need failure/recovery checks. When separately approved, mutation/fuzz
work must identify dangerous mechanisms, useful inputs, independent oracles,
actual discovery, budgets and incomplete outcomes; fuzz preparation/build and
execution have separate budgets. Keep reproducible synthetic failures.

## Diagnostics and real boundaries

Ordinary runs must retain significant transitions, decisions/reasons, attempts,
rejections, failures and outcomes with safe operation identities. Pure decisions
return outcomes/reasons; the actual execution boundary records them. Preserve
causes and give each final error record one owner rather than logging the same
exception in every layer. Record handled degradation too.

Keep secrets and dialogue corpora out of ordinary diagnostics; translation
journals remain private primary state. Review diagnostic record size, volume,
buffering, access, rotation and retention without truncating translation history.
Existing resource/diagnostic policy gaps remain migration work, not permission
to delete data or silently change failure behavior. For new unattended behavior,
resolve detection, notification, recipient and response ownership before
adding it.

Verify materially changed diagnostics by executing a controlled ordinary scenario
and finding correlated events in their final accessible destination. Do not add
a remote monitoring service solely to satisfy this local application contract.

Changes to Qt publication/lifecycle, embedded Python dependencies, native packet
transit, hook attachment, launcher behavior, or deployment require the affected
real boundary in addition to isolated tests. Native changes need matching
MSVC/ATL builds; capture changes also need the native state-machine tests.
UI changes require rendered evidence of affected states. Follow
`docs/grisaia-openai.md` for Grisaia procedures and external runtime boundaries.

If a required host, build, measurement or review source is unavailable, prepare
the candidate and a reproducible procedure, continue independent work, and report
awaiting verification. Acceptance waits for that evidence or an exact approved
exception. Historical live checkpoints are leads, not present acceptance.
