# ---------------------- Imports ----------------------
import re
import uuid
import shutil
import platform
import time
from pathlib import Path
from typing import Optional
from datetime import datetime

import click
import numpy as np
import tifffile as tiff
from readimc import MCDFile
from skimage.draw import polygon
from skimage.transform import resize

import xml.etree.ElementTree as ET
from xml.dom import minidom


# ---------------------- CLI ----------------------
@click.command(name='mcd_stitch')
@click.option('-d', '--output_type',type=click.Choice(['uint16', 'float32'], case_sensitive=False),default='uint16',show_default=True)
@click.option('-c','--compression',type=click.Choice(['None', 'LZW', 'zstd'], case_sensitive=True),default='zstd',show_default=True)
@click.argument('input_path', type=click.Path(exists=True, path_type=Path))
@click.argument('output_path', type=click.Path(exists=False, path_type=Path), required=False)

def main(output_type, compression, input_path, output_path):
    start_all = time.time()

    try:
        if input_path.is_file() and input_path.suffix == '.mcd':
            out_dir = make_out_dir(input_path, output_path)
            make_dir(out_dir)
            print(f"Processing MCD: {input_path}")
            mcd_stitch(input_path, out_dir, output_type, compression)
            print(f"Sucessfully Processed in {round(time.time() - start_all, 1)}s")

        elif input_path.is_dir():
            for mcd in input_path.glob('*.mcd'):
                start_mcd = time.time()
                out_dir = make_out_dir(mcd, output_path)
                make_dir(out_dir)
                print(f"Processing MCD: {mcd}")
                mcd_stitch(mcd, out_dir, output_type, compression)
                elapsed_mcd = time.time() - start_mcd
                print(f"Successfully processed {mcd.name} in {elapsed_mcd:.1f}s")
            elapsed_all = time.time() - start_all
            print(f"Finished all MCDs in {elapsed_all:.1f}s")
            
        else:
            print("Input must be an .mcd file or a folder of .mcd files")

    except Exception:
        print("Fatal error")
        raise


# ---------------------- Helpers ----------------------
def make_dir(path: Path):
    path.mkdir(parents=True, exist_ok=True)

def make_out_dir(input_path: Path, base_out: Optional[Path]) -> Path:
    base = base_out if base_out else input_path.parent
    return base / "TIFF_Stitched"

def clean_name(name: str) -> str:
    bad_chars = r'[\/:*?"<>|]' if platform.system() == 'Windows' else r'[|/:*?[$!]'
    return re.sub(bad_chars, '_', name).strip()

