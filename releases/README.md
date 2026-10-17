# Meridian Release Ledger

Each `releases/<version>.json` file is an append-only record of one framework
release, starting with the first release cut after this ledger was introduced
(there is no historical backfill). It is the machine-checked trace of whether a
release moved `workflowBaselineVersion`; `CHANGELOG.md` remains the prose record.

Fields (exactly these, no others):

- `version`: the release version; must equal the filename. No prerelease or
  build suffix.
- `releaseDate`: ISO date (`YYYY-MM-DD`).
- `gitTag`: the tag for the release (`v<version>`).
- `protocolVersion`: the manifest protocol version at the release.
- `workflowBaselineVersion`: the newest migration `to` at the release.
- `baselineChanged`: `true` iff `migrations` is non-empty.
- `migrations`: ids of the migrations the release introduced; each must target
  `workflowBaselineVersion`.

A correction ships as a new release, never as an edit to a past record.
`python3 scripts/check_repository.py` validates the ledger.
