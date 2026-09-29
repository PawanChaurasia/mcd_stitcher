# ---------------------- Imports ----------------------
import click
import numpy as np

from contextlib import nullcontext
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import List, Optional

from skimage.draw import polygon

from ._mcdread import MCDFile, read_acquisition
from .fastio import channel_group, work_budget, write_planes_fast, set_memory_limit
from .helper_utils import (PathLike, as_path, compute_canvas_bounds, ome_xml_builder, make_dir,
                           load_rois, validate_mcd_file, parse_index_string)

# ---------------------- ROI filtering ----------------------

def apply_roi_filter(rois: List[dict], roi_arg) -> List[dict]:
    if roi_arg is None:
        return rois

    indices = parse_index_string(roi_arg, max_idx=len(rois) - 1)
    if indices is None:
        return rois

    return [rois[i] for i in indices]

# ---------------------- Canvas compositing ----------------------

_SLABS_IN_FLIGHT = 2

# ---------------------- Python API ----------------------

def mcd_stitch(
    input_path: PathLike,
    output_path: Optional[PathLike] = None,
    dtype: str = "uint16",
    compression: str = "zstd",
    roi_arg: Optional[str] = None,
    out_dir: Optional[PathLike] = None,
    silent: bool = False,
    mcd: Optional[MCDFile] = None,
    all_rois: Optional[List[dict]] = None,
    selected_rois: Optional[List[dict]] = None,
    convert_out_dir: Optional[PathLike] = None,
) -> int:
    """Stitch selected ROIs from MCD into a single stitched canvas OME-TIFF.

    Args:
        input_path: Path to .mcd file.
        output_path: Optional base output path (used for standalone CLI).
        dtype: "uint16" or "float32".
        compression: "zstd" | "LZW" | "None".
        roi_arg: ROI filter. None | "0,2,5" | "3,5-6,2".
        out_dir: Explicit output directory (used when called from mcd_process).
        silent: Suppress status prints (used when called from mcd_process).
        mcd: Pre-opened MCDFile (used when called from mcd_process).
        all_rois: Pre-loaded ROI list (used when called from mcd_process). Newest first, as
            load_rois returns it.
        selected_rois: Pre-filtered ROI list (used when called from mcd_process), composited
            in the order given.
        convert_out_dir: If set, also write each ROI's own OME-TIFF here from the SAME read that
            feeds the canvas. `mcd_process --convert --stitch` used to read every acquisition
            twice; with this it reads once.

    Returns:
        Number of ROIs stitched (0 if no ROIs are found or selected).
    """
    input_path, output_path = as_path(input_path), as_path(output_path)
    out_dir, convert_out_dir = as_path(out_dir), as_path(convert_out_dir)
    with (nullcontext(mcd) if mcd is not None else MCDFile(input_path)) as mcd:
        if all_rois is None:
            all_rois = load_rois(mcd)

        if not all_rois:
            if not silent:
                print(f"  SKIPPED: No ROIs found in {input_path}")
            return 0

        if selected_rois is None:
            selected_rois = apply_roi_filter(all_rois, roi_arg)

        if not selected_rois:
            if not silent:
                print("  SKIPPED: No ROIs selected for stitching")
            return 0

        stem = input_path.stem
        if not out_dir:
            out_dir = output_path if output_path else input_path.parent / "MCD_Stitched"

        stitch_path = out_dir / f"{stem}_stitched.ome.tiff"
        channel_labels = selected_rois[0]["channel_labels"]

        selected_rois, min_x_um, max_x_um, min_y_um, max_y_um = compute_canvas_bounds(selected_rois)

        canvas_width_um = max_x_um - min_x_um
        canvas_height_um = max_y_um - min_y_um
        global_px = min(px for r in selected_rois for px in r["pixel_size"])

        canvas_width_px = int(np.ceil(canvas_width_um / global_px))
        canvas_height_px = int(np.ceil(canvas_height_um / global_px))
        channels = selected_rois[0]["num_channels"]

        np_dtype = np.uint16 if dtype == "uint16" else np.float32
        ome_dtype = "uint16" if dtype == "uint16" else "float"
        def _needs_resize(r):
            px_x, px_y = r["pixel_size"]
            return not (np.isclose(px_x, global_px) and np.isclose(px_y, global_px))

        def _dtype_for(r):
            return np.float32 if (_needs_resize(r) or dtype != "uint16") else np.uint16

        def _read(task):
            r, c_lo, c_hi = task
            dt = _dtype_for(r)
            kw = {"out_dtype": dt, "threads": 1}
            if (c_lo, c_hi) != (0, r["num_channels"]):
                kw["channels"] = (c_lo, c_hi)
            try:
                return read_acquisition(input_path, r["acq"], strict=True, **kw)
            except OSError:
                if not silent:
                    print(f"  Warning: strict read failed for {r['description']}. "
                          f"Retrying in recovery mode.")
                return read_acquisition(input_path, r["acq"], strict=False, **kw)

        # -------- Channel-slab sizing --------
        def _roi_out_hw(r):
            """This ROI's height and width once placed on the global grid."""
            acq = r["acq"]
            px_x, px_y = r["pixel_size"]
            return (int(np.ceil((acq.height_px or 1) * px_y / global_px)),
                    int(np.ceil((acq.width_px or 1) * px_x / global_px)))

        def _roi_channel_bytes(r):
            """Peak bytes one channel of this ROI occupies while it is being placed."""
            acq = r["acq"]
            h, w = acq.height_px or 1, acq.width_px or 1
            if not _needs_resize(r):
                return h * w * np.dtype(_dtype_for(r)).itemsize
            oh, ow = _roi_out_hw(r)
            return h * w * 4 + oh * ow * (8 + np.dtype(np_dtype).itemsize)

        plane_bytes = canvas_height_px * canvas_width_px * np.dtype(np_dtype).itemsize
        covered_px = sum(oh * ow for oh, ow in map(_roi_out_hw, selected_rois))
        plane_touched = min(plane_bytes, covered_px * np.dtype(np_dtype).itemsize)
        roi_ch_bytes = max(_roi_channel_bytes(r) for r in selected_rois)
        budget = max(256 * 2 ** 20, work_budget() - covered_px)
        rois_in_flight = 2 if len(selected_rois) > 1 else 1
        if channels * (plane_touched + rois_in_flight * roi_ch_bytes) <= budget:
            slab = channels
        else:
            per_channel = _SLABS_IN_FLIGHT * plane_touched + rois_in_flight * roi_ch_bytes
            slab = max(1, min(channels, int(budget // max(per_channel, 1))))
            slab = -(-channels // -(-channels // slab))
        n_passes = -(-channels // slab)
        if slab < channels:
            print(f"  Canvas is {channels * plane_bytes / 2**30:.1f} GB; compositing in "
                  f"{n_passes} passes of {slab} channel(s) "
                  f"(memory budget {budget / 2**30:.1f} GB)")

        if convert_out_dir is not None:
            make_dir(convert_out_dir)
        writer_pool = ThreadPoolExecutor(2) if convert_out_dir is not None else None
        writes = []

        def _emit_convert(r, arr):
            acq = r["acq"]
            path = convert_out_dir / f"{r['file_stem']}.ome.tiff"
            xml = ome_xml_builder(
                channel_names=acq.channel_labels,
                size_x=acq.width_px,
                size_y=acq.height_px,
                pixel_type={"uint16": "uint16", "float32": "float"}[dtype],
                tiff_name=path.name,
                image_id=f"Image:{acq.id}",
                image_name=acq.description,
                pixels_id=f"Pixels:{acq.id}",
                channel_id_prefix=f"Channel:{acq.id}:",
                physical_x=float(acq.metadata.get("AblationDistanceBetweenShotsX", 1.0)),
                physical_y=float(acq.metadata.get("AblationDistanceBetweenShotsY", 1.0)),
            )
            write_planes_fast(path, xml, (arr[i] for i in range(arr.shape[0])),
                              compression, dtype, maxworkers=4)

        def _emit_convert_grouped(r):
            """Convert output for an ROI whose channels are not all in hand: stream it in groups."""
            acq = r["acq"]
            n_ch = r["num_channels"]
            out_np = np.uint16 if dtype == "uint16" else np.float32
            per_ch = (acq.width_px or 1) * (acq.height_px or 1) * np.dtype(out_np).itemsize
            grp = channel_group(n_ch, per_ch, budget=work_budget())

            def planes():
                for c0 in range(0, n_ch, grp):
                    kw = {"out_dtype": out_np, "threads": 1,
                          "channels": (c0, min(c0 + grp, n_ch))}
                    try:
                        sub = read_acquisition(input_path, acq, strict=True, **kw)
                    except OSError:
                        if not silent:
                            print(f"  Warning: strict read failed for {acq.description}. "
                                  f"Retrying in recovery mode.")
                        sub = read_acquisition(input_path, acq, strict=False, **kw)
                    for k in range(sub.shape[0]):
                        yield sub[k]
                    del sub

            path = convert_out_dir / f"{r['file_stem']}.ome.tiff"
            xml = ome_xml_builder(
                channel_names=acq.channel_labels, size_x=acq.width_px, size_y=acq.height_px,
                pixel_type={"uint16": "uint16", "float32": "float"}[dtype],
                tiff_name=path.name, image_id=f"Image:{acq.id}", image_name=acq.description,
                pixels_id=f"Pixels:{acq.id}", channel_id_prefix=f"Channel:{acq.id}:",
                physical_x=float(acq.metadata.get("AblationDistanceBetweenShotsX", 1.0)),
                physical_y=float(acq.metadata.get("AblationDistanceBetweenShotsY", 1.0)),
            )
            write_planes_fast(path, xml, planes(), compression, dtype, maxworkers=4)

        _geom_cache = {}

        def _roi_geom(r):
            g = _geom_cache.get(id(r))
            if g is not None:
                return g
            px_x, px_y = r["pixel_size"]
            h_new, w_new = _roi_out_hw(r)
            on_grid = np.isclose(px_x, global_px) and np.isclose(px_y, global_px)

            roi = r["roi_translated"]
            xs_r = np.array([x for x, _ in roi])
            ys_r = np.array([y for _, y in roi])
            min_x_roi, min_y_roi = xs_r.min(), ys_r.min()

            canvas_x = int(round(min_x_roi / global_px))
            canvas_y = canvas_height_px - int(round(min_y_roi / global_px)) - h_new
            y0, y1 = max(0, canvas_y), min(canvas_height_px, canvas_y + h_new)
            x0, x1 = max(0, canvas_x), min(canvas_width_px, canvas_x + w_new)
            h_slice, w_slice = y1 - y0, x1 - x0

            poly_x = (xs_r - min_x_roi) / global_px
            poly_y = (ys_r - min_y_roi) / global_px
            rr, cc = polygon(poly_y, poly_x, (h_new, w_new))
            full = np.zeros((h_new, w_new), bool)
            full[rr, cc] = True
            del rr, cc
            mask = full[:h_slice, :w_slice].copy()
            del full

            g = (h_new, w_new, on_grid, mask, y0, y1, x0, x1, h_slice, w_slice)
            _geom_cache[id(r)] = g
            return g

        def _place(dest, r, img):
            """Composite one ROI's channel slice into `dest`, whose channel axis matches img."""
            h_new, w_new, on_grid, mask, y0, y1, x0, x1, h_slice, w_slice = _roi_geom(r)
            C = img.shape[0]

            if on_grid:
                planes = None
            else:
                from skimage.transform import resize
                planes = [
                    resize(img[c], (h_new, w_new), order=1, mode='reflect',
                           preserve_range=True, anti_aliasing=True)
                    for c in range(C)
                ]

            if on_grid and img.dtype == np_dtype:
                resized = img
            elif on_grid:
                resized = (np.clip(img, 0, 65535).astype(np.uint16) if dtype == "uint16"
                           else img.astype(np.float32, copy=False))
            elif dtype == "uint16":
                resized = np.stack([np.clip(p, 0, 65535).astype(np.uint16) for p in planes])
            else:
                resized = np.stack([p.astype(np.float32) for p in planes])

            del planes

            roi_block = resized[:, :h_slice, :w_slice]
            where = mask[np.newaxis] & (roi_block > 0)
            np.copyto(dest[:, y0:y1, x0:x1], roi_block, where=where)

        fuse_convert = writer_pool is not None and slab >= channels

        def _composite_slab(c_lo, c_hi):
            """Every ROI placed into one (c_hi - c_lo, H, W) canvas slab, in ROI order."""
            dest = np.zeros((c_hi - c_lo, canvas_height_px, canvas_width_px), np_dtype)
            with ThreadPoolExecutor(1) as reader:
                pending = reader.submit(_read, (selected_rois[0], c_lo, c_hi))
                for i, r in enumerate(selected_rois):
                    img = pending.result()
                    if i + 1 < len(selected_rois):
                        pending = reader.submit(_read, (selected_rois[i + 1], c_lo, c_hi))

                    if fuse_convert:
                        while len(writes) >= 2:
                            writes.pop(0).result()
                        writes.append(writer_pool.submit(_emit_convert, r, img))

                    _place(dest, r, img)
                    del img
            return dest

        def _canvas_planes():
            """Canvas planes in channel order, one slab resident at a time."""
            for c0 in range(0, channels, slab):
                dest = _composite_slab(c0, min(c0 + slab, channels))
                for k in range(dest.shape[0]):
                    yield dest[k]
                del dest

        try:
            make_dir(out_dir)

            ome_xml = ome_xml_builder(
                channel_names=channel_labels,
                size_x=canvas_width_px,
                size_y=canvas_height_px,
                pixel_type=ome_dtype,
                tiff_name=stitch_path.name,
                image_id='Image:Stitched',
                image_name=stitch_path.name,
                pixels_id='Pixels:Stitched',
                channel_id_prefix='Channel:Stitched:',
                physical_x=global_px,
                physical_y=global_px,
            )

            write_planes_fast(stitch_path, ome_xml, _canvas_planes(), compression, dtype)

            for f in writes:
                f.result()

            if writer_pool is not None and not fuse_convert:
                for r in selected_rois:
                    _emit_convert_grouped(r)
        finally:
            if writer_pool is not None:
                writer_pool.shutdown(wait=True)

    if not silent:
        print(f"  Processed {input_path.name}: {len(selected_rois)} ROIs stitched")
    return len(selected_rois)

# ---------------------- CLI ----------------------

@click.command(name='mcd_stitch')
@click.option('-d', '--output_type', type=click.Choice(['uint16', 'float32'], case_sensitive=True), default='uint16', metavar='TYPE', help="Output type (uint16 / float32).")
@click.option('-c', '--compression', type=click.Choice(['None', 'LZW', 'zstd'], case_sensitive=True), default='zstd', metavar='TYPE', help="Compression mode (none / LZW / zstd).")
@click.option('-r', '--roi', default=None, type=str, help="Stitch specified ROIs (e.g. '0-5,7,10').")
@click.option("--max-memory", "max_memory", default=None, metavar="SIZE", help="Cap memory for image buffers, e.g. '8G'. Overrides the detected limit; required only where none can be detected.")
@click.argument('input_path', type=click.Path(exists=True, dir_okay=False, path_type=Path), callback=validate_mcd_file)
@click.argument('output_path', type=click.Path(exists=False, path_type=Path), required=False)

def main(output_type, compression, roi, input_path, output_path, max_memory):
    if max_memory:
        set_memory_limit(max_memory)
    mcd_stitch(
        input_path=input_path,
        output_path=output_path,
        dtype=output_type,
        compression=compression,
        roi_arg=roi,
    )

if __name__ == '__main__':
    main()
