from dataclasses import dataclass

from sources.pcm import pack_pcm16, unpack_pcm16


@dataclass(frozen=True)
class Asset:
    asset_id: int
    source: str
    sample_rate: int
    samples: tuple[int, ...]

    @property
    def frames(self):
        return len(self.samples)


class AssetCatalog:
    def __init__(self, connection):
        self.connection = connection

    @staticmethod
    def initialize(connection):
        connection.execute('''
            CREATE TABLE IF NOT EXISTS assets (
                asset_id INTEGER PRIMARY KEY,
                source TEXT NOT NULL,
                sample_rate INTEGER NOT NULL CHECK (sample_rate > 0),
                pcm BLOB NOT NULL CHECK (length(pcm) > 0 AND length(pcm) % 2 = 0)
            )
        ''')

    def add(self, source, sample_rate, samples):
        row = self.connection.execute(
            'INSERT INTO assets(source, sample_rate, pcm) VALUES (?, ?, ?)',
            (source, sample_rate, pack_pcm16(samples)),
        )
        return Asset(row.lastrowid, source, sample_rate, samples)

    def get(self, asset_id):
        row = self.connection.execute(
            'SELECT asset_id, source, sample_rate, pcm FROM assets WHERE asset_id = ?',
            (asset_id,),
        ).fetchone()
        if row is None:
            return None
        return Asset(row['asset_id'], row['source'], row['sample_rate'], unpack_pcm16(row['pcm']))
