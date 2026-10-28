import json
import struct

ACTIONS = ("play", "pause", "resume", "stop", "volume")


def parse_url(url):
    """'http://host:port/path' -> (host, port, path). Hanya http:// yang didukung."""
    if not url.startswith("http://"):
        raise ValueError("only http:// is supported")
    rest = url[7:]
    slash = rest.find("/")
    hostport, path = (rest, "/") if slash < 0 else (rest[:slash], rest[slash:])
    if ":" in hostport:
        host, port = hostport.rsplit(":", 1)
        port = int(port)
    else:
        host, port = hostport, 80
    if not host or not 0 < port < 65536:
        raise ValueError("bad host or port")
    return host, port, path


def gain_for(volume):
    v = max(0, min(100, int(volume)))
    return (v * v * 256) // 10000


def _volume(value, max_volume):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return max(0, min(max_volume, int(value)))


def parse_command(raw, max_volume=100, allowed_host=""):
    try:
        cmd = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(cmd, dict) or cmd.get("action") not in ACTIONS:
        return None

    action = cmd["action"]
    out = {"action": action}

    if action == "play":
        url = cmd.get("url")
        if not isinstance(url, str):
            return None
        try:
            host = parse_url(url)[0]
        except ValueError:
            return None
        if allowed_host and host != allowed_host:
            return None
        out["url"] = url
        out["story_id"] = cmd.get("story_id")
        out["volume"] = _volume(cmd.get("volume"), max_volume)
    elif action == "volume":
        value = _volume(cmd.get("value"), max_volume)
        if value is None:
            return None
        out["volume"] = value
    return out


def read_wav_header(read_exact):
    if read_exact(4) != b"RIFF":
        raise ValueError("not a WAV file")
    read_exact(4)
    if read_exact(4) != b"WAVE":
        raise ValueError("not a WAV file")
    rate = bits = channels = None
    while True:
        chunk_id = read_exact(4)
        size = struct.unpack("<I", read_exact(4))[0]
        if chunk_id == b"fmt ":
            data = read_exact(size + (size & 1))
            fmt, channels, rate = struct.unpack("<HHI", data[:8])
            bits = struct.unpack("<H", data[14:16])[0]
            if fmt != 1:
                raise ValueError("WAV must be uncompressed PCM")
        elif chunk_id == b"data":
            if rate is None:
                raise ValueError("data chunk before fmt chunk")
            return rate, bits, channels, size
        else:
            read_exact(size + (size & 1))
