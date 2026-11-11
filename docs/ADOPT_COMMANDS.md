# Project adoption

`cardine adopt` installs Cardine in an existing project. Preview the choices with:

```sh
cardine adopt --project . --check --test "python3 -m unittest"
```

Use the same inputs with `--rehearse` to verify adoption in a disposable clone,
then with `--apply` to install it in the project. Apply uses a matching rehearsal
receipt or rehearses first. Review and commit the changes. Create subsequent
tasks with `cardine task new`; see the [Quickstart terminal section](QUICKSTART.md#start-in-the-terminal)
for the task and setup steps.
