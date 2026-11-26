from tests.support import HTTPCase, segment


class TestPreparation(HTTPCase):
    def test_preview_uses_half_open_source_ranges(self):
        asset = self.asset([1, 2, 3])
        cut = self.cut([segment(asset, 1, 3, 2)])
        self.assertEqual(cut['total_frames'], 2)
        self.assertEqual(cut['segments'][0]['source_window'], [1, 3])
        self.assertEqual(self.preview(cut['revision_id'])['samples'], [4, 6])

    def test_asset_input(self):
        body = {'source': '卷一正片', 'sample_rate': 8000, 'samples': [0, 3]}
        asset = self.call('POST', '/assets', body, 201)
        self.assertEqual(asset, {'asset_id': asset['asset_id'], 'source': '卷一正片',
                                 'sample_rate': 8000, 'frames': 2})
        for overrides in (
            {'samples': []}, {'samples': [32768]}, {'samples': [-32769]},
            {'samples': [True]}, {'samples': [None]}, {'samples': [1.5]}, {'samples': ['1']},
            {'samples': None}, {'sample_rate': 44100}, {'sample_rate': True},
            {'sample_rate': None}, {'source': ''}, {'source': None},
        ):
            with self.subTest(overrides=overrides):
                self.call('POST', '/assets', body | overrides, 400)
        self.assertEqual(self.work.count('assets'), 1)
        cut = self.cut([segment(asset['asset_id'], 0, 2)])
        self.assertEqual(self.preview(cut['revision_id'])['samples'], [0, 3])

    def test_output_window(self):
        asset = self.asset([4, 5, 6, 7, 8])
        cut = self.cut([segment(asset, 1, 3), segment(asset, 3, 5, -1)])
        revision = cut['revision_id']
        self.assertEqual(self.preview(revision, '?start=1&end=3'), {
            'revision_id': revision, 'window': [1, 3], 'samples': [6, -7],
        })
        self.assertEqual(self.preview(revision, '?start=4&end=4'), {
            'revision_id': revision, 'window': [4, 4], 'samples': [],
        })
        for query in ('?start=-1&end=1', '?start=0&end=5', '?start=3&end=1',
                      '?start=x', '?start=1&start=2', '?end='):
            with self.subTest(query=query):
                self.preview(revision, query, status=400)
        self.preview(999, status=404)

    def test_gain_saturation(self):
        asset = self.asset([20000, -20000])
        cut = self.cut([segment(asset, 0, 2, 2)])
        self.assertEqual(self.preview(cut['revision_id'])['samples'], [32767, -32768])

    def test_frozen_cut_survives_later_edit(self):
        first = self.asset([2, 3])
        second = self.asset([6, 7])
        original = self.cut([segment(first, 0, 2), segment(second, 0, 2)])
        update = self.cut([segment(second, 0, 2), segment(first, 0, 2)], original['revision_id'])
        self.assertEqual(update['parent_revision_id'], original['revision_id'])
        self.assertEqual(self.preview(original['revision_id'])['samples'], [2, 3, 6, 7])
        self.assertEqual(self.preview(update['revision_id'])['samples'], [6, 7, 2, 3])

    def test_repeated_instances(self):
        asset = self.asset([20000, -20000])
        first = segment(asset, 0, 2, 1)
        second = segment(asset, 0, 2, 2)
        original = self.cut([first, second])
        update = self.cut([second, first], original['revision_id'])
        all_ids = []
        for cut, gains, samples in (
            (original, [1, 2], [20000, -20000, 32767, -32768]),
            (update, [2, 1], [32767, -32768, 20000, -20000]),
        ):
            placements = cut['segments']
            self.assertEqual(cut['total_frames'], 4)
            self.assertEqual([p['ordinal'] for p in placements], [0, 1])
            self.assertEqual([p['asset_id'] for p in placements], [asset, asset])
            self.assertEqual([p['source_window'] for p in placements], [[0, 2], [0, 2]])
            self.assertEqual([p['output_window'] for p in placements], [[0, 2], [2, 4]])
            self.assertEqual([p['gain'] for p in placements], gains)
            self.assertEqual(self.preview(cut['revision_id'])['samples'], samples)
            all_ids.extend(p['segment_id'] for p in placements)
        self.assertEqual(len(set(all_ids)), 4)
        self.assertEqual(self.work.count('segments'), 4)

    def test_rejects_out_of_bounds_cut(self):
        asset = self.asset([1, 2, 3])
        original = self.cut([segment(asset, 1, 3)])
        for bad in (segment(asset, 1, 4), segment(asset, 1, 1), segment(asset, -1, 2),
                    segment(asset, False, 2), segment(asset, 0, None), segment(asset, 0, 1, False),
                    segment(999, 0, 1)):
            with self.subTest(bad=bad):
                self.call('POST', '/cuts', {
                    'project_id': 'film', 'parent_revision_id': original['revision_id'],
                    'segments': [segment(asset, 0, 1), bad],
                }, 400)
        self.call('POST', '/cuts', {'project_id': 'film', 'segments': []}, 400)
        self.assertEqual(self.work.count('revisions'), 1)
        self.assertEqual(self.work.count('segments'), 1)
        self.assertEqual(self.preview(original['revision_id'])['samples'], [2, 3])

    def test_parent_scope(self):
        asset = self.asset([7, 8, 9])
        original = self.cut([segment(asset, 0, 2)], project='north')
        self.call('POST', '/cuts', {
            'project_id': 'south', 'parent_revision_id': original['revision_id'],
            'segments': [segment(asset, 0, 2)],
        }, 409)
        self.call('POST', '/cuts', {
            'project_id': 'north', 'parent_revision_id': 999, 'segments': [segment(asset, 0, 2)],
        }, 400)
        self.assertEqual(self.work.count('revisions'), 1)
        self.assertEqual(self.preview(original['revision_id'])['samples'], [7, 8])
