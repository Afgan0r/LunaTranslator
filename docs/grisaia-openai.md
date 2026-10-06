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
`reasoning_effort`, `game_exe`, `hook_code`, and `hook_validated`. Each new
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

**Live game acceptance is pending.** The candidate is
`HSFN932#-4@B2721:Grisaia.exe`, derived from the installed executable's full-string
scenario path. `hook_validated` remains false. Its raw events are retained in a
private probe journal and are never sent to OpenAI. Live evidence must establish
complete window boundaries, speaker association and suppression of repeated
reads while preserving real replay occurrences. A generated occurrence UUID
alone does not establish those semantics.

The Codex bridge is deferred to a separate phase.
