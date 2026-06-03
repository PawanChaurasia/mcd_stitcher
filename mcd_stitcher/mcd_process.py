# ---------------------- Imports ----------------------
import re
import math
import time
import click

from pathlib import Path
from readimc import MCDFile
from datetime import datetime
from typing import List, Optional

from .mcd_convert import mcd_convert
from .mcd_stitch import mcd_stitch, apply_roi_filter
from .tiff_subset import tiff_subset
from .helper_utils import (
    resolve_mcd_files, make_dir, load_rois, parse_index_string,
    _resolve_panorama, _panorama_slide_bounds,
    _save_panorama_image, _draw_roi_overlay, _slide_to_panorama_pixel, _panorama_pixel_dims, compute_canvas_bounds,
)

# Panoramas smaller than this (either dimension) are likely JPG thumbnails; skip ROI overlays.
PANORAMA_OVERLAY_MIN_PX = 4000


# ---------------------- Pipeline Orchestration ----------------------

def mcd_process(
    input_path: Path,
    output_path: Optional[Path] = None,
    convert: bool = False,
    stitch: bool = False,
    panorama: Optional[str] = None,
    metadata: bool = False,
    roi_map: Optional[str] = None,
    filter: Optional[str] = None,
    pyramid: bool = False,
    roi: Optional[str] = None,
    output_type: str = "uint16",
    compression: str = "zstd",
) -> None:
    """Unified MCD processing pipeline.

    Orchestrates operations across mcd_convert and mcd_stitch modules.
    Opens each MCD once for light operations (metadata, panorama, roi_map).
    Heavy operations (convert, stitch) delegate to their respective modules.

    Args:
        input_path: Path to .mcd file or directory of .mcd files.
        output_path: Optional base output directory.
        convert: Per-ROI conversion to .ome.tiff.
        stitch: Stitch selected ROIs into one canvas.
        panorama: Export panorama(s). "all" or "1,3-5" index string.
        metadata: Print metadata summary to stdout.
        roi_map: Generate ROI overlay + mapping. "0" or "1,3-5".
        filter: Post-process channel subset, e.g. "0-5,7" (requires convert/stitch).
        pyramid: Post-process to a pyramidal OME-TIFF (requires convert/stitch).
        roi: ROI filter. None | "0,2,5" | "3,5-6,2".
        output_type: "uint16" or "float32".
        compression: "zstd" | "LZW" | "None".
    """


    active_ops = sum([convert, stitch, panorama is not None, metadata, roi_map is not None, filter is not None, pyramid])
    if active_ops == 0:
        raise ValueError("No operation specified. Use --convert, --stitch, -p/--panorama, -m/--metadata, or --roi_map.")

    if (filter or pyramid) and not convert and not stitch:
        raise ValueError("--filter/--pyramid requires --convert or --stitch.")

    mcd_files = resolve_mcd_files(input_path)
    start_all = time.time()

    for mcd_file in mcd_files:
        start_mcd = time.time()
        stem = mcd_file.stem
        print(f"Processing MCD: {mcd_file.name}")

        if output_path:
            out_dir = output_path / stem
        else:
            out_dir = mcd_file.parent / "MCD_Processed" / stem
        make_dir(out_dir)

        mcd = MCDFile(mcd_file)
        mcd.__enter__()

        try:
            rois = load_rois(mcd)
        except Exception:
            mcd.__exit__(None, None, None)
            print(f"  SKIPPED: No ROIs found in {mcd_file}")
            continue

        if not rois:
            mcd.__exit__(None, None, None)
            print(f"  SKIPPED: No ROIs found in {mcd_file}")
            continue

        panoramas = []
        for si, slide in enumerate(mcd.slides):
            pano_list = getattr(slide, 'panoramas', []) or []
            for pi, pano in enumerate(pano_list):
                panoramas.append({
                    "slide_index": si,
                    "index": pi,
                    "slide": slide,
                    "pano": pano,
                })

        channels = rois[0]["channel_labels"]
        all_rois = list(rois)
        selected_rois = apply_roi_filter(rois, roi)

        if metadata:
            _op_metadata(stem, selected_rois, channels, panoramas)

        if panorama is not None:
            print(f"  Exporting {len(panoramas)} panorama(s)... ", end="", flush=True)
            t0 = time.time()
            _op_panorama(mcd, stem, panoramas, all_rois, out_dir, panorama)
            print(f"done ({time.time() - t0:.1f}s)")

        if roi_map is not None:
            if stitch:
                canvas_bounds = compute_canvas_bounds(selected_rois)
                mapped_rois = canvas_bounds[0]
                global_px = min(r["pixel_size"][0] for r in selected_rois)
                _, min_x_um, max_x_um, min_y_um, max_y_um = canvas_bounds
                canvas_px_w = int(math.ceil((max_x_um - min_x_um) / global_px))
                canvas_px_h = int(math.ceil((max_y_um - min_y_um) / global_px))
                canvas_pixel_dims = (canvas_px_w, canvas_px_h)
                _op_roi_map(mcd, stem, panoramas, mapped_rois,
                            canvas_bounds, canvas_pixel_dims, out_dir, roi_map, convert=convert)
            else:
                _op_roi_map(mcd, stem, panoramas, all_rois, None, None, out_dir, roi_map, convert=convert)

        if convert:
            print(f"  Converting {len(selected_rois)} ROI(s)... ", end="", flush=True)
            t0 = time.time()
            mcd_convert(
                input_path=mcd_file,
                out_dir=out_dir,
                dtype=output_type,
                compression=compression,
                silent=True,
                mcd=mcd,
                rois=selected_rois,
            )
            print(f"done ({time.time() - t0:.1f}s)")

        if stitch:
            print(f"  Stitching {len(selected_rois)} ROI(s)... ", end="", flush=True)
            t0 = time.time()
            mcd_stitch(
                input_path=mcd_file,
                out_dir=out_dir,
                dtype=output_type,
                compression=compression,
                silent=True,
                mcd=mcd,
                all_rois=all_rois,
                selected_rois=selected_rois,
            )
            print(f"done ({time.time() - t0:.1f}s)")

        if filter or pyramid:
            produced = []
            if convert:
                produced.extend(out_dir / f"{r['acq'].description}.ome.tiff" for r in selected_rois)
            if stitch:
                produced.append(out_dir / f"{stem}_stitched.ome.tiff")
            if produced:
                print(f"  Post-processing {len(produced)} file(s)... ", end="", flush=True)
                t0 = time.time()
                tiff_subset(
                    tiff_files=produced,
                    out_dir=out_dir,
                    filter=filter,
                    pyramid=pyramid,
                    output_type=output_type,
                    compression=compression,
                    silent=True,
                )
                print(f"done ({time.time() - t0:.1f}s)")

        mcd.__exit__(None, None, None)

        print(f"  Processed {mcd_file.name} in {time.time() - start_mcd:.1f}s")

    print(f"Finished all MCDs in {time.time() - start_all:.1f}s")


