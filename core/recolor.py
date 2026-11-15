"""Colour discovery + recolouring for Cascade particle systems and material instances."""
import colorsys
import math
import re
import struct

from .uasset import Asset

DIST_NAMES = {'ColorOverLife', 'ColorScaleOverLife', 'StartColor'}
PARAM_RE = re.compile(r'colou?r|^EM$|hdr|tint|emis|gradation|fresnel|magma|^EM_|_EM$|^C\d$', re.I)
# Generic names some materials use for a colour; accepted only when the value looks like one.
GENERIC_RE = re.compile(r'^Param\d*$|lava|heat|burn|vein|glow|crack', re.I)


def looks_like_color(v):
    """Chromatic/non-mask RGB (not an axis like (0,0,1) or a channel mask)."""
    r, g, b = v[:3]
    if any(x < 0 for x in (r, g, b)) or max(r, g, b) <= 0:
        return False
    return not all(x in (0.0, 1.0) for x in (r, g, b))


def is_color_param(name, value=None):
    if PARAM_RE.search(name):
        return True
    return bool(value is not None and GENERIC_RE.search(name) and looks_like_color(value))
INDICATOR_RE = re.compile(r'enemy|friend|signarea|ally', re.I)
SAT_THR = 0.12


# ---------------------------------------------------------------- colour maths
def s2l(c):
    c = max(0.0, min(1.0, c))
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def l2s(c):
    c = max(0.0, min(1.0, c))
    return c * 12.92 if c <= 0.0031308 else 1.055 * (c ** (1 / 2.4)) - 0.055


def hex_to_rgb(h):
    h = h.lstrip('#')
    return tuple(int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))


def rgb_to_hex(rgb):
    return '#%02X%02X%02X' % tuple(int(round(max(0, min(1, c)) * 255)) for c in rgb)


def lin_norm_to_hex(rgb):
    """linear RGB (any intensity) -> display hex, normalised to max=1."""
    m = max(rgb)
    if m <= 1e-6:
        return '#000000'
    return rgb_to_hex(tuple(l2s(c / m) for c in rgb))


def analyse(rgb):
    """-> (m, h, s) where m = max linear comp, h/s from gamma-encoded normalised colour."""
    r, g, b = (max(0.0, c) for c in rgb)
    m = max(r, g, b)
    if m <= 1e-6 or math.isnan(m) or math.isinf(m):
        return 0.0, 0.0, 0.0
    h, s, _ = colorsys.rgb_to_hsv(l2s(r / m), l2s(g / m), l2s(b / m))
    return m, h, s


def reference(entries):
    """Dominant (hue, sat) of chromatic entries [(rgb, weight)]; None if none."""
    x = y = ws = wt = 0.0
    for rgb, w in entries:
        m, h, s = analyse(rgb)
        if m <= 0.02 or s < SAT_THR:
            continue
        ww = w * s * (0.25 + min(m, 2.0))
        x += math.cos(h * 2 * math.pi) * ww
        y += math.sin(h * 2 * math.pi) * ww
        ws += s * ww
        wt += ww
    if wt <= 0:
        return None
    return ((math.atan2(y, x) / (2 * math.pi)) % 1.0, ws / wt)


class Swap:
    """Pure colour function: linear rgb -> linear rgb."""

    def __init__(self, hex_color, mode='shift', ref=None, intensity=1.0, tint_white=False):
        r, g, b = hex_to_rgb(hex_color)
        self.th, self.ts, self.tv = colorsys.rgb_to_hsv(r, g, b)
        self.mode = mode
        self.ref = ref
        self.intensity = intensity
        self.tint_white = tint_white
        self.k = 1.0
        if ref and ref[1] > 1e-3:
            self.k = max(0.0, min(4.0, self.ts / ref[1]))

    def variant(self, steps, strength):
        """Slightly different colour for a lower skill level (steps below max).

        Max level (steps=0) is the exact picked colour; every step below shifts the
        hue a few degrees and takes a little saturation and brightness away.
        """
        if steps <= 0 or strength <= 0 or self.mode == 'original':
            return self
        key = (steps, round(strength, 4))
        cache = self.__dict__.setdefault('_variants', {})
        if key not in cache:
            v = Swap.__new__(Swap)
            v.__dict__.update(self.__dict__)
            v._variants = {}
            d = steps * strength
            v.th = (self.th + 0.02 * d) % 1.0
            v.ts = max(0.0, self.ts * (1 - 0.12 * d))
            v.tv = max(0.0, self.tv * (1 - 0.10 * d))
            cache[key] = v
        return cache[key]

    def __call__(self, rgb):
        if self.mode == 'original':
            return tuple(c * self.intensity for c in rgb)
        m, h, s = analyse(rgb)
        if m <= 0.0:
            return tuple(rgb)
        if s < SAT_THR:
            if not self.tint_white:
                return tuple(c * self.intensity for c in rgb)
            nh, ns = self.th, self.ts * 0.7
        else:
            if self.mode == 'unify' or not self.ref:
                nh = self.th
            else:
                nh = (h + (self.th - self.ref[0])) % 1.0
            if self.mode == 'unify' or not self.ref:
                ns = self.ts  # full strength: exactly the picked saturation
            else:
                ns = max(0.0, min(1.0, s * self.k))
        r, g, b = colorsys.hsv_to_rgb(nh, ns, 1.0)
        f = m * s2l(self.tv) * self.intensity  # tv is gamma-encoded; scale in linear light
        return (s2l(r) * f, s2l(g) * f, s2l(b) * f)


