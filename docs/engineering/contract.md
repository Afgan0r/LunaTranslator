# Engineering contract

## Scope and authority

Apply this contract to implementation, testing, diagnosis, review, and integration
work in this personal fork. Read the root `AGENTS.md` and the complete
`docs/agent-memory.md` first. The memory contract owns its lifecycle; this
document grants no memory, credential, game, deployment, or publication authority.

Development uses **fast** mode with the code-ownership scope below. Required
user behavior and protected state determine acceptance. Record unmet applicable
requirements and exact owner-approved exceptions in the task's existing evidence.
Do not describe partial adoption as whole-project compliance.

Use [verification](verification.md) to distinguish executable baseline checks
from migration work. Skills and repository instructions are canonical here;
ordinary tasks do not need the author's private standards or profiles.

## Code ownership and change scope

Classify code by provenance and responsibility, not its directory or whether
Git marks it added or changed:

- **Inherited upstream code:** preserve its structure and style. Do not refactor,
  split, reformat, or add coverage solely to meet this fork's engineering
  standards. The 500-line cap and 100% coverage target do not apply to it,
  including code imported by an upstream merge.
- **Fork patches in inherited files:** keep the patch small and verify its
  changed behavior and integration. A bridge, bug fix, or conflict resolution
  does not require migrating the surrounding file to the full standard.
- **Independently authored extensions:** apply the full standard to existing
  and future custom modules when working on them, including their adapters,
  tests and tools. This includes the Grisaia core under `src/LunaTranslator`,
  `extensions/grisaia`, and custom native helpers. A copied or moved upstream
  file does not become independently authored code merely by changing its path.

Keep substantial new extension logic separate from upstream integration sites
where practical. Do not hide a new custom subsystem in an inherited file to
evade its own obligations. Preserve attribution and notices; inherited project
code is not relabeled as vendor or generated code.

For an upstream update, unchanged custom modules need their existing regression
tests, not a new migration to coverage or size compliance. When a custom module
is changed, apply the full requirements to that affected module and its relevant
tests/adapters, rather than only the edited lines. Preserve existing approved
exceptions and their exact scope and revisit conditions. This boundary does not
waive failed regression tests or claim that unchanged modules are compliant.

## Upstream update acceptance

An explicit request to update upstream includes preparing the installed version
for use: merge while preserving fork changes, run the canonical gate and
applicable synthetic regression checks, build the native targets needed by the
new version, deploy through the existing manifest-managed tools with backups,
and verify startup of the updated installed Luna. A source merge, commit, push,
or successful build alone is not a completed application update. A request
explicitly limited to source work retains that narrower scope.

Do not run live game or real translation-API acceptance checks during an
upstream update, even when capture or translation integration changed. The owner
accepts discovering functional regressions during ordinary use and requesting
a separate repair. These unperformed checks do not block update acceptance;
report them as not performed, never as passed. Perform the startup check without
triggering game capture or real translation requests. Unavailable build,
deployment, or startup evidence still leaves the update incomplete.

Do not tour imported upstream screens. Rendered checks apply to UI behavior
changed by our own patches or extension work and only its affected states.
These update-specific acceptance rules take precedence over the general
real-boundary requirements below. They do not waive protected-state, credential,
deployment-integrity, review, or applicable automated-test requirements.

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
| `integrations/prompt.py` | Pure message construction and archived-run semantics; no UI, persistence, or transport effects |
| `integrations/engine.py` | Journal, ordering, history, run boundaries, duplicate policy, worker ownership and recovery; no Qt or deployment dependency |
| `integrations/transport.py` | Configuration, guarded egress, credential access, request and response handling; may consume the engine's error contract, never UI/adapters |
| `integrations/configuration.py` | Profile validation, shared defaults, overrides and isolated game-data paths |
| `integrations/session.py` and `integrations/luna.py` | Shared worker lifecycle and Qt publication bridge; consume core, transport and game adapters |
| `extensions/grisaia/adapter.py` | Game-specific packet validation, capture identities and diagnostic hooks |
| `extensions/grisaia/selfbuild.py` | Legacy entrypoint; consumes the shared session and Grisaia adapter |
| Existing Luna bridge sites | Optional integration before the ordinary queue, lifecycle forwarding and translator replacement; preserve unrelated translators |
| `GrisaiaWindowState.h` | Pure occurrence/presentation state and packet construction, independent of Win32 and Python |
| `GrisaiaWindows.h` and `CatSystem.cpp` | Game-specific executable/instruction guards, host-thread reads and hook attachment |
| `tools/deploy_grisaia.py` | Canonical deployment bridge list, manifest, digests, backups and refusal of independent modifications |
| `tools/workspace_build.py` and `tools/workspace_migrate.py` | Repository-local assembly, source/native provenance, staged activation and exact journal migration |
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

Independently authored source, tests, and service scripts in the applicable
change scope have a 500-physical-line limit after the canonical formatter,
counting comments and blanks. Generated output, verified third-party code,
documentation and data are distinct categories; custom generators remain owned.
Use the ownership rules above for mixed inherited files. Over-limit code needs
cohesive decomposition or an exact approved exception. Do not compress lines,
delete useful behavior or
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

For independently authored modules in the applicable change scope, the target
is 100% of every applicable coverage metric over their executable code, including
adapters, error paths, tests and scripts. Inventory files that
tests never import, target/runtime combinations, lines/statements, functions,
branches and other supported counters. A default coverage report is insufficient.
Unsupported measurement requires an exact code/metric/runtime exception with
mandatory alternative evidence; never label alternatives as measured 100%.
The ownership and unchanged-module boundaries above determine applicability;
they do not turn unmeasured coverage into a pass or lower this target within
an affected independently authored module.

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
Our own UI changes require rendered evidence of affected states. Apply
the upstream-update acceptance above before requiring game/API evidence. Follow
`docs/grisaia-openai.md` for Grisaia procedures and external runtime boundaries.

If a required host, build, measurement or review source is unavailable, prepare
the candidate and a reproducible procedure, continue independent work, and report
awaiting verification. Acceptance waits for that evidence or an exact approved
exception. Historical live checkpoints are leads, not present acceptance.
