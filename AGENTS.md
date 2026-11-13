# LunaTranslator personal fork

## Purpose and scope

Maintain a personal, general-purpose game translator while preserving the
upstream project's capabilities. Grisaia is one supported integration, not the
boundary of the application. Implement only the requested change; propose
additional features separately.

The interface is English only. Keep localization assets and translation
languages, including Russian, available. Source-language and target-language
settings are independent of the interface language.

## Required context

Before substantive project work, read `docs/agent-memory.md`. Resolve the
explicit client binding before project-memory I/O. A missing provider or
unavailable required memory stops dependent work under that contract.

Read the smallest relevant source files and tests. For Grisaia capture,
translation history, local deployment, or recovery, also read
`docs/grisaia-openai.md`. Recheck current sources and runtime evidence before
using historical results as proof of present behavior.
For workspace assembly, migration or game-profile integrations, also read
`docs/integrations.md`.

## Engineering skills

For implementation, tests, review, or integration work, read
[the engineering contract](docs/engineering/contract.md) and
[verification status](docs/engineering/verification.md), then the applicable
skill entrypoints below. Follow their required and conditional reads.

<!-- markdownlint-disable MD013 -->

| Task | Required skill |
| --- | --- |
| Implement, refactor, or diagnose project code | [lunatranslator-conventions](.agents/skills/lunatranslator-conventions/SKILL.md) |
| Write/review tests or verify behavior | [lunatranslator-tests](.agents/skills/lunatranslator-tests/SKILL.md) |
| Review changes or complete substantive work | [lunatranslator-review](.agents/skills/lunatranslator-review/SKILL.md) |
| Change hooks, native/Qt/runtime boundaries, launcher, deployment or recovery | [lunatranslator-integrations](.agents/skills/lunatranslator-integrations/SKILL.md) |

<!-- markdownlint-enable MD013 -->

Before applying engineering requirements, classify inherited code, fork patches,
and independently authored extensions through
`docs/engineering/contract.md` (Code ownership and change scope). That contract
also owns the complete installed-update acceptance and its live-check exception;
apply it before treating a missing check as a blocker.

For these four skills, agents may autonomously correct verified factual errors
and clarify already accepted requirements. New obligations, prohibitions,
exceptions, architecture restrictions, and acceptance changes require owner
approval. Skill maintenance grants no additional authority over application
code, memory contracts, live systems or publication.

## Source and runtime boundaries

- Python application code is in `src/LunaTranslator`; native launchers and
  libraries are in `src/NativeImpl`.
- Grisaia's capture adapter is in `extensions/grisaia`; the shared queue,
  profile runtime and API transport are in `src/LunaTranslator/integrations`.
  `translator/grisaia` contains compatibility aliases.
- Runtime binaries, builds, credentials, real game text, private configuration,
  translation journals, and diagnostic corpora stay outside Git.
- Use repository workspace tools and their manifests to assemble `dist` from
  source. Keep disposable builds in `build` and persistent data in `.local`,
  all excluded from Git. Build and launch are separate operations. Source edits
  alone do not update the installed application. Preserve
  backups and refuse to overwrite independently modified deployed files.
- Preserve the sequential durable queue, manual retry after uncertain API
  outcomes, complete history, and existing run boundaries. Do not truncate
  history or switch providers/models without a user decision.
- Keep game-specific capture and executable fingerprints in their adapters.
  Do not apply a Grisaia-specific hook or identity rule to another game without
  evidence from that game's engine and executable.

## Updates and Git

`upstream` is `HIllya51/LunaTranslator`; `origin` is
`Afgan0r/LunaTranslator`. Personal changes are maintained on `main`.
Preserve upstream history and integrate upstream by merge only when the user
explicitly requests an update. A freshness fetch is not permission to merge.
Unless the request is explicitly source-only, an upstream update includes the
necessary builds, safe deployment and installed startup verification defined
in the engineering contract; commit and push alone do not complete it.

The original binary updater is disabled. Do not download or install upstream
updates automatically, including cached packages. No release-publication
pipeline is required for this local workflow.

Preserve unrelated changes. Automatically commit completed, verified task
changes directly to `main` and push to `origin/main` without asking for
separate confirmation. Never force-push or rewrite existing history.
Use English Conventional Commits. Do not publish binary releases or change
the default branch without an explicit request.

## Implementation and verification

Use a repository-local pre-push hook as the mandatory quality gate instead of
requiring CI. The hook and agents must run the same existing verification
commands; a failed required check blocks the push. Run the applicable checks
before declaring a task complete, and do not bypass the hook to publish a
failing result. This local workflow does not require a CI or CD pipeline;
inherited publication workflows do not grant release authority.

Do not run skill or memory evaluations in this repository. Structural checks,
Markdown/link validation, ordinary application tests, and substantive review
remain applicable. This restriction does not change normal project-memory
recall, capture, or verification under `docs/agent-memory.md`.

Reuse neighboring Python, Qt, and C++ patterns. Keep changes narrow, with clear
failure handling and one source of truth for derived deployment artifacts.
Retain checks for missing runtime components when changing launcher behavior.

Run the existing Python regression suite for capture, queue, transport, or
deployment changes:

```sh
python -X utf8 -m unittest discover -s tests/grisaia -p 'test_*.py'
```

Compile changed Python files and run `git diff --check`. Build changed native
targets with the matching MSVC/ATL toolchain; keep output outside Git through
`LUNA_OUTPUT_DIRECTORY`. Run the native Grisaia state-machine tests when its
capture code changes. Our own UI changes require rendered checks of affected
states; imported upstream screens do not require a general visual tour.

Use synthetic dialogue in tests. For upstream updates, do not run live game or
real translation-API acceptance checks, including after integration changes;
use the engineering contract's update acceptance. Separately requested live
capture acceptance is distinct from unit-test success; report unperformed
checks explicitly. Do not restart the
game when detaching hooks and restarting Luna is sufficient. Before replacing
a loaded DLL, verify it has actually unloaded.

Read only the explicitly selected credential field inside its consuming
process. Never print keys, log them, or commit them. Do not read `.env`,
`.env.*`, or `.secrets` without exact-file authorization. A new OpenAI client
must verify its own configured egress before reading credentials or sending
a request. Real API calls and game actions require task-specific authority.

Write repository documents in English and run Markdownlint on edited Markdown
paths. Report code checks, build results, deployment, and observed live
behavior as separate evidence.
