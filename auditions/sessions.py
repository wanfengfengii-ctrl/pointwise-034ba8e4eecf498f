from dataclasses import dataclass
import json

from cuts.revisions import RevisionStore
from workspace import transaction


class UnknownRevision(LookupError):
    pass


class UnknownAudition(LookupError):
    pass


@dataclass(frozen=True)
class AuditionSession:
    audition_id: int
    revision_id: int
    position: int
    paused: bool
    heard: tuple[tuple[int, int], ...]
    total_frames: int


class AuditionStore:
    def __init__(self, connection):
        self.connection = connection

    @staticmethod
    def initialize(connection):
        connection.execute('''
            CREATE TABLE IF NOT EXISTS auditions (
                audition_id INTEGER PRIMARY KEY,
                revision_id INTEGER NOT NULL REFERENCES revisions(revision_id),
                position INTEGER NOT NULL CHECK (position >= 0),
                paused INTEGER NOT NULL CHECK (paused IN (0, 1)),
                heard TEXT NOT NULL
            )
        ''')

    def open_session(self, revision_id):
        with transaction(self.connection):
            revision = RevisionStore(self.connection).get(revision_id)
            if revision is None:
                raise UnknownRevision('unknown revision')
            result = self.connection.execute('''
                INSERT INTO auditions(revision_id, position, paused, heard) VALUES (?, 0, 1, '[]')
            ''', (revision_id,))
            session = AuditionSession(result.lastrowid, revision_id, 0, True, (), revision.total_frames)
        return session

    def get(self, audition_id):
        row = self.connection.execute('''
            SELECT a.audition_id, a.revision_id, a.position, a.paused, a.heard, r.total_frames
            FROM auditions AS a JOIN revisions AS r ON r.revision_id = a.revision_id
            WHERE a.audition_id = ?
        ''', (audition_id,)).fetchone()
        if row is None:
            return None
        heard = tuple(tuple(window) for window in json.loads(row['heard']))
        return AuditionSession(
            row['audition_id'], row['revision_id'], row['position'], bool(row['paused']), heard,
            row['total_frames'],
        )

    def save_transport(self, session):
        self.connection.execute('''
            UPDATE auditions SET position = ?, paused = ?, heard = ? WHERE audition_id = ?
        ''', (session.position, int(session.paused), json.dumps(session.heard), session.audition_id))
