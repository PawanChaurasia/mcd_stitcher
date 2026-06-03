# ---------------------- Imports ----------------------
import click
import numpy as np

from pathlib import Path
from typing import List, Optional

from PIL import Image
from readimc import MCDFile
from skimage.draw import polygon
from skimage.transform import resize

from .helper_utils import compute_canvas_bounds, ome_xml_builder, make_dir, read_acquisition_chunked, load_rois, validate_mcd_file, parse_index_string, write_planes

Image.MAX_IMAGE_PIXELS = None


# ---------------------- ROI Filtering ----------------------

def apply_roi_filter(rois: List[dict], roi_arg) -> List[dict]:
    if roi_arg is None:
        return rois

    indices = parse_index_string(roi_arg, max_idx=len(rois) - 1)
    if indices is None:
        return rois

    return [rois[i] for i in indices]


# ---------------------- Python API ----------------------

def mcd_stitch(
    input_path: Path,
    output_path: Optional[Path] = None,
    dtype: str = "uint16",
    compression: str = "zstd",
    roi_arg: Optional[str] = None,
    out_dir: Optional[Path] = None,
    silent: bool = False,
    mcd: Optional[MCDFile] = None,
    all_rois: Optional[List[dict]] = None,
    selected_rois: Optional[List[dict]] = None,
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
        all_rois: Pre-loaded ROI list (used when called from mcd_process).
        selected_rois: Pre-filtered ROI list (used when called from mcd_process).

    Returns:
        Number of ROIs stitched (0 if no ROIs are found or selected).
    """
    close_mcd = False
    if mcd is None:
        mcd = MCDFile(input_path)
        mcd.__enter__()
        close_mcd = True

    if all_rois is None:
        try:
            all_rois = load_rois(mcd)
        except Exception:
            if close_mcd:
                mcd.__exit__(None, None, None)
            raise

    if not all_rois:
        if close_mcd:
            mcd.__exit__(None, None, None)
        if not silent:
            print(f"  SKIPPED: No ROIs found in {input_path}")
        return 0

    if selected_rois is None:
        selected_rois = apply_roi_filter(all_rois, roi_arg)

    if not selected_rois:
        if close_mcd:
            mcd.__exit__(None, None, None)
        if not silent:
            print(f"  SKIPPED: No ROIs selected for stitching")
        return 0

    stem = input_path.stem

    if not out_dir:
        if output_path:
            out_dir = output_path
        else:
            out_dir = input_path.parent / "MCD_Stitched"

    stitch_path = out_dir / f"{stem}_stitched.ome.tiff"
    channel_labels = selected_rois[0]["channel_labels"]

    selected_rois, min_x_um, max_x_um, min_y_um, max_y_um = compute_canvas_bounds(selected_rois)

    canvas_width_um = max_x_um - min_x_um
    canvas_height_um = max_y_um - min_y_um
    global_px = min(px for r in selected_rois for px in r["pixel_size"])

    canvas_width_px = int(np.ceil(canvas_width_um / global_px))
    canvas_height_px = int(np.ceil(canvas_height_um / global_px))

    channels = selected_rois[0]["num_channels"]

    if dtype == "uint16":
        canvas = np.zeros((channels, canvas_height_px, canvas_width_px), np.uint16)
        ome_dtype = "uint16"
    else:
        canvas = np.zeros((channels, canvas_height_px, canvas_width_px), np.float32)
        ome_dtype = "float"

    for r in selected_rois:
        try:
            img = read_acquisition_chunked(mcd._fh, r["acq"], strict=True)
        except OSError:
            if not silent:
                print(f"  Warning: strict read failed for {r['description']}. Retrying in recovery mode.")
            img = read_acquisition_chunked(mcd._fh, r["acq"], strict=False)

        roi = r["roi_translated"]
        px_x, px_y = r["pixel_size"]
        C, h, w = img.shape

        scale_x = px_x / global_px
        scale_y = px_y / global_px
        h_new = int(np.ceil(h * scale_y))
        w_new = int(np.ceil(w * scale_x))

        # Resize to the global grid when the ROI resolution differs.
        if np.isclose(px_x, global_px) and np.isclose(px_y, global_px):
            planes = [img[c] for c in range(C)]
        else:
            planes = [
                resize(
                    img[c],
                    (h_new, w_new),
                    order=1, mode='reflect',
                    preserve_range=True, anti_aliasing=True,
                )
                for c in range(C)
            ]

        # Clip to the output range before casting, matching mcd_convert.
        if dtype == "uint16":
            resized = np.stack([np.clip(p, 0, 65535).astype(np.uint16) for p in planes])
        else:
            resized = np.stack([p.astype(np.float32) for p in planes])

        del img, planes

        xs_r = np.array([x for x, _ in roi])
        ys_r = np.array([y for _, y in roi])
        min_x_roi, min_y_roi = xs_r.min(), ys_r.min()

        poly_x = (xs_r - min_x_roi) / global_px
        poly_y = (ys_r - min_y_roi) / global_px
        rr, cc = polygon(poly_y, poly_x, (h_new, w_new))
        mask = np.zeros((h_new, w_new), bool)
        mask[rr, cc] = True

        canvas_x = int(round(min_x_roi / global_px))
        canvas_y = canvas_height_px - int(round(min_y_roi / global_px)) - h_new

        y0, y1 = max(0, canvas_y), min(canvas_height_px, canvas_y + h_new)
        x0, x1 = max(0, canvas_x), min(canvas_width_px, canvas_x + w_new)
        h_slice = y1 - y0
        w_slice = x1 - x0

        for c in range(C):
            roi_slice = resized[c, :h_slice, :w_slice]
            canvas_slice = canvas[c, y0:y1, x0:x1]
            mask_slice = mask[:h_slice, :w_slice]
            valid_pixels = mask_slice & (roi_slice > 0)
            canvas_slice[valid_pixels] = roi_slice[valid_pixels]

        del resized

    make_dir(out_dir)

    ome_xml = ome_xml_builder(
        channel_names=channel_labels,
        size_x=canvas.shape[2],
        size_y=canvas.shape[1],
        pixel_type=ome_dtype,
        tiff_name=stitch_path.name,
        image_id='Image:Stitched',
        image_name=stitch_path.name,
        pixels_id='Pixels:Stitched',
        channel_id_prefix='Channel:Stitched:',
        physical_x=global_px,
        physical_y=global_px,
    )

    write_planes(
        stitch_path, ome_xml,
        (canvas[c] for c in range(canvas.shape[0])),
        compression, dtype, tile=(256, 256),
    )
    del canvas

    if close_mcd:
        mcd.__exit__(None, None, None)
    if not silent:
        print(f"  Processed {input_path.name}: {len(selected_rois)} ROIs stitched")
    return len(selected_rois)


# ---------------------- CLI ----------------------

@click.command(name='mcd_stitch')
@click.option('-d', '--output_type', type=click.Choice(['uint16', 'float32'], case_sensitive=True), default='uint16', metavar='TYPE', help="Output type (uint16 / float32).")
@click.option('-c', '--compression', type=click.Choice(['None', 'LZW', 'zstd'], case_sensitive=True), default='zstd', metavar='TYPE', help="Compression mode (none / LZW / zstd).")
@click.option('-r', '--roi', default=None, type=str, help="Stitch specified ROIs (e.g. '0-5,7,10').")
@click.argument('input_path', type=click.Path(exists=True, dir_okay=False, path_type=Path), callback=validate_mcd_file)
@click.argument('output_path', type=click.Path(exists=False, path_type=Path), required=False)

def main(output_type, compression, roi, input_path, output_path):
    mcd_stitch(
        input_path=input_path,
        output_path=output_path,
        dtype=output_type,
        compression=compression,
        roi_arg=roi,
    )


if __name__ == '__main__':
    main()
