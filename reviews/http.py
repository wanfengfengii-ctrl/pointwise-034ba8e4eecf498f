from auditions.sessions import UnknownAudition
from http_support import Problem, require_id
from reviews.carry import (
    RootRevisionTarget,
    SelectionOutOfScope,
    UnconfirmedSelection,
    UnknownReviewTarget,
    UnknownSelectedAudition,
    confirm_audition_for_review,
    create_review,
)
from reviews.store import NoActualOutput, ReviewStore


def post_review_confirm(connection, audition_id, body):
    if body:
        raise Problem(400, 'review confirmation body must be empty')
    try:
        confirmation = confirm_audition_for_review(connection, audition_id)
    except UnknownAudition as error:
        raise Problem(404, str(error)) from error
    except NoActualOutput as error:
        raise Problem(409, str(error)) from error
    return {
        'audition_id': confirmation.audition_id,
        'revision_id': confirmation.revision_id,
    }


def post_review(connection, body):
    target_revision_id = require_id(body.get('target_revision_id'), 'target_revision_id')
    raw_ids = body.get('audition_ids')
    if not isinstance(raw_ids, list) or not raw_ids:
        raise Problem(400, 'audition_ids must be a non-empty array')
    audition_ids = [require_id(item, 'audition_id') for item in raw_ids]

    try:
        verdict = create_review(connection, target_revision_id, audition_ids)
    except UnknownReviewTarget as error:
        raise Problem(404, str(error)) from error
    except UnknownSelectedAudition as error:
        raise Problem(404, str(error)) from error
    except (RootRevisionTarget, UnconfirmedSelection, SelectionOutOfScope) as error:
        raise Problem(409, str(error)) from error
    return verdict.as_dict()


def get_review(connection, review_id):
    verdict = ReviewStore(connection).get(review_id)
    if verdict is None:
        raise Problem(404, 'unknown review')
    return verdict.as_dict()
