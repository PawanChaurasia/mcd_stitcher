# ---------------------- Imports ----------------------
import click
import numpy as np
import time
import tifffile as tiff
import traceback
import uuid
import xml.etree.ElementTree as ET

from datetime import datetime
from pathlib import Path
from typing import List, Optional
from .mcd_utils import CREATOR

# ---------------------- CLI ----------------------
@click.command(name='tiff_subset')
@click.option('-d','--output_type',type=click.Choice(['uint16','float32'],case_sensitive=False),default='uint16',show_default=True,help='Output data type for TIFF')
@click.option('-c','--compression',type=click.Choice(['None', 'LZW', 'zstd'], case_sensitive=True),default='zstd',show_default=True,help='Compression for output TIFF')
@click.option('-l','--list-channels',is_flag=True,help='List all channels in a TIFF')
@click.option('-f','--filter',type=str,nargs=1,required=False,help="Subset channels (e.g. '0-5,7,10')")
@click.option('-p','--pyramid',is_flag=True, help='Create a pyramidal (tiled) TIFF as output')
@click.argument('input_path', type=click.Path(exists=True, path_type=Path))

def main(output_type, compression, list_channels, filter, pyramid, input_path):
    start_all = time.time()
    
    if list_channels and (filter or pyramid):
        raise click.ClickException("-l cannot be combined with -f or -p")

    if not list_channels and not filter and not pyramid:
        raise click.ClickException("No action specified. Use -l, -f, or -p.")

    if input_path.is_file() and input_path.suffix.lower() == ".tiff":
        tiff_files = [input_path]
        input_root = input_path.parent
        
    elif input_path.is_dir():
        tiff_files = list(input_path.rglob("*.tiff"))
        if not tiff_files:
            raise click.ClickException("No .tiff files found in folder")
        input_root = input_path
        print(f"Found {len({f.parent for f in tiff_files})} folders")

    else:
        raise click.ClickException("Input must be a .tiff file or a folder of .tiff files")

    if list_channels:
        if len(tiff_files) != 1:
            raise click.ClickException("--list-channels requires a single .tiff file")
        list_channels_fn(tiff_files[0])
        return
    
    current_folder = None
    folder_start = None

    for tiff_path in tiff_files:
        folder = tiff_path.parent
        if folder != current_folder:
            if current_folder is not None:
                elapsed = time.time() - folder_start
                print(f"Successfully processed folder {current_folder.name} in {elapsed:.1f}s")
            current_folder = folder
            folder_start = time.time()
            print(f"Processing folder: {current_folder.name}")
        try:
            relative = tiff_path.relative_to(input_root)
            target_dir = input_root / relative.parent
            subset_single_file(tiff_path, target_dir, filter, compression, output_type, pyramid=pyramid)

        except Exception as e:
            log_path = input_root / "ome_subset_errors.log"
            with open(log_path, "a") as f:
                f.write(f"{datetime.now()} - {tiff_path}\n{e}\n{traceback.format_exc()}")
                
    if current_folder is not None:
        elapsed = time.time() - folder_start
        print(f"Successfully processed folder {current_folder.name} in {elapsed:.1f}s")
        
    print(f"Finished all folders in {round(time.time() - start_all, 1)}s")

# ---------------------- Helpers ----------------------
def read_ome_tiff(tiff_path: Path):
    with tiff.TiffFile(tiff_path) as tif:
        ome_xml = tif.ome_metadata
        if ome_xml is None:
            raise ValueError("No OME-XML metadata found")

        root = ET.fromstring(ome_xml)
        ns = {"ome": "http://www.openmicroscopy.org/Schemas/OME/2016-06"}

        channels = root.findall(".//ome:Channel", ns)
        channel_names = [c.get("Name") for c in channels]
        size_c = len(channel_names)

        pixels_elem = root.find(".//ome:Pixels", ns)
        phys_x = float(pixels_elem.get("PhysicalSizeX", "1.0"))
        phys_y = float(pixels_elem.get("PhysicalSizeY", "1.0"))

        if len(tif.series) == size_c:
            image_data = np.stack([s.asarray() for s in tif.series], axis=0)
        else:
            series = tif.series[0]
            level0 = series.levels[0]

            if len(level0.pages) < size_c:
                raise ValueError(f"Found {len(level0.pages)} planes, expected {size_c}")

            image_data = np.stack([level0.pages[i].asarray() for i in range(size_c)], axis=0)

    if image_data.shape[0] != size_c:
        raise ValueError(
            f"Channel mismatch: image has {image_data.shape[0]}, "
            f"OME XML lists {size_c}")

    return image_data, channel_names, phys_x, phys_y

