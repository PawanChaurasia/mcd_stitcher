# ---------------------- Imports ----------------------
import uuid
import click
import numpy as np
import tifffile as tiff
import xml.etree.ElementTree as ET

from pathlib import Path
from readimc import MCDFile
from dateutil.parser import isoparse
from typing import List, Optional, Sequence
from PIL import Image, ImageDraw, ImageFont
from importlib.metadata import version, PackageNotFoundError


# ---------------------- Package metadata ----------------------
try:
    CREATOR = f'MCD_Stitcher v{version("mcd_stitcher")}'
except PackageNotFoundError:
    CREATOR = 'MCD_Stitcher'

# ---------------------- File/Filesystem helpers ----------------------
def resolve_mcd_files(input_path: Path) -> List[Path]:
    if input_path.is_file() and input_path.suffix.lower() == ".mcd":
        return [input_path]

    if input_path.is_dir():
        mcd_files = list(input_path.glob("*.mcd"))
        if not mcd_files:
            raise click.ClickException("No .mcd files found in folder")
        return mcd_files

    raise click.ClickException("Input must be a .mcd file or a folder of .mcd files")

def validate_mcd_file(ctx, param, value):
    """Click callback: reject non-.mcd input (folders are already handled by dir_okay=False)."""
    if value is not None and value.suffix.lower() != ".mcd":
        raise click.BadParameter(f"expected a .mcd file (got: {value.name}).")
    return value

def make_dir(path: Path):
    path.mkdir(parents=True, exist_ok=True)

# ---------------------- MCD processing helpers ----------------------
def load_rois(mcd: MCDFile) -> List[dict]:
    roi_metadata = []
    for slide in mcd.slides:
        for acq in slide.acquisitions:
            if not acq.roi_points_um:
                continue
            roi_metadata.append({
                "slide": slide,
                "acq": acq,
                "description": acq.description,
                "timestamp": acq.metadata.get("StartTimeStamp"),
                "roi_coords": acq.roi_points_um,
                "pixel_size": (acq.pixel_size_x_um, acq.pixel_size_y_um),
                "width": acq.width_px,
                "height": acq.height_px,
                "channel_labels": acq.channel_labels,
                "num_channels": acq.num_channels,
            })

    roi_metadata.sort(
        key=lambda r: isoparse(r["timestamp"]) if r["timestamp"] else "",
        reverse=True,
    )
    return roi_metadata

def read_acquisition_chunked(fh, acq, strict=True, chunk_px=50000):
    md = acq.metadata
    data_start, data_end = int(md["DataStartOffset"]), int(md["DataEndOffset"])
    value_bytes = int(md.get("ValueBytes", 4))
    value_dtype = {2: np.float16, 4: np.float32, 8: np.float64}.get(value_bytes)
    if value_dtype is None:
        raise OSError(f"Unsupported ValueBytes={value_bytes} for '{acq.description}' (expected 2, 4, or 8)")
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
        chunk = np.frombuffer(raw, dtype=value_dtype).reshape(n, stride)

        xs, ys = chunk[:, 0].astype(int), chunk[:, 1].astype(int)
        valid = (0 <= xs) & (xs < width) & (0 <= ys) & (ys < height)
        xs, ys, chunk = xs[valid], ys[valid], chunk[valid]

        for c in range(num_channels):
            img[c, ys, xs] = chunk[:, c + 3]

        remaining -= n

    return img

