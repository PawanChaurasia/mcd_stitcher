from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

_CHANNEL_RE = re.compile(r"^(?P<metal>[a-zA-Z]+)\((?P<mass>[0-9]+)\)$")
_ENC = "utf-16-le"
_TAIL_STEPS_MB = (1, 4, 16, 64, 256, 1024)

class MCDParseError(Exception):
    pass

@dataclass
class Panorama:
    id: int
    slide_id: int
    metadata: Dict[str, str]

    @property
    def description(self) -> Optional[str]:
        return self.metadata.get("Description")

@dataclass
class Acquisition:
    id: int
    metadata: Dict[str, str]
    roi_points_um: Optional[Tuple[Tuple[float, float], ...]]
    _channel_labels: List[str] = field(default_factory=list)
    _channel_metals: List[str] = field(default_factory=list)
    _channel_masses: List[int] = field(default_factory=list)
    _num_channels: int = 0

    @property
    def description(self) -> Optional[str]:
        return self.metadata.get("Description")

    @property
    def num_channels(self) -> int:
        return self._num_channels

    @property
    def channel_labels(self) -> Sequence[str]:
        return self._channel_labels

    @property
    def channel_metals(self) -> Sequence[str]:
        return self._channel_metals

    @property
    def channel_masses(self) -> Sequence[int]:
        return self._channel_masses

    @property
    def channel_names(self) -> Sequence[str]:
        return [f"{m}{n}" for m, n in zip(self._channel_metals, self._channel_masses)]

    def _int(self, key: str) -> Optional[int]:
        v = self.metadata.get(key)
        return int(v) if v is not None else None

    def _float(self, key: str) -> Optional[float]:
        v = self.metadata.get(key)
        return float(v) if v is not None else None

    @property
    def width_px(self) -> Optional[int]:
        return self._int("MaxX")

    @property
    def height_px(self) -> Optional[int]:
        return self._int("MaxY")

    @property
    def pixel_size_x_um(self) -> Optional[float]:
        return self._float("AblationDistanceBetweenShotsX")

    @property
    def pixel_size_y_um(self) -> Optional[float]:
        return self._float("AblationDistanceBetweenShotsY")

@dataclass
class Slide:
    id: int
    metadata: Dict[str, str]
    acquisitions: List[Acquisition] = field(default_factory=list)
    panoramas: List[Panorama] = field(default_factory=list)

    @property
    def description(self) -> Optional[str]:
        return self.metadata.get("Description")

# ---------------------- Schema location ----------------------

def _read_schema_xml(path: Path) -> str:
    size = path.stat().st_size
    start_tok = "<MCDSchema".encode(_ENC)
    end_tok = "</MCDSchema>".encode(_ENC)
    with path.open("rb") as fh:
        for mb in _TAIL_STEPS_MB:
            n = min(size, mb * 2 ** 20)
            fh.seek(size - n)
            buf = fh.read(n)
            s = buf.rfind(start_tok)
            if s == -1:
                if n >= size:
                    break
                continue
            e = buf.rfind(end_tok, s)
            if e == -1:
                if n >= size:
                    break
                continue
            return buf[s:e + len(end_tok)].decode(_ENC)
    raise MCDParseError(f"MCD file '{path.name}' corrupted: MCDSchema not found")

def _localname(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]

def _txt(elem: ET.Element, tag: str) -> Optional[str]:
    for c in elem:
        if _localname(c.tag) == tag:
            return c.text
    return None

def _meta(elem: ET.Element) -> Dict[str, str]:
    return {_localname(c.tag): c.text for c in elem if c.text is not None}