# ---------------------------------------------------------------- fields
class DistField:
    """A RawDistributionVector that holds colours (LUT table + min/max)."""
    kind = 'dist'

    def __init__(self, label, tab_pos, stride, minv, maxv, smin, smax):
        self.label, self.tab, self.stride = label, tab_pos, stride
        self.minv, self.maxv, self.smin, self.smax = minv, maxv, smin, smax

    def entries(self, buf):
        if self.tab is not None:
            cnt = struct.unpack_from('<i', buf, self.tab)[0]
            st = self.stride
            n = cnt // st
            if n > 0:
                fl = struct.unpack_from(f'<{cnt}f', buf, self.tab + 4)
                return [tuple(fl[i * st:i * st + 3]) for i in range(n)]
        if self.minv is not None and self.maxv is not None:
            a = struct.unpack_from('<3f', buf, self.minv)
            b = struct.unpack_from('<3f', buf, self.maxv)
            return [a] if a == b else [a, b]
        return []

    def spans(self, buf):
        """Byte ranges this field may change (used by the cosmetic-only safety check)."""
        out = []
        if self.tab is not None:
            out.append((self.tab + 4, self.tab + 4 + 4 * max(0, struct.unpack_from('<i', buf, self.tab)[0])))
        out += [(p, p + 12) for p in (self.minv, self.maxv) if p is not None]
        out += [(p, p + 4) for p in (self.smin, self.smax) if p is not None]
        return out

    def apply(self, buf, fn):
        if self.tab is not None:
            cnt = struct.unpack_from('<i', buf, self.tab)[0]
            st = self.stride
            n = cnt // st
            if n > 0:
                fl = list(struct.unpack_from(f'<{cnt}f', buf, self.tab + 4))
                new = []
                for i in range(n):
                    c = fn(tuple(fl[i * st:i * st + 3]))
                    fl[i * st:i * st + 3] = c
                    new.append(c)
                struct.pack_into(f'<{cnt}f', buf, self.tab + 4, *fl)
                return
        if self.minv is not None and self.maxv is not None:
            a = fn(struct.unpack_from('<3f', buf, self.minv))
            b = fn(struct.unpack_from('<3f', buf, self.maxv))
            struct.pack_into('<3f', buf, self.minv, *a)
            struct.pack_into('<3f', buf, self.maxv, *b)


class ParamField:
    """LinearColor stored at a fixed position (MI vector param / Material default)."""
    kind = 'param'

    def __init__(self, label, pos):
        self.label, self.pos = label, pos

    def entries(self, buf):
        return [struct.unpack_from('<3f', buf, self.pos)]

    def spans(self, buf):
        return [(self.pos, self.pos + 12)]

    def apply(self, buf, fn):
        c = fn(struct.unpack_from('<3f', buf, self.pos))
        struct.pack_into('<3f', buf, self.pos, *c)