# ---------------------- Operation Implementations ----------------------

def _op_metadata(stem: str, rois: List[dict], channels: List[str], panoramas: List[dict]) -> None:
    print(f"\n  MCD FILE: {stem}")

    if panoramas:
        print("\n  PANORAMAS:")
        for idx, p in enumerate(panoramas):
            desc = p['pano'].metadata.get('Description', 'N/A')
            print(f"    {idx}: slide {p['slide_index']}, pano {p['index']}: {desc}")
    print()

    if rois:
        print("  ROI TABLE:")
        print(f"    {'Idx':<4} | {'Description':<35} | {'Timestamp':<19} | {'Size (WxH)':<12}")
        print(f"    {'-'*4}-+-{'-'*35}-+-{'-'*19}-+-{'-'*12}")
        for idx, r in enumerate(rois):
            desc = (r["description"] or "").strip()
            if len(desc) > 35:
                desc = desc[:32] + "..."
            ts = r["timestamp"]
            ts = re.sub(r'(\.\d{6})\d+', r'\1', ts)
            try:
                ts = datetime.fromisoformat(ts).strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                pass
            print(f"    {idx:<4} | {desc:<35} | {ts:<19} | {r['width']:>4}x{r['height']:<4}")

    print(f" \n CHANNELS ({len(channels)}): {', '.join(channels)} \n")


