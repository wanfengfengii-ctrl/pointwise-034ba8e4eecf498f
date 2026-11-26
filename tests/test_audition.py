from tests.support import HTTPCase, segment


class TestAudition(HTTPCase):
    def test_seek_does_not_confirm_skipped_content(self):
        asset = self.asset([10, 20, 30])
        revision = self.cut([segment(asset, 0, 3)])['revision_id']
        audition = self.audition(revision)
        self.assertEqual(self.transport(audition, 'advance', frames=1)['samples'], [10])
        seek = self.transport(audition, 'seek', position=2)
        self.assertEqual(seek['samples'], [])
        self.assertEqual(seek['heard'], [[0, 1]])
        final = self.transport(audition, 'advance', frames=1)
        self.assertEqual(final['samples'], [30])
        self.assertEqual(final['pending'], [[1, 2]])
        self.confirm(audition, status=409)
        self.assertEqual(self.work.count('confirmations'), 0)
        self.transport(audition, 'seek', position=1)
        self.assertEqual(self.transport(audition, 'advance', frames=1)['samples'], [20])
        self.assertEqual(self.confirm(audition)['revision_id'], revision)

    def test_transport_bounds(self):
        asset = self.asset([10, 20, 30])
        revision = self.cut([segment(asset, 0, 3)])['revision_id']
        audition = self.audition(revision)
        self.transport(audition, 'advance', frames=1)
        stopped = self.transport(audition, 'pause')
        self.assertTrue(stopped['paused'])
        self.assertEqual(stopped['position'], 1)
        self.assertEqual(stopped['output_window'], [1, 1])
        self.assertEqual(stopped['samples'], [])
        for op, fields in (
            ('seek', {'position': -1}), ('seek', {'position': 4}), ('seek', {'position': False}),
            ('seek', {}), ('advance', {'frames': 0}), ('advance', {'frames': -2}),
            ('advance', {'frames': 1.5}), ('advance', {'frames': True}), ('advance', {'frames': None}),
            ('pause', {'frames': 1}), ('unknown', {}),
        ):
            with self.subTest(op=op, fields=fields):
                self.transport(audition, op, status=400, **fields)
        self.assertEqual(self.transport(audition, 'pause'), stopped)
        resumed = self.transport(audition, 'advance', frames=99)
        self.assertFalse(resumed['paused'])
        self.assertEqual(resumed['samples'], [20, 30])
        self.assertEqual(resumed['output_window'], [1, 3])
        self.assertEqual(resumed['position'], 3)
        eof = self.transport(audition, 'advance', frames=1)
        self.assertEqual(eof['samples'], [])
        self.assertEqual(eof['output_window'], [3, 3])
        self.assertEqual(eof['heard'], [[0, 3]])
        self.call('POST', '/auditions', {'revision_id': 99}, 404)
        self.transport(99, 'pause', status=404)
        self.confirm(99, status=404)
        self.assertEqual(self.work.count('auditions'), 1)

    def test_fixed_revision(self):
        a = self.asset([9, 8])
        b = self.asset([1, 2])
        original = self.cut([segment(a, 0, 2)])['revision_id']
        old_audition = self.audition(original)
        self.assertEqual(self.preview(original)['samples'], [9, 8])
        child = self.cut([segment(b, 0, 2)], original)['revision_id']
        new_audition = self.audition(child)
        child_result = self.transport(new_audition, 'advance', frames=2)
        self.assertEqual((child_result['revision_id'], child_result['samples']), (child, [1, 2]))
        old_result = self.transport(old_audition, 'advance', frames=2)
        self.assertEqual((old_result['revision_id'], old_result['samples']), (original, [9, 8]))

    def test_session_isolation(self):
        asset = self.asset([4, 5])
        revision = self.cut([segment(asset, 0, 2)])['revision_id']
        first = self.audition(revision)
        second = self.audition(revision)
        self.transport(first, 'advance', frames=1)
        self.transport(second, 'seek', position=1)
        self.transport(second, 'advance', frames=1)
        self.confirm(first, status=409)
        self.confirm(second, status=409)
        self.assertEqual(self.work.count('confirmations'), 0)
        self.transport(first, 'advance', frames=1)
        confirmation = self.confirm(first)
        self.assertEqual(self.confirm(first), confirmation)
        self.confirm(second, status=409)
        self.assertEqual(self.work.count('confirmations'), 1)

    def test_missing_block_is_not_reviewed(self):
        asset = self.asset([1, 2, 3, 4])
        revision = self.cut([segment(asset, 0, 4)])['revision_id']
        audition = self.audition(revision)
        self.work.server.cache.defer_once(revision, 2, 4)
        result = self.transport(audition, 'advance', frames=3)
        self.assertEqual(result['samples'], [1, 2, 0])
        self.assertEqual(result['position'], 3)
        self.assertEqual(result['heard'], [[0, 2]])
        self.assertEqual(result['pending'], [[2, 4]])
        self.confirm(audition, status=409)
        self.transport(audition, 'seek', position=2)
        result = self.transport(audition, 'advance', frames=2)
        self.assertEqual(result['samples'], [3, 4])
        self.assertEqual(result['pending'], [])
        self.confirm(audition)

    def test_real_silence(self):
        asset = self.asset([0, 0])
        revision = self.cut([segment(asset, 0, 2)])['revision_id']
        genuine = self.audition(revision)
        result = self.transport(genuine, 'advance', frames=2)
        self.assertEqual(result['samples'], [0, 0])
        self.assertEqual(result['heard'], [[0, 2]])
        self.confirm(genuine)
        missing = self.audition(revision)
        self.work.server.cache.defer_once(revision, 0, 2)
        fallback = self.transport(missing, 'advance', frames=2)
        self.assertEqual(fallback['samples'], [0, 0])
        self.assertEqual(fallback['heard'], [])
        self.assertEqual(fallback['pending'], [[0, 2]])
        self.confirm(missing, status=409)
        self.assertEqual(self.work.count('confirmations'), 1)

    def test_session_integrity(self):
        old_asset = self.asset([9, 8, 3, 4, 5, 6])
        new_asset = self.asset([1, 2, 3, 4, 5, 6])
        original = self.cut([segment(old_asset, 0, 6)])['revision_id']
        self.assertEqual(self.preview(original, '?start=0&end=2')['samples'], [9, 8])
        revision = self.cut([segment(new_asset, 0, 6)], original)['revision_id']
        for backfill_start, still_missing in ((2, [4, 6]), (4, [2, 4])):
            with self.subTest(backfill_start=backfill_start):
                audition = self.audition(revision)
                self.assertEqual(self.transport(audition, 'advance', frames=2)['samples'], [1, 2])
                seek = self.transport(audition, 'seek', position=4)
                self.assertEqual(seek['pending'], [[2, 6]])
                self.work.server.cache.defer_once(revision, 4, 6)
                fallback = self.transport(audition, 'advance', frames=2)
                self.assertEqual(fallback['samples'], [0, 0])
                self.assertEqual(fallback['heard'], [[0, 2]])
                self.confirm(audition, status=409)
                self.transport(audition, 'seek', position=backfill_start)
                self.assertEqual(self.transport(audition, 'advance', frames=2)['pending'], [still_missing])
                self.confirm(audition, status=409)
                self.transport(audition, 'seek', position=still_missing[0])
                complete = self.transport(audition, 'advance', frames=2)
                self.assertEqual(complete['heard'], [[0, 6]])
                self.assertEqual(self.confirm(audition)['revision_id'], revision)

    def test_confirm_uses_merged_coverage(self):
        a = self.asset([7])
        b = self.asset([0])
        revision = self.cut([segment(a, 0, 1), segment(b, 0, 1)])['revision_id']
        continuous = self.audition(revision)
        separate = self.audition(revision)
        whole = self.transport(continuous, 'advance', frames=2)
        self.assertEqual(whole['samples'], [7, 0])
        self.transport(continuous, 'seek', position=2)
        self.transport(separate, 'seek', position=1)
        self.assertEqual(self.transport(separate, 'advance', frames=1)['samples'], [0])
        self.transport(separate, 'seek', position=0)
        self.assertEqual(self.transport(separate, 'advance', frames=1)['samples'], [7])
        split_state = self.transport(separate, 'seek', position=2)
        self.assertEqual(split_state['heard'], whole['heard'])
        self.assertEqual(split_state['position'], whole['position'])
        self.assertEqual(split_state['paused'], whole['paused'])
        self.assertEqual(self.confirm(continuous)['revision_id'], revision)
        self.assertEqual(self.confirm(separate)['revision_id'], revision)

    def test_incomplete_temporary_block_is_rebuilt(self):
        asset = self.asset([11, 12, 13])
        revision = self.cut([segment(asset, 0, 3)])['revision_id']
        self.work.server.cache.put((revision, 0, 2), (99,))
        self.assertEqual(self.preview(revision)['samples'], [11, 12, 13])
        self.assertEqual(self.work.server.cache.get((revision, 0, 2)), (11, 12))
        self.assertEqual(self.work.server.cache.get((revision, 2, 3)), (13,))
        self.work.server.cache.discard((revision, 0, 2))
        self.assertIsNone(self.work.server.cache.get((revision, 0, 2)))
        self.assertEqual(self.preview(revision)['samples'], [11, 12, 13])
