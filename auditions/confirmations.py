from dataclasses import dataclass

from auditions.progress import covers_whole_revision
from auditions.sessions import AuditionStore, UnknownAudition
from workspace import transaction


class InsufficientCoverage(ValueError):
    pass


@dataclass(frozen=True)
class Confirmation:
    confirmation_id: str
    audition_id: int
    revision_id: int


class ConfirmationStore:
    def __init__(self, connection):
        self.connection = connection

    @staticmethod
    def initialize(connection):
        connection.execute('''
            CREATE TABLE IF NOT EXISTS confirmations (
                confirmation_id TEXT PRIMARY KEY NOT NULL,
                audition_id INTEGER NOT NULL UNIQUE REFERENCES auditions(audition_id),
                revision_id INTEGER NOT NULL REFERENCES revisions(revision_id)
            )
        ''')

    def confirm(self, audition_id):
        with transaction(self.connection):
            audition = AuditionStore(self.connection).get(audition_id)
            if audition is None:
                raise UnknownAudition('unknown audition')
            confirmation_id = f'confirm-{audition_id}'
            confirmation = self.get(confirmation_id)
            if confirmation is None:
                if not covers_whole_revision(audition.heard, audition.total_frames):
                    raise InsufficientCoverage('audition has unheard frames')
                self.connection.execute('''
                    INSERT INTO confirmations(confirmation_id, audition_id, revision_id) VALUES (?, ?, ?)
                ''', (confirmation_id, audition_id, audition.revision_id))
                confirmation = Confirmation(confirmation_id, audition_id, audition.revision_id)
        return confirmation

    def get(self, confirmation_id):
        row = self.connection.execute('''
            SELECT confirmation_id, audition_id, revision_id FROM confirmations WHERE confirmation_id = ?
        ''', (confirmation_id,)).fetchone()
        if row is None:
            return None
        return Confirmation(row['confirmation_id'], row['audition_id'], row['revision_id'])
