from dataclasses import dataclass, replace

from auditions.evidence import EvidenceStore, break_continuity, integrate_advance
from auditions.progress import merge_heard
from auditions.sessions import AuditionSession, AuditionStore, UnknownAudition
from cuts.revisions import RevisionStore
from workspace import transaction


@dataclass(frozen=True)
class TransportResult:
    session: AuditionSession
    start: int
    end: int
    samples: tuple[int, ...]
    real_intervals: tuple[tuple[int, int], ...] = ()


class InvalidTransport(ValueError):
    pass


def _advance(connection, renderer, session, frames):
    if type(frames) is not int or frames <= 0:
        raise InvalidTransport('frames must be a positive integer')
    start = session.position
    end = min(start + frames, session.total_frames)
    revision = RevisionStore(connection).get(session.revision_id)
    samples = []
    heard = []
    real_intervals = []
    for block in renderer.iter_window(revision, start, end):
        if block.samples is None:
            samples.extend([0] * (block.end - block.start))
        else:
            samples.extend(block.samples)
            heard.append((block.start, block.end))
            real_intervals.append((block.start, block.end))
    updated = replace(session, position=end, paused=False, heard=merge_heard(session.heard, heard))
    return TransportResult(updated, start, end, tuple(samples), tuple(real_intervals))


def apply_transport(connection, renderer, audition_id, body):
    store = AuditionStore(connection)
    evidence_store = EvidenceStore(connection)
    with transaction(connection):
        session = store.get(audition_id)
        if session is None:
            raise UnknownAudition('unknown audition')

        evidence = evidence_store.get_or_empty(audition_id)
        operation = body.get('op')
        if operation == 'advance' and body.keys() == {'op', 'frames'}:
            result = _advance(connection, renderer, session, body['frames'])
            evidence = integrate_advance(
                evidence, result.start, result.end, result.real_intervals
            )
        elif operation == 'seek' and body.keys() == {'op', 'position'}:
            position = body['position']
            if type(position) is not int or not 0 <= position <= session.total_frames:
                raise InvalidTransport('position is outside the revision')
            result = TransportResult(replace(session, position=position), position, position, ())
            # Any seek, including to the current frame, breaks continuity.
            evidence = break_continuity(evidence)
        elif operation == 'pause' and body.keys() == {'op'}:
            position = session.position
            result = TransportResult(replace(session, paused=True), position, position, ())
            evidence = break_continuity(evidence)
        else:
            raise InvalidTransport('invalid transport operation or fields')
        store.save_transport(result.session)
        evidence_store.save(evidence)
    return result
