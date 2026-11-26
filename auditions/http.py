from auditions.confirmations import ConfirmationStore, InsufficientCoverage
from auditions.progress import pending_windows
from auditions.sessions import AuditionStore, UnknownAudition, UnknownRevision
from auditions.transport import InvalidTransport, apply_transport
from http_support import Problem, require_id


def _state(session):
    return {
        'audition_id': session.audition_id,
        'revision_id': session.revision_id,
        'position': session.position,
        'paused': session.paused,
        'heard': session.heard,
        'pending': pending_windows(session.heard, session.total_frames),
    }


def post_audition(connection, body):
    revision_id = require_id(body.get('revision_id'), 'revision_id')
    try:
        session = AuditionStore(connection).open_session(revision_id)
    except UnknownRevision as error:
        raise Problem(404, str(error)) from error
    return _state(session)


def post_transport(connection, renderer, audition_id, body):
    try:
        result = apply_transport(connection, renderer, audition_id, body)
    except UnknownAudition as error:
        raise Problem(404, str(error)) from error
    except InvalidTransport as error:
        raise Problem(400, str(error)) from error
    response = _state(result.session)
    response.update(output_window=[result.start, result.end], samples=result.samples)
    return response


def post_confirmation(connection, audition_id, body):
    if body:
        raise Problem(400, 'confirmation body must be empty')
    try:
        confirmation = ConfirmationStore(connection).confirm(audition_id)
    except UnknownAudition as error:
        raise Problem(404, str(error)) from error
    except InsufficientCoverage as error:
        raise Problem(409, str(error)) from error
    return {
        'confirmation_id': confirmation.confirmation_id,
        'audition_id': confirmation.audition_id,
        'revision_id': confirmation.revision_id,
    }
