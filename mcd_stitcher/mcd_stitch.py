# ---------------------- Imports ----------------------
import click
import numpy as np
import re
import time
import tifffile as tiff
import uuid
import xml.etree.ElementTree as ET

from datetime import datetime
from dateutil.parser import isoparse
from pathlib import Path
from readimc import MCDFile
from skimage.draw import polygon
from skimage.transform import resize
from typing import Optional
from .mcd_utils import make_dir, read_acquisition_chunked, CREATOR

# ---------------------- CLI ----------------------
@click.command(name='mcd_stitch')
@click.option('-d','--output_type',type=click.Choice(['uint16', 'float32'], case_sensitive=True),default='uint16',show_default=True)
@click.option('-c','--compression',type=click.Choice(['None', 'LZW', 'zstd'], case_sensitive=True),default='zstd',show_default=True)
@click.option('-r','--roi',is_flag=True,help="Interactively select which ROIs to stitch.")
@click.argument('input_path',type=click.Path(exists=True, path_type=Path))
@click.argument('output_path',type=click.Path(exists=False, path_type=Path), required=False)

def main(output_type, compression, roi, input_path, output_path):
    start_all = time.time()

    if roi and input_path.is_dir():
        raise click.ClickException("--roi can only be used with a single .mcd file")
        
    if input_path.is_file() and input_path.suffix.lower() == '.mcd':
        mcd_files = [input_path]
        
    elif input_path.is_dir():
        mcd_files = list(input_path.glob("*.mcd"))
        if not mcd_files:
            raise click.ClickException("No .mcd files found in folder")
        print(f"Found {len(mcd_files)} MCD files")
            
    else:
        raise click.ClickException("Input must be an .mcd file or a folder of .mcd files")
    
    for mcd in mcd_files:
        start_mcd = time.time()
        out_dir = make_out_dir(mcd, output_path)
        make_dir(out_dir)
        print(f"Processing MCD: {mcd}")
        out_tiff = out_dir / f"{mcd.stem}_stitched.ome.tiff"
        mcd_stitch(mcd, out_tiff, output_type, compression, select_roi=roi if len(mcd_files) == 1 else False)
        print(f"Successfully processed {mcd.name} in {time.time() - start_mcd:.1f}s")

    print(f"Finished all MCDs in {time.time() - start_all:.1f}s")

# ---------------------- Helpers ----------------------
def make_out_dir(input_path: Path, base_out: Optional[Path]) -> Path:
    base = base_out if base_out else input_path.parent
    return base / "TIFF_Stitched"

def build_ome_xml(shape, channels, px, tiff_name, ome_dtype):
    C, H, W = shape

    ome = ET.Element('OME', {
        'xmlns': 'http://www.openmicroscopy.org/Schemas/OME/2016-06',
        'Creator': CREATOR
    })

    ET.SubElement(ome, 'Instrument', {'ID': 'Instrument:StandardBioToolsInstrument'})
    img = ET.SubElement(ome, 'Image', {'ID':'Image:Stitched', 'Name':tiff_name})
    
    pixels = ET.SubElement(img, 'Pixels', {
        'ID': 'Pixels:Stitched',
        'DimensionOrder': 'XYZCT',
        'Type': ome_dtype,
        'SizeX': str(W),
        'SizeY': str(H),
        'SizeZ': '1',
        'SizeC': str(C),
        'SizeT': '1',
        'PhysicalSizeX': f'{float(px)}',
        'PhysicalSizeY': f'{float(px)}'
    })

    for i, ch in enumerate(channels):
        ET.SubElement(pixels, 'Channel', {'ID': f'Channel:Stitched:{i}', 'Name': ch, 'SamplesPerPixel': '1'})

    for i in range(C):
        td = ET.SubElement(pixels, 'TiffData', {'FirstC': str(i), 'FirstT': '0', 'FirstZ': '0', 'IFD': str(i), 'PlaneCount':'1'})
        ET.SubElement(td, 'UUID', {'FileName': tiff_name}).text = f'urn:uuid:{uuid.uuid4()}'

    ET.indent(ome, space='  ')
    return ET.tostring(ome, encoding='unicode', xml_declaration=True)

def select_rois(rois):
    if not rois:
        raise ValueError("No ROIs found")

    print("\n" + "="*90)
    print("DETECTED ROIs")
    print("="*90)
    print(f"{'Idx':<4} | {'Description':<40} | {'Timestamp':<19} | {'Size (W×H)':<12}")
    print("-"*90)

    for idx, r in enumerate(rois):
        desc = (r["description"] or "").strip()
        if len(desc) > 40:
            desc = desc[:37] + "..."
        ts = r["timestamp"]
        ts = re.sub(r'(\.\d{6})\d+', r'\1', ts)
        try:
            ts = datetime.fromisoformat(ts).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            pass
        print(f"{idx:<4} | {desc:<40} | {ts:<19} | {r['width']:>4} × {r['height']:<4}")

    print("="*90)

    user = input('\nEnter comma-separated indices to KEEP (e.g., 0,3,5), or press Enter to keep all: ').strip()

    if user == "":
        print("Keeping all ROIs.")
        return rois

    try:
        indices = [int(p.strip()) for p in user.split(",") if p.strip()]
    except Exception:
        raise ValueError("Invalid input. Expected comma-separated integers.")

    max_idx = len(rois) - 1
    for i in indices:
        if i < 0 or i > max_idx:
            raise ValueError(f"Invalid index {i}. Valid range: 0..{max_idx}")

    seen = set()
    selected = []
    for i in indices:
        if i not in seen:
            seen.add(i)
            selected.append(rois[i])

    print(f"Keeping {len(selected)} of {len(rois)} ROIs.")

    return selected

