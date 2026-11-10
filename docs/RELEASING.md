# Releasing Cardine

Until 1.0, prepare a release by hand, as task 240 did for 0.9.1. Do not run
`scripts/release.py prepare`: its preflight requires a migration for any template
change, and no template change adds a migration before 1.0 (ADR work item 4).

1. Confirm that no task is in progress.
2. A task bumps `VERSION` and `.claude-plugin/plugin.json`, adds
   `releases/<VERSION>.json`, writes the `CHANGELOG.md` section, consumes the fragments in
   `changelog.d/`, and replaces the previous tag in `README.md` and `docs/QUICKSTART.md`.
3. Run `python3 scripts/check_repository.py`.
4. Confirm that the full suite is green on `main` in CI.
5. The developer runs `git tag v<VERSION>` and `git push origin v<VERSION>`.
6. `.github/workflows/release.yml` verifies the tag and publishes the GitHub release.
7. Update the installed runtime, then run `cardine authorize` in each checkout. Update
   the Claude Code plugin; `cardine doctor --host claude` reports a mismatch.

PyPI publication and the merge of `release.py` and `prepare_release.py` come with 1.0.
