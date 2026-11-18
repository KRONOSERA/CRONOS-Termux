# Working on CRONOS Termux

## Project and publication destination

- Product: CRONOS, the Python media downloader for Android Termux.
- Canonical repository: https://github.com/KRONOSERA/CRONOS-Termux
- Default publication branch: main.
- Python distribution/import names remain cronos-yt / cronos_yt for compatibility.
- GloriousCronos, CronosFetch, Seal and manga projects are separate projects. Do not publish their sources here.

## Standing user request

The owner explicitly requested on 2026-11-18 that completed updates to this
CRONOS project developed in the ChatGPT development conversation be published
to this repository, together with accurate installation and operation guidance.

Treat publishing completed, relevant updates here as part of the requested
work. Do not stop at a local ZIP or a proposed change when a working publishing
route is available. This standing request does not authorize unrelated account,
permission, repository, or project changes.

For every completed update:

1. Read the current remote branch and preserve changes made since the local
   baseline. Never force-push, reset user work, or remove unrelated files.
2. Apply the update to the correct CRONOS Termux source. When importing an
   archive, inspect its package identity, version and contents first; an archive
   modification timestamp alone is not evidence that its contents are newer.
3. Update CHANGELOG.md and the Arabic guide when behavior changes. Keep README.md
   and README.ar.md consistent. Documentation-only changes do not require a
   software version bump.
4. Run checks appropriate to the actual change. For documentation, validate
   local links, shell syntax and command examples against the real parser.
   For runtime changes, run relevant tests using real dependencies when available
   and disclose checks that could not run.
5. Publish the completed changes to this repository using an authorized route.
   Prefer the GitHub connection when it supports the needed write. If it reports
   insufficient integration permissions, an already authorized signed-in browser
   is an acceptable fallback. Do not request or expose access tokens.
6. Verify the remote files or their Git blob hashes, then report the actual
   commit/link and any remaining installation limitation. Never report an upload
   as complete on the basis of a staged browser upload alone.

## Current installation contract

The 3.0.1 source is a verification candidate. Its requirements.lock is an
intentional placeholder. Fresh installation and locked engine updates reject
an incomplete lock. An existing working CRONOS 3.0.0 environment may be reused
for a code-only upgrade, subject to import/runtime checks.

Do not claim that a clean install, Android device test, real YouTube transfer,
dependency audit or rollback passed unless that check actually ran successfully.
Do not replace the lock gate with an unpinned default installer to make a guide
appear to work.

If a reviewed lock is generated, keep requirements.lock and
cronos_yt/requirements.lock consistent and verify both. The installed updater
also supports CRONOS_LOCK_FILE; its default lookup can prefer ~/CRONOS over a
clone in ~/CRONOS-Termux.

## User data and archives

Publish project source, tests and documentation. Keep downloaded media, private
history/queue SQLite files, settings backups, credentials, cookies, logs and
virtual environments out of the public repository.

Importing a later source archive must not silently overwrite the maintained
guides or these instructions with older bundled documentation. Merge relevant
documentation changes and preserve accurate release status. Do not publish
unfinished artifacts or downgrade code simply because an older file was touched.

## Useful commands and files

- User guide: README.ar.md.
- Release history and remaining limitations: CHANGELOG.md and SECURITY.md.
- Entry-point flags: cronos_yt/cli/parser.py.
- Source compilation: python -m compileall -q cronos_yt tests.
- Offline suite with installed dependencies:
  python -m unittest discover -s tests -v.
- Optional real-dependency integration:
  CRONOS_INTEGRATION=1 python -m unittest discover -s tests/integration -v.
- On-device validation after installation: bash verify_termux.sh.
- Release gate: bash scripts/ci_check.sh. A valid lock and audit/lint tools are
  required; missing gates must not be silently treated as passing.
