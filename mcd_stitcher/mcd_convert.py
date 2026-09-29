# ---------------------- Imports ----------------------
import os
import click

from contextlib import nullcontext
from pathlib import Path
from typing import List, Optional
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from ._mcdread import MCDFile, read_acquisition
from .fastio import channel_group, plan_workers, work_budget, write_planes_fast, set_memory_limit
from .helper_utils import (PathLike, as_path, ome_xml_builder, make_dir, load_rois,
                           validate_mcd_file)

# ---------------------- Python API ----------------------

def _convert_one(input_path: Path, roi_meta: dict, out_dir: Path, dtype: str,
                 compression: str, out_np, writer_workers: int, silent: bool,
                 read_block: int, roi_budget: int) -> int:
    """Read one acquisition and write its OME-TIFF. Self-contained so it can run on a worker."""
    acq = roi_meta["acq"]
    tiff_path = out_dir / f"{roi_meta['file_stem']}.ome.tiff"

    def _read(c0=None, c1=None):
        kw = dict(max_bytes=read_block, threads=1)
        if c0 is not None:
            kw["channels"] = (c0, c1)
        try:
            return read_acquisition(input_path, acq, strict=True, out_dtype=out_np, **kw)
        except OSError:
            if not silent:
                print(f"  Warning: strict read failed for {acq.description}. "
                      f"Retrying in recovery mode.")
            return read_acquisition(input_path, acq, strict=False, out_dtype=out_np, **kw)

    n_ch = acq.num_channels
    per_channel = (acq.width_px or 1) * (acq.height_px or 1) * np.dtype(out_np).itemsize
    group = channel_group(n_ch, per_channel, budget=roi_budget)

    ome_xml = ome_xml_builder(
        channel_names=acq.channel_labels,
        size_x=acq.width_px,
        size_y=acq.height_px,
        pixel_type={"uint16": "uint16", "float32": "float"}[dtype],
        tiff_name=tiff_path.name,
        image_id=f"Image:{acq.id}",
        image_name=acq.description,
        pixels_id=f"Pixels:{acq.id}",
        channel_id_prefix=f"Channel:{acq.id}:",
        physical_x=float(acq.metadata.get("AblationDistanceBetweenShotsX", 1.0)),
        physical_y=float(acq.metadata.get("AblationDistanceBetweenShotsY", 1.0)),
    )

    if group >= n_ch:
        img = _read()
        planes = (img[i] for i in range(img.shape[0]))
    else:
        print(f"  {acq.description}: {n_ch}ch x {per_channel / 2**20:.1f} MB "
              f"({n_ch * per_channel / 2**30:.1f} GB) exceeds the memory budget; "
              f"reading in groups of {group}")
        img = None

        def planes():
            for c0 in range(0, n_ch, group):
                sub = _read(c0, min(c0 + group, n_ch))
                for i in range(sub.shape[0]):
                    yield sub[i]
                del sub
        planes = planes()

    write_planes_fast(tiff_path, ome_xml, planes, compression, dtype,
                      maxworkers=writer_workers)
    del img
    return 1

def mcd_convert(
    input_path: PathLike,
    output_path: Optional[PathLike] = None,
    dtype: str = "uint16",
    compression: str = "zstd",
    out_dir: Optional[PathLike] = None,
    silent: bool = False,
    mcd: Optional[MCDFile] = None,
    rois: Optional[List[dict]] = None,
    workers: Optional[int] = None,
) -> int:
    """Per-ROI conversion from MCD to OME-TIFF.

    Args:
        input_path: Path to a single .mcd file.
        output_path: Optional base output directory (used for standalone CLI).
        dtype: "uint16" or "float32".
        compression: "zstd" | "LZW" | "None".
        out_dir: Explicit output directory (used when called from mcd_process).
        silent: Suppress status prints (used when called from mcd_process).
        mcd: Pre-opened MCDFile (used when called from mcd_process).
        rois: Pre-loaded ROI list (used when called from mcd_process).
        workers: Override the automatic ROI concurrency.

    Returns:
        Number of ROIs converted (0 if the MCD has no ROIs).
    """
    input_path, output_path, out_dir = (as_path(input_path), as_path(output_path),
                                       as_path(out_dir))
    with (nullcontext(mcd) if mcd is not None else MCDFile(input_path)) as mcd:
        if rois is None:
            rois = load_rois(mcd)

        if not rois:
            if not silent:
                print(f"  SKIPPED: No ROIs found in {input_path}")
            return 0

        stem = input_path.stem
        if not out_dir and output_path:
            out_dir = output_path / stem
        elif not out_dir:
            out_dir = input_path.parent / "MCD_Converted" / stem

        out_np = np.uint16 if dtype == "uint16" else np.float32
        make_dir(out_dir)

        bpp = 2 if dtype == "uint16" else 4
        biggest = max((r["acq"].width_px or 1) * (r["acq"].height_px or 1) *
                      (r["acq"].num_channels or 1) * bpp for r in rois)
        n_workers = workers or plan_workers(
            len(rois), bytes_per_task=int(biggest * 1.25) + 96 * 2 ** 20)
        writer_workers = max(1, min(8, (os.cpu_count() or 4) // max(1, n_workers)))
        read_block = 1 * 2 ** 20
        roi_budget = max(256 * 2 ** 20, work_budget() // max(1, n_workers))

        if n_workers == 1:
            for r in rois:
                _convert_one(input_path, r, out_dir, dtype, compression, out_np, 8, silent,
                             read_block, roi_budget)
        else:
            with ThreadPoolExecutor(n_workers) as ex:
                list(ex.map(
                    lambda r: _convert_one(input_path, r, out_dir, dtype, compression,
                                           out_np, writer_workers, silent, read_block,
                                           roi_budget), rois))

    if not silent:
        print(f"  Processed {input_path.name}: {len(rois)} ROI(s) converted")

    return len(rois)

# ---------------------- CLI ----------------------

@click.command(name='mcd_convert')
@click.option('-d', '--output_type', type=click.Choice(['uint16', 'float32'], case_sensitive=True), default='uint16', metavar='TYPE', help="Output type (uint16 / float32).")
@click.option('-c', '--compression', type=click.Choice(['None', 'LZW', 'zstd'], case_sensitive=True), default='zstd', metavar='TYPE', help="Compression mode (none / LZW / zstd).")
@click.option('-j', '--workers', type=int, default=None, help="ROI concurrency (default: auto from free RAM and CPU count).")
@click.option("--max-memory", "max_memory", default=None, metavar="SIZE", help="Cap memory for image buffers, e.g. '8G'. Overrides the detected limit; required only where none can be detected.")
@click.argument('input_path', type=click.Path(exists=True, dir_okay=False, path_type=Path), callback=validate_mcd_file)
@click.argument('output_path', type=click.Path(exists=False, path_type=Path), required=False)

def main(output_type, compression, workers, input_path, output_path, max_memory):
    if max_memory:
        set_memory_limit(max_memory)
    mcd_convert(
        input_path=input_path,
        output_path=output_path,
        dtype=output_type,
        compression=compression,
        workers=workers,
    )

if __name__ == '__main__':
    main()
