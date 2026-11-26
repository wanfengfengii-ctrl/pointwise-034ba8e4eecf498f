"""Persistence for carry confirmations and fixed review verdicts."""
from dataclasses import dataclass
import json


class NoActualOutput(ValueError):
    pass


@dataclass(frozen=True)
class ReviewConfirmation:
    audition_id: int
    revision_id: int
    runs: tuple[tuple[int, int], ...]


class ReviewConfirmationStore:
    def __init__(self, connection):
        self.connection = connection

    @staticmethod
    def initialize(connection):
        connection.execute('''
            CREATE TABLE IF NOT EXISTS review_confirmations (
                audition_id INTEGER PRIMARY KEY REFERENCES auditions(audition_id),
                revision_id INTEGER NOT NULL REFERENCES revisions(revision_id),
                runs TEXT NOT NULL
            )
        ''')

    def get(self, audition_id):
        row = self.connection.execute('''
            SELECT audition_id, revision_id, runs
            FROM review_confirmations WHERE audition_id = ?
        ''', (audition_id,)).fetchone()
        if row is None:
            return None
        runs = tuple((left, right) for left, right in json.loads(row['runs']))
        return ReviewConfirmation(row['audition_id'], row['revision_id'], runs)

    def freeze(self, audition_id, revision_id, runs):
        self.connection.execute('''
            INSERT INTO review_confirmations(audition_id, revision_id, runs)
            VALUES (?, ?, ?)
        ''', (audition_id, revision_id, json.dumps(tuple(runs))))
        return ReviewConfirmation(audition_id, revision_id, tuple(runs))


@dataclass(frozen=True)
class ReviewVerdict:
    review_id: int
    target_revision_id: int
    audition_ids: tuple[int, ...]
    unheard: tuple[dict, ...]
    missing_seams: tuple[int, ...]
    ready: bool

    def as_dict(self):
        return {
            'review_id': self.review_id,
            'target_revision_id': self.target_revision_id,
            'audition_ids': list(self.audition_ids),
            'unheard': [dict(item) for item in self.unheard],
            'missing_seams': list(self.missing_seams),
            'ready': self.ready,
        }


class ReviewStore:
    def __init__(self, connection):
        self.connection = connection

    @staticmethod
    def initialize(connection):
        connection.execute('''
            CREATE TABLE IF NOT EXISTS reviews (
                review_id INTEGER PRIMARY KEY,
                target_revision_id INTEGER NOT NULL REFERENCES revisions(revision_id),
                audition_ids TEXT NOT NULL,
                unheard TEXT NOT NULL,
                missing_seams TEXT NOT NULL,
                ready INTEGER NOT NULL CHECK (ready IN (0, 1))
            )
        ''')

    def insert(self, target_revision_id, audition_ids, unheard, missing_seams, ready):
        # Caller owns the surrounding workspace transaction.
        result = self.connection.execute('''
            INSERT INTO reviews(target_revision_id, audition_ids, unheard, missing_seams, ready)
            VALUES (?, ?, ?, ?, ?)
        ''', (
            target_revision_id,
            json.dumps(list(audition_ids)),
            json.dumps(list(unheard)),
            json.dumps(list(missing_seams)),
            1 if ready else 0,
        ))
        review_id = result.lastrowid
        return ReviewVerdict(
            review_id, target_revision_id, tuple(audition_ids),
            tuple(unheard), tuple(missing_seams), ready,
        )

    def get(self, review_id):
        row = self.connection.execute('''
            SELECT review_id, target_revision_id, audition_ids, unheard, missing_seams, ready
            FROM reviews WHERE review_id = ?
        ''', (review_id,)).fetchone()
        if row is None:
            return None
        return ReviewVerdict(
            row['review_id'], row['target_revision_id'],
            tuple(json.loads(row['audition_ids'])),
            tuple(json.loads(row['unheard'])),
            tuple(json.loads(row['missing_seams'])),
            bool(row['ready']),
        )

    def has_for_revision(self, target_revision_id):
        row = self.connection.execute('''
            SELECT 1 FROM reviews WHERE target_revision_id = ? LIMIT 1
        ''', (target_revision_id,)).fetchone()
        return row is not None
