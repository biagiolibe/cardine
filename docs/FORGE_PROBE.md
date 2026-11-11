# Forge probe

Evidence for the External facts G1 to G6 of `docs/ADR_REVIEW_VERDICT_SOURCES.md`.
The developer ran the probe on 2026-11-11 with `gh` 2.103.3 on a private scratch
repository, `<owner>/cardine-forge-probe`, since deleted. The implementer recorded
the output and ran none of these commands. The page re-read happened on 2026-11-12.

## Probe results

### G5: the author cannot approve or request changes on their own pull request

```text
$ gh pr review 1 --approve --body "self approval"
failed to create review: GraphQL: Review Can not approve your own pull request (addPullRequestReview)
$ gh pr review 1 --request-changes --body "self changes"
failed to create review: GraphQL: Review Can not request changes on your own pull request (addPullRequestReview)
```

Verdict: **confirmed**. This tests a self-review by the pull request author only. It
cannot show how a second account is treated.

### G6: the existing login reads reviews without a write scope

```text
$ gh pr review 1 --comment --body "author comment"
- Reviewed pull request <owner>/cardine-forge-probe#1
$ gh api repos/<owner>/cardine-forge-probe/pulls/1/reviews --jq '[.[] | {id, state, commit_id, login: .user.login}]'
[{"commit_id":"325293148a62643da36101d30755753ce07e2df6","id":5866439456,"login":"<owner>","state":"COMMENTED"}]
$ gh auth status
Token scopes: 'gist', 'read:org', 'repo', 'workflow'   (no admin or delete scope needed to read reviews)
```

Verdict: **confirmed**. The token held no scope beyond the ones a normal login has.

### G4: a pull request survives a landing outside GitHub

```text
$ git switch main && git merge --no-ff task-probe -m "Integrate probe" && git push origin main
   1e71360..a1c7241  main -> main
$ gh pr view 1 --json state,mergedAt,closedAt,mergeCommit,headRefOid
{"closedAt":"2026-11-11T23:00:49Z","headRefOid":"325293148a62643da36101d30755753ce07e2df6","mergeCommit":{"oid":"a1c7241e99f2122c4d6abcfda299fe98c627f1a0"},"mergedAt":"2026-11-11T23:00:49Z","state":"MERGED"}
```

Verdict: **confirmed**. GitHub marked the pull request merged from the pushed history
of `main`; the head stayed the task-branch commit. The engine therefore need not close
the pull request after a direct landing.

## What the probe adds to G1

The review list returned the fields `id`, `state`, `commit_id` and `user.login`, and the
`COMMENTED` review carried the pull request head as its `commit_id`. The probe saw one
state only, so it does not show the other states or that `commit_id` stays on the commit
a review was made on after the head moves.

## Re-read of the cited pages (2026-11-12)

| Fact | Page | Still states it? |
|------|------|------------------|
| G1 | REST reviews | **Partly.** The response schema lists `id`, `user.login` (nullable), `state` and `commit_id` (string or null). It does not list the state values, and describes `commit_id` only in the create request ("The SHA of the commit that needs a review"). |
| G2 | About pull request reviews | **No.** The page covers who may request reviews and lists Comment, Approve and Request changes. It has no rule on self-approval. The G5 probe is the evidence for it. |
| G3 | REST reviews and About protected branches | **Partly.** The protected-branches page states that approvals can be dismissed when commits are pushed. The reviews page does not say that a dismissed review keeps its record with state `DISMISSED`. |

Consequences for the reading rules, stated as unverified rather than refuted:

- Rule 2 assumes `commit_id` is the commit reviewed. Treat a null `commit_id` as not equal to the head.
- Rule 3 assumes a dismissed review stays in the list with state `DISMISSED`. If GitHub removes it, the rule still gives the right result.
- `user.login` can be null, so a review without a login never decides.
