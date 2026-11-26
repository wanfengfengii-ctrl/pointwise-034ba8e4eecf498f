import struct


PCM_MIN = -32768
PCM_MAX = 32767


def validate_pcm(samples):
    if not isinstance(samples, list) or not samples:
        raise ValueError('samples must be a non-empty array')
    for sample in samples:
        if type(sample) is not int or not PCM_MIN <= sample <= PCM_MAX:
            raise ValueError('samples must be signed 16-bit integers')
    return tuple(samples)


def pack_pcm16(samples):
    return struct.pack(f'<{len(samples)}h', *samples)


def unpack_pcm16(data):
    if len(data) % 2:
        raise ValueError('PCM byte count must be even')
    return struct.unpack(f'<{len(data) // 2}h', data)