def ome_xml_builder(
    channel_names: Sequence[str],
    size_x: int,
    size_y: int,
    pixel_type: str,
    tiff_name: str,
    image_id: str = "Image:0",
    image_name: Optional[str] = None,
    pixels_id: str = "Pixels:0",
    channel_id_prefix: str = "Channel:0:",
    physical_x: float = 1.0,
    physical_y: float = 1.0,
) -> str:
    ome = ET.Element('OME', {
        'xmlns': 'http://www.openmicroscopy.org/Schemas/OME/2016-06',
        'Creator': CREATOR
    })

    ET.SubElement(ome, 'Instrument', {'ID': 'Instrument:StandardBioToolsInstrument'})
    img = ET.SubElement(ome, 'Image', {'ID': image_id, 'Name': image_name or tiff_name})

    pixels = ET.SubElement(img, 'Pixels', {
        'ID': pixels_id,
        'DimensionOrder': 'XYZCT',
        'Type': pixel_type,
        'SizeX': str(size_x),
        'SizeY': str(size_y),
        'SizeZ': '1',
        'SizeC': str(len(channel_names)),
        'SizeT': '1',
        'PhysicalSizeX': str(physical_x),
        'PhysicalSizeY': str(physical_y),
    })

    for i, name in enumerate(channel_names):
        ET.SubElement(pixels, 'Channel', {'ID': f'{channel_id_prefix}{i}', 'Name': name, 'SamplesPerPixel': '1'})

    for i in range(len(channel_names)):
        td = ET.SubElement(pixels, 'TiffData', {'FirstC': str(i), 'FirstZ': '0', 'FirstT': '0', 'IFD': str(i), 'PlaneCount': '1' })

    ET.indent(ome, space='  ')
    return ET.tostring(ome, encoding='unicode', xml_declaration=True)

# ---------------------- Index / range parsing ----------------------
def parse_index_string(value: str, max_idx: Optional[int] = None) -> Optional[List[int]]:
    """Parse "all" (-> None), "0,2,5", "1-5" into an ordered, de-duplicated index list; max_idx range-checks each."""
    if value == "all":
        return None

    indices = []
    seen = set()
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            for i in range(int(a.strip()), int(b.strip()) + 1):
                if i not in seen:
                    seen.add(i)
                    indices.append(i)
        else:
            i = int(part)
            if i not in seen:
                seen.add(i)
                indices.append(i)

    if max_idx is not None:
        for i in indices:
            if i < 0 or i > max_idx:
                raise click.ClickException(f"Invalid index {i}. Valid range: 0..{max_idx}")

    return indices

def parse_channels(filter_str: str) -> List[int]:
    """Parse a channel-filter string (e.g. "0-5,7") into a sorted, de-duplicated index list."""
    return sorted(parse_index_string(filter_str) or [])

# ---------------------- TIFF / OME helpers ----------------------

def read_ome_metadata_only(tiff_path: Path):
    with tiff.TiffFile(tiff_path) as tif:
        ome_xml = tif.ome_metadata
        if ome_xml is None:
            raise ValueError("No OME-XML metadata found")
        root = ET.fromstring(ome_xml)
        ns = {"ome": "http://www.openmicroscopy.org/Schemas/OME/2016-06"}
        channels = [c.get("Name") for c in root.findall(".//ome:Channel", ns)]
        pixels = root.find(".//ome:Pixels", ns)
        return (
            channels,
            float(pixels.get("PhysicalSizeX", "1.0")),
            float(pixels.get("PhysicalSizeY", "1.0")),
            int(pixels.get("SizeX", "0")),
            int(pixels.get("SizeY", "0")),
        )

def read_channel_lazy(tiff_path: Path, channel_idx: int) -> np.ndarray:
    with tiff.TiffFile(tiff_path) as tif:
        if not tif.series:
            raise ValueError("Could not read TIFF data")
        if len(tif.series) == 1:
            return tif.series[0].levels[0].pages[channel_idx].asarray()
        return tif.series[channel_idx].asarray()

def _to_output_dtype(arr: np.ndarray, output_type: str) -> np.ndarray:
    """Cast to the output dtype. Clip before a uint16 cast so resampled/overshoot values don't wrap into bright artifacts."""
    if output_type == "uint16":
        return np.clip(arr, 0, 65535).astype(np.uint16)
    return arr.astype(np.float32)

def write_planes(output_path, ome_xml, planes, compression, output_type, tile=(256, 256)):
    """Write 2D channel planes to one OME-TIFF (OME-XML on the first plane; tile=None for strips)."""
    with tiff.TiffWriter(output_path, bigtiff=True) as writer:
        for i, plane in enumerate(planes):
            writer.write(
                _to_output_dtype(plane, output_type),
                tile=tile,
                compression=compression,
                photometric="minisblack",
                description=ome_xml if i == 0 else None,
            )
            del plane

