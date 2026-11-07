# Grisaia OpenAI deployment

This branch adds an opt-in, durable translation queue for the English Steam
edition of *The Fruit of Grisaia*. The custom translator is installed as
`userconfig/selfbuild.py`; runtime files, credentials, game text and journals
stay outside Git.

## Source provenance and updates

The original repository history is preserved. `upstream` points to
[HIllya51/LunaTranslator](https://github.com/HIllya51/LunaTranslator).
The personal branch is `main`; the earlier `grisaia-openai` branch remains
in local history. `origin` points to
[Afgan0r/LunaTranslator](https://github.com/Afgan0r/LunaTranslator).
Upstream updates require an explicit request. Unless explicitly source-only,
that request includes the installed-version workflow in
[Upstream update acceptance](engineering/contract.md#upstream-update-acceptance).
Binary releases are not part of this personal workflow.

The supplied x64 ZIP matches source revision
`2f65c65eb2f6ea6584a4210a982f64412df071cd`, version `12.0.0.1`:
all 235 packaged Python files match after line-ending normalization. ZIP
SHA-256: `4b93035ee7029a7f2cf70ddd669c9c13b20c391b3a2c8c2ca18aaff9bfa65988`.
This comparison does not independently establish native binary build provenance.

Integrate updates through a merge, after checking for local changes:

```sh
git fetch --prune upstream
git switch main
git merge upstream/main
python -X utf8 -m unittest discover -s tests/grisaia -v
```

Match a new runtime ZIP to its source before deployment. Review the three
bridge sites and native hook for compatibility after updates; the custom engine
remains separate. Follow the engineering contract's code-ownership scope;
an update does not require restructuring inherited files.

## Local fork behavior

The interface is fixed to English. Translation languages remain independent,
and other localization assets remain in the source tree. Existing interface
settings are migrated to English at startup without changing source or target
translation languages. Grisaia deployment also selects English UI.

The original binary updater is disabled at startup and shutdown, including
installation of previously cached upstream packages. The language selector
and update controls are removed from About; theme controls remain available.
Updates consist of an explicitly requested source merge, checks, native build
where needed, and manifest-managed deployment to the existing private runtime,
followed by startup verification of that installed version. Live game and real
translation-API checks are excluded from upstream-update acceptance even when
integration code changes. Functional regressions noticed during use are handled
in a separately requested repair. Do not claim unperformed live checks passed.

The local launcher permits modified files without a confirmation dialog.
It retains startup failures for missing required Python files, a missing
interpreter, and an invalid signature on a signed launcher. Generate the
required-file header from the current source before building; keep the header,
native output, compiler/dependency identities and build logs outside Git.

<!-- markdownlint-disable MD013 -->
```text
python -X utf8 src/scripts/createsigexe.py header <private-build>/checksigs.hpp
cmake -S src/NativeImpl -B <private-build>/launcher -G "Visual Studio 17 2022" -A x64 -DBUILD_EXEC_ONLY=ON -DWIN10ABOVE=ON -DLUNA_OUTPUT_DIRECTORY=<private-build>/bin -DLUNA_CHECKSIGS_HEADER=<private-build>/checksigs.hpp
cmake --build <private-build>/launcher --config Release --target LunaTranslator LunaTranslator_admin
python -X utf8 tools/deploy_grisaia.py --home <private-home> --game-dir <installed-game> --launcher-dir <private-build>/bin
```
<!-- markdownlint-enable MD013 -->

Use matching MSVC and x64 ATL headers/libraries when configuring the launcher.
Deployment validates both supplied EXEs as x64 PE files and retains originals
and installed hashes in the existing runtime manifest. A source edit or a
successful build alone is not proof of runtime deployment or live capture.

## External installation

Use an absolute private directory outside the checkout, restricted to the
Windows user and SYSTEM. Extract the matched ZIP into
`<private-home>/runtime/LunaTranslator_x64`. Keep the API key in an independent
text file and reference its absolute path in the private `settings.json`.
Do not read `.env`, `.env.*` or `.secrets` without exact-file authorization.

The supplied runtime omits `_ssl` and `stringprep`, which its packaged IDNA
codec requires for HTTPS hostnames. The deployment tool supplies `_ssl.pyd`,
its two OpenSSL dependencies and `stringprep.pyc` from the
[official Python 3.13.13 amd64 embeddable archive](https://www.python.org/downloads/release/python-31313/).
It checks the published archive SHA-256 and requires an exact match of
`python313.dll`; it does not replace Luna's interpreter. The TLS binaries and
their license remain outside Git.

<!-- markdownlint-disable MD013 -->
```text
python -X utf8 tools/deploy_grisaia.py --home <private-home> --game-dir <installed-game> --python-embed <official-python-archive>
```
<!-- markdownlint-enable MD013 -->

Deployment records original bridge backups and installed digests in the
private runtime manifest. An independently modified deployed file stops an
update. The generated `Start Luna.cmd` sets the private home and capture route.

Private settings include `key_file`, explicit HTTP `proxy` host/port,
`expected_country`, optional `expected_region`, `geo_host`, `model`,
`reasoning_effort`, `game_exe`, `hook_code`, `capture_protocol`, and
`hook_validated`. Each new
client checks its own HTTPS CONNECT route before reading the key or calling
OpenAI. Successful checks are committed to the private `egress.jsonl` before
credential access. Proxy credentials are optional. Redirects, direct fallback and
automatic retries are disabled.

## Game patches and rollback

The selected components from
[Ultimate's patch publication](https://www.reddit.com/r/vns/comments/zpzlpf/the_ultimate_fruit_of_grisaia_patches/)
are HCG `update98.int` and Movie `UNRATED & HCG/update97.int`.
Both archive READMEs were read. Bundled completed saves are excluded. The
base executable and assets remain unchanged and the game script stays English.

The HCG README warns that saves from other versions can crash; use New Game
for initial acceptance. Patch installation backs up existing targets, records
hashes before copying and verifies every installed file. `Rollback Patches.cmd`
preflights every target and backup before restoring the original file state.
Changed files cause a refusal before any restore.

## Capture and history

Credentials can come from a standalone text file or a shared JSON file outside
Git. For JSON, set `key_file` to its absolute path and explicitly select
`key_field`: `OPENAI_API_KEY_WITH_SHARING` or
`OPENAI_API_KEY_WITHOUT_SHARING`. Only the selected value is used; a missing,
empty or invalid field stops the request without trying another credential.
The client reads credentials only after its egress check succeeds.

The Steam executable is fingerprinted before attaching `GrisaiaScript`,
`GrisaiaControl` and `GrisaiaWindows`. The validated hook observes the
scenario separator command as its generation signal. Its active `str[0]` and
`name[0]` model aliases identify the body and speaker; their presentation IDs
can change when the game recreates its windows. The native hook reads the engine's
model registry and requires text models with a shared owner and distinct IDs.
Presentation messages track layout rebuilding separately. A snapshot
immediately after
complete layout generation reads both glyph vectors on the game's thread.
The packet carries an empty name for narration and a native session/serial ID.
Closing the game's backlog can clear and repopulate the same presentation;
that rebuild keeps its serial. A later script occurrence advances it, even
when its text is identical. Rebuilt snapshots carry a separate render revision
so a manual new-run marker can accept a loaded save with unchanged text.
This avoids reading a mutable game buffer after the host has received an event.
The executable hash and instruction-byte guards prevent attaching these fixed
addresses to a different executable.

The supported private setting is `capture_protocol: "grisaia-windows-v1"`.
The adapter consumes other streams of this game and submits only complete
`GrisaiaWindows` packets. Native IDs suppress duplicate delivery across an
adapter restart and backlog restoration. A malformed packet or changed original
under an already used identity pauses API processing and is retained in a
private capture-fault log; later valid windows remain durably queued.

The ordinary Luna queue can discard waiting jobs when newer text arrives.
An optional bridge intercepts native hook output before that queue and passes
it directly to the custom translator. Other translator queues retain their
upstream behavior.

The journal uses SQLite WAL, full synchronous commits and an OS worker lock.
Captures commit immediately while a single worker translates in FIFO order.
Completed translations and queued originals survive a restart. An interrupted
in-flight request becomes uncertain and needs manual retry, because it may
already have been billed. A stopped worker cannot replace a newer overlay.

Every request contains the immutable developer instructions, run markers,
the retained context described below, and the current original.
Prior assistant translations use the documented plain-text assistant-message
form in [conversation state](https://developers.openai.com/api/docs/guides/conversation-state)
(accessed 2026-11-06), preserving the text and role without input-only blocks.
Queued future text is excluded. The original prompt is pinned in the journal;
changing it in place is refused. Only the current window is translated, with
prior runs treated as archived context rather than plot knowledge.

`New Run.cmd` appends a manual new-playthrough / older-save marker without
removing history. Use it before advancing after a replay or loading an older
save. `Retry.cmd` releases the failed head only; subsequent captured windows
remain queued. `Status.cmd` shows queue counts without corpus or credentials.
Context overflow pauses with an explicit message; journal history is never deleted.
Free-credit exhaustion does not trigger a model or provider change. Paid
requests continue according to the account's billing settings.

## Benchmark and selected configuration

Fifteen consecutive windows from the active patched opening were tested with
all earlier opening context, using identical instructions and inputs. Candidate
translations were excluded from benchmark context to keep model comparisons
identical; production uses paired original/translation history.

| Model | Effort | Median (s) | Input | Output | Reasoning | Est. USD |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| gpt-6-astra | low | 3.110 | 10394 | 608 | 95 | 0.134340 |
| gpt-6-astra | medium | 6.531 | 10394 | 1704 | 1169 | 0.189140 |
| gpt-5.6-terra | low | 2.735 | 10394 | 1065 | 548 | 0.033568 |
| gpt-5.6-terra | medium | 2.516 | 10394 | 1376 | 453 | 0.037300 |

Output counts include reasoning tokens. Latency is measured by the client and
excludes its earlier egress check. Costs are estimates from measured usage at
the published standard rates, not account invoices or credit consumption.
Sources: [Astra model](https://developers.openai.com/api/docs/models/gpt-6-astra),
[Terra model](https://developers.openai.com/api/docs/models/gpt-5.6-terra).

All requests contained 503–901 input tokens and reported zero cached tokens.
[Prompt caching](https://developers.openai.com/api/docs/guides/prompt-caching)
starts at 1024 tokens. Longer production history preserves its prefix unchanged
for cache reuse; cache hits are measured rather than assumed.

The user selected **gpt-6-astra / low**. Both Astra settings translated the
current windows consistently. Terra low repeated a previous translation once;
Terra medium translated the accumulated history once. Full originals, outputs,
per-request usage, latency and costs are retained privately under logical
artifact ID `grisaia-opening-benchmark-v1`. Its stable locator is
`F:\LunaTranslator-Grisaia\artifact-locator.json`; the corpus is not in Git.

## Verification and remaining acceptance

Queue order, concurrent capture, errors, exact-request retry, process restart,
run boundaries, immutable prefixes, egress guards and patch rollback have
automated tests using synthetic dialogue. The deployed Luna successfully loads
the custom translator and creates its private journal.

The custom native state machine also has a C++ test for generation changes,
redraws, identical later utterances, empty names and JSON escaping. Python tests
exercise native packet deduplication and speaker clearing against a real journal.

**The separator hook passed the live advancement/backlog check.** Four complete
snapshots carried serials `1, 1, 1, 2` and scenario counters `2, 2, 2, 4`:
two backlog restores retained the original identity, and the next spoken
window advanced it. Narration had an empty speaker; the next window correctly
identified Policeman. Earlier UI-command and frame-setter candidates failed;
ordinary source replacement and append operations also occurred on backlog
restoration and could not identify new occurrences. Temporary stack and
model-writer tracing has been removed, with evidence retained privately.
The older
`HSFN932#-4@B2721:Grisaia.exe` script-reader hook was rejected because it captures
commands and repeated out-of-order reads. The built-in character hook matches
visible bodies but leaves its last name in the hook list after the game has
cleared that name's glyph vector. Its raw events remain private diagnostics.
The verified checkpoint is `grisaia-scenario-separator-passed-live-v1` at the
stable private locator above. The installed hook is enabled. Forty-one verified
opening windows from two observed game runs were imported in order after
comparison with the installed English script. Diagnostic rebuilds were excluded.

An intentionally unavailable proxy stopped the first request before OpenAI;
three subsequent captures were retained while paused. Restoring the proxy did
not retry automatically. Restart also preserved the stopped queue. A manual
retry with the normal proxy exposed a missing `stringprep` dependency in
Luna's reduced Python library. The exact Python 3.13.13 interpreter reproduced
both the failed IDNA import and `LookupError`; adding the official module
restored IDNA and verified HTTPS egress with the installed Luna library.
The restarted Luna process passed its own route check and translated queued
windows in order. The first paired-history request exposed an incompatible
assistant content form; the documented plain-text form restored subsequent
requests. Live usage includes measured cache reads and writes. The initial
route-failure and paired-history-failure checks both preserved later captures
until manual Retry.

The production acceptance checkpoint completed all 47 retained windows with
each request starting after the preceding translation committed. Reopening the
completed journal preserved all results and every reconstructed history prefix.
The actual New Run control was tested on an isolated copy: it preserved all
47 translations, accepted the same window in run 3, and survived reopening.
Production remains on its actual run 2; the control test made no API requests.

Measured production totals were 86,889 input tokens, including 75,904 cached
reads and 3,411 cache writes, plus 1,603 output tokens. Median API latency was
2.835 seconds; the standard-rate estimate for successful translations was
USD 0.2744315. Account credits and invoices remain separate. The private
receipt and isolated control journal are retained as
`grisaia-production-acceptance-v1` at the same stable locator. Runtime file
digests and credential field binding were rechecked; temporary connection
instrumentation was removed.

Install the DLL after detaching its hooks and closing Luna. Verify that the
game no longer has the old module loaded; otherwise close the game before
replacement. Build the matched
source using MSVC and the compiler's matching ATL headers/libraries. Native
binaries, build directories and dependency payloads belong outside Git. The
private build manifest retains compiler, dependency and source hashes.

<!-- markdownlint-disable MD013 -->
```text
cmake -S src/NativeImpl/LunaHook -B <private-build> -G "Visual Studio 17 2022" -A Win32 -DBUILD_HOST=OFF -DWIN10ABOVE=ON -DLUNA_OUTPUT_DIRECTORY=<private-native-output>
cmake --build <private-build> --config Release --target LunaHook
cmake -S tests/grisaia/native -B <private-native-test-build> -G "Visual Studio 17 2022" -A Win32
cmake --build <private-native-test-build> --config Release
ctest --test-dir <private-native-test-build> -C Release --output-on-failure
python -X utf8 tools/deploy_grisaia.py --home <private-home> --game-dir <installed-game> --native-hook <private-native-output>/LunaHook32.dll
```
<!-- markdownlint-enable MD013 -->

Deployment backs up the original DLL and disables the old script-reader and
diagnostic hooks. For separately requested capture development or recovery,
live acceptance verifies complete ordered windows, names, narration and redraw
suppression before enabling translation. This is not an upstream-update gate;
apply the engineering contract's update exception.
The retained build and diagnostic checkpoint uses logical artifact ID
`grisaia-native-window-capture-v1` and the same stable private locator above.

The dynamic-role recovery check resolved body/name IDs `100/101` without a
numeric allowlist. Live window serials were `1, 1, 2`: backlog restoration
preserved the first original and identity, and the next narration cleared its
speaker. Eight missed windows and
the two diagnostic windows were verified against the exact loaded patched
`op.cst`, then translated in FIFO order with one request each. All 120 previous
event rows retained their exact stored values, and the journal
reached 128 completed captures in run 2. This checkpoint is
`grisaia-dynamic-scene-roles-v1`; its machine-local locator is
`F:\LunaTranslator-Grisaia\checkpoints\scene-role-v1\locator.json`.

For this recovery change only, the owner approved an exception to the 100%
measured coverage target. It covers `GrisaiaModelRoles.h`,
`GrisaiaWindowState.h` and `GrisaiaWindows.h` under
`src/NativeImpl/LunaHook/LunaHook/engine32/`, plus
`tests/grisaia/native/window_state.cpp`, `tools/deploy_grisaia.py` and
`tests/grisaia/test_deploy_grisaia.py`. The pure native logic and its test
measured 97.84% lines, 68.39% branches and 100% functions on LLVM x64. The
installed LLVM lacks the x86 profiling runtime; production x86 and Python
full-file coverage remain unmeasured. Alternative acceptance evidence is the
44-test Python suite, native CTest, matching MSVC x86 build, independent reviews
and the live capture/recovery check above. Reconsider this exception on the
next change to these files; it is not a general coverage exemption.

## Sol 6.1 selection

On 2026-11-07 the owner selected `gpt-6.1-sol / low` to reduce translation
cost after inspecting sequential examples against saved Astra translations.
Luna remains an optional future choice, not an automatic fallback. The private
settings file owns the active runtime selection.

The transport and model-selection control now accept Sol 6.1 and estimate its
standard token costs. The owner approved a task-specific exception to full-module
100% measured coverage for `src/LunaTranslator/translator/grisaia/transport.py`,
`tests/grisaia/test_transport.py`, and `tools/grisaia_control.py`. Coverage was
not measured. Alternative evidence is the passing 45-test regression suite,
Python compilation, independent code and historical review, and a successful
synthetic translation through the installed transport using Sol 6.1 / low.
Reconsider coverage when these files next change; this is not a general exemption.

The installed application retains the compatible bridge files from the verified
`lunatranslator-local-before-20261107` checkpoint, plus the updated transport.
Deploying newer upstream bridge files into this older runtime caused a startup
failure because its `NativeUtils` module lacked `CheckMaybeUNCFile`. Restoring
the seven bridge files against checkpoint hashes restored startup. The manifest
records their restored hashes. This installation is not a deployment of the
complete current source tree; a future full deployment needs a matched runtime.
The existing 727 completed translations were preserved, and the model check did
not write synthetic dialogue into the game journal.

The Codex bridge is deferred to a separate phase.

## Automatic context summaries

The owner requested automatic context compaction on 2026-11-07. Before translating
the next window after 100 completed windows in a run, the worker summarizes those
completed original/translation pairs through `gpt-6.1-sol` with `high` reasoning.
Subsequent checkpoints merge the previous summary with the next 100 completed
pairs. One captured dialogue window counts as one message for this threshold.
The goal is to reduce repeated API context while retaining translation continuity.
On an existing journal, the first checkpoint includes all complete hundred-window
blocks preceding the pending head; the remaining pairs stay verbatim in context.

This is an explicit textual summary through Responses, not the opaque
[`/responses/compact` window](https://developers.openai.com/api/docs/guides/compaction)
(accessed 2026-11-07). The summary retains names, Russian forms, voice, relevant
events and uncertainty. Summarization can lose detail; the full originals and
translations remain unchanged in SQLite for inspection and recovery.

Summaries are journal checkpoints, committed before the next translation. A
restart or failed translation reuses a committed checkpoint. A failed or interrupted
summary pauses the FIFO head and requires manual Retry; it is never retried
automatically. Each run is summarized separately; archived summaries stay before
their run boundary and cannot inform the current run. Future queued windows are
excluded. The immutable translation prompt and selected translation model/effort
are unchanged. Summary usage and estimated cost are stored with each checkpoint.

For an older compatible installation, `tools/deploy_grisaia.py --core-only`
updates only manifest-managed Grisaia Python modules, verifies all selected
installed digests before copying, and preserves bridges, capture settings and
native binaries. Stop Luna before deploying and restart it afterwards.

For this task only, the owner approved replacing the full-module 100% coverage
requirement with focused synthetic regression tests, the complete existing suite,
Python compilation and independent code/history reviews. This covers
`src/LunaTranslator/translator/grisaia/{engine,prompt,transport}.py`,
`tests/grisaia/{test_compaction,test_transport,test_deploy_grisaia}.py` and
`tools/deploy_grisaia.py`. Coverage is not measured; reconsider this exception
on the next change. Durable history, manual recovery, egress and deployment
integrity requirements remain in force.

Installation verification passed on 2026-11-07: 52 synthetic regression tests,
Python compilation, Markdownlint, whitespace checks and independent code/history
reviews. A real installed-transport request summarized only synthetic dialogue
using Sol 6.1 / high. All 775 production event rows (773 completed translations
and two run markers) retained their exact values. Manifest digests matched, and
the installed Luna restarted with no pending head. The first production summary
is deferred until the next captured window; its translation quality is unmeasured.
