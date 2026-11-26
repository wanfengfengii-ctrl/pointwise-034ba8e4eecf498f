from cuts.drafts import InvalidCut, ParentProjectConflict, freeze_cut
from http_support import Problem


def post_cut(connection, body):
    try:
        revision = freeze_cut(
            connection, body.get('project_id'), body.get('parent_revision_id'), body.get('segments')
        )
    except InvalidCut as error:
        raise Problem(400, str(error)) from error
    except ParentProjectConflict as error:
        raise Problem(409, str(error)) from error
    return {
        'revision_id': revision.revision_id,
        'project_id': revision.project_id,
        'parent_revision_id': revision.parent_revision_id,
        'total_frames': revision.total_frames,
        'segments': revision.describe_segments(),
    }
