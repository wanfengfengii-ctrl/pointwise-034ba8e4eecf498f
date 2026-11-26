from releases.service import initialize_workspace
from tests.support import HTTPCase, Workspace, decode_package, segment


class TestRelease(HTTPCase):
    def _ready(self, samples):
        asset = self.asset(samples)
        revision = self.cut([segment(asset, 0, len(samples))])['revision_id']
        confirmation = self.confirm_all(revision, len(samples))
        return revision, confirmation

    def _defer_commit_failure(self):
        with self.work.connection() as connection:
            connection.executescript('''
                CREATE TABLE test_commit_parent (id INTEGER PRIMARY KEY);
                CREATE TABLE test_commit_guard (
                    id INTEGER REFERENCES test_commit_parent(id) DEFERRABLE INITIALLY DEFERRED
                );
                CREATE TRIGGER test_reject_package_commit AFTER INSERT ON packages
                BEGIN
                    INSERT INTO test_commit_guard VALUES (NEW.release_id);
                END;
            ''')

    def _allow_commit(self):
        with self.work.connection() as connection:
            connection.execute('DROP TRIGGER test_reject_package_commit')

    def test_ready_package_survives_reopen(self):
        revision, confirmation = self._ready([8, 4, 0])
        release = self.release(revision, confirmation)['release_id']
        before = self.package(release)
        self.assertEqual(before['revision_id'], revision)
        self.assertEqual(before['confirmation_id'], confirmation)
        self.assertEqual(decode_package(before)['samples'], [8, 4, 0])
        self.assertGreater(self.work.server.cache.reclaim(), 0)
        self.work.reopen()
        self.assertEqual(self.package(release), before)
        self.assertEqual(self.work.server.cache.reclaim(), 0)

    def test_package_content(self):
        a = self.asset([90, 91, 92, 93, 12, -13])
        b = self.asset([80, 7, 81])
        cut = self.cut([segment(a, 4, 6, 2), segment(b, 1, 2, -1)])
        revision = cut['revision_id']
        confirmation = self.confirm_all(revision, 3)
        package = self.package(self.release(revision, confirmation)['release_id'])
        self.assertEqual(decode_package(package), {
            'sample_rate': 8000, 'channels': 1, 'width': 2, 'frames': 3, 'samples': [24, -26, -7],
        })
        self.assertEqual(package['cue_sheet'], {
            'revision_id': revision, 'project_id': 'film', 'sample_rate': 8000, 'total_frames': 3,
            'segments': [
                {'segment_id': cut['segments'][0]['segment_id'], 'ordinal': 0, 'asset_id': a,
                 'source_window': [4, 6], 'gain': 2, 'output_window': [0, 2]},
                {'segment_id': cut['segments'][1]['segment_id'], 'ordinal': 1, 'asset_id': b,
                 'source_window': [1, 2], 'gain': -1, 'output_window': [2, 3]},
            ],
        })

    def test_schema_reopen(self):
        self.work = self.enterContext(Workspace(sample_rate=11025))
        original, original_confirmation = self._ready([6, 0])
        original_release = self.release(original, original_confirmation)['release_id']
        package = self.package(original_release)
        asset = self.asset([11, 12, 13], source='夜班修复')
        child = self.cut([segment(asset, 1, 3, -1)], original)['revision_id']
        audition = self.audition(child)
        self.transport(audition, 'advance', frames=1)
        with self.assertRaises(ValueError):
            initialize_workspace(self.work.database, 8000)
        self.assertEqual(initialize_workspace(self.work.database), 11025)
        self.assertEqual(initialize_workspace(self.work.database, 11025), 11025)
        self.work.reopen()
        self.assertEqual(self.work.server.sample_rate, 11025)
        self.assertEqual(self.package(original_release), package)
        self.assertEqual(decode_package(package)['sample_rate'], 11025)
        self.assertEqual(self.preview(child)['samples'], [-12, -13])
        restored = self.transport(audition, 'advance', frames=1)
        self.assertEqual((restored['samples'], restored['heard']), ([-13], [[0, 2]]))
        child_confirmation = self.confirm(audition)['confirmation_id']
        child_issue = self.release(child, child_confirmation)['release_id']
        self.assertEqual(self.package(child_issue)['revision_id'], child)
        self.assertEqual(self.work.count('assets'), 2)
        self.assertEqual(self.work.count('revisions'), 2)
        self.assertEqual(self.work.count('confirmations'), 2)
        self.package(9999, status=404)

    def test_confirmation_must_match_revision(self):
        original, confirmation = self._ready([3, 4])
        asset = self.asset([9, 0])
        child = self.cut([segment(asset, 0, 2)], original)['revision_id']
        self.release(child, confirmation, status=409)
        self.assertEqual(self.work.count('packages'), 0)
        self.package(1, status=404)
        self.assertEqual(self.release(original, confirmation)['revision_id'], original)

    def test_unconfirmed(self):
        asset = self.asset([8, 7])
        revision = self.cut([segment(asset, 0, 2)])['revision_id']
        audition = self.audition(revision)
        self.call('POST', '/releases', {'revision_id': revision}, 409)
        for invalid in ('confirm-999', audition, f'confirm-{audition}', None):
            with self.subTest(confirmation=invalid):
                self.release(revision, invalid, status=409)
        self.assertEqual(self.work.count('packages'), 0)
        self.assertEqual(self.work.count('confirmations'), 0)
        self.package(1, status=404)

    def test_confirmation_then_package(self):
        original, original_confirmation = self._ready([3, 4])
        asset = self.asset([9, 8, 7, 6])
        cut = self.cut([segment(asset, 2, 4), segment(asset, 1, 2, 2)], original)
        child = cut['revision_id']
        self.release(child, original_confirmation, status=409)
        self.assertEqual(self.work.count('packages'), 0)
        valid = self.confirm_all(child, 3)
        package = self.package(self.release(child, valid)['release_id'])
        self.assertEqual((package['revision_id'], package['confirmation_id']), (child, valid))
        clips = package['cue_sheet']['segments']
        self.assertEqual([clip['source_window'] for clip in clips], [[2, 4], [1, 2]])
        self.assertEqual([clip['output_window'] for clip in clips], [[0, 2], [2, 3]])
        samples = decode_package(package)['samples']
        self.assertEqual(samples, [7, 6, 16])
        self.assertEqual([samples[left:right] for left, right in (c['output_window'] for c in clips)],
                         [[7, 6], [16]])

    def test_failed_issue_does_not_publish(self):
        revision, confirmation = self._ready([10, 0])
        old_release = self.release(revision, confirmation)['release_id']
        before = self.package(old_release)
        self._defer_commit_failure()
        response = self.release(revision, confirmation, status=500)
        self.assertNotIn('release_id', response)
        self.assertEqual(self.work.count('packages'), 1)
        self.package(old_release + 1, status=404)
        self.assertEqual(self.package(old_release), before)
        with self.work.connection() as connection:
            self.assertEqual(connection.execute('SELECT count(*) FROM test_commit_guard').fetchone()[0], 0)

    def test_recover_after_rollback(self):
        original, original_confirmation = self._ready([9, 0])
        old_id = self.release(original, original_confirmation)['release_id']
        before = self.package(old_id)
        revision, confirmation = self._ready([3, 6, 9])
        self._defer_commit_failure()
        self.release(revision, confirmation, status=500)
        self.assertGreater(self.work.server.cache.reclaim(), 0)
        self.work.reopen()
        self.package(old_id + 1, status=404)
        self.assertEqual(self.work.count('packages'), 1)
        self.assertEqual(self.package(old_id), before)
        self._allow_commit()
        new_id = self.release(revision, confirmation)['release_id']
        self.assertNotEqual(new_id, old_id)
        after = self.package(new_id)
        self.assertEqual(after['revision_id'], revision)
        self.assertEqual(decode_package(after)['samples'], [3, 6, 9])
        self.assertEqual(self.package(old_id), before)
        self.assertEqual(self.work.count('packages'), 2)

    def test_preview_and_issue_require_complete_render(self):
        revision, confirmation = self._ready([2, 3, 4])
        self.work.server.cache.defer_once(revision, 2, 3)
        self.preview(revision, status=503)
        self.work.server.cache.defer_once(revision, 2, 3)
        self.release(revision, confirmation, status=503)
        self.assertEqual(self.work.count('packages'), 0)
        self.package(1, status=404)
        package = self.package(self.release(revision, confirmation)['release_id'])
        self.assertEqual(decode_package(package)['samples'], [2, 3, 4])
