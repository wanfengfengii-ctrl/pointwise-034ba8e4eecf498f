from urllib.parse import parse_qs

from cuts.revisions import RevisionStore
from http_support import Problem


def _endpoint(query, name, default):
    values = query.get(name)
    if values is None:
        return default
    if len(values) != 1:
        raise Problem(400, f'{name} must occur once')
    try:
        return int(values[0])
    except ValueError as error:
        raise Problem(400, f'{name} must be an integer') from error


def get_preview(connection, renderer, revision_id, raw_query):
    revision = RevisionStore(connection).get(revision_id)
    if revision is None:
        raise Problem(404, 'unknown revision')
    query = parse_qs(raw_query, keep_blank_values=True)
    if query.keys() - {'start', 'end'}:
        raise Problem(400, 'unknown preview parameter')
    start = _endpoint(query, 'start', 0)
    end = _endpoint(query, 'end', revision.total_frames)
    if not 0 <= start <= end <= revision.total_frames:
        raise Problem(400, 'output window is outside the revision')
    samples = renderer.render_strict(revision, start, end)
    return {'revision_id': revision.revision_id, 'window': [start, end], 'samples': samples}
