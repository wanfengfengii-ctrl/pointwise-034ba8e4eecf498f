"""Durable evidence of what an audition actually output.

The merged ``heard`` windows only prove coverage.  Carry reviews additionally
need maximal *continuous* passages so that an ordered pair of neighbouring
frames can be proved to have been heard back to back.  Every real
``advance`` output is therefore recorded as one run ``[start, end)`` of
revision output coordinates.

A run is never merged with a neighbouring run after the fact: seek (even to
the current frame), pause and a missing-block fill all break continuity and
therefore start a fresh run on the next real output.  Runs may overlap or
repeat the same interval when a listener replays a passage.
"""
from dataclasses import dataclass, replace
import json


@dataclass(frozen=True)
class EvidenceState:
    audition_id: int
    runs: tuple[tuple[int, int], ...]
    # Output coordinate at which the last run may be extended by the next
    # advance when continuity is still unbroken; None after an interruption.
    live_edge: int | None


def empty_evidence(audition_id):
    return EvidenceState(audition_id, (), None)


def break_continuity(state):
    """Seek or pause: keep every recorded run but sever the extendable edge."""
    if state.live_edge is None:
        return state
    return replace(state, live_edge=None)


def integrate_advance(state, start, end, real_intervals):
    """Fold one advance's real intervals into the evidence state.

    ``real_intervals`` are the rendered, non-fill half-open output windows of
    the advance, in output order.  A gap between the live edge and the next
    real interval (caused by fill frames) automatically starts a new run.
    """
    runs = [[left, right] for left, right in state.runs]
    edge = state.live_edge if state.live_edge == start else None

    for left, right in real_intervals:
        if left >= right:
            continue
        if edge is not None and left == edge and runs and runs[-1][1] == edge:
            runs[-1][1] = right
        else:
            runs.append([left, right])
        edge = right

    live_edge = edge if edge is not None and edge == end else None
    return EvidenceState(
        state.audition_id,
        tuple((left, right) for left, right in runs),
        live_edge,
    )


class EvidenceStore:
    def __init__(self, connection):
        self.connection = connection

    @staticmethod
    def initialize(connection):
        connection.execute('''
            CREATE TABLE IF NOT EXISTS audition_evidence (
                audition_id INTEGER PRIMARY KEY REFERENCES auditions(audition_id),
                runs TEXT NOT NULL,
                live_edge INTEGER
            )
        ''')

    def get(self, audition_id):
        row = self.connection.execute('''
            SELECT audition_id, runs, live_edge FROM audition_evidence WHERE audition_id = ?
        ''', (audition_id,)).fetchone()
        if row is None:
            return None
        runs = tuple((left, right) for left, right in json.loads(row['runs']))
        return EvidenceState(row['audition_id'], runs, row['live_edge'])

    def get_or_empty(self, audition_id):
        evidence = self.get(audition_id)
        return evidence if evidence is not None else empty_evidence(audition_id)

    def save(self, state):
        runs = json.dumps(state.runs)
        if self.get(state.audition_id) is None:
            self.connection.execute('''
                INSERT INTO audition_evidence(audition_id, runs, live_edge) VALUES (?, ?, ?)
            ''', (state.audition_id, runs, state.live_edge))
        else:
            self.connection.execute('''
                UPDATE audition_evidence SET runs = ?, live_edge = ? WHERE audition_id = ?
            ''', (runs, state.live_edge, state.audition_id))