def create_pyramid(image: np.ndarray, levels: int = 4) -> List[np.ndarray]:
    pyramid = [image]
    for level in range(1, levels):
        scale = 2 ** level
        downsampled = image[:, ::scale, ::scale]
        pyramid.append(downsampled)
    return pyramid

def write_ome_tiff_streaming(
    input_path: Path,
    output_path: Path,
    channel_indices: Optional[List[int]],
    compression: str,
    output_type: str,
):
    channel_names, phys_x, phys_y, size_x, size_y = read_ome_metadata_only(input_path)
    channel_indices = channel_indices or list(range(len(channel_names)))
    selected_names = [channel_names[i] for i in channel_indices]

    ome_xml = ome_xml_builder(
        channel_names=selected_names,
        size_x=size_x,
        size_y=size_y,
        pixel_type="uint16" if output_type == "uint16" else "float",
        tiff_name=output_path.name,
        physical_x=phys_x,
        physical_y=phys_y,
    )

    planes = (read_channel_lazy(input_path, ch_idx) for ch_idx in channel_indices)
    write_planes(output_path, ome_xml, planes, compression, output_type, tile=(256, 256))

def write_pyramidal_ome_tiff_streaming(
    input_path: Path,
    output_path: Path,
    channel_indices: Optional[List[int]],
    compression: str,
    output_type: str,
    levels: int = 4,
):
    channel_names, phys_x, phys_y, size_x, size_y = read_ome_metadata_only(input_path)
    channel_indices = channel_indices or list(range(len(channel_names)))
    selected_names = [channel_names[i] for i in channel_indices]

    img = np.zeros((len(selected_names), size_y, size_x), dtype=np.float32)
    for out_idx, ch_idx in enumerate(channel_indices):
        img[out_idx] = read_channel_lazy(input_path, ch_idx)
    img = _to_output_dtype(img, output_type)

    pyramid = create_pyramid(img, levels)
    ome_xml = ome_xml_builder(
        channel_names=selected_names,
        size_x=size_x,
        size_y=size_y,
        pixel_type="uint16" if output_type == "uint16" else "float",
        tiff_name=output_path.name,
        physical_x=phys_x,
        physical_y=phys_y,
    )

    with tiff.TiffWriter(output_path, bigtiff=True) as tif:
        opts = dict(tile=(256, 256), compression=compression, photometric="minisblack", metadata={"axes": "CYX"})
        for i, level in enumerate(pyramid):
            tif.write(level, subifds=levels - 1 if i == 0 else None, subfiletype=1 if i > 0 else None,
                      description=ome_xml if i == 0 else None, **opts)


# ---------------------- Canvas bounds ----------------------

def compute_canvas_bounds(rois: List[dict]):
    xs = [x for r in rois for x, _ in r["roi_coords"]]
    ys = [y for r in rois for _, y in r["roi_coords"]]
    min_x_um, max_x_um = min(xs), max(xs)
    min_y_um, max_y_um = min(ys), max(ys)

    rois_translated = []
    for r in rois:
        translated_roi = {
            **r,
            "roi_translated": [(x - min_x_um, y - min_y_um) for x, y in r["roi_coords"]],
        }
        rois_translated.append(translated_roi)

    return rois_translated, min_x_um, max_x_um, min_y_um, max_y_um


# ---------------------- Panorama helpers ----------------------

def _resolve_panorama(slide, panorama_index: int):
    panoramas = getattr(slide, 'panoramas', []) or []
    if not panoramas:
        raise RuntimeError("No panoramas found in the selected slide")
    if panorama_index < 0 or panorama_index >= len(panoramas):
        raise ValueError(f"Invalid panorama index {panorama_index}. Available: 0..{len(panoramas)-1}")
    return panoramas[panorama_index]