class GpuColorField:
    """GPU sprite emitter colour baked into ParticleModuleTypeDataGpu.ResourceData.

    In game the colour is QuantizedColorSamples (FColor, BGRA) * ColorScale + ColorBias;
    the CPU ColorOverLife modules are not evaluated for GPU emitters.
    """
    kind = 'gpu'

    def __init__(self, label, samples_pos, count, scale_pos, bias_pos):
        self.label, self.samples, self.count = label, samples_pos, count
        self.scale_pos, self.bias_pos = scale_pos, bias_pos

    def _decode(self, buf):
        sc = struct.unpack_from('<3f', buf, self.scale_pos)
        bi = struct.unpack_from('<3f', buf, self.bias_pos)
        out = []
        for i in range(self.count):
            b, g, r, _a = buf[self.samples + 4 * i:self.samples + 4 * i + 4]
            out.append(tuple(q / 255.0 * s + o for q, s, o in zip((r, g, b), sc, bi)))
        return out or [tuple(bi)]

    def entries(self, buf):
        return self._decode(buf)

    def spans(self, buf):
        return [(self.samples, self.samples + 4 * self.count),
                (self.scale_pos, self.scale_pos + 12), (self.bias_pos, self.bias_pos + 12)]

    def apply(self, buf, fn):
        old = self._decode(buf)
        new = [tuple(max(0.0, x) for x in fn(c)) for c in old]
        if all(abs(a - b) < 1e-7 for o, n in zip(old, new) for a, b in zip(o, n)):
            return  # unchanged colours: keep the original bytes (no requantisation noise)
        lo = [min(c[k] for c in new) for k in range(3)]
        hi = [max(c[k] for c in new) for k in range(3)]
        span = [h - l for h, l in zip(hi, lo)]
        for i, c in enumerate(new[:self.count]):
            q = [0 if span[k] <= 1e-9 else max(0, min(255, round((c[k] - lo[k]) / span[k] * 255))) for k in range(3)]
            p = self.samples + 4 * i
            buf[p], buf[p + 1], buf[p + 2] = q[2], q[1], q[0]   # BGRA, alpha kept
        struct.pack_into('<3f', buf, self.scale_pos, *span)
        struct.pack_into('<3f', buf, self.bias_pos, *lo)


def _prop_map(props):
    return {p.name: p for p in (props or [])}


def find_fields(asset: Asset):
    """Return list of colour fields in the asset's .uexp."""
    out = []
    buf = asset.ux
    for ei, e in enumerate(asset.exports):
        first = len(out)
        cls = e['class']
        if cls.startswith('ParticleModule') and ('Color' in cls or 'Light' in cls):
            for p in asset.export_props(ei):
                if p.sname == 'RawDistributionVector' and p.name in DIST_NAMES and p.children:
                    d = _prop_map(p.children)
                    t = _prop_map(d['Table'].children) if 'Table' in d else {}
                    tab = t['Values'].vpos if 'Values' in t else None
                    stride = buf[t['EntryStride'].vpos] if 'EntryStride' in t else 3
                    if stride < 3:
                        continue
                    out.append(DistField(f'{e["name"]}.{p.name}', tab, stride,
                                         d['MinValueVec'].vpos if 'MinValueVec' in d else None,
                                         d['MaxValueVec'].vpos if 'MaxValueVec' in d else None,
                                         d['MinValue'].vpos if 'MinValue' in d else None,
                                         d['MaxValue'].vpos if 'MaxValue' in d else None))
        elif cls == 'ParticleModuleTypeDataGpu':
            for p in asset.export_props(ei):
                if p.name != 'ResourceData' or not p.children:
                    continue
                d = _prop_map(p.children)
                qs, sc, bi = d.get('QuantizedColorSamples'), d.get('ColorScale'), d.get('ColorBias')
                if not (qs and sc and bi and isinstance(qs.value, tuple)):
                    continue
                count, data, size = qs.value
                if count < 0 or size != count * 4:
                    continue
                out.append(GpuColorField(f'{e["name"]}.GPU', data, count, sc.vpos, bi.vpos))
        elif cls == 'MaterialInstanceConstant':
            for p in asset.export_props(ei):
                if p.name == 'VectorParameterValues' and p.children:
                    for c in p.children:
                        d = _prop_map(c.children)
                        if 'ParameterInfo' not in d or 'ParameterValue' not in d:
                            continue
                        info = d['ParameterInfo'].children
                        if not info:
                            continue
                        name = asset.fname(buf, info[0].vpos)
                        if is_color_param(name, struct.unpack_from('<3f', buf, d['ParameterValue'].vpos)):
                            out.append(ParamField(name, d['ParameterValue'].vpos))
        elif cls == 'Material':
            for p in asset.export_props(ei):
                if p.name != 'CachedExpressionData' or not p.children:
                    continue
                par = _prop_map(p.children).get('Parameters')
                if not par or not par.children:
                    continue
                vec_entry = None
                vals = None
                for c in par.children:
                    if c.name == 'RuntimeEntries' and c.idx == 1:
                        vec_entry = c
                    if c.name == 'VectorValues':
                        vals = c
                if not vec_entry or not vals or not vals.value:
                    continue
                infos = _prop_map(vec_entry.children).get('ParameterInfos')
                if not infos or not infos.children:
                    continue
                cnt, q, _ = vals.value
                if cnt != len(infos.children):
                    continue
                for i, ch in enumerate(infos.children):
                    nm = ch.children and asset.fname(buf, ch.children[0].vpos)
                    if nm and is_color_param(nm, struct.unpack_from('<3f', buf, q + i * 16)):
                        out.append(ParamField(nm + ' (default)', q + i * 16))
        for field in out[first:]:
            field.export_index = ei
    return out
