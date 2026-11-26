"""Match real audition output against a target revision.

Every output frame has a provenance key ``(asset_id, source_frame, gain)``.
Segment coverage matches those keys, so several listenings merge and the same
evidence can cover repeated instances of one source fragment.  Seam coverage
additionally requires the target's ordered neighbouring key pair to occur at
consecutive coordinates inside a single continuous run.
"""
from bisect import bisect_right


class FrameIndex:
    """Maps revision output coordinates to provenance keys efficiently."""

    def __init__(self, revision):
        self.revision_id = revision.revision_id
        self.placements = revision.placements
        self.starts = [placement.start for placement in self.placements]

    def key_at(self, coordinate):
        index = bisect_right(self.starts, coordinate) - 1
        placement = self.placements[index]
        segment = placement.segment
        source_frame = segment.start + (coordinate - placement.start)
        return segment.asset_id, source_frame, segment.gain


def evidence_keys_and_pairs(index, runs):
    keys = set()
    pairs = set()
    for start, end in runs:
        previous = None
        for coordinate in range(start, end):
            key = index.key_at(coordinate)
            keys.add(key)
            if previous is not None:
                pairs.add((previous, key))
            previous = key
    return keys, pairs


def _merged_windows(frame_numbers):
    """Merge sorted unique frame coordinates into half-open windows."""
    windows = []
    for frame in frame_numbers:
        if windows and frame == windows[-1][1]:
            windows[-1][1] = frame + 1
        else:
            windows.append([frame, frame + 1])
    return windows


def build_verdict(target, evidence):
    """Compute unheard windows and missing seams for chosen confirmations.

    ``evidence`` is an iterable of ``(revision, runs)`` pairs taken from the
    frozen carry confirmations in selection order.
    """
    target_index = FrameIndex(target)
    heard_keys = set()
    adjacent_pairs = set()
    for revision, runs in evidence:
        keys, pairs = evidence_keys_and_pairs(FrameIndex(revision), runs)
        heard_keys.update(keys)
        adjacent_pairs.update(pairs)

    unheard = []
    for placement in target.placements:
        missing = [
            coordinate
            for coordinate in range(placement.start, placement.end)
            if target_index.key_at(coordinate) not in heard_keys
        ]
        unheard.append({
            'segment_id': f'{target.revision_id}:{placement.ordinal}',
            'windows': _merged_windows(missing),
        })

    missing_seams = []
    for index in range(1, len(target.placements)):
        seam_position = target.placements[index].start
        left = target_index.key_at(seam_position - 1)
        right = target_index.key_at(seam_position)
        if (left, right) not in adjacent_pairs:
            missing_seams.append(seam_position)

    ready = not missing_seams and all(not item['windows'] for item in unheard)
    return tuple(unheard), tuple(missing_seams), ready