def _panorama_slide_bounds(panorama):
    metadata = getattr(panorama, 'metadata', {})
    coords = []
    for i in range(1, 5):
        x_key = f"SlideX{i}PosUm"
        y_key = f"SlideY{i}PosUm"
        if x_key not in metadata or y_key not in metadata:
            raise RuntimeError(f"Panorama metadata missing {x_key} or {y_key}")
        coords.append((float(metadata[x_key]), float(metadata[y_key])))
    xs = [x for x, _ in coords]
    ys = [y for _, y in coords]
    return min(xs), max(xs), min(ys), max(ys)


def _slide_to_panorama_pixel(x_um, y_um, pano_bounds, pano_width, pano_height):
    pano_min_x, pano_max_x, pano_min_y, pano_max_y = pano_bounds
    if pano_max_x == pano_min_x or pano_max_y == pano_min_y:
        raise RuntimeError("Invalid panorama bounds for pixel mapping")
    scale_x = pano_width / (pano_max_x - pano_min_x)
    scale_y = pano_height / (pano_max_y - pano_min_y)
    px = (x_um - pano_min_x) * scale_x
    py = (pano_max_y - y_um) * scale_y
    return px, py


def _panorama_pixel_dims(mcd, panorama, png_path=None):
    """Panorama (width, height) in px: from an existing PNG's header if given, else by decoding the raster."""
    if png_path is not None and png_path.exists():
        with Image.open(png_path) as im:
            return im.size
    img = mcd.read_panorama(panorama)
    if img is None:
        return None, None
    return img.shape[1], img.shape[0]

def _save_panorama_image(mcd, panorama, out_path: Path):
    img = mcd.read_panorama(panorama)
    if img is None:
        raise RuntimeError("Panorama image could not be read")
    image = Image.fromarray(img)
    image.save(out_path)
    return image.width, image.height


_OVERLAY_FONT_CANDIDATES = ("arial.ttf", "Arial.ttf", "DejaVuSans.ttf", "LiberationSans-Regular.ttf")

def _load_overlay_font(font_size: int, fallback):
    """Return a TrueType font at font_size, trying common cross-platform faces before the bundled default."""
    for name in _OVERLAY_FONT_CANDIDATES:
        try:
            return ImageFont.truetype(name, font_size)
        except OSError:
            continue
    return fallback

def _draw_roi_overlay(panorama_path: Path, rois: List[dict],
                      pano_bounds: tuple, pano_w: int, pano_h: int,
                      out_path: Path) -> None:
    roi_colors = [
        (255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0),
        (255, 0, 255), (0, 255, 255), (255, 128, 0), (128, 0, 255),
    ]

    src_img = Image.open(panorama_path)
    img = src_img.copy()
    src_img.close()
    del src_img
    draw = ImageDraw.Draw(img)

    font_cache = {}
    fallback_font = ImageFont.load_default()

    for i, roi_meta in enumerate(rois):
        color = roi_colors[i % len(roi_colors)]
        roi_name = roi_meta.get("description") or f"ROI_{i}"
        roi_coords = roi_meta["roi_coords"]

        pano_corners = []
        for x_um, y_um in roi_coords:
            px, py = _slide_to_panorama_pixel(x_um, y_um, pano_bounds, pano_w, pano_h)
            pano_corners.append((px, py))

        xs = [p[0] for p in pano_corners]
        ys = [p[1] for p in pano_corners]
        extent = max(max(xs) - min(xs), max(ys) - min(ys))

        font_size = int((extent ** 0.7) - 20)
        font_size = max(10, min(192, font_size))

        line_width = max(2, min(10, int(extent / 100)))
        draw.polygon(pano_corners, outline=color, width=line_width)

        if font_size not in font_cache:
            font_cache[font_size] = _load_overlay_font(font_size, fallback_font)

        font = font_cache[font_size]

        cx = sum(xs) / len(xs)
        cy = sum(ys) / len(ys)
        bbox = draw.textbbox((0, 0), roi_name, font=font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        text_x = cx - text_w / 2
        text_y = cy - text_h / 2
        padding = 4

        draw.rectangle(
            [text_x - padding, text_y - padding, text_x + text_w + padding, text_y + text_h + padding],
            fill=color
        )
        draw.text((text_x, text_y), roi_name, fill=(0, 0, 0), font=font)

    img.save(out_path)
