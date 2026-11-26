"""Tests for the REVIEW.md cut-carrying audition review flow."""
from tests.support import HTTPCase, decode_package, segment


class ReviewFixture(HTTPCase):
    def build_abcd(self, include_e=True):
        clips = {}
        for name, samples in (
            ("A", [31, 7]), ("B", [8]), ("C", [9]), ("D", [0, 11]), ("E", [0, 11]),
        ):
            if name == "E" and not include_e:
                continue
            asset = self.asset(samples, source=f"馆藏 {name}")
            clips[name] = segment(asset, 0, len(samples))
        parent = self.cut([clips["A"], clips["B"], clips["C"], clips["D"]])
        target = self.cut([clips["A"], clips["D"]], parent=parent["revision_id"])
        return parent, target, clips

    def review_confirm(self, audition_id, status=200):
        return self.call(
            "POST", f"/auditions/{audition_id}/review-confirm", {}, status
        )

    def create_review(self, target_id, audition_ids, status=201):
        return self.call("POST", "/reviews", {
            "target_revision_id": target_id, "audition_ids": audition_ids,
        }, status)

    def db_count(self, table):
        # Direct SQL so these tests do not depend on the support count
        # helper's table whitelist for the newly added tables.
        with self.work.connection() as connection:
            return connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]

    def listen_parent_halves(self, parent_id):
        first = self.audition(parent_id)
        self.transport(first, "seek", position=0)
        self.assertEqual(self.transport(first, "advance", frames=3)["samples"], [31, 7, 8])
        self.review_confirm(first)

        second = self.audition(parent_id)
        self.transport(second, "seek", position=3)
        self.assertEqual(self.transport(second, "advance", frames=3)["samples"], [9, 0, 11])
        self.review_confirm(second)
        return first, second


