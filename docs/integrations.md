# Local workspace and game integrations

## Workspace layout

The working repository owns the source and the commands used to assemble the
application. Generated files and personal data are excluded from Git:

<!-- markdownlint-disable MD013 -->
| Directory | Contents | Lifetime |
| --- | --- | --- |
| `src/LunaTranslator` | Application and shared integration source | Versioned |
| `src/NativeImpl` | Native application and capture components | Versioned |
| `extensions/grisaia` | Grisaia capture adapter and legacy entrypoint | Versioned |
| `build` | Compiler output, dependency cache and previous assembled versions | Rebuildable |
| `dist` | Complete runnable application assembled from this source | Rebuildable |
| `.local` | Workspace settings, Luna user configuration and game journals | Persistent |
<!-- markdownlint-enable MD013 -->

Building and launching are separate. Launch never updates source, compiles code,
or replaces the prepared application. Deleting `build` or `dist` does not delete
`.local`. Preserve `.local` before replacing or deleting the checkout itself.

## Responsibilities

<!-- markdownlint-disable MD013 -->
| Component | Responsibility |
| --- | --- |
| `integrations/configuration.py` | Validate game profiles, merge defaults and overrides, locate game data |
| `integrations/luna.py` | Resolve the current Luna game profile and publish active results |
| `integrations/session.py` | Own one game's worker and its lifecycle |
| `integrations/engine.py` | Durable FIFO journal, history, context checkpoints and recovery |
| `integrations/prompt.py` | Construct translation and context messages |
| `integrations/transport.py` | Guarded API connection, credentials, requests and response validation |
| `extensions/grisaia/adapter.py` | Validate Grisaia capture packets, occurrence identities and diagnostic hooks |
<!-- markdownlint-enable MD013 -->

The common engine does not interpret native Grisaia packets or access Qt. The
adapter supplies complete original text and occurrence identities; the Luna
bridge owns presentation. Existing `translator.grisaia` imports remain aliases
to the shared modules for compatibility, rather than a second implementation.

One application serves all game profiles. A profile with a configured adapter
uses its own journal and context. Unconfigured games retain Luna's ordinary
capture path. A recognized but invalid integration profile blocks custom capture
with an error instead of silently passing its text to the ordinary lossy queue.

Switching games stops new requests for the old game. An already-sent request can
finish and commit, but cannot publish into the newly active game. Its remaining
queue resumes when that game becomes active again. Uncertain requests require
manual Retry. Switching is not an automatic retry or a new playthrough.

## Configuration and controls

`.local/config.json` has schema version `1`, common `defaults`, and `profiles`
keyed by the existing Luna game UID. Each profile specifies `adapter`, an absolute
`game_exe`, and its `settings` overrides. Nested settings merge recursively.
The Grisaia migration explicitly retains all its existing settings, including
model/effort and credential-file field selection.

Persistent game files live under `.local/games/<uid>`. Each journal keeps its
original prompt, cache identity, complete dialogue history, run markers and
context checkpoints. No summary rebuild or API request occurs during migration.
API credentials remain referenced through their existing private file; their
values do not belong in repository source or documentation.

Controls use the same profile resolver as the application:

```text
python -X utf8 tools/integration_control.py --game <uid> status
python -X utf8 tools/integration_control.py --game <uid> retry
python -X utf8 tools/integration_control.py --game <uid> new-run
python -X utf8 tools/integration_control.py --game <uid> select-model <model> <effort>
```

Status contains queue metadata, not dialogue or credentials. Retry remains an
explicit operation. Use New Run for an older save or a new playthrough; it
preserves previous history. No new management screens are added to Luna.

## Prepare, build and launch

The first assembly needs an existing compatible portable runtime as its
dependency template, matched x64 native outputs and the verified Grisaia hook.
The template is copied into the local build cache. Cache/user configuration and
translation records are not imported into the disposable application payload.

