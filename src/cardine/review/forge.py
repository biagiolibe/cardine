"""Read-only GitHub client and the reading rules for a forge review verdict.

Nothing here writes to GitHub, to the task state or to the worktree.
"""

from __future__ import annotations

import json
import os
import subprocess

from cardine.integration.ci import PAGE_LIMIT, QUERY_SECONDS, _refused, _require_gh, remote_repository
from cardine.shared.errors import CardineError

_IGNORED_STATES = frozenset({'COMMENTED', 'PENDING'})


def _gh_json(root, endpoint, host=None):
    """One read-only `gh api` call; a missing gh, a refusal or non-JSON raises CardineError."""
    gh = _require_gh()
    host = host or remote_repository(root)[0]
    try:
        done = subprocess.run([gh, 'api', '--hostname', host, '-H', 'Accept: application/vnd.github+json', endpoint],
                              capture_output=True, text=True, timeout=QUERY_SECONDS, check=False,
                              env={**os.environ, 'GH_PROMPT_DISABLED': '1'})
    except subprocess.TimeoutExpired as error:
        raise CardineError(f'gh api {endpoint} timed out') from error
    if done.returncode:
        text = done.stderr.strip() or done.stdout.strip()
        prefix = 'GitHub refused the query: ' if _refused(done.stderr + done.stdout) else 'GitHub query failed: '
        raise CardineError(prefix + text)
    try:
        return json.loads(done.stdout)
    except ValueError as error:
        raise CardineError('GitHub returned invalid JSON') from error


def _login(value):
    user = value.get('user') if isinstance(value, dict) else None
    login = user.get('login') if isinstance(user, dict) else None
    return login if isinstance(login, str) else None


def read_pull_request(root, branch):
    """The open or closed pull request whose head is `branch` on origin, or None."""
    host, owner, name = remote_repository(root)
    found = _gh_json(root, f'repos/{owner}/{name}/pulls?state=all&head={owner}:{branch}&per_page=100', host)
    if not isinstance(found, list):
        raise CardineError('GitHub returned an invalid pull request list')
    matches = [pull for pull in found if isinstance(pull, dict) and isinstance(pull.get('number'), int)
               and isinstance(pull.get('head'), dict) and pull['head'].get('ref') == branch
               and isinstance(pull['head'].get('repo'), dict)
               and str(pull['head']['repo'].get('full_name', '')).lower() == f'{owner}/{name}'.lower()]
    if not matches:
        return None
    pull = max(matches, key=lambda item: item['number'])
    state = pull.get('state')
    if pull.get('merged_at'):
        state = 'merged'
    return dict(number=pull['number'], author=_login(pull), head=pull['head'].get('sha'), state=state)


def read_reviews(root, number):
    """Every review of the pull request, at most PAGE_LIMIT pages of 100."""
    host, owner, name = remote_repository(root)
    reviews = []
    for page in range(1, PAGE_LIMIT + 1):
        listed = _gh_json(root, f'repos/{owner}/{name}/pulls/{number}/reviews?per_page=100&page={page}', host)
        if not isinstance(listed, list):
            raise CardineError('GitHub returned an invalid review list')
        for review in listed:
            if not isinstance(review, dict):
                raise CardineError('GitHub returned an invalid review')
            reviews.append(dict(id=review.get('id'), login=_login(review), state=review.get('state'),
                                commit_id=review.get('commit_id'), body=review.get('body') or ''))
        if len(listed) < 100:
            break
    return reviews


def current_login(root):
    """The login of the gh account."""
    user = _gh_json(root, 'user')
    login = user.get('login') if isinstance(user, dict) else None
    if not isinstance(login, str) or not login:
        raise CardineError('GitHub returned an invalid user')
    return login


def forge_verdict(reviews, *, head, excluded_logins):
    """Rules 1 to 5 of the ADR: returns (verdict, deciding review, stale).

    `verdict` is 'APPROVE', 'CHANGES_REQUESTED' or None. `stale` is True when an
    APPROVED or CHANGES_REQUESTED review was dropped because its commit is not `head`.
    """
    excluded = set(excluded_logins)
    kept, stale = [], False
    for review in reviews:                                     # rules 1 and 2
        if review.get('state') in _IGNORED_STATES:
            continue
        if review.get('commit_id') != head:
            stale = stale or review.get('state') in ('APPROVED', 'CHANGES_REQUESTED')
            continue
        kept.append(review)
    latest = {}                                                # rule 3
    for review in kept:
        login = review.get('login')
        if login is not None and (login not in latest or review['id'] > latest[login]['id']):
            latest[login] = review
    decided = [review for review in latest.values()            # rules 3 and 4
               if review.get('state') != 'DISMISSED' and review['login'] not in excluded]
    for state, verdict in (('CHANGES_REQUESTED', 'CHANGES_REQUESTED'), ('APPROVED', 'APPROVE')):   # rule 5
        chosen = sorted((review for review in decided if review['state'] == state), key=lambda item: item['id'])
        if chosen:
            return verdict, chosen[-1], stale
    return None, None, stale
