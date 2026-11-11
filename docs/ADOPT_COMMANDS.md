# Project adoption

`cardine init` adopts an existing project when it finds one, so most users never call
`cardine adopt` directly. See the [quick start](QUICKSTART.md#configure-the-project).

For automation, `cardine adopt` takes explicit flags. Preview, then apply:

```sh
cardine adopt --project . --check --test "python3 -m unittest"
cardine adopt --project . --apply --test "python3 -m unittest"
```

Apply first rehearses the adoption in a disposable clone. `--rehearse` runs only that
rehearsal.
