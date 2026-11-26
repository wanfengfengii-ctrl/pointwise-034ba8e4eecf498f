from cuts.revisions import RevisionStore
from cuts.segments import InvalidSegment, validate_segment
from cuts.timeline import place_segments
from sources.catalog import AssetCatalog
from workspace import transaction


class InvalidCut(ValueError):
    pass


class ParentProjectConflict(ValueError):
    pass


def _valid_id(value):
    return type(value) is int and 1 <= value < 1 << 63


def freeze_cut(connection, project_id, parent_revision_id, draft):
    if not isinstance(project_id, str) or not project_id.strip():
        raise InvalidCut('project_id must be a non-empty label')
    try:
        project_id.encode('utf-8')
    except UnicodeError as error:
        raise InvalidCut('project_id must contain valid Unicode') from error
    if not isinstance(draft, list) or not draft:
        raise InvalidCut('segments must be a non-empty array')
    if parent_revision_id is not None and not _valid_id(parent_revision_id):
        raise InvalidCut('invalid parent revision ID')

    revisions = RevisionStore(connection)
    catalog = AssetCatalog(connection)
    with transaction(connection):
        if parent_revision_id is not None:
            parent = revisions.get(parent_revision_id)
            if parent is None:
                raise InvalidCut('unknown parent revision')
            if parent.project_id != project_id:
                raise ParentProjectConflict('parent revision belongs to another project')

        frame_counts = {}
        segments = []
        for ordinal, item in enumerate(draft):
            if not isinstance(item, dict) or not _valid_id(item.get('asset_id')):
                raise InvalidCut(f'segment {ordinal} must identify an asset')
            asset_id = item['asset_id']
            if asset_id not in frame_counts:
                asset = catalog.get(asset_id)
                if asset is None:
                    raise InvalidCut(f'segment {ordinal} references an unknown asset')
                frame_counts[asset_id] = asset.frames
            try:
                segment = validate_segment(
                    asset_id, item.get('start'), item.get('end'), item.get('gain'),
                    frame_counts[asset_id],
                )
            except InvalidSegment as error:
                raise InvalidCut(f'segment {ordinal}: {error}') from error
            segments.append(segment)
        placements, total_frames = place_segments(segments)
        revision = revisions.insert_frozen(project_id, parent_revision_id, placements, total_frames)
    return revision
