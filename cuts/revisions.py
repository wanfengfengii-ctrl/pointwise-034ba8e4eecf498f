from dataclasses import dataclass

from cuts.segments import Segment
from cuts.timeline import Placement


@dataclass(frozen=True)
class Revision:
    revision_id: int
    project_id: str
    parent_revision_id: int | None
    total_frames: int
    placements: tuple[Placement, ...]

    def describe_segments(self):
        return [
            {
                'segment_id': f'{self.revision_id}:{placement.ordinal}',
                'ordinal': placement.ordinal,
                'asset_id': placement.segment.asset_id,
                'source_window': [placement.segment.start, placement.segment.end],
                'gain': placement.segment.gain,
                'output_window': [placement.start, placement.end],
            }
            for placement in self.placements
        ]


class RevisionStore:
    def __init__(self, connection):
        self.connection = connection

    @staticmethod
    def initialize(connection):
        connection.execute('''
            CREATE TABLE IF NOT EXISTS revisions (
                revision_id INTEGER PRIMARY KEY,
                project_id TEXT NOT NULL,
                parent_revision_id INTEGER REFERENCES revisions(revision_id),
                total_frames INTEGER NOT NULL CHECK (total_frames > 0)
            )
        ''')
        connection.execute('''
            CREATE TABLE IF NOT EXISTS segments (
                revision_id INTEGER NOT NULL REFERENCES revisions(revision_id),
                ordinal INTEGER NOT NULL,
                asset_id INTEGER NOT NULL REFERENCES assets(asset_id),
                source_start INTEGER NOT NULL,
                source_end INTEGER NOT NULL,
                gain TEXT NOT NULL,
                output_start INTEGER NOT NULL,
                output_end INTEGER NOT NULL,
                PRIMARY KEY (revision_id, ordinal)
            )
        ''')

    def insert_frozen(self, project_id, parent_revision_id, placements, total_frames):
        result = self.connection.execute(
            'INSERT INTO revisions(project_id, parent_revision_id, total_frames) VALUES (?, ?, ?)',
            (project_id, parent_revision_id, total_frames),
        )
        revision_id = result.lastrowid
        self.connection.executemany('''
            INSERT INTO segments(revision_id, ordinal, asset_id, source_start, source_end,
                                 gain, output_start, output_end)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            (revision_id, p.ordinal, p.segment.asset_id, p.segment.start, p.segment.end,
             str(p.segment.gain), p.start, p.end)
            for p in placements
        ))
        return Revision(revision_id, project_id, parent_revision_id, total_frames, placements)

    def get(self, revision_id):
        header = self.connection.execute(
            'SELECT project_id, parent_revision_id, total_frames FROM revisions WHERE revision_id = ?',
            (revision_id,),
        ).fetchone()
        if header is None:
            return None
        rows = self.connection.execute('''
            SELECT ordinal, asset_id, source_start, source_end, gain, output_start, output_end
            FROM segments WHERE revision_id = ? ORDER BY ordinal
        ''', (revision_id,))
        placements = []
        for row in rows:
            segment = Segment(row['asset_id'], row['source_start'], row['source_end'], int(row['gain']))
            placements.append(Placement(row['ordinal'], row['output_start'], row['output_end'], segment))
        return Revision(
            revision_id, header['project_id'], header['parent_revision_id'], header['total_frames'],
            tuple(placements),
        )
