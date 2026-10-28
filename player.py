import socket
import time

import micropython
from machine import I2S, Pin

import config
from util import gain_for, parse_url, read_wav_header

CHUNK = 4096


class PlayerError(Exception):
    def __init__(self, code):
        Exception.__init__(self, code)
        self.code = code


@micropython.viper
def _apply_gain(buf, n: int, gain: int):
    p = ptr16(buf)
    for i in range(n >> 1):
        v = int(p[i])
        if v >= 32768:
            v -= 65536
        p[i] = ((v * gain) >> 8) & 0xFFFF


class Player:

    def __init__(self, volume):
        self.state = "idle"
        self.reason = None
        self.story_id = None
        self.volume = 0
        self._gain = 0
        self.set_volume(volume)

        self._buf = bytearray(CHUNK)
        self._mv = memoryview(self._buf)
        self._silence = bytes(CHUNK)
        self._sock = None
        self._i2s = None
        self._remaining = 0
        self._played = 0
        self._total = 0
        self._byte_rate = 1
        self._frame = 2

    @property
    def position(self):
        return self._played // self._byte_rate

    @property
    def duration(self):
        return self._total // self._byte_rate

    @property
    def active(self):
        return self.state in ("playing", "paused")

    def set_volume(self, volume):
        self.volume = volume
        self._gain = gain_for(volume)

    def start(self, url, story_id=None):
        self._close()
        self.state = "loading"
        self.reason = None
        self.story_id = story_id
        try:
            host, port, path = parse_url(url)
            sock = socket.socket()
            self._sock = sock
            sock.settimeout(10)
            sock.connect(socket.getaddrinfo(host, port)[0][-1])
            sock.send("GET {} HTTP/1.0\r\nHost: {}\r\n\r\n".format(path, host).encode())
            self._skip_http_header()

            rate, bits, channels, size = read_wav_header(self._read_exact)
            if bits != 16 or channels not in (1, 2):
                raise PlayerError("bad_wav")
            self._i2s = I2S(
                0,
                sck=Pin(config.PIN_BCLK),
                ws=Pin(config.PIN_BCLK + 1),
                sd=Pin(config.PIN_DIN),
                mode=I2S.TX,
                bits=16,
                format=I2S.MONO if channels == 1 else I2S.STEREO,
                rate=rate,
                ibuf=40000,
            )
            self._frame = 2 * channels
            self._byte_rate = rate * self._frame
            self._total = self._remaining = size
            self._played = 0
            self.state = "playing"
        except PlayerError as e:
            self._fail(e.code)
        except ValueError:
            self._fail("bad_wav")
        except OSError:
            self._fail("unreachable")

    def pause(self):
        if self.state == "playing":
            self.state = "paused"

    def resume(self):
        if self.state == "paused":
            self.state = "playing"

    def stop(self, reason="stopped"):
        if self.state == "idle":
            return
        self._close()
        self.state = "idle"
        self.reason = reason

    def step(self):
        """Proses satu potongan (~85 ms). False bila tidak ada yang diputar."""
        if self.state == "paused":
            self._i2s.write(self._silence)  # menjaga I2S tetap diberi data (tanpa dengung), sekaligus pengatur waktu
            return True
        if self.state != "playing":
            return False
        try:
            if self._remaining <= 0:
                time.sleep_ms(1000)
                self.stop("ended")
                return False
            n = self._read_chunk(min(CHUNK, self._remaining))
            if n == 0:
                raise PlayerError("stream_lost")
            _apply_gain(self._buf, n, self._gain)
            self._i2s.write(self._mv[:n])
            self._remaining -= n
            self._played += n
            return True
        except PlayerError as e:
            self._fail(e.code)
        except OSError:
            self._fail("stream_lost")
        return False

    def _skip_http_header(self):
        status = self._sock.readline()
        if not status:
            raise PlayerError("no_response")
        code = int(status.split()[1])
        if code != 200:
            raise PlayerError("http_{}".format(code))
        while True:
            line = self._sock.readline()
            if line in (b"\r\n", b""):
                return

    def _read_exact(self, n):
        data = b""
        while len(data) < n:
            part = self._sock.read(n - len(data))
            if not part:
                raise PlayerError("stream_lost")
            data += part
        return data

    def _read_chunk(self, want):
        got = 0
        while got < want:
            n = self._sock.readinto(self._mv[got:want])
            if not n:
                break
            got += n
            if got % self._frame == 0:
                break
        return got - got % self._frame

    def _fail(self, code):
        self._close()
        self.state = "error"
        self.reason = code

    def _close(self):
        if self._i2s is not None:
            self._i2s.deinit()
            self._i2s = None
        if self._sock is not None:
            self._sock.close()
            self._sock = None
