from dataclasses import dataclass
import json


@dataclass(frozen=True)
class FixedPackage:
    release_id: int
    revision_id: int
    confirmation_id: str
    cue_sheet: dict
    wav: bytes


class PackageStore:
    def __init__(self, connection):
        self.connection = connection

    @staticmethod
    def initialize(connection):
        connection.execute('''
            CREATE TABLE IF NOT EXISTS packages (
                release_id INTEGER PRIMARY KEY,
                revision_id INTEGER NOT NULL REFERENCES revisions(revision_id),
                confirmation_id TEXT NOT NULL REFERENCES confirmations(confirmation_id),
                cue_sheet TEXT NOT NULL,
                wav BLOB NOT NULL CHECK (length(wav) > 0)
            )
        ''')

    def insert_package(self, revision_id, confirmation_id, cue_sheet, wav):
        result = self.connection.execute('''
            INSERT INTO packages(revision_id, confirmation_id, cue_sheet, wav) VALUES (?, ?, ?, ?)
        ''', (revision_id, confirmation_id, json.dumps(cue_sheet), wav))
        return FixedPackage(result.lastrowid, revision_id, confirmation_id, cue_sheet, wav)

    def get(self, release_id):
        row = self.connection.execute('''
            SELECT release_id, revision_id, confirmation_id, cue_sheet, wav
            FROM packages WHERE release_id = ?
        ''', (release_id,)).fetchone()
        if row is None:
            return None
        return FixedPackage(
            row['release_id'], row['revision_id'], row['confirmation_id'],
            json.loads(row['cue_sheet']), row['wav'],
        )
