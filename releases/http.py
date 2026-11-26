import base64

from http_support import Problem, require_id
from releases.eligibility import IneligibleRelease
from releases.issue import UnknownReleaseRevision, issue_release
from releases.packages import PackageStore


def post_release(connection, renderer, sample_rate, body):
    revision_id = require_id(body.get('revision_id'), 'revision_id')
    try:
        package = issue_release(
            connection, renderer, sample_rate, revision_id, body
        )
    except UnknownReleaseRevision as error:
        raise Problem(404, str(error)) from error
    except IneligibleRelease as error:
        raise Problem(409, str(error)) from error
    return {'release_id': package.release_id, 'revision_id': package.revision_id}


def get_release(connection, release_id):
    package = PackageStore(connection).get(release_id)
    if package is None:
        raise Problem(404, 'unknown release')
    payload = {
        'release_id': package.release_id,
        'revision_id': package.revision_id,
    }
    if package.review_id is not None:
        # Carry releases explicitly carry the verdict and a null confirmation.
        payload['review_id'] = package.review_id
        payload['confirmation_id'] = None
    else:
        # Original same-revision confirmation packages keep README's shape.
        payload['confirmation_id'] = package.confirmation_id
    payload['cue_sheet'] = package.cue_sheet
    payload['wav_base64'] = base64.b64encode(package.wav).decode('ascii')
    return payload
