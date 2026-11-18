# CRONOS security policy

## Authorization and access controls

CRONOS is for media that the user owns, is licensed to download, or is otherwise authorized to save. Interactive flows require an affirmative rights confirmation; `--yes` is the user's explicit noninteractive declaration. Every selected item receives a session-scoped SQLite authorization receipt containing the confirmation time, SHA-256 of the URL, authorization mode, and optional queue item ID. A receipt records *the user's statement*, not proof of copyright ownership. Downloads refuse missing or stale receipts. Previously queued work requires re-authorization when started in a new process; `--run-queue --yes --confirm-queued` explicitly reaffirms it after printing the count. Jobs above the configured threshold require another confirmation (or `--confirm-large-batch` for noninteractive runs).

CRONOS does not circumvent DRM, authentication, geo-restrictions, private-video permissions, protected media, account restrictions, or similar access controls; it does not import cookies, extract browser cookies, or accept user credentials.

## Supply chain

The intended trust root is the human-reviewed `requirements.lock` containing exact package pins and PyPI SHA-256 hashes for *all* transitive dependencies. `install.sh` and the default `cronos --update` fail closed if the lock is missing or incomplete. No unverifiable hashes were fabricated during the offline hardening process: **the shipped placeholder is not a production lock**. A networked maintainer must explicitly generate, verify, audit, and release a locked artifact before fresh installs or locked engine updates can be trusted. `scripts/generate_lock.sh` requires an explicit `CRONOS_TRUST_INDEX=1` and downloads from the configured Python index; its result is a candidate for review, not a preapproved supply-chain attestation. A single lock generated on Android may have platform markers/wheel availability constraints; validate on both supported Python versions and Termux.

`cronos --update-unpinned --yes` is an *explicit, higher-risk* escape hatch. It shows the exact selected wheel filenames and SHA-256 hashes before installation. The updater attempts to cache prior wheels before modifying dependencies. Rollback verifies manifest SHA-256 values and refuses a tampered cache. Cache misses can trigger an index fallback using exact old versions; network may still be required in that case. Android system Python extensions are accessible only when the installer is run with `CRONOS_SYSTEM_SITE=1` as an intentional fallback.

## Sensitive data and vulnerability reporting

Keep the private SQLite database, engine-cache and backup ZIP archives out of public uploads: history and queued jobs can reveal viewing interests, and backups are not encrypted. File permissions use 0600 where supported. Lyrics are written to a temporary 0600 FFmetadata file instead of process argv. Logs redact probable secrets, but arbitrary filenames/titles may contain sensitive text: review before sharing. Redaction is defense in depth, not a cryptographic privacy guarantee.

To report a security issue, contact the project maintainer privately through the distribution channel rather than publishing exploit details or user data in a public issue. Provide the CRONOS version, reproduction steps using synthetic URLs, and a minimal redacted log. Do not include credentials, cookies, private media links, or real personal information.
