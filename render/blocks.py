from dataclasses import dataclass

from cuts.timeline import iter_intersections
from render.gain import apply_gain
from sources.catalog import AssetCatalog


@dataclass(frozen=True)
class RenderBlock:
    start: int
    end: int
    samples: tuple[int, ...] | None


class BlockUnavailable(Exception):
    def __init__(self, start, end):
        super().__init__(f'render unavailable for output window [{start},{end})')


class BlockRenderer:
    def __init__(self, connection, cache, block_frames):
        if type(block_frames) is not int or block_frames <= 0:
            raise ValueError('block size must be positive')
        self.catalog = AssetCatalog(connection)
        self.cache = cache
        self.block_frames = block_frames

    def _build_block(self, revision, start, end):
        samples = []
        assets = {}
        for placement, left, right in iter_intersections(revision.placements, start, end):
            segment = placement.segment
            if segment.asset_id not in assets:
                asset = self.catalog.get(segment.asset_id)
                if asset is None:
                    return None
                assets[segment.asset_id] = asset.samples
            source_start = segment.start + left - placement.start
            source_end = source_start + right - left
            raw = assets[segment.asset_id][source_start:source_end]
            if len(raw) != right - left:
                return None
            samples.extend(apply_gain(sample, segment.gain) for sample in raw)
        if len(samples) != end - start:
            return None
        return tuple(samples)

    def _load_block(self, revision, start, end):
        key = (revision.revision_id, start, end)
        if self.cache.take_deferral(key):
            return None
        cached = self.cache.get(key)
        if cached is not None:
            if len(cached) == end - start:
                return cached
            self.cache.discard(key)
        samples = self._build_block(revision, start, end)
        if samples is not None:
            self.cache.put(key, samples)
        return samples

    def iter_window(self, revision, start, end):
        if not 0 <= start <= end <= revision.total_frames:
            raise ValueError('output window is outside the revision')
        if start == end:
            return
        first_block = (start // self.block_frames) * self.block_frames
        for block_start in range(first_block, end, self.block_frames):
            block_end = min(block_start + self.block_frames, revision.total_frames)
            left = max(block_start, start)
            right = min(block_end, end)
            samples = self._load_block(revision, block_start, block_end)
            if samples is not None:
                samples = samples[left - block_start:right - block_start]
            yield RenderBlock(left, right, samples)

    def render_strict(self, revision, start, end):
        samples = []
        for block in self.iter_window(revision, start, end):
            if block.samples is None:
                raise BlockUnavailable(block.start, block.end)
            samples.extend(block.samples)
        return tuple(samples)
