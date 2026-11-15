"""In-place recoloring of cooked UE4.27 Texture2D colour data (DXT1, DXT5, BC7).

Block-compressed textures store two endpoint colours per 4x4 block (per subset
for BC7) and per-pixel interpolation indices. Recoloring the endpoints changes
the colours while the indices (the texture's shape, cracks, edges) stay as they
are, and every mip keeps its exact size. Normal maps, packed masks and float /
uncompressed formats are never touched.
"""
import re
import struct

import colorsys

from .recolor import hex_to_rgb, l2s, s2l

SUPPORTED = {'PF_DXT1': 8, 'PF_DXT5': 16, 'PF_BC7': 16}
BULK_SEPARATE = 0x100      # payload in .ubulk
BULK_UNUSED = 0x20
BULK_OPTIONAL = 0x800      # payload in .uptnl (not shipped in mods we write)
BULK_SIZE64 = 0x2000

# Textures that carry colour (base colour / diffuse / albedo). Anything that
# looks like data (normals, masks, packed channels, noise, flow, distortion,
# alpha, roughness/metal) is excluded: recoloring those would break the effect.
COLOR_NAME = re.compile(r'(_D|_Base|_BaseColor|_Basecolor|_Diffuse|_Albedo|_Color|_Col|_BC)(_\d+)?$', re.I)
DATA_NAME = re.compile(r'(_N|_M|_R|_H|_O|_S|_ARM\w*|_ORM\w*|_RMA\w*|_Mask\w*|RGBA|Normal|Noise|Flow|Distort|Dissolve|Alpha|Height|Rough|Metal|Spec|Opacity|_pos|_rot|_nrm|VAT|Gradient|gradetion|Ramp|LUT|Cubemap|dummy|glow|smoke|cloud|fire|spark|trail|line|circle|ring)(_\d+)?(_|$)', re.I)
# Words that describe solid move objects; such textures are recolored only when they are
# stored as sRGB colour (masks / data textures are stored linear and would break).
OBJECT_WORDS = re.compile(r'(crack|rock|stone|ice|concrete|cement|wall|debris|debri|spike|needle|pill?ar|piller|break|block|ground|floor|rubble|crystal|brick|thorn|decay|lava|magma|vein|ember)', re.I)
# Emissive (glow) colour textures, e.g. glowing crack lines; recolored only when sRGB colour.
EMISSIVE_NAME = re.compile(r'(_E|_Emi|_Emis|_Emissive|_Emit)(_\d+)?$', re.I)


def texture_kind(name):
    """'color' (base colour), 'object' (solid-object texture, needs sRGB) or None."""
    stem = name.rsplit('/', 1)[-1]
    if not stem.startswith('T_') or DATA_NAME.search(stem[2:]):
        return None
    if COLOR_NAME.search(stem):
        return 'color'
    if EMISSIVE_NAME.search(stem) or OBJECT_WORDS.search(stem[2:]):
        return 'object'
    return None


def is_color_texture(name):
    return texture_kind(name) is not None


class Mip:
    __slots__ = ('where', 'offset', 'size', 'width', 'height')

    def __init__(self, where, offset, size, width, height):
        self.where, self.offset, self.size, self.width, self.height = where, offset, size, width, height


class TextureInfo:
    def __init__(self, fmt, width, height, srgb, mips):
        self.format, self.width, self.height, self.srgb, self.mips = fmt, width, height, srgb, mips


