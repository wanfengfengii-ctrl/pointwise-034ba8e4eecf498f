from dataclasses import dataclass


class InvalidSegment(ValueError):
    pass


@dataclass(frozen=True)
class Segment:
    asset_id: int
    start: int
    end: int
    gain: int

    @property
    def length(self):
        return self.end - self.start


def validate_segment(asset_id, start, end, gain, asset_frames):
    if type(start) is not int or type(end) is not int:
        raise InvalidSegment('source window endpoints must be integers')
    if not 0 <= start < end <= asset_frames:
        raise InvalidSegment('source window must be non-empty and within the asset')
    if type(gain) is not int:
        raise InvalidSegment('gain must be an integer')
    return Segment(asset_id, start, end, gain)
