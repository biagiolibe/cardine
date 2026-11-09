# Releasing Cardine

For 0.9.0, perform these steps in order:

1. Confirm that no task is in progress.
2. Run `python3 scripts/check_repository.py`.
3. Confirm that the full suite is green on `main` in CI.
4. The developer runs `git tag v0.9.0` and `git push origin v0.9.0`.
5. `.github/workflows/release.yml` verifies the tag and publishes the GitHub release.
6. Update the installed runtime, then run `cardine authorize` in each checkout.

PyPI publication and the merge of `release.py` and `prepare_release.py` come with 1.0.
