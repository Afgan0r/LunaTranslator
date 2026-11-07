# Verification and adoption status

## Local pre-push checks

The Windows checkout uses a short Git hook that directly invokes existing
commands. There is no custom Python verification runner or test suite for one.
The checked-in [hook](../../.githooks/pre-push) is the canonical command list.

The hook requires a clean working tree, checks whitespace, runs Markdownlint
on project instructions/engineering docs/skill entrypoints, then runs the
existing synthetic Grisaia unittest suite. Agents run these same existing
commands before completion; run additional affected checks described below.
No skill or memory evaluations are performed.

Install the hook with:

```sh
git config --local core.hooksPath .githooks
```

Inspect an existing `core.hooksPath` and pre-push hook first. Preserve foreign
hooks and stop for explicit integration rather than replacing them.
Installation is local to each checkout. Do not bypass failed checks to push.

The hook checks the checkout and HEAD, not an independently selected Git tree.
Push the same clean HEAD that was checked and reviewed. This local gate is not
remote enforcement and does not replace substantive review or real-host checks.

## Existing program checks

For capture, queue, transport or deployment changes:

```sh
python -X utf8 -m unittest discover -s tests/grisaia -p 'test_*.py'
```

These tests use synthetic dialogue. Journal tests use real temporary SQLite and
worker exclusion; adapter tests use fake Luna/Qt modules; transport tests do not
prove actual API calls or embedded TLS interoperability. Keep those limits
visible in review. Compile changed Python files as required by root instructions.

Native state-machine checks use `tests/grisaia/native/CMakeLists.txt`.
Configure/build outside Git with the matching Windows toolchain and execute
CTest. The full commands and native deployment procedure are in
`docs/grisaia-openai.md`. A pure state-machine pass does not verify executable
fingerprints, memory layouts, hook callbacks or real packet transit.

Native changes require affected MSVC/ATL builds; our own UI changes require
rendered checks of affected states. Apply the engineering contract's
[upstream update acceptance](contract.md#upstream-update-acceptance) instead of
requiring live game/API checks or a tour of imported upstream screens.
Run other required real-boundary scenarios under task-specific authority.
Retain compiler/source/dependency identities and outputs outside Git.
A missing toolchain or real host leaves the affected check awaiting verification.

## Incremental adoption

The local hook is a baseline, not proof of full engineering adoption.
[The engineering contract](contract.md#code-ownership-and-change-scope) defines
the inherited-code, fork-patch and custom-module boundaries before applying
coverage, size, architecture, diagnostics and behavioral requirements. Remaining
formatter/lint/type/dependency/coverage enforcement for custom modules is
adoption work, not an obligation to migrate upstream. A passing hook does not
prove whole-application compliance or satisfy missing applicable checks.

The documented Grisaia runtime is Windows with Python 3.13.13 x64 and an x86
game hook. Preserve inherited older runtime/build capabilities when modifying
shared code; custom support is not inferred from upstream Python 3.7 packaging.

Existing and future independently authored modules, tools, tests and native
adapters retain the full standard when worked on. An upstream update runs
existing regression tests without forcing unchanged custom modules into a new
coverage/size migration. Small patches do not bring whole inherited files into
that denominator. Preserve notices and classify by actual provenance, not by
relabeling inherited code as vendor.

Within affected custom modules, measurement exceptions still require exact
paths, metrics/runtimes, alternative checks, approval and revisit conditions.
Preserve the recovery-specific exception recorded in `docs/grisaia-openai.md`;
the update policy neither revokes it nor expands it to other development.

## Completion evidence

State the fixed base and current result, behavior changed, actual commands and
results, reviewed identity and scopes, and outstanding limitations. Report
source checks, builds, deployment and observed live behavior separately.
Historical checkpoints do not establish present acceptance.

Validate the short hook through actual isolated Git push scenarios and shell
syntax checks. Do not describe these as Python coverage or skill evaluations.
Application test coverage remains a separate obligation.

Use the task's existing report or chat rather than creating a duplicate report.
The project contract and skills must remain usable from this repository alone.
