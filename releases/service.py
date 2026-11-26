import argparse
from contextlib import closing
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import sqlite3
from urllib.parse import urlsplit

from auditions.confirmations import ConfirmationStore
from auditions.http import post_audition, post_confirmation, post_transport
from auditions.sessions import AuditionStore
from cuts.http import post_cut
from cuts.revisions import RevisionStore
from http_support import Problem, path_id, read_object
from releases.http import get_release, post_release
from releases.packages import PackageStore
from render.blocks import BlockRenderer, BlockUnavailable
from render.cache import BlockCache
from render.http import get_preview
from sources.catalog import AssetCatalog
from sources.http import post_asset
from workspace import connect, transaction


DEFAULT_SAMPLE_RATE = 8000
MAX_SAMPLE_RATE = ((1 << 32) - 1) // 2


def initialize_workspace(database, sample_rate=None):
    if sample_rate is not None and (type(sample_rate) is not int or not 1 <= sample_rate <= MAX_SAMPLE_RATE):
        raise ValueError('invalid workspace sample rate')
    with closing(connect(database)) as connection, transaction(connection):
        connection.execute('''
            CREATE TABLE IF NOT EXISTS workspace_settings (
                singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                sample_rate INTEGER NOT NULL CHECK (sample_rate > 0)
            )
        ''')
        row = connection.execute('SELECT sample_rate FROM workspace_settings WHERE singleton = 1').fetchone()
        if row is None:
            rate = DEFAULT_SAMPLE_RATE if sample_rate is None else sample_rate
            connection.execute('INSERT INTO workspace_settings VALUES (1, ?)', (rate,))
        else:
            rate = row['sample_rate']
            if sample_rate is not None and sample_rate != rate:
                raise ValueError('sample rate does not match the existing workspace')
        AssetCatalog.initialize(connection)
        RevisionStore.initialize(connection)
        AuditionStore.initialize(connection)
        ConfirmationStore.initialize(connection)
        PackageStore.initialize(connection)
    return rate


class _RequestHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def _reply(self, status, payload):
        data = json.dumps(payload, separators=(',', ':'), ensure_ascii=True).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _dispatch(self, method, path, connection):
        parts = path.path.split('/')[1:]
        if method == 'GET':
            if len(parts) == 3 and parts[0] == 'cuts' and parts[2] == 'preview':
                return 200, get_preview(connection, self._renderer(connection), path_id(parts[1]), path.query)
            if len(parts) == 2 and parts[0] == 'releases':
                return 200, get_release(connection, path_id(parts[1]))
            raise Problem(404, 'unknown endpoint')

        body = read_object(self)
        if parts == ['assets']:
            return 201, post_asset(connection, self.server.sample_rate, body)
        if parts == ['cuts']:
            return 201, post_cut(connection, body)
        if parts == ['auditions']:
            return 201, post_audition(connection, body)
        if parts == ['releases']:
            return 201, post_release(connection, self._renderer(connection), self.server.sample_rate, body)
        if len(parts) == 3 and parts[0] == 'auditions':
            audition_id = path_id(parts[1])
            if parts[2] == 'transport':
                return 200, post_transport(connection, self._renderer(connection), audition_id, body)
            if parts[2] == 'confirm':
                return 200, post_confirmation(connection, audition_id, body)
        raise Problem(404, 'unknown endpoint')

    def _renderer(self, connection):
        return BlockRenderer(connection, self.server.cache, self.server.block_frames)

    def _handle(self, method):
        try:
            try:
                path = urlsplit(self.path)
            except ValueError as error:
                raise Problem(400, 'invalid request target') from error
            with closing(connect(self.server.database)) as connection:
                status, payload = self._dispatch(method, path, connection)
        except Problem as error:
            status, payload = error.status, {'error': str(error)}
        except BlockUnavailable as error:
            status, payload = 503, {'error': str(error)}
        except sqlite3.Error:
            status, payload = 500, {'error': 'workspace storage operation failed'}
        try:
            self._reply(status, payload)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        self._handle('GET')

    def do_POST(self):
        self._handle('POST')


class _WorkspaceServer(HTTPServer):
    def __init__(self, database, address, sample_rate, block_frames):
        self.database = database
        self.sample_rate = sample_rate
        self.block_frames = block_frames
        self.cache = BlockCache()
        super().__init__(address, _RequestHandler)


def build_server(database, port=0, *, sample_rate=None, block_frames=1024):
    if type(block_frames) is not int or block_frames <= 0:
        raise ValueError('block size must be positive')
    rate = initialize_workspace(database, sample_rate)
    return _WorkspaceServer(database, ('127.0.0.1', port), rate, block_frames)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Film archive sound restoration service')
    parser.add_argument('--db', required=True, help='SQLite workspace path')
    parser.add_argument('--port', type=int, default=8080)
    parser.add_argument('--sample-rate', type=int)
    parser.add_argument('--block-frames', type=int, default=1024)
    args = parser.parse_args(argv)
    if not 0 <= args.port <= 65535:
        parser.error('port must be between 0 and 65535')
    try:
        server = build_server(args.db, args.port, sample_rate=args.sample_rate, block_frames=args.block_frames)
    except (ValueError, OSError, sqlite3.Error) as error:
        parser.error(str(error))
    with server:
        print(f'Listening on http://127.0.0.1:{server.server_port}', flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            return 0
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
