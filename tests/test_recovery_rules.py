"""Pure recovery decisions need no repository or processes."""
import unittest
from dataclasses import replace

from cardine.stops.causes import (LeaseFacts, CleanupFacts, OriginFacts,
                                  resolve_lease, resolve_cleanup_branch, resolve_main_ahead)
from cardine.integration.residue import ResidueFacts, resolve_landing_residue


class RecoveryRulesTest(unittest.TestCase):
    def test_lease(self):
        facts = LeaseFacts()
        self.assertEqual(resolve_lease(facts), 'LEASE_INTERRUPTED')
        for field in ('readable', 'task_matches', 'branch_matches', 'project_matches'):
            with self.subTest(field=field):
                self.assertEqual(resolve_lease(replace(facts, **{field: False})), 'LEASE_HELD')
        self.assertEqual(resolve_lease(replace(facts, writer_live=True)), 'LEASE_HELD')
        self.assertEqual(resolve_lease(replace(facts, merge_exists=True)), 'LEASE_INTERRUPTED')
        for field in ('main_matches', 'merge_matches'):
            with self.subTest(field=field):
                self.assertEqual(resolve_lease(replace(facts, merge_exists=True, **{field: False})), 'LEASE_HELD')
                self.assertEqual(resolve_lease(replace(facts, **{field: False})), 'LEASE_INTERRUPTED')

    def test_cleanup(self):
        facts = CleanupFacts()
        self.assertEqual(resolve_cleanup_branch(facts), 'CLEANUP_PARTIAL')
        for field in ('has_commit', 'writable', 'on_main', 'branch_matches', 'merged'):
            with self.subTest(field=field):
                self.assertEqual(resolve_cleanup_branch(replace(facts, **{field: False})), 'CLEANUP_BLOCKED')

    def test_origin(self):
        self.assertFalse(resolve_main_ahead(OriginFacts(exists=False)))
        self.assertFalse(resolve_main_ahead(OriginFacts(equal=True)))
        self.assertTrue(resolve_main_ahead(OriginFacts(ancestor=True)))
        self.assertFalse(resolve_main_ahead(OriginFacts(ancestor=False)))

    def test_residue(self):
        facts = ResidueFacts(intent='intent', staged=(('stage', 'digest'),), intent_digest='hash')
        self.assertEqual(resolve_landing_residue(facts), {'intent': 'intent', 'staged': {'stage': 'digest'},
                                                         'intent_digest': 'hash', 'paths': {'intent', 'stage'}})
        for field in ('pending', 'valid', 'owner_matches', 'authority_matches', 'files_match',
                      'kind_matches', 'status_matches', 'source_matches', 'staged_bytes_match', 'status_lines_valid'):
            with self.subTest(field=field):
                self.assertIsNone(resolve_landing_residue(replace(facts, **{field: False})))
        self.assertIsNone(resolve_landing_residue(replace(facts, staged_symlink=True)))
