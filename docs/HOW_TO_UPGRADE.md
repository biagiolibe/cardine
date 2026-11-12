# Upgrade Cardine

Finish in-progress tasks before updating. Preview the release from a terminal:

```sh
cardine self-update --check --project .
cardine self-update --apply --project .
```

Add `--to v0.11.0` to select a particular release. The Plan shows the current
and target versions, release kind, notes, and the Git operation or installer.
The Apply section reports progress as Cardine updates and aligns the Claude
Code plugin. Installer output is displayed if the reinstall fails.

After an update, follow Next steps for every project that uses Cardine:

1. Restart running Claude Code and Codex sessions.
2. Run `cardine authorize --check --project <checkout>` and then
   `cardine authorize --apply --project <checkout>`.
3. For a template-changing release, run `cardine upgrade --check --project <checkout>`
   and then `cardine upgrade --apply --project <checkout>`. Review and commit
   the managed files.
4. Run `cardine doctor --project <checkout>` to confirm each project.

A selected checkout is reported if its accepted runtime was replaced. A plain
(non-terminal) preview looks like:

```text
Plan
Installer: pipx
Current: 1.0.0
Target: 2.0.0
Release kind: template-changing
Release notes: https://github.com/biagiolibe/cardine/releases/tag/v2.0.0
Reinstall: pipx install --force git+https://github.com/biagiolibe/cardine@v2.0.0
Note: Run cardine self-update --apply to update
```

## Update notices

Cardine shows update notices in the agent's per-turn briefing, after interactive
`guide`, `status`, and `doctor` commands, and in the console. It checks at most
once every 24 hours with a single request to the GitHub latest release API. Set
`CARDINE_NO_UPDATE_NOTICE=1` to turn off checks and notices.
