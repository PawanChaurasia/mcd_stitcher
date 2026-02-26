import numpy as np
from importlib.metadata import version, PackageNotFoundError
from pathlib import Path

try:
    CREATOR = f'MCD_Stitcher v{version("mcd_stitcher")}'
except PackageNotFoundError:
    CREATOR = 'MCD_Stitcher'

def make_dir(path: Path):
    path.mkdir(parents=True, exist_ok=True)

def read_acquisition_chunked(fh, acq, strict=True, chunk_px=50000):
    md = acq.metadata
    data_start, data_end = int(md["DataStartOffset"]), int(md["DataEndOffset"])
    value_bytes = int(md.get("ValueBytes", 4))
    width, height = int(md["MaxX"]), int(md["MaxY"])
    num_channels = acq.num_channels

    stride = num_channels + 3
    bpp = stride * value_bytes
    data_size = data_end - data_start

    if data_size % bpp != 0 and strict:
        raise OSError(f"Acquisition data size mismatch for '{acq.description}'")

    num_pixels = data_size // bpp
    img = np.zeros((num_channels, height, width), dtype=np.float32)

    fh.seek(data_start)
    remaining = num_pixels
    while remaining:
        n = min(chunk_px, remaining)
        raw = fh.read(n * bpp)
        chunk = np.frombuffer(raw, dtype=np.float32).reshape(n, stride)

        xs, ys = chunk[:, 0].astype(int), chunk[:, 1].astype(int)
        valid = (0 <= xs) & (xs < width) & (0 <= ys) & (ys < height)
        xs, ys, chunk = xs[valid], ys[valid], chunk[valid]

        for c in range(num_channels):
            img[c, ys, xs] = chunk[:, c + 3]

        remaining -= n

    return img