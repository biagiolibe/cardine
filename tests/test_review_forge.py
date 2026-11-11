"""The forge verdict reading rules and the read-only GitHub client."""

import json
import subprocess
import unittest
from unittest import mock

from cardine.review import forge
from cardine.shared.errors import CardineError

HEAD, OLD = 'a' * 40, 'b' * 40


def review(id, login, state, commit=HEAD, body=''):
    return dict(id=id, login=login, state=state, commit_id=commit, body=body)


def verdict(reviews, excluded=('author',)):
    return forge.forge_verdict(reviews, head=HEAD, excluded_logins=excluded)


class ForgeVerdictTest(unittest.TestCase):
    def test_comments_and_pending_are_ignored(self):
        self.assertEqual(verdict([review(1, 'r', 'COMMENTED'), review(2, 'r', 'PENDING')]), (None, None, False))

    def test_stale_approval_is_dropped_and_reported(self):
        self.assertEqual(verdict([review(1, 'r', 'APPROVED', OLD)]), (None, None, True))

    def test_stale_comment_is_not_reported_stale(self):
        self.assertEqual(verdict([review(1, 'r', 'COMMENTED', OLD)]), (None, None, False))

    def test_latest_review_per_reviewer_wins(self):
        reviews = [review(1, 'r', 'CHANGES_REQUESTED'), review(2, 'r', 'APPROVED')]
        self.assertEqual(verdict(reviews)[0], 'APPROVE')
        reviews = [review(3, 'r', 'APPROVED'), review(2, 'r', 'CHANGES_REQUESTED')]
        self.assertEqual(verdict(reviews)[0], 'APPROVE')

    def test_dismissed_latest_review_is_absent(self):
        self.assertEqual(verdict([review(1, 'r', 'APPROVED'), review(2, 'r', 'DISMISSED')])[0], None)
        self.assertEqual(verdict([review(1, 'r', 'CHANGES_REQUESTED'), review(2, 'r', 'DISMISSED'),
                                  review(3, 's', 'APPROVED')])[0], 'APPROVE')

    def test_author_and_pusher_are_ignored(self):
        reviews = [review(1, 'author', 'APPROVED'), review(2, 'pusher', 'APPROVED')]
        self.assertEqual(verdict(reviews, ('author', 'pusher'))[0], None)

    def test_changes_requested_wins_over_approved(self):
        reviews = [review(1, 'a', 'APPROVED'), review(2, 'b', 'CHANGES_REQUESTED', body='fix')]
        got, deciding, stale = verdict(reviews)
        self.assertEqual((got, deciding['body'], stale), ('CHANGES_REQUESTED', 'fix', False))

    def test_approval_returns_the_deciding_review(self):
        got, deciding, _ = verdict([review(1, 'a', 'APPROVED'), review(2, 'b', 'APPROVED')])
        self.assertEqual((got, deciding['id']), ('APPROVE', 2))

    def test_no_reviews_gives_no_verdict(self):
        self.assertEqual(verdict([]), (None, None, False))

    def test_review_without_login_never_decides(self):
        self.assertEqual(verdict([review(1, None, 'APPROVED')])[0], None)


def completed(out='', err='', code=0):
    return subprocess.CompletedProcess(['gh'], code, out, err)


class ForgeClientTest(unittest.TestCase):
    def run_gh(self, *answers):
        patches = (mock.patch.object(forge, 'remote_repository', return_value=('github.com', 'o', 'r')),
                   mock.patch.object(forge, '_require_gh', return_value='gh'),
                   mock.patch.object(forge.subprocess, 'run', side_effect=list(answers)))
        return patches

    def call(self, function, answers, *args):
        first, second, third = self.run_gh(*answers)
        with first, second, third as run:
            try:
                return function('root', *args), run
            finally:
                self.run = run

    def test_reviews_paginate_and_map_fields(self):
        page = [dict(id=i, user=dict(login='r'), state='APPROVED', commit_id=HEAD, body=None) for i in range(100)]
        got, run = self.call(forge.read_reviews, [completed(json.dumps(page)), completed(json.dumps(page[:1]))], 7)
        self.assertEqual(len(got), 101)
        self.assertEqual(got[0], dict(id=0, login='r', state='APPROVED', commit_id=HEAD, body=''))
        self.assertEqual(run.call_count, 2)
        command = run.call_args_list[1].args[0]
        self.assertEqual(command[:4], ['gh', 'api', '--hostname', 'github.com'])
        self.assertIn('repos/o/r/pulls/7/reviews?per_page=100&page=2', command)

    def test_reviews_stop_at_the_page_limit(self):
        page = json.dumps([dict(id=1, user=dict(login='r'), state='APPROVED', commit_id=HEAD)] * 100)
        _, run = self.call(forge.read_reviews, [completed(page)] * 12, 7)
        self.assertEqual(run.call_count, forge.PAGE_LIMIT)

    def test_refusal_raises_with_the_gh_text(self):
        with self.assertRaisesRegex(CardineError, 'HTTP 403'):
            self.call(forge.read_reviews, [completed(err='gh: HTTP 403', code=1)], 7)

    def test_other_failure_raises(self):
        with self.assertRaisesRegex(CardineError, 'GitHub query failed: boom'):
            self.call(forge.current_login, [completed(err='boom', code=1)])

    def test_non_json_answer_raises(self):
        with self.assertRaisesRegex(CardineError, 'invalid JSON'):
            self.call(forge.read_reviews, [completed('<html>')], 7)

    def test_missing_gh_raises(self):
        with mock.patch.object(forge, 'remote_repository', return_value=('github.com', 'o', 'r')), \
                mock.patch.object(forge, '_require_gh', side_effect=CardineError('requires the gh command')):
            with self.assertRaisesRegex(CardineError, 'gh command'):
                forge.current_login('root')

    def test_current_login(self):
        got, _ = self.call(forge.current_login, [completed('{"login": "me"}')])
        self.assertEqual(got, 'me')

    def test_pull_request_is_matched_on_the_head_branch(self):
        pulls = [dict(number=1, state='closed', merged_at=None, user=dict(login='x'),
                      head=dict(ref='task-1', sha=OLD, repo=dict(full_name='O/R'))),
                 dict(number=2, state='open', merged_at=None, user=dict(login='me'),
                      head=dict(ref='task-1', sha=HEAD, repo=dict(full_name='o/r'))),
                 dict(number=3, state='open', merged_at=None, user=dict(login='f'),
                      head=dict(ref='task-1', sha=HEAD, repo=dict(full_name='fork/r')))]
        got, run = self.call(forge.read_pull_request, [completed(json.dumps(pulls))], 'task-1')
        self.assertEqual(got, dict(number=2, author='me', head=HEAD, state='open'))
        self.assertIn('repos/o/r/pulls?state=all&head=o:task-1&per_page=100', run.call_args.args[0])

    def test_merged_pull_request_and_none(self):
        merged = [dict(number=4, state='closed', merged_at='t', user=dict(login='me'),
                       head=dict(ref='b', sha=HEAD, repo=dict(full_name='o/r')))]
        got, _ = self.call(forge.read_pull_request, [completed(json.dumps(merged))], 'b')
        self.assertEqual(got['state'], 'merged')
        got, _ = self.call(forge.read_pull_request, [completed('[]')], 'b')
        self.assertIsNone(got)

    def test_only_get_calls(self):
        _, run = self.call(forge.current_login, [completed('{"login": "me"}')])
        command = run.call_args.args[0]
        self.assertNotIn('-X', command)
        self.assertNotIn('--method', command)


if __name__ == '__main__':
    unittest.main()
