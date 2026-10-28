import io
import json
import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from util import gain_for, parse_command, parse_url, read_wav_header  # noqa: E402


def wav(rate=24000, bits=16, channels=1, pcm=b"\x01\x00" * 8, extra_chunk=False, fmt=1):
    fmt_chunk = struct.pack("<HHIIHH", fmt, channels, rate, rate * channels * bits // 8, channels * bits // 8, bits)
    body = b"WAVE" + b"fmt " + struct.pack("<I", len(fmt_chunk)) + fmt_chunk
    if extra_chunk:
        body += b"LIST" + struct.pack("<I", 5) + b"abcde" + b"\x00"  # panjang ganjil -> padding 1 byte
    body += b"data" + struct.pack("<I", len(pcm)) + pcm
    return b"RIFF" + struct.pack("<I", len(body)) + body


def exact(data):
    stream = io.BytesIO(data)

    def read(n):
        chunk = stream.read(n)
        if len(chunk) < n:
            raise RuntimeError("short read")
        return chunk

    return read


class ParseUrl(unittest.TestCase):
    def test_host_port_path(self):
        self.assertEqual(parse_url("http://192.168.1.5:8000/audio/a.wav"), ("192.168.1.5", 8000, "/audio/a.wav"))

    def test_defaults(self):
        self.assertEqual(parse_url("http://laptop.local"), ("laptop.local", 80, "/"))

    def test_rejects(self):
        for bad in ["https://a/b", "ftp://a", "a/b", "http://:80/x", "http://a:0/x", "http://a:99999/x"]:
            with self.assertRaises(ValueError, msg=bad):
                parse_url(bad)


class Gain(unittest.TestCase):
    def test_range(self):
        self.assertEqual(gain_for(0), 0)
        self.assertEqual(gain_for(100), 256)
        self.assertEqual(gain_for(500), 256)
        self.assertEqual(gain_for(-5), 0)

    def test_monotonic(self):
        values = [gain_for(v) for v in range(101)]
        self.assertEqual(values, sorted(values))


class Command(unittest.TestCase):
    def cmd(self, payload, **kw):
        return parse_command(json.dumps(payload).encode(), **kw)

    def test_play(self):
        got = self.cmd({"action": "play", "url": "http://10.0.0.2:8000/a.wav", "story_id": 7, "volume": 50})
        self.assertEqual(got, {"action": "play", "url": "http://10.0.0.2:8000/a.wav", "story_id": 7, "volume": 50})

    def test_volume_is_capped_by_the_device(self):
        got = self.cmd({"action": "volume", "value": 100}, max_volume=80)
        self.assertEqual(got["volume"], 80)
        got = self.cmd({"action": "play", "url": "http://a/b.wav", "volume": 999}, max_volume=80)
        self.assertEqual(got["volume"], 80)

    def test_simple_actions(self):
        for action in ("pause", "resume", "stop"):
            self.assertEqual(self.cmd({"action": action}), {"action": action})

    def test_audio_host_allow_list(self):
        url = {"action": "play", "url": "http://10.0.0.2:8000/a.wav"}
        self.assertIsNotNone(self.cmd(url, allowed_host="10.0.0.2"))
        self.assertIsNone(self.cmd(url, allowed_host="10.0.0.9"))

    def test_garbage_is_ignored(self):
        for raw in [b"", b"nope", b"[]", b'{"action":"reboot"}', b'{"action":"play"}',
                    b'{"action":"play","url":"https://a/b"}', b'{"action":"volume"}',
                    b'{"action":"volume","value":true}', b'{"action":"volume","value":"loud"}']:
            self.assertIsNone(parse_command(raw), raw)


class WavHeader(unittest.TestCase):
    def test_reads_format_and_size(self):
        self.assertEqual(read_wav_header(exact(wav())), (24000, 16, 1, 16))

    def test_skips_other_chunks_even_with_odd_length(self):
        self.assertEqual(read_wav_header(exact(wav(extra_chunk=True, channels=2, rate=16000))), (16000, 16, 2, 16))

    def test_stream_is_left_at_the_first_sample(self):
        stream = io.BytesIO(wav(pcm=b"\x05\x00\x06\x00"))
        read_wav_header(stream.read)
        self.assertEqual(stream.read(4), b"\x05\x00\x06\x00")

    def test_rejects_non_wav_and_compressed(self):
        with self.assertRaises(ValueError):
            read_wav_header(exact(b"ID3\x04" + b"\x00" * 40))
        with self.assertRaises(ValueError):
            read_wav_header(exact(wav(fmt=3)))


if __name__ == "__main__":
    unittest.main()