class TestCarryVerdict(ReviewFixture):
    def test_canonical_verdict_then_ready_release_and_reopen(self):
        parent, target, _ = self.build_abcd()
        revision = target["revision_id"]
        first, second = self.listen_parent_halves(parent["revision_id"])

        verdict = self.create_review(revision, [first, second])
        self.assertEqual(verdict, {
            "review_id": 1,
            "target_revision_id": revision,
            "audition_ids": [first, second],
            "unheard": [
                {"segment_id": f"{revision}:0", "windows": []},
                {"segment_id": f"{revision}:1", "windows": []},
            ],
            "missing_seams": [2],
            "ready": False,
        })
        self.assertEqual(self.call("GET", "/reviews/1"), verdict)

        # A not-ready verdict cannot issue.
        self.call("POST", "/releases", {
            "revision_id": revision, "review_id": 1,
        }, 409)
        self.assertEqual(self.work.count("packages"), 0)

        # Continuous run from output frame 1 through 3 hears A1, D0, D1 and
        # the ordered pair (A1, D0) across the seam.
        bridge = self.audition(revision)
        self.transport(bridge, "seek", position=1)
        self.assertEqual(self.transport(bridge, "advance", frames=3)["samples"], [7, 0, 11])
        self.review_confirm(bridge)

        ready = self.create_review(revision, [first, second, bridge])
        self.assertEqual(ready["review_id"], 2)
        self.assertTrue(ready["ready"])
        self.assertEqual(ready["missing_seams"], [])
        self.assertEqual(ready["unheard"], [
            {"segment_id": f"{revision}:0", "windows": []},
            {"segment_id": f"{revision}:1", "windows": []},
        ])
        self.assertEqual(self.call("GET", "/reviews/2"), ready)

        issued = self.call("POST", "/releases", {
            "revision_id": revision, "review_id": 2,
        }, 201)
        self.assertEqual(issued, {"release_id": 1, "revision_id": revision})
        package = self.package(1)
        self.assertEqual(package["review_id"], 2)
        self.assertIsNone(package["confirmation_id"])
        self.assertEqual(decode_package(package)["samples"], [31, 7, 0, 11])

        # Reclaim temporary blocks and reopen: verdict and issue survive.
        self.assertGreater(self.work.server.cache.reclaim(), 0)
        self.work.reopen()
        self.assertEqual(self.call("GET", "/reviews/1"), verdict)
        self.assertEqual(self.call("GET", "/reviews/2"), ready)
        self.assertEqual(self.review_confirm(first), {
            "audition_id": first, "revision_id": parent["revision_id"],
        })
        reopened = self.package(1)
        self.assertEqual(reopened, package)
        self.assertEqual(decode_package(reopened)["samples"], [31, 7, 0, 11])

    def test_in_place_seek_between_frames_breaks_seam(self):
        parent, target, _ = self.build_abcd()
        revision = target["revision_id"]
        first, second = self.listen_parent_halves(parent["revision_id"])

        split = self.audition(revision)
        self.transport(split, "seek", position=1)
        self.transport(split, "advance", frames=1)   # A1 at output 1
        self.transport(split, "seek", position=2)    # in-place seek breaks
        self.transport(split, "advance", frames=1)   # D0 at output 2
        self.review_confirm(split)

        edge_a = self.audition(revision)
        self.transport(edge_a, "advance", frames=1)  # A0
        self.review_confirm(edge_a)
        edge_d = self.audition(revision)
        self.transport(edge_d, "seek", position=3)
        self.transport(edge_d, "advance", frames=1)  # D1
        self.review_confirm(edge_d)

        verdict = self.create_review(revision, [first, second, split, edge_a, edge_d])
        self.assertEqual(verdict["unheard"], [
            {"segment_id": f"{revision}:0", "windows": []},
            {"segment_id": f"{revision}:1", "windows": []},
        ])
        self.assertEqual(verdict["missing_seams"], [2])
        self.assertFalse(verdict["ready"])
        self.call("POST", "/releases", {"revision_id": revision, "review_id": verdict["review_id"]}, 409)

    def test_pause_between_frames_breaks_seam(self):
        _, target, _ = self.build_abcd()
        revision = target["revision_id"]
        paused = self.audition(revision)
        self.transport(paused, "seek", position=1)
        self.transport(paused, "advance", frames=1)
        self.transport(paused, "pause")
        self.transport(paused, "advance", frames=1)
        self.review_confirm(paused)
        verdict = self.create_review(revision, [paused])
        self.assertIn(2, verdict["missing_seams"])

    def test_fill_block_across_cut_keeps_seam_unheard(self):
        parent, target, _ = self.build_abcd()
        revision = target["revision_id"]
        first, second = self.listen_parent_halves(parent["revision_id"])

        repaired = self.audition(revision)
        self.work.server.cache.defer_once(revision, 2, 4)
        self.transport(repaired, "seek", position=1)
        crossing = self.transport(repaired, "advance", frames=2)
        self.assertEqual(crossing["samples"], [7, 0])
        self.assertEqual(crossing["heard"], [[1, 2]])
        # Listen back to cover D cleanly, but as a separate passage.
        self.transport(repaired, "seek", position=2)
        self.assertEqual(self.transport(repaired, "advance", frames=2)["samples"], [0, 11])
        self.review_confirm(repaired)

        verdict = self.create_review(revision, [first, second, repaired])
        self.assertEqual(verdict["unheard"], [
            {"segment_id": f"{revision}:0", "windows": []},
            {"segment_id": f"{revision}:1", "windows": []},
        ])
        self.assertEqual(verdict["missing_seams"], [2])
        self.assertFalse(verdict["ready"])

    def test_equivalent_independent_asset_does_not_cover(self):
        parent, _, clips = self.build_abcd()
        asset_e = self.asset([0, 11], source="馆藏 E 独立素材")
        ae_target = self.cut(
            [clips["A"], segment(asset_e, 0, 2)], parent=parent["revision_id"]
        )
        first, second = self.listen_parent_halves(parent["revision_id"])
        revision = ae_target["revision_id"]
        verdict = self.create_review(revision, [first, second])
        self.assertEqual(verdict["unheard"], [
            {"segment_id": f"{revision}:0", "windows": []},
            {"segment_id": f"{revision}:1", "windows": [[2, 4]]},
        ])
        self.assertEqual(verdict["missing_seams"], [2])
        self.assertFalse(verdict["ready"])

    def test_repeated_instance_reuses_evidence_but_seam_is_independent(self):
        asset = self.asset([5, 6, 7])
        parent = self.cut([segment(asset, 0, 2)])
        repeated = self.cut(
            [segment(asset, 0, 2), segment(asset, 0, 2)], parent=parent["revision_id"]
        )
        revision = repeated["revision_id"]

        half = self.audition(revision)
        self.assertEqual(self.transport(half, "advance", frames=2)["samples"], [5, 6])
        self.review_confirm(half)
        verdict = self.create_review(revision, [half])
        # The same key evidence covers both repeated instances ...
        self.assertEqual(verdict["unheard"], [
            {"segment_id": f"{revision}:0", "windows": []},
            {"segment_id": f"{revision}:1", "windows": []},
        ])
        # ... but the seam needs the ordered pair (6, 5), not (5, 6).
        self.assertEqual(verdict["missing_seams"], [2])

        whole = self.audition(revision)
        self.transport(whole, "advance", frames=4)
        self.review_confirm(whole)
        ready = self.create_review(revision, [half, whole])
        self.assertEqual(ready["missing_seams"], [])
        self.assertTrue(ready["ready"])

    def test_continuity_spans_separate_advance_requests(self):
        _, target, _ = self.build_abcd()
        revision = target["revision_id"]
        audition = self.audition(revision)
        self.transport(audition, "seek", position=1)
        self.transport(audition, "advance", frames=1)   # A1
        self.transport(audition, "advance", frames=1)   # D0, still continuous
        self.transport(audition, "advance", frames=1)   # D1
        self.review_confirm(audition)
        verdict = self.create_review(revision, [audition])
        self.assertNotIn(2, verdict["missing_seams"])

    def test_partial_selection_reports_merged_global_windows(self):
        parent, target, _ = self.build_abcd()
        first, second = self.listen_parent_halves(parent["revision_id"])
        revision = target["revision_id"]

        only_first = self.create_review(revision, [first])
        self.assertEqual(only_first["unheard"], [
            {"segment_id": f"{revision}:0", "windows": []},
            {"segment_id": f"{revision}:1", "windows": [[2, 4]]},
        ])

        only_second = self.create_review(revision, [second])
        self.assertEqual(only_second["unheard"], [
            {"segment_id": f"{revision}:0", "windows": [[0, 2]]},
            {"segment_id": f"{revision}:1", "windows": []},
        ])

    def test_partial_window_merges_disjoint_gaps(self):
        asset = self.asset([10, 11, 12, 13])
        parent = self.cut([segment(asset, 0, 4)])["revision_id"]
        child = self.cut([segment(asset, 0, 4)], parent=parent)["revision_id"]
        audition = self.audition(parent)
        # Hear source frames 10 and 12 only, in two broken passages.
        self.transport(audition, "advance", frames=1)
        self.transport(audition, "seek", position=2)
        self.transport(audition, "advance", frames=1)
        self.review_confirm(audition)
        verdict = self.create_review(child, [audition])
        self.assertEqual(verdict["unheard"], [
            {"segment_id": f"{child}:0", "windows": [[1, 2], [3, 4]]},
        ])

    def test_each_seam_checked_separately(self):
        x = self.asset([1, 2])
        y = self.asset([3])
        z = self.asset([4])
        parent = self.cut([segment(x, 0, 2), segment(y, 0, 1)])
        target = self.cut(
            [segment(x, 0, 2), segment(y, 0, 1), segment(z, 0, 1)],
            parent=parent["revision_id"],
        )
        audition = self.audition(parent["revision_id"])
        self.transport(audition, "seek", position=1)
        self.transport(audition, "advance", frames=2)  # X1 then Y0
        self.review_confirm(audition)
        verdict = self.create_review(target["revision_id"], [audition])
        # Seam at 2 (X1|Y0) is evidenced; seam at 3 (Y0|Z0) is not.
        self.assertEqual(verdict["missing_seams"], [3])