<!-- markdownlint-disable MD013 -->
```text
python -X utf8 tools/build_native.py
python -X utf8 tools/workspace.py build --runtime-template <runtime-root> --native-dir <x64-output> --hook-dir <hook-output>
python -X utf8 tools/workspace.py migrate --legacy-home <legacy-home>
python -X utf8 tools/workspace.py launch
```
<!-- markdownlint-enable MD013 -->

`Build.cmd` runs the native builder and application assembly. After bootstrap,
the builder reuses the recorded local inputs. `Start Luna.cmd` only launches the
prepared `dist` application. Native compilation uses the matching MSVC toolchain;
optional machine-specific CMake/ATL/dependency paths belong in the ignored
`.local/native-toolchain.json`. Native output provenance records source and
binary hashes. Changed native source requires a new matching build.

Assembly checks the previous runtime manifest before changing anything, refuses
independently modified files, stages the complete application and retains the
previous version for rollback. Luna configuration and cache use `.local`
directories supplied by the launcher, rather than disposable `dist` directories.
Discovered interface-language entries are cached under `.local/userconfig/lang`;
packaged translations remain authoritative after source updates.

Migration uses SQLite backup, including committed WAL contents, and verifies all
tables, rows and schema. It keeps the established game UID and original source
installation. Existing destination state causes refusal rather than merging or
overwriting histories. The initial migration does not sweep or delete the legacy
home; historical artifacts require the separate archival transfer below.

## Archived legacy installation

The remaining legacy files are preserved under `.local/legacy-grisaia`, including
benchmark evidence, historical checkpoints, the former journal and patch rollback
materials. This archive is private persistent data, excluded from Git. Its
`relocation-locator.json` identifies the relocated metadata and records historical
validation gaps; `relocation-original-inventory.json` records the exact original
file hashes. Original metadata is retained under `relocation-originals`.

Relocated locators use the archive paths. Parent hashes are refreshed only when
the original reference matched; pre-existing stale hashes and missing evidence
remain explicitly recorded. They are not made valid merely by moving them.
Historical compiler caches and logs remain evidence rather than current build
inputs. Current builds use `build` and the workspace's own dependency template.

The archive's Start, Status, Retry and New Run wrappers use the current workspace.
Its `Rollback Patches.cmd` uses the retained patch manifest; running it is a
separate explicit action that changes the installed game. The Windows Start menu
shortcut named LunaTranslator launches the workspace with its prepared runtime.
Preserve the archive together with the rest of `.local` when replacing a checkout.

## Verification

Run the canonical repository checks and the existing synthetic regression suite.
Relevant tests cover old imports, configuration isolation, game switching,
in-flight completion, cancellation before paid requests, SQLite migration,
modified-runtime refusal, staging rollback and separate launch behavior.

Source tests do not establish the actual embedded Python/native/game crossing.
This redesign additionally requires startup of the assembled application and a
short agreed Grisaia capture/translation/recovery scenario after the build is
ready. Report source, native build, migration, startup and live acceptance
evidence separately. The upstream-update acceptance policy remains distinct.

On 2026-11-13 the assembled Windows application passed the live Grisaia check:
one captured window survived an egress failure and restart, then completed after
the owner's explicit Retry; two subsequent windows were translated and reported
visible by the owner. The journal advanced from 5,440 to 5,443 completed
translations in the existing run, with no pending head. A further graceful Luna
restart preserved those results while the game stayed open. The synthetic suite
passed 139 tests and the implementation received independent source and
historical review; inaccessible pull-request discussions remain a review gap.

The initial egress failure exposed an assembly defect: excluding all `.pyc`
files removed the embedded runtime's required `stringprep.pyc`. Assembly now
preserves standalone bytecode and excludes `__pycache__`. The dependency seed
was recreated from the validated original, its dependency bytes were checked,
and the actual embedded client's guarded HTTPS preflight passed before Retry.
