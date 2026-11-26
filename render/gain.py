from sources.pcm import PCM_MAX, PCM_MIN


def apply_gain(sample, gain):
    product = sample * gain
    return min(PCM_MAX, max(PCM_MIN, product))