def parse_texture(asset, ux, ubulk_size=None):
    """Mip layout of a cooked Texture2D, or None when it is not a supported colour texture."""
    if not asset.exports or asset.exports[0]['class'] != 'Texture2D':
        return None
    props = {p.name: p for p in asset.export_props(0)}
    srgb = True
    if 'SRGB' in props and props['SRGB'].type == 'BoolProperty':
        srgb = bool(ux[props['SRGB'].bool_pos])
    m = re.search(rb'PF_[A-Za-z0-9_]+\x00', ux)
    if not m:
        return None
    fmt = m.group(0)[:-1].decode('ascii')
    if fmt not in SUPPORTED:
        return None
    strlen_pos = m.start() - 4
    if struct.unpack_from('<i', ux, strlen_pos)[0] != len(fmt) + 1:
        return None
    width, height, packed = struct.unpack_from('<iiI', ux, strlen_pos - 12)
    if packed & 0x40000000 or packed & 0x3FFFFFFF != 1:
        return None   # optional data / cubemaps / arrays: not touched
    pos = m.end()
    _first, nmips = struct.unpack_from('<ii', ux, pos)
    pos += 8
    if not 0 < nmips <= 16:
        return None
    mips = []
    block = SUPPORTED[fmt]
    for _ in range(nmips):
        cooked, flags = struct.unpack_from('<iI', ux, pos)
        pos += 8
        if flags & BULK_SIZE64:
            count, size = struct.unpack_from('<qq', ux, pos)
            pos += 16
        else:
            count, size = struct.unpack_from('<ii', ux, pos)
            pos += 8
        offset = struct.unpack_from('<q', ux, pos)[0]
        pos += 8
        where = None
        if flags & BULK_UNUSED or size <= 0:
            where = None
        elif flags & BULK_OPTIONAL:
            where = None
        elif flags & BULK_SEPARATE:
            where = 'ubulk'
        else:
            where = 'uexp'
            offset = pos
            pos += size
        mw, mh, _depth = struct.unpack_from('<iii', ux, pos)
        pos += 12
        expected = max(1, (mw + 3) // 4) * max(1, (mh + 3) // 4) * block
        if where and size != expected:
            return None   # unexpected layout: leave the texture alone
        if where == 'ubulk' and ubulk_size is not None and offset + size > ubulk_size:
            return None
        if where:
            mips.append(Mip(where, offset, size, mw, mh))
        if not cooked:
            return None
    return TextureInfo(fmt, width, height, srgb, mips)


# ------------------------------------------------------------------ colour helpers
def _to_linear(rgb8, srgb):
    return tuple(s2l(c / 255.0) if srgb else c / 255.0 for c in rgb8)


def _to_8bit(rgb, srgb):
    out = []
    for c in rgb:
        c = min(1.0, max(0.0, c))
        out.append(round((l2s(c) if srgb else c) * 255))
    return out


def _memo(fn, srgb):
    cache = {}

    def color(rgb8):
        v = cache.get(rgb8)
        if v is None:
            v = cache[rgb8] = _to_8bit(fn(_to_linear(rgb8, srgb)), srgb)
        return v
    return color


# ------------------------------------------------------------------ DXT1 / DXT5 colour blocks
def _unpack565(c):
    r, g, b = (c >> 11) & 31, (c >> 5) & 63, c & 31
    return ((r << 3) | (r >> 2), (g << 2) | (g >> 4), (b << 3) | (b >> 2))


def _pack565(rgb):
    r, g, b = rgb
    return ((round(r * 31 / 255) & 31) << 11) | ((round(g * 63 / 255) & 63) << 5) | (round(b * 31 / 255) & 31)


def _recolor_bc1(buf, start, size, stride, color_offset, color, keep_mode):
    for p in range(start + color_offset, start + size, stride):
        c0, c1, idx = struct.unpack_from('<HHI', buf, p)
        n0, n1 = _pack565(color(_unpack565(c0))), _pack565(color(_unpack565(c1)))
        if keep_mode:  # DXT1: c0 > c1 means opaque 4-colour mode, c0 <= c1 has transparency
            if c0 > c1:
                if n0 < n1:
                    n0, n1, idx = n1, n0, idx ^ 0x55555555          # 0<->1, 2<->3
                elif n0 == n1:
                    if n0 == 0:
                        n0, idx = 1, 0
                    else:
                        n1, idx = n0 - 1, 0
            elif n0 > n1:
                low = ~(idx >> 1) & 0x55555555                     # only indices 0/1 swap
                n0, n1, idx = n1, n0, idx ^ low
        struct.pack_into('<HHI', buf, p, n0, n1, idx & 0xFFFFFFFF)


# ------------------------------------------------------------------ BC7
#        subsets, partition bits, rotation bits, index-sel bits, colour bits, alpha bits, endpoint pbits, shared pbits
BC7_MODES = [(3, 4, 0, 0, 4, 0, 1, 0), (2, 6, 0, 0, 6, 0, 0, 1), (3, 6, 0, 0, 5, 0, 0, 0), (2, 6, 0, 0, 7, 0, 1, 0),
             (1, 0, 2, 1, 5, 6, 0, 0), (1, 0, 2, 0, 7, 8, 0, 0), (1, 0, 0, 0, 7, 7, 1, 0), (2, 6, 0, 0, 5, 5, 1, 0)]


def _expand(v, bits):
    return (v << (8 - bits)) | (v >> (2 * bits - 8)) if bits < 8 else v


def _quantize(target, bits, pbit):
    """Closest value with the given precision (and fixed p-bit when pbit is not None)."""
    best, err = 0, 1 << 30
    if pbit is None:
        n = bits
        guess = round(target * ((1 << n) - 1) / 255)
        for q in (guess - 1, guess, guess + 1):
            if 0 <= q < (1 << n):
                e = abs(_expand(q, n) - target)
                if e < err:
                    best, err = q, e
        return best
    n = bits + 1
    guess = round((target * ((1 << n) - 1) / 255 - pbit) / 2)
    for q in (guess - 1, guess, guess + 1):
        if 0 <= q < (1 << bits):
            e = abs(_expand((q << 1) | pbit, n) - target)
            if e < err:
                best, err = q, e
    return best


def _recolor_bc7_block(block, color):
    mode = 0
    while mode < 8 and not (block >> mode) & 1:
        mode += 1
    if mode == 8:
        return block
    ns, pb, rb, isb, cb, ab, epb, spb = BC7_MODES[mode]
    pos = mode + 1 + pb
    if rb:
        if (block >> pos) & 3:      # channel rotation swaps alpha into colour: leave the block
            return block
    pos += rb + isb
    ne = ns * 2
    cpos = pos                                         # R[e], G[e], B[e]
    apos = cpos + 3 * ne * cb
    ppos = apos + ne * ab                              # alpha endpoints are not touched
    pbits = [None] * ne
    if epb:
        pbits = [(block >> (ppos + e)) & 1 for e in range(ne)]
    elif spb:
        pbits = [(block >> (ppos + e // 2)) & 1 for e in range(ne)]
    bits = cb + (1 if (epb or spb) else 0)
    mask = (1 << cb) - 1
    for e in range(ne):
        raw = []
        for ch in range(3):
            q = (block >> (cpos + (ch * ne + e) * cb)) & mask
            v = (q << 1) | pbits[e] if pbits[e] is not None else q
            raw.append(_expand(v, bits))
        new = color(tuple(raw))
        for ch in range(3):
            q = _quantize(new[ch], cb, pbits[e])
            at = cpos + (ch * ne + e) * cb
            block = (block & ~(mask << at)) | (q << at)
    return block


def _recolor_bc7(buf, start, size, color):
    for p in range(start, start + size, 16):
        old = int.from_bytes(buf[p:p + 16], 'little')
        new = _recolor_bc7_block(old, color)
        if new != old:
            buf[p:p + 16] = new.to_bytes(16, 'little')


# ------------------------------------------------------------------ colorize
class TextureTint:
    """Colorize a texture so that its typical colour becomes exactly the picked colour.

    The texture's median saturation and brightness are mapped onto the picked
    colour's saturation and brightness; every texel keeps its offset from that
    median, so highlights stay lighter and shadows darker (detail is kept) while the
    overall look matches the chosen colour. Whites get a light tint of the hue.
    """

    def __init__(self, hex_color, mode='unify', intensity=1.0, samples=(), srgb=True, second=None):
        self.th, self.ts, self.tv = colorsys.rgb_to_hsv(*hex_to_rgb(hex_color))
        # two-colour mode: the object's body takes the main colour, its highlights the second
        self.second = colorsys.rgb_to_hsv(*hex_to_rgb(second)) if second else None
        self.mode, self.intensity = mode, float(intensity)
        hsv = []
        for rgb in samples:
            c = [x / 255 for x in rgb]
            if not srgb:
                c = [l2s(x) for x in c]
            hsv.append(colorsys.rgb_to_hsv(*c))
        chroma = [(h, s) for h, s, v in hsv if s > 0.15 and v > 0.15]
        values = sorted(v for h, s, v in hsv if v > 0.03)
        self.ref_v = values[len(values) // 2] if values else None
        # two-colour gradient: from the coloured part's typical brightness up to the brightest highlights
        cv = sorted(v for h, s, v in hsv if s > 0.15 and v > 0.15)
        self.lo_v = cv[len(cv) // 2] if cv else self.ref_v
        hi = max(values[int(len(values) * 0.85)] if values else 1.0, (self.lo_v or 0) + 0.08)
        self.hi_v = max(min(hi, 1.0), (self.lo_v or 0) + 0.01)
        if chroma:
            sats = sorted(s for _, s in chroma)
            self.ref_s = sats[len(sats) // 2]
            import math
            x = sum(math.cos(h * 2 * math.pi) for h, _ in chroma)
            y = sum(math.sin(h * 2 * math.pi) for h, _ in chroma)
            self.ref_h = (math.atan2(y, x) / (2 * math.pi)) % 1.0
        else:
            self.ref_s, self.ref_h = None, None

    def __call__(self, rgb_linear):
        g = [l2s(min(1.0, max(0.0, c))) for c in rgb_linear]
        h, s, v = colorsys.rgb_to_hsv(*g)
        if self.mode == 'original':
            nh, ns = h, s
        elif self.mode == 'shift' and self.ref_h is not None:
            nh, ns = (h + self.th - self.ref_h) % 1.0, s
        else:
            nh = self.th
            if self.ref_s:
                ns = max(min(1.0, s * self.ts / self.ref_s), self.ts * 0.35)
            else:   # grey texture (stone, concrete): becomes the picked colour
                ns = self.ts * (0.75 + 0.25 * min(1.0, s / 0.15))
        if self.mode == 'original':
            nv = v * self.intensity
        else:
            scale = self.tv / self.ref_v if self.ref_v else self.tv
            nv = v * scale * self.intensity
        main = colorsys.hsv_to_rgb(nh, ns, min(1.0, nv))
        if self.second and self.mode != 'original' and self.lo_v:
            # weight: 0 at the coloured part's typical brightness, 1 at the brightest highlights
            w = min(1.0, max(0.0, (v - self.lo_v) / (self.hi_v - self.lo_v)))
            w = w * w * (3 - 2 * w)
            if w > 0:
                h2, s2, v2 = self.second
                sat2 = max(min(1.0, s * s2 / self.ref_s), s2 * 0.6) if self.ref_s else s2
                val2 = min(1.0, v * v2 / self.ref_v * self.intensity)
                h1, s1, v1 = colorsys.rgb_to_hsv(*main)
                dh = ((h2 - h1 + 0.5) % 1.0) - 0.5          # shortest way round the colour wheel
                main = colorsys.hsv_to_rgb((h1 + dh * w) % 1.0, s1 + (sat2 - s1) * w, v1 + (val2 - v1) * w)
        return tuple(s2l(c) for c in main)


# ------------------------------------------------------------------ public
def recolor_texture(info, ux, ubulk, fn):
    """Recolor all mips. Returns (new_uexp, new_ubulk, spans_uexp, spans_ubulk)."""
    color = _memo(fn, info.srgb)
    out = {'uexp': bytearray(ux), 'ubulk': bytearray(ubulk or b'')}
    spans = {'uexp': [], 'ubulk': []}
    for mip in info.mips:
        buf = out[mip.where]
        if mip.offset + mip.size > len(buf):
            continue
        if info.format == 'PF_DXT1':
            _recolor_bc1(buf, mip.offset, mip.size, 8, 0, color, True)
        elif info.format == 'PF_DXT5':
            _recolor_bc1(buf, mip.offset, mip.size, 16, 8, color, False)
        else:
            _recolor_bc7(buf, mip.offset, mip.size, color)
        spans[mip.where].append((mip.offset, mip.offset + mip.size))
    return bytes(out['uexp']), bytes(out['ubulk']), spans['uexp'], spans['ubulk']


def endpoint_colors(info, ux, ubulk, limit=4096):
    """Decoded endpoint colours (8-bit) of the largest mip, for previews and tests."""
    mip = info.mips[0]
    buf = ux if mip.where == 'uexp' else ubulk
    out = []
    if info.format in ('PF_DXT1', 'PF_DXT5'):
        stride, off = (8, 0) if info.format == 'PF_DXT1' else (16, 8)
        for p in range(mip.offset + off, mip.offset + mip.size, stride):
            c0, c1 = struct.unpack_from('<HH', buf, p)
            out += [_unpack565(c0), _unpack565(c1)]
            if len(out) >= limit:
                break
    else:
        got = []
        for p in range(mip.offset, mip.offset + mip.size, 16):
            _recolor_bc7_block(int.from_bytes(buf[p:p + 16], 'little'), lambda c: (got.append(c), c)[1])
            if len(got) >= limit:
                break
        out = got
    return out