# ---------------------- Core Functions ----------------------
def mcd_stitch(
    mcd_path: Path,
    output_path: Optional[Path] = None,
    dtype: str = "uint16",
    compression: str = "zstd",
    select_roi: bool = False
    ):

    roi_metadata = []

    with MCDFile(mcd_path) as mcd:

        # ---------------- Pass 1: collect metadata (no images) ----------------
        for slide in mcd.slides:
            for acq in slide.acquisitions:
                if not acq.roi_points_um:
                    continue
                roi_metadata.append({
                    "acq":           acq,
                    "description":   acq.description,
                    "timestamp":     acq.metadata.get("StartTimeStamp"),
                    "roi_coords":    acq.roi_points_um,
                    "pixel_size":    (acq.pixel_size_x_um, acq.pixel_size_y_um),
                    "width":         acq.width_px,
                    "height":        acq.height_px,
                    "channel_labels": acq.channel_labels,
                    "num_channels":  acq.num_channels
                })

        if not roi_metadata:
            raise RuntimeError("No ROIs found")

        if select_roi:
            roi_metadata = select_rois(roi_metadata)

        # ---------------- ROI order ----------------
        roi_metadata = sorted(roi_metadata, key=lambda r: isoparse(r["timestamp"]), reverse=True)
        channel_labels = roi_metadata[0]["channel_labels"]

        # ---------------- Global canvas ----------------
        xs = [x for r in roi_metadata for x, _ in r["roi_coords"]]
        ys = [y for r in roi_metadata for _, y in r["roi_coords"]]

        min_x_um, max_x_um = min(xs), max(xs)
        min_y_um, max_y_um = min(ys), max(ys)

        for r in roi_metadata:
            r["roi_translated"] = [(x - min_x_um, y - min_y_um) for x, y in r["roi_coords"]]

        canvas_width_um  = max_x_um - min_x_um
        canvas_height_um = max_y_um - min_y_um
        global_px = min(px for r in roi_metadata for px in r["pixel_size"])

        canvas_width_px  = int(np.ceil(canvas_width_um  / global_px))
        canvas_height_px = int(np.ceil(canvas_height_um / global_px))

        channels = roi_metadata[0]["num_channels"]

        if dtype == "uint16":
            canvas = np.zeros((channels, canvas_height_px, canvas_width_px), np.uint16)
            ome_dtype = "uint16"
        else:
            canvas = np.zeros((channels, canvas_height_px, canvas_width_px), np.float32)
            ome_dtype = "float"

        # ---------------- Pass 2: read, paste, free each ROI ----------------
        for r in roi_metadata:
            try:
                img = read_acquisition_chunked(mcd._fh, r["acq"], strict=True)
            except OSError:
                print(f"Warning: strict read failed for {r['description']}. Retrying in recovery mode.")
                img = read_acquisition_chunked(mcd._fh, r["acq"], strict=False)

            roi = r["roi_translated"]
            px_x, px_y = r["pixel_size"]
            C, h, w = img.shape

            scale_x = px_x / global_px
            scale_y = px_y / global_px

            h_new = int(np.ceil(h * scale_y))
            w_new = int(np.ceil(w * scale_x))

            if np.isclose(px_x, global_px) and np.isclose(px_y, global_px):
                resized = img.astype(canvas.dtype)
            else:
                resized = np.stack([
                    resize(
                        img[c].astype(canvas.dtype),
                        (h_new, w_new),
                        order=1,
                        mode='reflect',
                        preserve_range=True,
                        anti_aliasing=True
                    ).astype(canvas.dtype)
                    for c in range(C)
                ])

            del img

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
                roi_slice    = resized[c, :h_slice, :w_slice]
                canvas_slice = canvas[c, y0:y1, x0:x1]
                mask_slice   = mask[:h_slice, :w_slice]
                valid_pixels = mask_slice & (roi_slice > 0)
                canvas_slice[valid_pixels] = roi_slice[valid_pixels]

            del resized

    # ---------------- Save ----------------
    if output_path is not None:
        ome_xml = build_ome_xml(canvas.shape, channel_labels, global_px, output_path.name, ome_dtype)

        with tiff.TiffWriter(output_path, bigtiff=True) as writer:
            for c in range(canvas.shape[0]):
                writer.write(
                    canvas[c],
                    compression=compression,
                    photometric="minisblack",
                    description=ome_xml if c == 0 else None
                )

    return canvas

if __name__ == '__main__':
    main()
