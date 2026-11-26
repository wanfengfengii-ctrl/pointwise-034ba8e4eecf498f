import json
from pathlib import Path

from tests.support import Workspace, decode_package


def check(actual, expected):
    if actual != expected:
        raise AssertionError(f'expected {expected!r}, received {actual!r}')


def call(work, method, path, body=None, status=200):
    result_status, response = work.request(method, path, body)
    if result_status != status:
        raise AssertionError(f'{method} {path}: expected {status}, received {result_status}: {response}')
    return response


def main():
    sample = json.loads((Path(__file__).parent / 'examples' / 'restoration.json').read_text(encoding='utf-8'))
    expected_samples = [32767, -32768, 0, 6]
    expected_windows = [[0, 3], [3, 4]]
    with Workspace(sample_rate=sample['asset']['sample_rate']) as work:
        asset = call(work, 'POST', '/assets', sample['asset'], 201)
        segments = [item | {'asset_id': asset['asset_id']} for item in sample['segments']]
        cut = call(work, 'POST', '/cuts', {'project_id': sample['project_id'], 'segments': segments}, 201)
        revision = cut['revision_id']
        preview = call(work, 'GET', f'/cuts/{revision}/preview')
        check(preview['samples'], expected_samples)
        audition = call(work, 'POST', '/auditions', {'revision_id': revision}, 201)['audition_id']
        transport = f'/auditions/{audition}/transport'
        confirmation = f'/auditions/{audition}/confirm'
        first = call(work, 'POST', transport, {'op': 'advance', 'frames': 1})
        check(first['samples'], [32767])
        call(work, 'POST', transport, {'op': 'seek', 'position': 3})
        tail = call(work, 'POST', transport, {'op': 'advance', 'frames': 1})
        check(tail['samples'], [6])
        check(tail['pending'], [[1, 3]])
        call(work, 'POST', confirmation, {}, 409)
        call(work, 'POST', transport, {'op': 'seek', 'position': 1})
        replay = call(work, 'POST', transport, {'op': 'advance', 'frames': 2})
        check(replay['samples'], [-32768, 0])
        check(replay['pending'], [])
        confirmed = call(work, 'POST', confirmation, {})
        issue = call(work, 'POST', '/releases', {
            'revision_id': revision, 'confirmation_id': confirmed['confirmation_id'],
        }, 201)
        path = f"/releases/{issue['release_id']}"
        original = call(work, 'GET', path)
        if work.server.cache.reclaim() < 1:
            raise AssertionError('expected rendered temporary blocks before reclamation')
        work.reopen()
        package = call(work, 'GET', path)
        check(package, original)
        clips = package['cue_sheet']['segments']
        check([clip['source_window'] for clip in clips], [[1, 4], [4, 5]])
        windows = [clip['output_window'] for clip in clips]
        downstream_expected = {
            'revision_id': revision, 'output_windows': expected_windows,
            'wave': {'sample_rate': 8000, 'channels': 1, 'width': 2, 'frames': 4, 'samples': expected_samples},
        }
        downstream_actual = {
            'revision_id': package['revision_id'], 'output_windows': windows, 'wave': decode_package(package),
        }
        check(downstream_actual, downstream_expected)
        print('POINTWISE_SCENARIO ' + json.dumps({
            'case_id': 'v6.package_content',
            'input': sample,
            'expected': expected_samples,
            'actual': preview['samples'],
            'downstream_expected': downstream_expected,
            'downstream_actual': downstream_actual,
            'code_paths': ['cuts/timeline.py', 'render/blocks.py', 'render/gain.py', 'auditions/transport.py',
                           'releases/issue.py', 'releases/cues.py', 'render/wave.py', 'releases/packages.py'],
            'oracle': '手算源窗 [1,4) 乘 2 后饱和，再接源窗 [4,5)。用标准 WAV 读取器及小端整数解码重领取件。',
        }, ensure_ascii=False, separators=(',', ':')))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
