import json
from pathlib import Path

from tests.support import Workspace, decode_package
from tests.support import segment as make_segment


def check(actual, expected):
    if actual != expected:
        raise AssertionError(f'expected {expected!r}, received {actual!r}')


def call(work, method, path, body=None, status=200):
    result_status, response = work.request(method, path, body)
    if result_status != status:
        raise AssertionError(f'{method} {path}: expected {status}, received {result_status}: {response}')
    return response


def package_demo():
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


def _abcd_fixture(work):
    clips = {}
    for name, samples in (("A", [31, 7]), ("B", [8]), ("C", [9]), ("D", [0, 11])):
        asset = call(work, 'POST', '/assets', {
            'source': f'馆藏声带 {name}', 'sample_rate': work.sample_rate, 'samples': samples,
        }, 201)
        clips[name] = make_segment(asset['asset_id'], 0, len(samples))
    parent = call(work, 'POST', '/cuts', {
        'project_id': 'screening-restoration',
        'segments': [clips[name] for name in 'ABCD'],
    }, 201)
    target = call(work, 'POST', '/cuts', {
        'project_id': 'screening-restoration', 'parent_revision_id': parent['revision_id'],
        'segments': [clips['A'], clips['D']],
    }, 201)
    return parent, target


def _listen_parent_half(work, parent_id, offset):
    audition = call(work, 'POST', '/auditions', {'revision_id': parent_id}, 201)['audition_id']
    call(work, 'POST', f'/auditions/{audition}/transport', {'op': 'seek', 'position': offset})
    call(work, 'POST', f'/auditions/{audition}/transport', {'op': 'advance', 'frames': 3})
    confirmed = call(work, 'POST', f'/auditions/{audition}/review-confirm', {})
    check(confirmed, {'audition_id': audition, 'revision_id': parent_id})
    return audition


def carry_demo():
    """Real-HTTP walkthrough: unheard seam blocks issue, relisten, reopen."""
    with Workspace(block_frames=2) as work:
        parent, target = _abcd_fixture(work)
        revision = target['revision_id']
        first = _listen_parent_half(work, parent['revision_id'], 0)
        second = _listen_parent_half(work, parent['revision_id'], 3)

        unheard = call(work, 'POST', '/reviews', {
            'target_revision_id': revision, 'audition_ids': [first, second],
        }, 201)
        check(unheard['ready'], False)
        check(unheard['missing_seams'], [2])
        print('POINTWISE_REVIEW_UNHEARD ' + json.dumps(unheard, ensure_ascii=False))

        # The not-ready verdict must not issue a release.
        blocked_status, blocked = work.request('POST', '/releases', {
            'revision_id': revision, 'review_id': unheard['review_id'],
        })
        check(blocked_status, 409)
        print('POINTWISE_REVIEW_BLOCKED ' + json.dumps(
            {'status': blocked_status, 'error': blocked.get('error')}, ensure_ascii=False))

        # Supplementary continuous listening on the new cut crosses A1 -> D0.
        bridge = call(work, 'POST', '/auditions', {'revision_id': revision}, 201)['audition_id']
        call(work, 'POST', f'/auditions/{bridge}/transport', {'op': 'seek', 'position': 1})
        crossed = call(work, 'POST', f'/auditions/{bridge}/transport', {'op': 'advance', 'frames': 3})
        check(crossed['samples'], [7, 0, 11])
        call(work, 'POST', f'/auditions/{bridge}/review-confirm', {})

        ready = call(work, 'POST', '/reviews', {
            'target_revision_id': revision, 'audition_ids': [first, second, bridge],
        }, 201)
        check(ready['ready'], True)
        check(ready['missing_seams'], [])
        print('POINTWISE_REVIEW_READY ' + json.dumps(ready, ensure_ascii=False))

        issued = call(work, 'POST', '/releases', {
            'revision_id': revision, 'review_id': ready['review_id'],
        }, 201)
        release_path = f"/releases/{issued['release_id']}"
        before = call(work, 'GET', release_path)
        check(before['confirmation_id'], None)
        check(before['review_id'], ready['review_id'])
        check(decode_package(before)['samples'], [31, 7, 0, 11])

        # Reclaim rendered blocks, restart the service and claim by old number.
        work.server.cache.reclaim()
        work.reopen()
        after = call(work, 'GET', release_path)
        check(after, before)
        check(call(work, 'GET', f"/reviews/{ready['review_id']}"), ready)
        samples = decode_package(after)['samples']
        check(samples, [31, 7, 0, 11])
        print('POINTWISE_REVIEW_DEMO ' + json.dumps({
            'unheard_verdict': unheard,
            'missing_seam_release_status': blocked_status,
            'ready_review_id': ready['review_id'],
            'release_id': issued['release_id'],
            'review_id': after['review_id'],
            'confirmation_id': after['confirmation_id'],
            'reopen_claim_matches': after == before,
            'wav_samples': samples,
        }, ensure_ascii=False, separators=(',', ':')))
    return 0


def main():
    package_demo()
    carry_demo()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