def build_ome_xml(shape, channels, px, tiff_name, dtype):
    C, H, W = shape

    ome = ET.Element('OME', {
        'xmlns': 'http://www.openmicroscopy.org/Schemas/OME/2016-06',
        'Creator': 'MCD_Stitcher'
    })

    ET.SubElement(ome, 'Instrument', {'ID': 'Instrument:StandardBioToolsInstrument'})
    img = ET.SubElement(ome, 'Image', {'ID':'Image:Stitched', 'Name':tiff_name})
    
    pixels = ET.SubElement(img, 'Pixels', {
        'ID': 'Pixels:Stitched',
        'DimensionOrder': 'XYZCT',
        'Type': dtype,
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
        td = ET.SubElement(pixels, 'TiffData', {'FirstC': str(i), 'FirstT': '0', 'FirstZ': '0', 'IFD': str(i), 'PlaneCount':'1' })
        ET.SubElement(td, 'UUID', {'FileName': tiff_name}).text = f'urn:uuid:{uuid.uuid4()}'

    return minidom.parseString(ET.tostring(ome)).toprettyxml(indent='  ')


# ---------------------- Core Function ----------------------
def mcd_stitch(mcd_path, out_dir, dtype, compression):
    
    out_tiff = out_dir / f"{mcd_path.stem}_stitched.ome.tiff"

    roi_coords = {}
    images = {}
    pixel_size = {}
    roi_time = {}
    channel_labels = []

    # ---------------- Read MCD ----------------
    with MCDFile(mcd_path) as mcd:
        for slide in mcd.slides:
            for acq in slide.acquisitions:
                if acq.roi_points_um:
                    roi_coords[acq.description] = acq.roi_points_um
                    pixel_size[acq.description] = (acq.pixel_size_x_um, acq.pixel_size_y_um)
                    images[acq.description] = mcd.read_acquisition(acq)
                    roi_time[acq.description] = datetime.fromisoformat(acq.metadata["StartTimeStamp"])
                    if not channel_labels:
                        channel_labels = acq.channel_labels

    if not images:
        raise RuntimeError("No ROIs found")

    # ---------------- Global canvas ----------------
    xs = [x for roi in roi_coords.values() for x, _ in roi]
    ys = [y for roi in roi_coords.values() for _, y in roi]

    min_x_um, max_x_um = min(xs), max(xs)
    min_y_um, max_y_um = min(ys), max(ys)

    rois_translated = {
        name: [(x - min_x_um, y - min_y_um) for x, y in points]
        for name, points in roi_coords.items()
    }

    canvas_width_um = max_x_um - min_x_um
    canvas_height_um = max_y_um - min_y_um
    px_sizes = np.array(list(pixel_size.values()))
    global_px = np.min(px_sizes)
    
    canvas_width_px = int(np.ceil(canvas_width_um / global_px))
    canvas_height_px = int(np.ceil(canvas_height_um / global_px))

    channels = next(iter(images.values())).shape[0]
    canvas = np.zeros((channels, canvas_height_px, canvas_width_px), np.float32)
    written = np.zeros((canvas_height_px, canvas_width_px), bool)

    # ---------------- ROI order ----------------
    roi_order = sorted(images.keys(), key=lambda k: roi_time[k], reverse=True)

    # ---------------- Paste ROIs ----------------
    for name in roi_order:
        img = images[name]
        roi = rois_translated[name]
        px_x, px_y = pixel_size[name]
        C, h, w = img.shape

        scale_x = px_x / global_px
        scale_y = px_y / global_px

        h_new = int(np.ceil(h * scale_y))
        w_new = int(np.ceil(w * scale_x))

        resized = np.zeros((C, h_new, w_new), np.float32)
        for c in range(C):
            resized[c] = resize(
                img[c].astype(np.float32),
                (h_new, w_new),
                order=1,
                mode='reflect',
                preserve_range=True,
                anti_aliasing=True
            )

        xs = np.array([x for x, _ in roi])
        ys = np.array([y for _, y in roi])

        min_x_roi, min_y_roi = xs.min(), ys.min()
        poly_x = (xs - min_x_roi) / global_px
        poly_y = (ys - min_y_roi) / global_px

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
            src = resized[c, :h_slice, :w_slice]
            dst = canvas[c, y0:y1, x0:x1]
            valid = mask[:h_slice, :w_slice] & (src > 0)
            write_mask = valid & (~written[y0:y1, x0:x1])
            dst[write_mask] = src[write_mask]

        written[y0:y1, x0:x1][valid] = True
        
    # ---------------- Save ----------------
    if dtype == "uint16":
        canvas = np.clip(canvas, 0, 65535).astype(np.uint16)
        ome_dtype = "uint16"
    else:
        canvas = canvas.astype(np.float32)
        ome_dtype = "float"

    ome_xml = build_ome_xml(
        canvas.shape,
        channel_labels,
        global_px,
        out_tiff.name,
        ome_dtype
    )

    with tiff.TiffWriter(out_tiff, bigtiff=True) as writer:
        for c in range(canvas.shape[0]):
            writer.write(
                canvas[c],
                compression=compression,
                photometric="minisblack",
                description=ome_xml if c == 0 else None
            )

if __name__ == '__main__':
    main()