def _parse(xml: str) -> List[Slide]:
    root = ET.fromstring(xml)
    buckets: Dict[str, List[ET.Element]] = {}
    for c in root:
        buckets.setdefault(_localname(c.tag), []).append(c)

    def all_of(tag: str) -> List[ET.Element]:
        return buckets.get(tag, [])

    by_acq_id: Dict[int, List[ET.Element]] = {}
    for ch in all_of("AcquisitionChannel"):
        by_acq_id.setdefault(int(_txt(ch, "AcquisitionID")), []).append(ch)

    roipoints_by_roi: Dict[int, List[ET.Element]] = {}
    for rp in all_of("ROIPoint"):
        roipoints_by_roi.setdefault(int(_txt(rp, "AcquisitionROIID")), []).append(rp)

    roi_to_pano: Dict[int, Optional[int]] = {}
    for r in all_of("AcquisitionROI"):
        pid = _txt(r, "PanoramaID")
        roi_to_pano[int(_txt(r, "ID"))] = int(pid) if pid is not None else None

    pano_to_slide: Dict[int, int] = {}
    panos_by_slide: Dict[int, List[Panorama]] = {}
    for p in all_of("Panorama"):
        pid, sid = int(_txt(p, "ID")), int(_txt(p, "SlideID"))
        pano_to_slide[pid] = sid
        if _txt(p, "Type") != "Default":
            panos_by_slide.setdefault(sid, []).append(Panorama(pid, sid, _meta(p)))

    slides: Dict[int, Slide] = {}
    for s in all_of("Slide"):
        sid = int(_txt(s, "ID"))
        slides[sid] = Slide(sid, _meta(s), [], panos_by_slide.get(sid, []))

    for a in all_of("Acquisition"):
        aid = int(_txt(a, "ID"))
        md = _meta(a)

        chans = sorted(by_acq_id.get(aid, []), key=lambda e: int(_txt(e, "OrderNumber")))
        acq = Acquisition(aid, md, None, _num_channels=max(0, len(chans) - 3))
        for i, ch in enumerate(chans):
            name = _txt(ch, "ChannelName")
            if i < 3:
                expected = ("X", "Y", "Z")[i]
                if name != expected:
                    raise MCDParseError(
                        f"Channel {i} named '{name}', expected '{expected}' for acquisition {aid}")
                continue
            if name in ("X", "Y", "Z"):
                continue
            m = _CHANNEL_RE.match(name or "")
            if m is None:
                raise MCDParseError(
                    f"Cannot extract channel information from '{name}' for acquisition {aid}")
            acq._channel_metals.append(m.group("metal"))
            acq._channel_masses.append(int(m.group("mass")))
            acq._channel_labels.append(_txt(ch, "ChannelLabel"))

        roi_id_txt = md.get("AcquisitionROIID")
        sid = None
        if roi_id_txt is not None:
            roi_id = int(roi_id_txt)
            pts = sorted(roipoints_by_roi.get(roi_id, []),
                         key=lambda e: int(_txt(e, "OrderNumber")))
            if len(pts) == 4:
                acq.roi_points_um = tuple(
                    (float(_txt(p, "SlideXPosUm")), float(_txt(p, "SlideYPosUm"))) for p in pts)
            pano_id = roi_to_pano.get(roi_id)
            if pano_id is not None:
                sid = pano_to_slide.get(pano_id)

        if sid is None:
            sid = next(iter(slides), None)
        if sid in slides:
            slides[sid].acquisitions.append(acq)

    for sl in slides.values():
        sl.acquisitions.sort(key=lambda a: a.id)
    return [slides[k] for k in sorted(slides)]

class MCDFile:
    def __init__(self, path):
        self.path = Path(path)
        self._fh = None
        self._slides: Optional[List[Slide]] = None

    def open(self) -> "MCDFile":
        if self._fh is None:
            self._fh = self.path.open("rb")
        if self._slides is None:
            self._slides = _parse(_read_schema_xml(self.path))
        return self

    def close(self) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None

    def __enter__(self) -> "MCDFile":
        return self.open()

    def __exit__(self, *exc) -> None:
        self.close()

    @property
    def slides(self) -> List[Slide]:
        if self._slides is None:
            self.open()
        return self._slides

    def read_panorama(self, panorama: Panorama) -> Optional[np.ndarray]:
        from io import BytesIO
        from PIL import Image

        try:
            start = int(panorama.metadata["ImageStartOffset"])
            end = int(panorama.metadata["ImageEndOffset"])
        except (KeyError, ValueError):
            return None
        if start == end == 0:
            return None
        start += 161
        end -= 1
        if start >= end:
            return None
        self.open()
        self._fh.seek(start)
        data = self._fh.read(end - start)
        prev, Image.MAX_IMAGE_PIXELS = Image.MAX_IMAGE_PIXELS, None
        try:
            with Image.open(BytesIO(data)) as im:
                if im.mode == "P":
                    im = im.convert("RGBA" if "transparency" in im.info else "RGB")
                elif im.mode in ("1", "L", "I;16", "I"):
                    im = im.convert("RGB")
                elif im.mode == "LA":
                    im = im.convert("RGBA")
                return np.asarray(im)
        finally:
            Image.MAX_IMAGE_PIXELS = prev

# ---------------------- Acquisition pixel data ----------------------

_VALUE_DTYPE = {2: np.float16, 4: np.float32, 8: np.float64}

def _ramp(n: int, dt):
    return np.arange(n, dtype=dt)

def _ramp_from(start: int, n: int, dt):
    return np.arange(start, start + n, dtype=dt)

_BAND_BYTES = 1 * 2 ** 20
_SCATTER_BLOCK_BYTES = 128 * 2 ** 20

class _VerificationFailed(Exception):
    pass

