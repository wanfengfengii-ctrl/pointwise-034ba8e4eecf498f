"""Run the V1 comparison for the A, B, C, D review sample over HTTP."""
import json

from demo import call, check
from tests.support import Workspace, decode_package, segment


def prepare(work):
    clips = {}
    for name, samples in (("A", [31, 7]), ("B", [8]), ("C", [9]), ("D", [0, 11]), ("E", [0, 11])):
        asset = call(work, "POST", "/assets", {
            "source": f"馆藏声带 {name}", "sample_rate": work.sample_rate, "samples": samples,
        }, 201)
        clips[name] = segment(asset["asset_id"], 0, len(samples))
    parent = freeze(work, clips, "ABCD")
    target = freeze(work, clips, "AD", parent["revision_id"])
    return parent, target, clips


def freeze(work, clips, order, parent=None):
    return call(work, "POST", "/cuts", {
        "project_id": "screening-restoration", "parent_revision_id": parent,
        "segments": [clips[name] for name in order],
    }, 201)


def open_audition(work, revision):
    return call(work, "POST", "/auditions", {"revision_id": revision}, 201)["audition_id"]


def transport(work, audition, op, **fields):
    return call(work, "POST", f"/auditions/{audition}/transport", {"op": op, **fields})


def main():
    with Workspace(block_frames=2) as work:
        parent, target, _ = prepare(work)
        for offset in (0, 3):
            audition = open_audition(work, parent["revision_id"])
            transport(work, audition, "seek", position=offset)
            result = transport(work, audition, "advance", frames=3)
            check(result["samples"], [31, 7, 8] if offset == 0 else [9, 0, 11])
            call(work, "POST", f"/auditions/{audition}/confirm", {}, 409)

        revision = target["revision_id"]
        straight = open_audition(work, revision)
        check(transport(work, straight, "advance", frames=2)["samples"], [31, 7])
        check(transport(work, straight, "advance", frames=2)["samples"], [0, 11])

        split = open_audition(work, revision)
        transport(work, split, "seek", position=2)
        transport(work, split, "advance", frames=2)
        transport(work, split, "seek", position=0)
        transport(work, split, "advance", frames=2)

        repaired = open_audition(work, revision)
        work.server.cache.defer_once(revision, 2, 4)
        fallback = transport(work, repaired, "advance", frames=3)
        check(fallback["samples"], [31, 7, 0])
        check(fallback["pending"], [[2, 4]])
        transport(work, repaired, "seek", position=2)
        transport(work, repaired, "advance", frames=2)

        states, confirmations = [], []
        for audition in (straight, split, repaired):
            state = transport(work, audition, "seek", position=4)
            states.append({key: state[key] for key in ("position", "paused", "heard", "pending")})
            confirmed = call(work, "POST", f"/auditions/{audition}/confirm", {})
            check(confirmed["revision_id"], revision)
            confirmations.append(confirmed["confirmation_id"])
        check(states, [{"position": 4, "paused": False, "heard": [[0, 4]], "pending": []}] * 3)
        issued = call(work, "POST", "/releases", {
            "revision_id": revision, "confirmation_id": confirmations[1],
        }, 201)
        path = "/releases/" + str(issued["release_id"])
        original = call(work, "GET", path)
        assert work.server.cache.reclaim() > 0
        work.reopen()
        check(call(work, "GET", path), original)
        samples = decode_package(original)["samples"]
        check(samples, [31, 7, 0, 11])
        print(json.dumps({"v1_progress": states, "fallback_pending": fallback["pending"],
                          "v1_release_id": issued["release_id"], "wav_samples": samples}, ensure_ascii=False))


if __name__ == "__main__":
    main()