def _op_panorama(mcd, stem: str, panoramas: List[dict], all_rois: List[dict], out_dir: Path, panorama_arg: str) -> None:
    indices = parse_index_string(panorama_arg)
    if indices is None:
        indices = list(range(len(panoramas)))

    for pi in indices:
        if pi >= len(panoramas):
            continue
        p = panoramas[pi]

        try:
            slide = all_rois[0]["slide"]
            pano = _resolve_panorama(slide, pi)
        except (ValueError, RuntimeError):
            continue

        pano_out = out_dir / f"{stem}_slide_{p['slide_index']}_pano_{p['index']}.png"
        pano_w, pano_h = _save_panorama_image(mcd, pano, pano_out)
        pano_bounds = _panorama_slide_bounds(pano)

        # Skip overlay for small panoramas (e.g. embedded JPG thumbnails)
        if all_rois and pano_w >= PANORAMA_OVERLAY_MIN_PX and pano_h >= PANORAMA_OVERLAY_MIN_PX:
            _draw_roi_overlay(
                pano_out, all_rois, pano_bounds, pano_w, pano_h,
                out_dir / f"{stem}_slide_{p['slide_index']}_pano_{p['index']}_overlay.png",
            )


def _op_roi_map(
    mcd, stem: str, panoramas: List[dict], rois: List[dict],
    canvas_bounds: Optional[tuple], canvas_pixel_dims: Optional[tuple],
    out_dir: Path, roi_map_arg: Optional[str], convert: bool = False,
) -> None:
    if not rois:
        return

    indices = parse_index_string(roi_map_arg)
    if indices is None:
        indices = [0]

    for pi in indices:
        if pi >= len(panoramas):
            continue
        p = panoramas[pi]

        try:
            slide = rois[0]["slide"]
            pano = _resolve_panorama(slide, pi)
        except (ValueError, RuntimeError) as e:
            print(f"  WARNING: Could not resolve panorama {pi}: {e}")
            continue

        png_path = out_dir / f"{stem}_slide_{p['slide_index']}_pano_{p['index']}.png"
        pano_w, pano_h = _panorama_pixel_dims(mcd, pano, png_path)
        if pano_w is None:
            print(f"  WARNING: Could not read panorama {pi}")
            continue
        pano_bounds = _panorama_slide_bounds(pano)

        lines = []

        if canvas_bounds is not None:
            _, min_x_um, max_x_um, min_y_um, max_y_um = canvas_bounds
            canvas_px_w, canvas_px_h = canvas_pixel_dims

            canvas_corners_slide = [
                ("top_left", min_x_um, max_y_um),
                ("top_right", max_x_um, max_y_um),
                ("bottom_right", max_x_um, min_y_um),
                ("bottom_left", min_x_um, min_y_um),
            ]

            canvas_corners_pano = []
            for name, sx, sy in canvas_corners_slide:
                px, py = _slide_to_panorama_pixel(sx, sy, pano_bounds, pano_w, pano_h)
                canvas_corners_pano.append((name, px, py))
                
            lines.append("Stitched-ROIs to Panorama Mapping")
            lines.append("=" * 40)
            lines.append("")

            lines.append("stitched_canvas_pixels: {} x {}".format(canvas_px_w, canvas_px_h))
            lines.append("stitched_canvas_slide_um: x_min={:.3f} x_max={:.3f} y_min={:.3f} y_max={:.3f}".format(
                min_x_um, max_x_um, min_y_um, max_y_um,
            ))
            lines.append("panorama_pixels: {} x {}".format(pano_w, pano_h))
            lines.append("panorama_slide_um: x_min={:.1f} x_max={:.1f} y_min={:.1f} y_max={:.1f}".format(
                pano_bounds[0], pano_bounds[1], pano_bounds[2], pano_bounds[3],
            ))
            lines.append("")
            lines.append("corner_mapping (stitched corner -> panorama pixel):")
            for name, px, py in canvas_corners_pano:
                lines.append("  {}: {:.3f}, {:.3f}".format(name, px, py))
            lines.append("")

        if convert or canvas_bounds is None:
            lines.append("Individual-ROIs to Panorama Mapping")
            lines.append("=" * 40)
            lines.append("")

            for i, roi_meta in enumerate(reversed(rois)):
                desc = (roi_meta["description"] or "").strip() or "ROI_{}".format(
                    len(rois) - 1 - i,
                )
                lines.append("--- {} ---".format(desc))
                lines.append("  Dimensions: {}x{} px".format(roi_meta["width"], roi_meta["height"]))
                lines.append("  Pixel size: {:.4f} x {:.4f} um".format(
                    roi_meta["pixel_size"][0], roi_meta["pixel_size"][1],
                ))
                lines.append("  Corners (panorama px):")
                coords = roi_meta["roi_coords"]
                for label, (x, y) in zip(
                    ["top_left", "top_right", "bottom_right", "bottom_left"], coords,
                ):
                    px, py = _slide_to_panorama_pixel(x, y, pano_bounds, pano_w, pano_h)
                    lines.append("    {}: {:.1f}, {:.1f}".format(label, px, py))
                lines.append("")

        out_path = out_dir / "{}_slide_{}_pano_{}_roi_map.txt".format(stem, p['slide_index'], p['index'])
        out_path.write_text("\n".join(lines), encoding="utf-8")


