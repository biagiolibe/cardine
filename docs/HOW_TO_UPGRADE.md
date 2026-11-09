# Upgrade Cardine

Update the CLI only when no project has a task in progress. A task in progress
binds its operation to the current runtime. After updating Cardine, the developer
must run `cardine authorize` in each checkout from an interactive terminal.

## Update the CLI

Cardine is installed from a clone. For a new installation:

```bash
git clone https://github.com/biagiolibe/cardine ~/src/cardine
pipx install --editable ~/src/cardine
```

To update an existing installation, update the clone to the desired version.
For Cardine 0.9, select its Git tag in the clone. Review the release notes in
[CHANGELOG.md](../CHANGELOG.md) before updating projects.

## Authorize each checkout

In each project checkout, inspect and then apply authorization from the
developer's interactive terminal:

```bash
cardine authorize --check --project /path/to/contoso
cardine authorize --apply --project /path/to/contoso
```

Authorization verifies task states and refuses while an operation is pending.
It re-accepts the checkout and runtime for the project's task states.

## Upgrade a project

From the Contoso checkout, inspect the upgrade plan:

```bash
cardine upgrade --check --project /path/to/contoso
```

Review the plan and address any reported blockers. Then apply the upgrade:

```bash
cardine upgrade --apply --project /path/to/contoso
```

Review the resulting changes, run the project's validation, and commit them.
