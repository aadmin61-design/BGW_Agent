import base64
import struct
import zlib
import pytest
from backend.profile import PNG, normalise_avatar, png_chunk


def avatar_data(size=2, metadata=False):
    header = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    rows = (b"\x00" + b"\x18\x75\x65\xff" * size) * size
    image = PNG + png_chunk(b"IHDR", header)
    if metadata:
        image += png_chunk(b"tEXt", b"Comment\x00private metadata")
    image += png_chunk(b"IDAT", zlib.compress(rows)) + png_chunk(b"IEND", b"")
    return "data:image/png;base64," + base64.b64encode(image).decode()


def test_png_avatar_strips_metadata():
    result = normalise_avatar(avatar_data(metadata=True))
    assert b"private metadata" not in result
    assert result.startswith(PNG)


def test_avatar_rejects_wrong_format_and_oversize_dimensions():
    for value in ["data:image/svg+xml;base64,PHN2Zz4=", "data:image/png;base64,@@@", avatar_data(257)]:
        with pytest.raises(ValueError):
            normalise_avatar(value)


def test_avatar_rejects_trailing_payload_and_decompression_bomb():
    image = base64.b64decode(avatar_data().split(",")[1])
    with pytest.raises(ValueError):
        normalise_avatar("data:image/png;base64," + base64.b64encode(image + b"unexpected").decode())
    header = struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)
    bomb = PNG + png_chunk(b"IHDR", header) + png_chunk(b"IDAT", zlib.compress(b"\0" * 1000000)) + png_chunk(b"IEND", b"")
    with pytest.raises(ValueError):
        normalise_avatar("data:image/png;base64," + base64.b64encode(bomb).decode())