def _read_fast(path, data_start, width, height, num_channels, stride, bpp,
               value_dtype, out_dtype, img, band_rows, threads, ch0=0):
    edges = [int(round(i * height / threads)) for i in range(threads + 1)]
    x_ramp = _ramp(width, value_dtype)

    def worker(k):
        r0, r1 = edges[k], edges[k + 1]
        if r0 >= r1:
            return
        with open(path, "rb") as fh:
            fh.seek(data_start + r0 * width * bpp)
            row = r0
            while row < r1:
                rows = min(band_rows, r1 - row)
                want = rows * width * bpp
                raw = fh.read(want)
                if len(raw) < want:
                    raise _VerificationFailed("short read")
                block = np.frombuffer(raw, dtype=value_dtype,
                                      count=rows * width * stride).reshape(rows * width, stride)
                if not (np.array_equal(block[:, 0], np.tile(x_ramp, rows))
                        and np.array_equal(block[:, 1],
                                           np.repeat(_ramp_from(row, rows, value_dtype), width))):
                    raise _VerificationFailed("row %d" % row)
                vals = block[:, 3 + ch0:3 + ch0 + num_channels]
                if out_dtype == np.uint16:
                    vals = np.clip(vals, 0, 65535).astype(np.uint16)
                img[:, row:row + rows, :] = vals.T.reshape(num_channels, rows, width)
                row += rows

    if threads == 1:
        worker(0)
        return
    with ThreadPoolExecutor(threads) as ex:
        futs = [ex.submit(worker, k) for k in range(threads)]
        for f in futs:
            f.result()

def _scatter_block(block, width, height, out_dtype, img, threads, ch0=0):
    xs = block[:, 0].astype(np.int32)
    ys = block[:, 1].astype(np.int32)
    ok = (xs >= 0) & (xs < width) & (ys >= 0) & (ys < height)
    if not ok.all():
        xs, ys, block = xs[ok], ys[ok], block[ok]

    n_ch = img.shape[0]

    def put(sel_xs, sel_ys, sel_block):
        vals = sel_block[:, 3 + ch0:3 + ch0 + n_ch]
        if out_dtype == np.uint16:
            vals = np.clip(vals, 0, 65535).astype(np.uint16)
        img[:, sel_ys, sel_xs] = vals.T

    threads = 1

    if threads == 1 or ys.size < 200_000:
        put(xs, ys, block)
        return

    edges = [int(round(i * height / threads)) for i in range(threads + 1)]

    def worker(k):
        r0, r1 = edges[k], edges[k + 1]
        if r0 >= r1:
            return
        m = (ys >= r0) & (ys < r1)
        if m.any():
            put(xs[m], ys[m], block[m])

    with ThreadPoolExecutor(threads) as ex:
        futs = [ex.submit(worker, k) for k in range(threads)]
        for f in futs:
            f.result()

def read_acquisition(path, acq, strict: bool = True, out_dtype=np.float32,
                     max_bytes: int = _BAND_BYTES, threads: Optional[int] = None,
                     channels: Optional[Tuple[int, int]] = None) -> np.ndarray:
    """Read one acquisition into a (C, H, W) array."""
    md = acq.metadata
    data_start, data_end = int(md["DataStartOffset"]), int(md["DataEndOffset"])
    value_bytes = int(md.get("ValueBytes", 4))
    value_dtype = _VALUE_DTYPE.get(value_bytes)
    if value_dtype is None:
        raise OSError(
            "Unsupported ValueBytes=%d for '%s' (expected 2, 4, or 8)"
            % (value_bytes, acq.description))

    width, height = int(md["MaxX"]), int(md["MaxY"])
    total_channels = acq.num_channels
    ch0, ch1 = (0, total_channels) if channels is None else channels
    if not (0 <= ch0 < ch1 <= total_channels):
        raise ValueError(f"channels {channels!r} outside 0..{total_channels}")
    num_channels = ch1 - ch0
    stride = total_channels + 3
    bpp = stride * value_bytes
    data_size = data_end - data_start

    if data_size % bpp != 0 and strict:
        raise OSError("Acquisition data size mismatch for '%s'" % acq.description)

    num_pixels = data_size // bpp
    img = np.zeros((num_channels, height, width), dtype=out_dtype)

    if threads is None:
        threads = max(1, min(8, (os.cpu_count() or 4) // 3))

    fast_ok = (num_pixels == width * height and
               (value_dtype is not np.float16 or max(width, height) <= 2048))

    if fast_ok:
        band_rows = max(1, (max_bytes // bpp) // width)
        try:
            _read_fast(path, data_start, width, height, num_channels, stride, bpp,
                       value_dtype, out_dtype, img, band_rows, threads, ch0)
            return img
        except _VerificationFailed:
            img[...] = 0

    # -------- Scatter fallback --------
    rows_per_block = max(1, _SCATTER_BLOCK_BYTES // bpp)
    with open(path, "rb") as fh:
        fh.seek(data_start)
        remaining = num_pixels
        while remaining:
            n = min(rows_per_block, remaining)
            raw = fh.read(n * bpp)
            got = len(raw) // bpp
            if got == 0:
                break
            if got < n:
                if strict:
                    raise OSError("Truncated acquisition data for '%s'" % acq.description)
                n = got
            block = np.frombuffer(raw, dtype=value_dtype, count=n * stride).reshape(n, stride)
            _scatter_block(block, width, height, out_dtype, img, threads, ch0)
            remaining -= n
    return img