# Upgrade Cardine

Finish any in-progress tasks before updating. Run the update from your
terminal. Preview the latest release, then apply it from your project checkout.

```sh
cardine self-update --check --project .
cardine self-update --apply --project .
```

To select a release explicitly, add `--to v0.9.2` to both commands.
Self-update uses the installer that owns the CLI, aligns the Claude Code
plugin, and prints the command for any checkout it finds that needs to
re-accept the runtime.

Run the printed command in your terminal for each affected checkout. For
example, to inspect and re-accept the current checkout:

```sh
cardine authorize --check --project .
cardine authorize --apply --project .
```

For project template changes announced in a release, inspect
`cardine upgrade --check --project .`, then apply the reviewed plan with
`cardine upgrade --apply --project .`. Validate and commit the project changes.
