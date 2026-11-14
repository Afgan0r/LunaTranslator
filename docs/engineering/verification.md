# Verification and adoption status

## Local pre-push checks

The checked-in [hook](../../.githooks/pre-push) is the canonical command list.
It invokes the affected-module mechanical checker, Markdownlint and the two
unittest suites directly; application tests are not hidden behind a new runner.

The hook requires a clean working tree, checks whitespace, runs Markdownlint
on project instructions/engineering docs/skill entrypoints, then runs the
engineering-checker fixtures and existing synthetic Grisaia suite. Agents use
these same
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

Prepare the separate developer environment once; it does not modify the embedded
application or global Python packages:

```sh
python -m venv build/engineering-venv
build/engineering-venv/Scripts/python.exe -m pip install -r requirements-engineering.txt
```

On POSIX use `build/engineering-venv/bin/python` for installation. The checker
resolves the platform-specific executables itself. `requirements-engineering.txt`
pins Ruff, Pyright and clang-format; the checker refuses missing or mismatched
tool versions instead of using an unrelated global installation.

Before committing, compare against the task's fixed base:

```sh
python -X utf8 tools/check_engineering.py --base <task-base>
python -X utf8 -m unittest discover -s tests/engineering -p 'test_*.py'
```

`pyproject.toml` owns source discovery, strict Python analysis/lint and formatting
settings, and the physical-line limit. `.clang-format` owns native formatting.
The helper includes committed changes since the base, staged/unstaged changes
and non-ignored untracked files, excluding deleted paths. It checks entire
affected own files, never only changed lines. During pre-push it uses the server's
actual old ref and refuses a candidate other than the checked-out HEAD branch.
New branches compare with their merge base against `origin/main`.

For affected own Python modules it runs Ruff format/check and strict Pyright;
for own native files, clang-format check. The 500-line check follows formatting
and includes own tests and scripts. Compiler/MSVC/ATL checks retain their separate
task-specific acceptance below. Extend the canonical discovery patterns when
adding another owned source class; reviewers verify provenance and completeness.
Inherited files retain their existing style and patch acceptance.

The tool configuration follows [Ruff configuration][ruff] and
[Pyright configuration][pyright]; explicit file arguments select affected files
under the documented [Pyright CLI behavior][pyright-cli]. Native formatting uses
[clang-format style configuration][clang-format]. Sources accessed 2026-11-14.

Demonstrate allowed and violating cases after materially changing a checker,
configuration or discovery: formatting, lint, strict types, native formatting,
500/501 lines, and affected-file discovery. Require the intended diagnostic and
nonzero exit, not an unrelated setup error. Keep synthetic fixtures isolated
from live repositories, credentials and private data.

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
size, architecture, diagnostics and behavioral requirements. Mechanical checks
are configured for affected own modules; unchanged modules are not migrated
merely to enable this gate. No separate architecture checker or coverage quota
is required. A passing hook does not
prove whole-application compliance or satisfy missing applicable checks.

The documented Grisaia runtime is Windows with Python 3.13.13 x64 and an x86
game hook. Preserve inherited older runtime/build capabilities when modifying
shared code; custom support is not inferred from upstream Python 3.7 packaging.

Existing and future independently authored modules, tools, tests and native
adapters follow the fast contract when worked on. An upstream update runs
existing regression tests without forcing unchanged custom modules into a new
size migration. Small patches do not bring whole inherited files into
the own-module scope. Preserve notices and classify by actual provenance, not by
relabeling inherited code as vendor.

There is no mandatory coverage percentage or coverage-exception process.
Historical recovery/redesign measurements remain evidence for their original
tasks. Their independently agreed alternative checks and authority boundaries
are not silently waived by this policy change.

An initial read-only probe of the 34 pre-existing own Python files found 60
Ruff diagnostics, 3111 strict Pyright diagnostics and 34 files needing formatting.
These are measurements before migration, not distinct defect counts or a
passing whole-project result. Existing modules must meet applicable checks when
changed; completing this setup does not claim that they already do.

## Completion evidence

State the fixed base and current result, behavior changed, actual commands and
results, reviewed identity and scopes, and outstanding limitations. Report
source checks, builds, deployment and observed live behavior separately.
Historical checkpoints do not establish present acceptance.

Validate the short hook through actual isolated Git push scenarios and shell
syntax checks. Do not describe these as Python coverage or skill evaluations.
Program behavior tests remain separate from checker controls.

Use the task's existing report or chat rather than creating a duplicate report.
The project contract and skills must remain usable from this repository alone.

## Historical workspace redesign coverage exception

The following describes the earlier task's acceptance and measurements. It is
not a continuing percentage requirement under the current fast contract.

On 2026-11-13 the owner approved a task-specific exception to the full-module
100% coverage target for the repository-centered workspace and shared integration
redesign. It covers:

- `src/LunaTranslator/integrations/*.py`;
- `extensions/grisaia/adapter.py` and `extensions/grisaia/selfbuild.py`;
- `tools/build_native.py`, `tools/workspace.py`, `tools/workspace_build.py`,
  `tools/workspace_migrate.py`, `tools/integration_control.py`, and
  `tools/deploy_grisaia.py`;
- the changed tests under `tests/grisaia` for this redesign.

The accepted alternative is the complete regression suite, independent source
and historical review, real native build, exact journal migration checks,
assembled-application startup, and the agreed live Grisaia capture/translation
and queue-recovery scenario. This exception does not waive any of those checks
or protected history, credential, egress, retry or deployment requirements.

The measured adapter/session/dispatcher and legacy entrypoint reached 100% of
statements and branches. Transport and prompt reached 100%; journal engine and
configuration remained below 100%. The five workspace/control/native tools
measured 97.95% statements and 92.67% branches in the final dedicated run.
The POSIX permission branch was not exercised on Windows. Test-file and
function-level coverage are not claimed. These are partial metric results,
not full-scope 100% coverage. Reconsider this exact exception when these modules
next change; it is not a general exemption for future integrations.

[ruff]: https://docs.astral.sh/ruff/configuration/
[pyright]: https://github.com/microsoft/pyright/blob/main/docs/configuration.md
[pyright-cli]: https://github.com/microsoft/pyright/blob/main/docs/command-line.md
[clang-format]: https://clang.llvm.org/docs/ClangFormatStyleOptions.html
