from dataclasses import dataclass

from cuts.segments import Segment


@dataclass(frozen=True)
class Placement:
    ordinal: int
    start: int
    end: int
    segment: Segment


def place_segments(segments):
    placements = []
    position = 0
    for ordinal, segment in enumerate(segments):
        end = position + segment.length
        placements.append(Placement(ordinal, position, end, segment))
        position = end
    return tuple(placements), position


def iter_intersections(placements, start, end):
    for placement in placements:
        if placement.end <= start:
            continue
        if placement.start >= end:
            break
        left = max(start, placement.start)
        right = min(end, placement.end)
        if left < right:
            yield placement, left, right