class TestReviewConfirmation(ReviewFixture):
    def test_no_real_output_is_409(self):
        revision = self.cut([segment(self.asset([1, 2]), 0, 2)])["revision_id"]
        empty = self.audition(revision)
        self.review_confirm(empty, 409)
        self.assertEqual(self.db_count("review_confirmations"), 0)

        paused = self.audition(revision)
        self.transport(paused, "pause")
        self.review_confirm(paused, 409)

    def test_fill_only_output_is_409(self):
        revision = self.cut([segment(self.asset([1, 2]), 0, 2)])["revision_id"]
        audition = self.audition(revision)
        self.work.server.cache.defer_once(revision, 0, 2)
        result = self.transport(audition, "advance", frames=2)
        self.assertEqual(result["heard"], [])
        self.review_confirm(audition, 409)
        self.assertEqual(self.db_count("review_confirmations"), 0)

    def test_confirmation_freezes_later_output_and_is_idempotent(self):
        asset = self.asset([1, 2, 3])
        parent = self.cut([segment(asset, 0, 3)])["revision_id"]
        child = self.cut([segment(asset, 0, 3)], parent=parent)["revision_id"]

        audition = self.audition(parent)
        self.transport(audition, "advance", frames=1)
        first = self.review_confirm(audition)
        self.assertEqual(first, {"audition_id": audition, "revision_id": parent})

        # More output after confirmation does not change the frozen fact.
        self.transport(audition, "advance", frames=2)
        again = self.review_confirm(audition)
        self.assertEqual(again, first)

        verdict = self.create_review(child, [audition])
        self.assertEqual(verdict["unheard"], [
            {"segment_id": f"{child}:0", "windows": [[1, 3]]},
        ])
        self.assertFalse(verdict["ready"])

        fresh = self.audition(parent)
        self.transport(fresh, "advance", frames=3)
        self.review_confirm(fresh)
        ready = self.create_review(child, [audition, fresh])
        self.assertTrue(ready["ready"])

    def test_old_merged_progress_is_not_continuous_evidence(self):
        revision = self.cut([segment(self.asset([1, 2, 3]), 0, 3)])["revision_id"]
        with self.work.connection() as connection:
            connection.execute('''
                INSERT INTO auditions(audition_id, revision_id, position, paused, heard)
                VALUES (?, ?, 3, 0, '[[0,3]]')
            ''', (55, revision))
        self.review_confirm(55, 409)
        self.assertEqual(self.db_count("review_confirmations"), 0)

    def test_nonempty_confirm_body_rejected(self):
        revision = self.cut([segment(self.asset([1]), 0, 1)])["revision_id"]
        audition = self.audition(revision)
        self.transport(audition, "advance", frames=1)
        self.call("POST", f"/auditions/{audition}/review-confirm", {"unexpected": 1}, 400)


