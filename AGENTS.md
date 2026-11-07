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

## Source and runtime boundaries

- Python application code is in `src/LunaTranslator`; native launchers and
  libraries are in `src/NativeImpl`.
- Grisaia's extension is in `extensions/grisaia`; its durable queue and API
  transport are in `src/LunaTranslator/translator/grisaia`.
- Runtime binaries, builds, credentials, real game text, private configuration,
  translation journals, and diagnostic corpora stay outside Git.
- Use repository deployment tools and their manifests to update the external
  runtime. Source edits alone do not update the installed application. Preserve
  backups and refuse to overwrite independently modified deployed files.
- Preserve the sequential durable queue, manual retry after uncertain API
  outcomes, complete history, and existing run boundaries. Do not truncate
  history or switch providers/models without a user decision.
- Keep game-specific capture and executable fingerprints in their adapters.
  Do not apply a Grisaia-specific hook or identity rule to another game without
  evidence from that game's engine and executable.

## Updates and Git

`upstream` is `HIllya51/LunaTranslator`; `origin` is
`Afgan0r/LunaTranslator`. Personal changes are maintained on `master`.
Preserve upstream history and integrate upstream by merge only when the user
explicitly requests an update. A freshness fetch is not permission to merge.

The original binary updater is disabled. Do not download or install upstream
updates automatically, including cached packages. No release-publication
pipeline is required for this local workflow.

Preserve unrelated changes. Automatically commit completed, verified task
changes directly to `master` and push to `origin/master` without asking for
separate confirmation. Never force-push or rewrite existing history.
Use English Conventional Commits. Do not publish binary releases or change
the default branch without an explicit request.

## Implementation and verification

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
capture code changes. UI changes require rendered checks of the affected
screen and relevant states, not source-only approval.

Use synthetic dialogue in tests. Live capture acceptance is distinct from
unit-test success; report unperformed checks explicitly. Do not restart the
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
