"""Unreal Engine 4 .pak (version 3, zlib) reader / writer.

Only what is needed for MHUR mods: unencrypted paks, zlib or no compression.
"""
import hashlib
import os
import tempfile
from pathlib import Path
import struct
import zlib

MAGIC = 0x5A6F12E1
BLOCK = 65536


def _fstr(d, p):
    n = struct.unpack_from('<i', d, p)[0]
    p += 4
    if n < 0:
        n = -n
        s = d[p:p + n * 2 - 2].decode('utf-16le')
        p += n * 2
    else:
        s = d[p:p + n - 1].decode('utf-8', 'replace')
        p += n
    return s, p


def _wstr(s):
    b = s.encode('utf-8') + b'\0'
    return struct.pack('<i', len(b)) + b


def read_pak(path):
    """Return (mount_point, {relative_path: bytes})."""
    with open(path, 'rb') as f:
        d = f.read()
    i = d.rfind(struct.pack('<I', MAGIC))
    if i < 0:
        raise ValueError('Not a .pak file (magic not found)')
    ver = struct.unpack_from('<I', d, i + 4)[0]
    if ver > 3:
        raise ValueError(f'Pak version {ver} not supported (only v3 mod paks)')
    idx_off, idx_size = struct.unpack_from('<QQ', d, i + 8)
    p = idx_off
    mount, p = _fstr(d, p)
    n = struct.unpack_from('<i', d, p)[0]
    p += 4
    out = {}
    for _ in range(n):
        name, p = _fstr(d, p)
        off, size, usize, comp = struct.unpack_from('<QQQI', d, p)
        p += 28 + 20
        blocks = []
        if comp:
            nb = struct.unpack_from('<I', d, p)[0]
            p += 4
            for _ in range(nb):
                blocks.append(struct.unpack_from('<QQ', d, p))
                p += 16
        p += 5  # encrypted flag + block size
        # skip in-data header
        q = off + 28 + 20
        if comp:
            nb = struct.unpack_from('<I', d, q)[0]
            q += 4 + 16 * nb
        q += 5
        if comp == 0:
            data = d[q:q + size]
        elif comp == 1:
            data = b''.join(zlib.decompress(d[s:e]) for s, e in blocks)
        else:
            raise ValueError(f'Unsupported compression method {comp} for {name}')
        out[name] = data
    return mount, out


def write_pak(path, mount, files):
    """files: {relative_path: bytes}. Writes v3 zlib pak."""
    target = Path(path)
    fd, temporary = tempfile.mkstemp(dir=target.parent, prefix='.' + target.name, suffix='.tmp')
    try:
        with os.fdopen(fd, 'wb') as stream:
            index = bytearray(_wstr(mount) + struct.pack('<i', len(files)))
            for name, data in files.items():
                blocks = [data[i:i + BLOCK] for i in range(0, len(data), BLOCK)] or [b'']
                compressed = [zlib.compress(block, 9) for block in blocks]
                csize = sum(map(len, compressed))
                digest = hashlib.sha1()
                for block in compressed:
                    digest.update(block)
                sha = digest.digest()
                base = stream.tell()
                header_size = 28 + 20 + 4 + 16 * len(compressed) + 5
                pos = base + header_size
                ranges = []
                for block in compressed:
                    ranges.append((pos, pos + len(block)))
                    pos += len(block)

                def record(offset):
                    result = struct.pack('<QQQI', offset, csize, len(data), 1) + sha
                    result += struct.pack('<I', len(ranges))
                    for first, last in ranges:
                        result += struct.pack('<QQ', first, last)
                    return result + struct.pack('<BI', 0, BLOCK)

                stream.write(record(0))
                for block in compressed:
                    stream.write(block)
                index += _wstr(name) + record(base)
            index_offset = stream.tell()
            stream.write(index)
            stream.write(struct.pack('<IIQQ', MAGIC, 3, index_offset, len(index))
                         + hashlib.sha1(index).digest())
        os.replace(temporary, target)
    finally:
        Path(temporary).unlink(missing_ok=True)