class TestReviewValidation(ReviewFixture):
    def test_malformed_requests_are_400(self):
        target = self.cut([segment(self.asset([1]), 0, 1)])["revision_id"]
        for body in (
            {},
            {"target_revision_id": target},
            {"target_revision_id": "2", "audition_ids": [1]},
            {"target_revision_id": True, "audition_ids": [1]},
            {"target_revision_id": 0, "audition_ids": [1]},
            {"target_revision_id": target, "audition_ids": []},
            {"target_revision_id": target, "audition_ids": "1"},
            {"target_revision_id": target, "audition_ids": ["1"]},
            {"target_revision_id": target, "audition_ids": [True]},
            {"target_revision_id": target, "audition_ids": [0]},
            {"target_revision_id": target, "audition_ids": [1.5]},
        ):
            with self.subTest(body=body):
                self.call("POST", "/reviews", body, 400)
        self.assertEqual(self.db_count("reviews"), 0)

    def test_unknown_target_and_selection_are_404(self):
        parent, target, _ = self.build_abcd()
        first, _ = self.listen_parent_halves(parent["revision_id"])
        self.create_review(999, [first], 404)
        self.create_review(target["revision_id"], [999], 404)
        self.call("GET", "/reviews/999", status=404)
        self.call("GET", "/reviews/not-an-id", status=404)

    def test_root_target_is_409(self):
        root = self.cut([segment(self.asset([1, 2]), 0, 2)])["revision_id"]
        audition = self.audition(root)
        self.transport(audition, "advance", frames=2)
        self.review_confirm(audition)
        self.create_review(root, [audition], 409)
        self.assertEqual(self.db_count("reviews"), 0)

    def test_unconfirmed_selection_is_409(self):
        _, target, _ = self.build_abcd()
        plain = self.audition(target["revision_id"])
        self.transport(plain, "advance", frames=4)
        # A legacy whole-draft confirmation is not a carry credential.
        self.confirm(plain)
        self.create_review(target["revision_id"], [plain], 409)
        self.assertEqual(self.db_count("reviews"), 0)

    def test_out_of_scope_revision_is_409(self):
        asset = self.asset([1, 2])
        grandparent = self.cut([segment(asset, 0, 1)])["revision_id"]
        parent = self.cut([segment(asset, 0, 1)], parent=grandparent)["revision_id"]
        target = self.cut([segment(asset, 0, 1)], parent=parent)["revision_id"]

        remote = self.audition(grandparent)
        self.transport(remote, "advance", frames=1)
        self.review_confirm(remote)
        self.create_review(target, [remote], 409)
        self.assertEqual(self.db_count("reviews"), 0)


