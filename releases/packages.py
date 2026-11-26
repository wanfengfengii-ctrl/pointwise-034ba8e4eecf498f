from dataclasses import dataclass
import json


@dataclass(frozen=True)
class FixedPackage:
    release_id: int
    revision_id: int
    confirmation_id: str | None
    cue_sheet: dict
    wav: bytes
    review_id: int | None = None


_PACKAGES_SCHEMA = '''
    CREATE TABLE packages (
        release_id INTEGER PRIMARY KEY,
        revision_id INTEGER NOT NULL REFERENCES revisions(revision_id),
        confirmation_id TEXT REFERENCES confirmations(confirmation_id),
        review_id INTEGER REFERENCES reviews(review_id),
        cue_sheet TEXT NOT NULL,
        wav BLOB NOT NULL CHECK (length(wav) > 0)
    )
'''


class PackageStore:
    def __init__(self, connection):
        self.connection = connection

    @staticmethod
    def initialize(connection):
        existing = connection.execute('''
            SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'packages'
        ''').fetchone()
        if existing is None:
            connection.execute(_PACKAGES_SCHEMA)
            return

        columns = {
            row['name']: row
            for row in connection.execute('PRAGMA table_info(packages)')
        }
        # Original databases made confirmation_id NOT NULL and had no
        # review_id.  Rebuild once so a carry package may store a NULL
        # confirmation together with its review verdict.
        needs_rebuild = (
            'review_id' not in columns
            or columns['confirmation_id']['notnull'] == 1
        )
        if not needs_rebuild:
            return

        connection.execute('ALTER TABLE packages RENAME TO packages_legacy')
        connection.execute(_PACKAGES_SCHEMA)
        connection.execute('''
            INSERT INTO packages(release_id, revision_id, confirmation_id, review_id, cue_sheet, wav)
            SELECT release_id, revision_id, confirmation_id, NULL, cue_sheet, wav
            FROM packages_legacy
        ''')
        connection.execute('DROP TABLE packages_legacy')

    def insert_package(self, revision_id, confirmation_id, cue_sheet, wav, review_id=None):
        result = self.connection.execute('''
            INSERT INTO packages(revision_id, confirmation_id, review_id, cue_sheet, wav)
            VALUES (?, ?, ?, ?, ?)
        ''', (revision_id, confirmation_id, review_id, json.dumps(cue_sheet), wav))
        return FixedPackage(
            result.lastrowid, revision_id, confirmation_id, cue_sheet, wav, review_id
        )

    def get(self, release_id):
        row = self.connection.execute('''
            SELECT release_id, revision_id, confirmation_id, review_id, cue_sheet, wav
            FROM packages WHERE release_id = ?
        ''', (release_id,)).fetchone()
        if row is None:
            return None
        return FixedPackage(
            row['release_id'], row['revision_id'], row['confirmation_id'],
            json.loads(row['cue_sheet']), row['wav'], row['review_id'],
        )
