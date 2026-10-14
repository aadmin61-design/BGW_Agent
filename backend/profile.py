"""校验浏览器缩小后的PNG头像；只用标准库，限制解压内存并移除元数据。"""
import base64
import binascii
import struct
import zlib


PNG = b"\x89PNG\r\n\x1a\n"
MAX_AVATAR_BYTES = 256 * 1024


def png_chunk(kind, content):
    return (struct.pack(">I", len(content)) + kind + content +
            struct.pack(">I", binascii.crc32(kind + content) & 0xffffffff))


def normalise_avatar(value):
    try:
        prefix = "data:image/png;base64,"
        if not value.startswith(prefix):
            raise ValueError()
        image = base64.b64decode(value[len(prefix):], validate=True)
        if not image.startswith(PNG) or len(image) > MAX_AVATAR_BYTES:
            raise ValueError()
        pos = len(PNG)
        header = None
        compressed = bytearray()
        ended = False
        idat_ended = False
        while pos + 12 <= len(image):
            length = struct.unpack(">I", image[pos:pos + 4])[0]
            kind = image[pos + 4:pos + 8]
            end = pos + length + 12
            if end > len(image):
                raise ValueError()
            content = image[pos + 8:end - 4]
            crc = struct.unpack(">I", image[end - 4:end])[0]
            if crc != binascii.crc32(kind + content) & 0xffffffff:
                raise ValueError()
            if kind == b"IHDR":
                if header is not None or pos != len(PNG) or length != 13:
                    raise ValueError()
                header = content
            elif kind == b"IDAT":
                if header is None or idat_ended:
                    raise ValueError()
                compressed.extend(content)
            elif kind == b"IEND":
                if length or end != len(image):
                    raise ValueError()
                ended = True
            else:
                # 拒绝未知关键块和动画；其他元数据不保存到数据库。
                if not kind[0] & 32 or kind in {b"acTL", b"fcTL", b"fdAT"}:
                    raise ValueError()
                if compressed:
                    idat_ended = True
            pos = end
            if ended:
                break
        if header is None or not ended or not compressed:
            raise ValueError()
        width, height, depth, colour, compression, filtering, interlace = struct.unpack(">IIBBBBB", header)
        if not (1 <= width <= 256 and 1 <= height <= 256) or depth != 8 or colour not in {2, 6}:
            raise ValueError()
        if compression or filtering or interlace:
            raise ValueError()
        row_size = 1 + width * (4 if colour == 6 else 3)
        expected = row_size * height
        decoder = zlib.decompressobj()
        # 限制解压输出，压缩炸弹也最多分配约256KiB。
        pixels = decoder.decompress(compressed, expected + 1)
        if len(pixels) != expected or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
            raise ValueError()
        if any(pixels[i] > 4 for i in range(0, expected, row_size)):
            raise ValueError()
        return PNG + png_chunk(b"IHDR", header) + png_chunk(b"IDAT", zlib.compress(pixels)) + png_chunk(b"IEND", b"")
    except (ValueError, struct.error, zlib.error, IndexError) as error:
        raise ValueError("头像格式无效，请重新选择图片") from error