class TestReleaseGate(ReviewFixture):
    def _ready_review(self):
        parent, target, _ = self.build_abcd()
        first, second = self.listen_parent_halves(parent["revision_id"])
        bridge = self.audition(target["revision_id"])
        self.transport(bridge, "seek", position=1)
        self.transport(bridge, "advance", frames=3)
        self.review_confirm(bridge)
        verdict = self.create_review(target["revision_id"], [first, second, bridge])
        return target["revision_id"], verdict["review_id"]

    def test_old_confirmation_cannot_bypass_after_review(self):
        revision, ready_id = self._ready_review()
        # Build a valid same-revision legacy confirmation as well.
        legacy = self.confirm_all(revision, 4)
        self.call("POST", "/releases", {
            "revision_id": revision, "confirmation_id": legacy,
        }, 409)
        self.call("POST", "/releases", {"revision_id": revision}, 409)
        self.call("POST", "/releases", {
            "revision_id": revision, "review_id": "2",
        }, 409)
        self.call("POST", "/releases", {
            "revision_id": revision, "review_id": 999,
        }, 409)
        self.assertEqual(self.work.count("packages"), 0)
        issued = self.call("POST", "/releases", {
            "revision_id": revision, "review_id": ready_id,
        }, 201)
        self.assertEqual(issued["release_id"], 1)

    def test_wrong_revision_verdict_is_409(self):
        revision, ready_id = self._ready_review()
        other_asset = self.asset([9, 9])
        other = self.cut([segment(other_asset, 0, 2)], parent=revision)["revision_id"]
        # Give `other` its own (not ready) verdict so it is carry-managed.
        aud = self.audition(other)
        self.transport(aud, "advance", frames=1)
        self.review_confirm(aud)
        self.create_review(other, [aud])
        self.call("POST", "/releases", {
            "revision_id": other, "review_id": ready_id,
        }, 409)

    def test_carry_release_keeps_complete_render_boundary(self):
        revision, ready_id = self._ready_review()
        self.work.server.cache.defer_once(revision, 0, 2)
        self.call("POST", "/releases", {
            "revision_id": revision, "review_id": ready_id,
        }, 503)
        self.assertEqual(self.db_count("packages"), 0)
        issued = self.call("POST", "/releases", {
            "revision_id": revision, "review_id": ready_id,
        }, 201)
        self.assertEqual(issued["release_id"], 1)

    def test_failed_review_does_not_change_eligibility(self):
        asset = self.asset([4, 5, 6])
        parent = self.cut([segment(asset, 0, 3)])["revision_id"]
        child = self.cut([segment(asset, 0, 3)], parent=parent)["revision_id"]
        plain = self.audition(child)
        self.transport(plain, "advance", frames=1)
        # A valid-shaped but invalid selection leaves no verdict and no lock.
        self.create_review(child, [plain], 409)
        self.assertEqual(self.db_count("reviews"), 0)
        confirmation = self.confirm_all(child, 3)
        issued = self.release(child, confirmation)
        self.assertEqual(issued["revision_id"], child)
        package = self.package(issued["release_id"])
        self.assertEqual(package["confirmation_id"], confirmation)
        self.assertNotIn("review_id", package)
