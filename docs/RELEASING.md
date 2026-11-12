# Releasing Cardine

Until 1.0, prepare a release by hand, as task 240 did for 0.9.1. Do not run
`scripts/release.py prepare`: its preflight requires a migration for any template
change, and no template change adds a migration before 1.0 (ADR work item 4).

1. Confirm that no task is in progress.
2. A task bumps `VERSION` and `.claude-plugin/plugin.json`, adds
   `releases/<VERSION>.json`, writes the `CHANGELOG.md` section, consumes the fragments in
   `changelog.d/`, and replaces the previous tag in `README.md` and `docs/QUICKSTART.md`. The section starts with `CLI-only release: ` or `Template-changing release: `, with the colon, because every runtime reads only that form. A template-changing release is a minor release. Before 1.0, a template-changing release sets `baselineChanged: true` with no migrations, and `workflowBaselineVersion` equals its version. A fragment with `### Removed` needs a major release, except before `1.0.0`: then a minor release with an `Upgrade notes` subsection that names the replacement is enough (amendment of 2026-11-12 in `docs/ADR_PUBLIC_SURFACE_AND_STABILITY.md`, decision 2). When a release breaks these rules, stop and ask the developer. Check the CLI commands, agent prompt, plugin pin, links, and console keys against that tag. Switch the recommended path to `guide` only when the new tag provides it; remove the old version-specific instructions together.
3. Run `python3 scripts/check_repository.py`.
4. Confirm that the full suite is green on `main` in CI.
5. The developer runs `git tag v<VERSION>` and `git push origin v<VERSION>`.
6. `.github/workflows/release.yml` verifies the tag and publishes the GitHub release.
7. Update the installed runtime, then run `cardine authorize` in each checkout. Update
   the Claude Code plugin; `cardine doctor --host claude` reports a mismatch.

PyPI publication and the merge of `release.py` and `prepare_release.py` come with 1.0.

After publication, open the new GitHub release page and smoke-test both the terminal and agent paths in isolated environments with no existing runtime or project configuration. Record the published documentation revision, runtime and plugin versions, and evidence that each first task reached `main`. Repair any mismatch in a subsequent documentation change.