def build_ome_xml(
    image_data: np.ndarray,
    channel_names: List[str],
    tiff_name: str,
    physical_x: float = 1.0,
    physical_y: float = 1.0,
) -> str:
    C, Y, X = image_data.shape

    dtype_map = {np.dtype("uint16"): "uint16", np.dtype("float32"): "float"}
    ome_type = dtype_map.get(image_data.dtype)
    if ome_type is None:
        raise ValueError(f"Unsupported dtype {image_data.dtype}")

    ome = ET.Element('OME', {
        'xmlns': 'http://www.openmicroscopy.org/Schemas/OME/2016-06',
        'Creator': CREATOR
    })

    img = ET.SubElement(ome, 'Image', {'ID': 'Image:0', 'Name': tiff_name})

    pixels = ET.SubElement(img, 'Pixels', {
        'ID': 'Pixels:0',
        'DimensionOrder': 'XYZCT',
        'Type': ome_type,
        'SizeX': str(X),
        'SizeY': str(Y),
        'SizeZ': '1',
        'SizeC': str(C),
        'SizeT': '1',
        'PhysicalSizeX': str(physical_x),
        'PhysicalSizeY': str(physical_y),
    })

    for i, name in enumerate(channel_names):
        ET.SubElement(pixels, 'Channel', {'ID': f'Channel:0:{i}', 'Name': name, 'SamplesPerPixel': '1'})

    for i in range(C):
        td = ET.SubElement(pixels, 'TiffData', {'FirstC': str(i), 'FirstZ': '0', 'FirstT': '0', 'IFD': str(i), 'PlaneCount': '1' })
        ET.SubElement(td, 'UUID', {'FileName': tiff_name}).text = f'urn:uuid:{uuid.uuid4()}'

    ET.indent(ome, space='  ')
    return ET.tostring(ome, encoding='unicode', xml_declaration=True)

def create_pyramid(image: np.ndarray, levels: int = 4) -> List[np.ndarray]:
    pyramid = [image]
    for level in range(1, levels):
        scale = 2 ** level
        downsampled = image[:, ::scale, ::scale]
        pyramid.append(downsampled)
    return pyramid

def write_pyramidal_ome_tiff(
    image_data: np.ndarray,
    channel_names: List[str],
    output_path: Path,
    compression: str,
    output_type: str,
    phys_x: float = 1.0,
    phys_y: float = 1.0,
    levels: int = 4,
):
    if output_type == "uint16":
        image_data = image_data.astype(np.uint16)
    else:
        image_data = image_data.astype(np.float32)

    pyramid_levels = create_pyramid(image_data, levels=levels)
    ome_xml = build_ome_xml(image_data, channel_names, output_path.name, physical_x=phys_x, physical_y=phys_y)

    with tiff.TiffWriter(output_path, bigtiff=True) as tif:
        options = dict(
            tile=(256, 256),
            compression=compression,
            photometric="minisblack",
            metadata={"axes": "CYX"},
        )

        for i, level_data in enumerate(pyramid_levels):
            if i == 0:
                tif.write(level_data, subifds=levels - 1, description=ome_xml, **options)
            else:
                tif.write(level_data, subfiletype=1, **options)

def write_ome_tiff(
    image_data: np.ndarray,
    channel_names: List[str],
    output_path: Path,
    compression: str,
    output_type: str,
    phys_x: float = 1.0,
    phys_y: float = 1.0,
):
    if output_type == "uint16":
        image_data = image_data.astype(np.uint16)
    else:
        image_data = image_data.astype(np.float32)

    ome_xml = build_ome_xml(image_data, channel_names, output_path.name, physical_x=phys_x, physical_y=phys_y)

    with tiff.TiffWriter(output_path, bigtiff=True) as writer:
        for i in range(image_data.shape[0]):
            writer.write(
                image_data[i],
                tile=(256, 256),
                compression=compression,
                photometric="minisblack",
                description=ome_xml if i == 0 else None,
            )

def parse_channels(filter_str: str) -> List[int]:
    channels = set()
    for part in filter_str.split(","):
        if "-" in part:
            a, b = map(int, part.split("-"))
            channels.update(range(a, b + 1))
        else:
            channels.add(int(part))
    return sorted(channels)

# ---------------------- Core Function ----------------------
def list_channels_fn(tiff_path: Path):
    _, channel_names, _, _ = read_ome_tiff(tiff_path)
    click.echo(f"Channels in {tiff_path}:")
    for i, name in enumerate(channel_names):
        click.echo(f"  {i}: {name}")
        
def subset_single_file(
    tiff_path: Path,
    out_dir: Path,
    filter_str: str,
    compression: str,
    output_type: str,
    pyramid: bool = False, 
):
    image_data, channel_names, phys_x, phys_y = read_ome_tiff(tiff_path)

    if filter_str:
        selected = parse_channels(filter_str)
        selected = [i for i in selected if 0 <= i < len(channel_names)]

        if not selected:
            raise ValueError("No valid channels selected")

        subset_img = image_data[selected]
        subset_names = [channel_names[i] for i in selected]
        filtered = True
    else:
        subset_img = image_data
        subset_names = channel_names
        filtered = False

    out_dir.mkdir(parents=True, exist_ok=True)

    base = tiff_path.stem.replace(".ome", "")
    suffixes = []
    if filtered:
        suffixes.append("filtered")
    if pyramid:
        suffixes.append("pyramid")

    suffix_str = "_" + "_".join(suffixes) if suffixes else ""
    output_path = out_dir / f"{base}{suffix_str}.ome.tiff"

    if pyramid:
        write_pyramidal_ome_tiff(subset_img, subset_names, output_path, compression, output_type, phys_x, phys_y)
    else:
        write_ome_tiff(subset_img, subset_names, output_path, compression, output_type, phys_x, phys_y)

if __name__ == "__main__":
    main()
