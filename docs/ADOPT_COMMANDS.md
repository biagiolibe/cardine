# Project adoption

`cardine adopt` installs Cardine in an existing project. For Contoso, declare
validation commands in a JSON file as shown in [First 5 minutes](../README.md#first-5-minutes),
then inspect the plan:

```bash
cardine adopt --project . --check --name "Contoso API" --slug contoso-api \
  --preset lean --language English --task-identity opaque \
  --validation ~/contoso-validation.json
```

Use the same inputs with `--rehearse` to verify adoption in a disposable clone,
then with `--apply` to install it in the project. Apply uses a matching rehearsal
receipt or rehearses first. Review and commit the changes. Create subsequent
tasks with `cardine task new`; see [First 5 minutes](../README.md#first-5-minutes)
for the task and setup steps.
