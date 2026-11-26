from auditions.confirmations import ConfirmationStore
from reviews.store import ReviewStore


class IneligibleRelease(ValueError):
    pass


def require_same_revision_confirmation(connection, revision, confirmation_id):
    if not isinstance(confirmation_id, str) or not confirmation_id.startswith('confirm-'):
        raise IneligibleRelease('same-revision confirmation required')
    suffix = confirmation_id.removeprefix('confirm-')
    if len(suffix) > 19 or not suffix.isascii() or not suffix.isdecimal():
        raise IneligibleRelease('same-revision confirmation required')
    confirmation = ConfirmationStore(connection).get(confirmation_id)
    if confirmation is None or confirmation.revision_id != revision.revision_id:
        raise IneligibleRelease('same-revision confirmation required')
    return confirmation


def revision_has_review(connection, revision_id):
    return ReviewStore(connection).has_for_revision(revision_id)


def require_ready_review(connection, revision, review_id):
    # Any missing, malformed or unknown verdict is "缺裁决" and therefore a
    # 409 at the release boundary rather than a request-shape 400.
    if type(review_id) is not int or not 1 <= review_id <= (1 << 63) - 1:
        raise IneligibleRelease('a ready review verdict for this revision is required')
    verdict = ReviewStore(connection).get(review_id)
    if verdict is None:
        raise IneligibleRelease('a ready review verdict for this revision is required')
    if verdict.target_revision_id != revision.revision_id:
        raise IneligibleRelease('review verdict belongs to another revision')
    if not verdict.ready:
        raise IneligibleRelease('review verdict still has unheard frames or seams')
    return verdict
