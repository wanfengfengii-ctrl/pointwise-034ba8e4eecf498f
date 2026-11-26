from auditions.confirmations import ConfirmationStore


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
