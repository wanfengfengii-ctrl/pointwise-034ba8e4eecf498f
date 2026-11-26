import base64

from http_support import Problem, require_id
from releases.eligibility import IneligibleRelease
from releases.issue import UnknownReleaseRevision, issue_release
from releases.packages import PackageStore


def post_release(connection, renderer, sample_rate, body):
    revision_id = require_id(body.get('revision_id'), 'revision_id')
    try:
        package = issue_release(connection, renderer, sample_rate, revision_id, body.get('confirmation_id'))
    except UnknownReleaseRevision as error:
        raise Problem(404, str(error)) from error
    except IneligibleRelease as error:
        raise Problem(409, str(error)) from error
    return {'release_id': package.release_id, 'revision_id': package.revision_id}


def get_release(connection, release_id):
    package = PackageStore(connection).get(release_id)
    if package is None:
        raise Problem(404, 'unknown release')
    return {
        'release_id': package.release_id,
        'revision_id': package.revision_id,
        'confirmation_id': package.confirmation_id,
        'cue_sheet': package.cue_sheet,
        'wav_base64': base64.b64encode(package.wav).decode('ascii'),
    }
