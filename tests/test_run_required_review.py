"""Required review delivery through the interactive developer channel."""
import json
import os
import sys

from run_delivery_support import DisposableDelivery, ROOT, TASK
import test_developer_channel

CHILD = '''
import os, sys
from pathlib import Path
from cardine.lifecycle import receipts
receipts.boundary = lambda name: os._exit(77) if name == sys.argv[3] else None
from cardine.review.verdict import record_review_verdict
record_review_verdict(Path(sys.argv[1]), '001', sys.argv[2], owner=True)
'''


class RequiredReviewTest(test_developer_channel.Terminal):
    def verdict(self, fixture, verdict, point=''):
        worker = fixture.locations.worktree
        head = fixture.git('rev-parse', 'HEAD', cwd=worker)
        command = [sys.executable, '-c', CHILD, str(worker), verdict, point]
        return self.terminal(command, worker, f'{TASK} {head}')

    def prepare_review(self, fixture):
        self.assertEqual(fixture.run()['step'], 'worktree')
        self.assertEqual(fixture.run()['step'], 'implementation')
        fixture.implement()
        result = fixture.run()
        self.assertEqual(result['step'], 'review', result)
        self.assertEqual(result['work']['role'], 'reviewer')
        self.assertEqual(result['next']['argv'], ['cardine', 'review', 'verdict', TASK, 'APPROVE',
                                                  '--owner', '--project', str(fixture.locations.worktree)])
        return result

    def test_changes_then_approval_lands_and_stale_approval_is_refused(self):
        with DisposableDelivery(review=True) as fixture:
            self.prepare_review(fixture)
            code, out, err = self.verdict(fixture, 'CHANGES_REQUESTED')
            self.assertEqual(code, 0, out + err)
            self.assertEqual(fixture.run()['outcome'], 'iterate')
            fixture.commit_implementation('result = 2\n')
            fixture.deliver()
            self.assertEqual(fixture.run()['step'], 'review')
            code, out, err = self.verdict(fixture, 'APPROVE')
            self.assertEqual(code, 0, out + err)
            self.assertEqual(fixture.drive()[-1][2], 'done')
            self.assertEqual(fixture.git('rev-parse', 'main'), fixture.remote_main())

    def test_stale_commit_is_refused(self):
        with DisposableDelivery(review=True) as fixture:
            self.prepare_review(fixture)
            fixture.commit_implementation('result = 3\n')
            code, out, err = self.verdict(fixture, 'APPROVE')
            self.assertNotEqual(code, 0, out + err)
            self.assertIn('stale', err)

    def test_each_verdict_recovers_at_effect_boundaries(self):
        for verdict in ('CHANGES_REQUESTED', 'APPROVE'):
            for point in ('before_intent', 'after_result_receipt'):
                with self.subTest(verdict=verdict, point=point), DisposableDelivery(review=True) as fixture:
                    self.prepare_review(fixture)
                    code, out, err = self.verdict(fixture, verdict, point)
                    self.assertEqual(code, 77, out + err)
                    code, out, err = self.verdict(fixture, verdict)
                    self.assertEqual(code, 0, out + err)
                    state = json.loads((fixture.locations.worktree / '.cardine/tasks/001.json').read_text())
                    self.assertEqual(len(state['review_history']), 1)
                    self.assertEqual(state['review']['verdict'], verdict)
                    code, out, err = self.verdict(fixture, verdict)
                    self.assertEqual(code, 0, out + err)
