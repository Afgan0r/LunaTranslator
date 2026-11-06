# Grisaia OpenAI deployment

This branch adds an opt-in, durable translation queue for the English Steam
edition of *The Fruit of Grisaia*. The custom translator is installed as
`userconfig/selfbuild.py`; runtime files, credentials, game text and journals
stay outside Git.

## Source provenance and updates

The original repository history is preserved. `upstream` points to
[HIllya51/LunaTranslator](https://github.com/HIllya51/LunaTranslator).
The integration branch is `grisaia-openai`; no personal publishing remote is
configured.

The supplied x64 ZIP matches source revision
`2f65c65eb2f6ea6584a4210a982f64412df071cd`, version `12.0.0.1`:
all 235 packaged Python files match after line-ending normalization. ZIP
SHA-256: `4b93035ee7029a7f2cf70ddd669c9c13b20c391b3a2c8c2ca18aaff9bfa65988`.
This comparison does not independently establish native binary build provenance.

Integrate updates through a merge, after checking for local changes:

```sh
git fetch --prune upstream
git switch grisaia-openai
git merge upstream/main
python -X utf8 -m unittest discover -s tests/grisaia -v
```

Match a new runtime ZIP to its source before deployment. Recheck the three
bridge sites and native hook after updates; the custom engine remains separate.

## External installation

Use an absolute private directory outside the checkout, restricted to the
Windows user and SYSTEM. Extract the matched ZIP into
`<private-home>/runtime/LunaTranslator_x64`. Keep the API key in an independent
text file and reference its absolute path in the private `settings.json`.
Do not read `.env`, `.env.*` or `.secrets` without exact-file authorization.

The supplied runtime omits `_ssl`. The deployment tool can supply `_ssl.pyd`
and its two OpenSSL dependencies from the
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
OpenAI. Proxy credentials are optional. Redirects, direct fallback and
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
`GrisaiaControl` and `GrisaiaWindows`. The current candidate observes source-text
model writes as its generation signal. Presentation messages for IDs 15 and 16 identify the body
and name and track layout rebuilding separately. A snapshot immediately after
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
all preceding original/translation message pairs, and the current original.
Queued future text is excluded. The original prompt is pinned in the journal;
changing it in place is refused. Only the current window is translated, with
prior runs treated as archived context rather than plot knowledge.

`New Run.cmd` appends a manual new-playthrough / older-save marker without
removing history. Use it before advancing after a replay or loading an older
save. `Retry.cmd` releases the failed head only; subsequent captured windows
remain queued. `Status.cmd` shows queue counts without corpus or credentials.
Context overflow pauses with an explicit message; no history is shortened.
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

**Live acceptance of the revised native hook is pending.** Both the UI-command
and scenario-frame setter candidates failed to produce script events. The
second live check captured two different windows and two backlog rebuilds,
all incorrectly carrying serial 1. Presentation tracing subsequently succeeded
for 67 stack reads and located both normal updates and history reconstruction
in the same updater. The current candidate observes the model's source-text
replacement and append operations; their caller metadata must establish the
difference from backlog restoration before accepting this signal. Address
tracing remains temporary validation instrumentation.
The API remains disabled. Speaker clearing and complete English bodies have
been observed. The older
`HSFN932#-4@B2721:Grisaia.exe` script-reader hook was rejected because it captures
commands and repeated out-of-order reads. The built-in character hook matches
visible bodies but leaves its last name in the hook list after the game has
cleared that name's glyph vector. Its raw events remain private diagnostics.
`hook_validated` remains false; no diagnostic event is sent to OpenAI.

The new DLL must be installed with Luna and the game closed. Build the matched
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
diagnostic hooks. Live evidence must verify complete ordered windows, names,
narration and redraw suppression before enabling translation.
The retained build and diagnostic checkpoint uses logical artifact ID
`grisaia-native-window-capture-v1` and the same stable private locator above.

The Codex bridge is deferred to a separate phase.
