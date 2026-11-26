import io
import wave

from sources.pcm import pack_pcm16


def encode_wave(samples, sample_rate):
    output = io.BytesIO()
    with wave.open(output, 'wb') as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(sample_rate)
        writer.writeframes(pack_pcm16(samples))
    return output.getvalue()
