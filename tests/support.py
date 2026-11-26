import base64
from contextlib import closing
import http.client
import io
import json
from pathlib import Path
import struct
from tempfile import TemporaryDirectory
from threading import Thread
import unittest
import wave

from releases.service import build_server
from workspace import connect


class Workspace:
    def __init__(self, sample_rate=8000, block_frames=2):
        self.sample_rate = sample_rate
        self.block_frames = block_frames
        self.server = None

    def __enter__(self):
        self.directory = TemporaryDirectory(prefix='restoration-')
        self.database = Path(self.directory.name) / 'workspace.sqlite'
        try:
            self.start(self.sample_rate)
        except BaseException:
            self.directory.cleanup()
            raise
        return self

    def start(self, sample_rate=None):
        self.server = build_server(self.database, sample_rate=sample_rate, block_frames=self.block_frames)
        self.thread = Thread(target=self.server.serve_forever, kwargs={'poll_interval': 0.02})
        self.thread.start()

    def stop(self):
        if self.server is not None:
            self.server.shutdown()
            self.thread.join()
            self.server.server_close()
            self.server = None

    def reopen(self):
        self.stop()
        self.start()

    def __exit__(self, exc_type, exc, tb):
        try:
            self.stop()
        finally:
            self.directory.cleanup()

    def request(self, method, path, body=None):
        client = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        with closing(client):
            headers = {'Content-Type': 'application/json'}
            data = None if body is None else json.dumps(body).encode('utf-8')
            client.request(method, path, body=data, headers=headers)
            response = client.getresponse()
            return response.status, json.loads(response.read())

    def connection(self):
        return closing(connect(self.database))

    def count(self, table):
        if table not in {'assets', 'revisions', 'segments', 'auditions', 'confirmations', 'packages'}:
            raise ValueError('unknown workspace table')
        with self.connection() as connection:
            return connection.execute(f'SELECT count(*) FROM {table}').fetchone()[0]


def segment(asset_id, start, end, gain=1):
    return {'asset_id': asset_id, 'start': start, 'end': end, 'gain': gain}


def decode_package(package):
    pcm = base64.b64decode(package['wav_base64'], validate=True)
    with wave.open(io.BytesIO(pcm), 'rb') as reader:
        frame_count = reader.getnframes()
        samples = list(struct.unpack(f'<{frame_count}h', reader.readframes(frame_count)))
        return {
            'sample_rate': reader.getframerate(), 'channels': reader.getnchannels(),
            'width': reader.getsampwidth(), 'frames': frame_count, 'samples': samples,
        }


class HTTPCase(unittest.TestCase):
    def setUp(self):
        self.work = self.enterContext(Workspace())

    def call(self, method, path, body=None, status=200):
        actual_status, response = self.work.request(method, path, body)
        self.assertEqual(actual_status, status, (method, path, response))
        if status >= 400:
            self.assertTrue(response.get('error'), response)
        return response

    def asset(self, samples, source='片库声带'):
        return self.call('POST', '/assets', {
            'source': source, 'sample_rate': self.work.sample_rate, 'samples': samples,
        }, 201)['asset_id']

    def cut(self, segments, parent=None, project='film'):
        return self.call('POST', '/cuts', {
            'project_id': project, 'parent_revision_id': parent, 'segments': segments,
        }, 201)

    def preview(self, revision_id, query='', status=200):
        return self.call('GET', f'/cuts/{revision_id}/preview{query}', status=status)

    def audition(self, revision_id):
        response = self.call('POST', '/auditions', {'revision_id': revision_id}, 201)
        self.assertEqual(response['revision_id'], revision_id)
        self.assertEqual(response['position'], 0)
        self.assertEqual(response['heard'], [])
        return response['audition_id']

    def transport(self, audition_id, op, status=200, **fields):
        return self.call('POST', f'/auditions/{audition_id}/transport', {'op': op, **fields}, status)

    def confirm(self, audition_id, status=200):
        return self.call('POST', f'/auditions/{audition_id}/confirm', {}, status)

    def confirm_all(self, revision_id, frames):
        audition_id = self.audition(revision_id)
        result = self.transport(audition_id, 'advance', frames=frames)
        self.assertEqual(result['pending'], [])
        return self.confirm(audition_id)['confirmation_id']

    def release(self, revision_id, confirmation_id, status=201):
        return self.call('POST', '/releases', {
            'revision_id': revision_id, 'confirmation_id': confirmation_id,
        }, status)

    def package(self, release_id, status=200):
        return self.call('GET', f'/releases/{release_id}', status=status)