# ---------------------- CLI ----------------------

@click.command(name="mcd_process")
@click.option("--convert", "convert", is_flag=True, default=False, help="Convert all ROIs in MCD into individual OME-TIFF.")
@click.option("--stitch", "stitch", is_flag=True, default=False, help="Convert all ROIs in MCD into a stitched OME-TIFF.")
@click.option("-p", "--panorama", "panorama", flag_value="all", default=None, type=str, help="Export all panoramas with ROI overlay.")
@click.option("-m", "--metadata", "metadata", is_flag=True, default=False, help="Print MCD metadata.")
@click.option("--roi_map", "roi_map", default=None, type=str, help="ROI-to-panorama mapping TXT. Index: '0', '1,3-5'.")
@click.option("-f", "--filter", "filter", default=None, type=str, help="Post-process: keep only these channels, e.g. '0-5,7'. Requires --convert/--stitch.")
@click.option("--pyramid", "pyramid", is_flag=True, default=False, help="Post-process: also write a pyramidal OME-TIFF. Requires --convert/--stitch.")
@click.option("-d", "--output_type", type=click.Choice(["uint16", "float32"], case_sensitive=True), default="uint16", metavar="TYPE", help="Output data type (uint16 / float32).")
@click.option("-c", "--compression", type=click.Choice(["None", "LZW", "zstd"], case_sensitive=True), default="zstd", metavar="TYPE", help="Compression mode (none / LZW / zstd).")
@click.option("-r", "--roi", default=None, type=str, help="Stitch specified ROIs (e.g. '0-5,7,10').")
@click.argument("input_path", type=click.Path(exists=True, path_type=Path))
@click.argument("output_path", type=click.Path(exists=False, path_type=Path), required=False)
@click.pass_context
def _cli_main(ctx, convert, stitch, panorama, metadata, roi_map, filter, pyramid, output_type, compression, roi, input_path, output_path):

    if not convert and not stitch and not panorama and not metadata and roi_map is None and not filter and not pyramid:
        click.echo("Error: No operation specified. Use --convert, --stitch, -p/--panorama, -m/--metadata, or --roi_map.")
        click.echo("")
        click.echo(ctx.get_help())
        ctx.exit(1)

    if roi and input_path.is_dir():
        raise click.ClickException("ROI selection (-r) can only be used with a single .mcd file.")

    if roi_map and not convert and not stitch:
        raise click.ClickException("--roi_map requires --convert or --stitch.")

    if (filter or pyramid) and not convert and not stitch:
        raise click.ClickException("--filter/--pyramid requires --convert or --stitch.")

    if panorama is not None and panorama != "all" and not panorama.replace("-", "").replace(",", "").isdigit():
        raise click.ClickException("Panorama argument must be 'all' or comma-separated indices (e.g., '0,1,2').")

    mcd_process(
        input_path=input_path,
        output_path=output_path,
        convert=convert,
        stitch=stitch,
        panorama=panorama,
        metadata=metadata,
        roi_map=roi_map,
        filter=filter,
        pyramid=pyramid,
        roi=roi,
        output_type=output_type,
        compression=compression,
    )


if __name__ == "__main__":
    _cli_main()
