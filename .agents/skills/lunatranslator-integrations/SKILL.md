---
name: lunatranslator-integrations
description: Change or verify LunaTranslator game adapters, hooks, native/Qt boundaries, launcher, embedded runtime, deployment, or recovery. Use for «проверь интеграцию LunaTranslator», not ordinary game advice.
---

# LunaTranslator integrations

## Identify the boundary

Read root `AGENTS.md`, `docs/agent-memory.md`, `docs/engineering/contract.md`,
and `docs/engineering/verification.md`. For Grisaia, local deployment, or
recovery, also read `docs/grisaia-openai.md` for current procedures and
commands. Follow the project memory and authority contracts. Determine the
affected producer, consumer, host, runtime/ABI, and observable scenario before
changing a boundary. Inspect both sides and relevant existing tests. Use
evidence from each game's engine and executable; do not generalize Grisaia's
fingerprint or hook rules to other games.

## Verify the actual crossing

First apply the engineering contract's ownership scope and Upstream update
acceptance. During upstream updates, never require or run live game or real
translation-API acceptance, even after integration changes. Complete the
required builds, synthetic tests, safe deployment and installed startup check;
report game/API behavior as untested. Do not tour imported upstream screens.
The general real-crossing requirements below apply outside that update exception.

Exercise the changed producer and consumer together, including malformed
input, failure, and recovery as applicable. Native changes require the
matching MSVC/ATL build with output outside Git; capture changes also require
native state-machine checks. Qt, embedded Python, hook callbacks, packet
transit, launcher, and other changed boundaries require their actual host
scenario in addition to isolated tests. Our own UI changes require rendered
checks of affected states. Use the documented procedures rather than treating
an old checkpoint
or a successful import as current live evidence.

For authorized deployment, use the repository deployment tool and manifest;
verify digests, preserve backups, and refuse independently modified deployed
files. Before replacing a loaded DLL verify it unloaded; detach hooks and
restart Luna where sufficient instead of unnecessarily restarting the game.
Real game, API, and deployment actions require task-specific authority. Do not
create a release workflow as a substitute for the local process.

Run the canonical gate and applicable checks in
`docs/engineering/verification.md` that it does not cover. Report
source, build, deployment, and observed host behavior separately. If the
required real host, toolchain, or authorization is unavailable, prepare a
reproducible procedure and report awaiting verification; obtain owner approval
for any exact exception.
