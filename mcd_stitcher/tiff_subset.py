# ---------------------- Imports ----------------------
import re
import uuid
import platform
import time
from pathlib import Path
from typing import List, Optional, Union

import click
import numpy as np
import tifffile as tiff

import xml.etree.ElementTree as ET
from xml.dom import minidom
from datetime import datetime
import traceback

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

    try:
        input_path = Path(input_path)

        if not (list_channels or filter or pyramid):
            click.echo(click.get_current_context().get_help())
            click.echo("\nError: No action specified.")
            return

        if list_channels:
            if not input_path.is_file():
                raise click.ClickException("--list-channels requires a single file")
            list_channels_fn(input_path)
            return

        if input_path.is_file():
            out_dir = input_path.parent
            subset_single_file(input_path, out_dir, filter, compression, output_type, pyramid=pyramid)

        elif input_path.is_dir():
            out_dir = input_path
            subset_directory(input_path, out_dir, filter, compression, output_type, pyramid=pyramid)
            
        else:
            print("Input must be an .tiff file or a folder of .tiff files")

        print(f"Finished in {round(time.time() - start_all, 1)}s")

    except Exception:
        print("Fatal error")
        raise


#---------------------- Helpers ----------------------
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
            image_data = np.stack([s.asarray() for s in tif.series],axis=0)

        else:
            series = tif.series[0]
            level0 = series.levels[0]

            if len(level0.pages) < size_c:
                raise ValueError(f"Found {len(level0.pages)} planes, expected {size_c}")

            image_data = np.stack([level0.pages[i].asarray() for i in range(size_c)],axis=0)

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
        'Creator': 'MCD_Stitcher',
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

    return minidom.parseString(ET.tostring(ome)).toprettyxml(indent='  ')

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

    comp_args = {"level": 15} if compression == "zstd" else None
    comp = None if compression == "None" else compression

    ome_xml = build_ome_xml(
        image_data,
        channel_names,
        output_path.name,
        physical_x=phys_x,
        physical_y=phys_y,
    )

    with tiff.TiffWriter(output_path, bigtiff=True) as tif:
        options = dict(
            tile=(256, 256),
            compression=comp,
            compressionargs=comp_args,
            photometric="minisblack",
            metadata={"axes": "CYX"},
        )

        for i, level_data in enumerate(pyramid_levels):
            if i == 0:
                # First image with SubIFDs pointing to lower resolutions
                tif.write(level_data, subifds=levels - 1, description=ome_xml, **options)
            else:
                # Lower resolution levels
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

    ome_xml = build_ome_xml(
        image_data,
        channel_names,
        output_path.name,
        physical_x=phys_x,
        physical_y=phys_y,
    )

    comp_args = {"level": 15} if compression == "zstd" else None
    comp = None if compression == "None" else compression

    with tiff.TiffWriter(output_path) as writer:
        for i in range(image_data.shape[0]):
            writer.write(
                image_data[i],
                tile=(256, 256),
                compression=comp,
                compressionargs=comp_args,
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
    filter_str: Optional[str],
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
        write_pyramidal_ome_tiff(
            subset_img, subset_names, output_path, compression, output_type, phys_x, phys_y
        )
    else:
        write_ome_tiff(
            subset_img, subset_names, output_path, compression, output_type, phys_x, phys_y
        )

def subset_directory(
    input_dir: Path,
    out_dir: Path,
    filter_str: str,
    compression: str,
    output_type: str,
    pyramid: bool = False,
):
    start_all = time.time()
    input_dir = input_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    folders = {t.parent for t in input_dir.rglob("*.ome.tiff")}
    if not folders:
        click.echo("No OME-TIFF files found to process.")
        return

    for folder in sorted(folders):
        rel_folder = folder.relative_to(input_dir)
        tiff_files = list(folder.glob("*.ome.tiff"))
        click.echo(f"Processing {len(tiff_files)} TIFFs in {rel_folder}")
        start_folder = time.time()

        target_dir = out_dir / rel_folder
        target_dir.mkdir(parents=True, exist_ok=True)

        tiff_files = list(folder.glob("*.ome.tiff"))
        for tiff_path in tiff_files:
            try:
                subset_single_file(tiff_path, target_dir, filter_str, compression, output_type,pyramid=pyramid)
            except Exception as e:
                log_path = out_dir / "ome_subset_errors.log"
                with open(log_path, "a") as f:
                    f.write(
                        f"{datetime.now()} - {tiff_path}\n{e}\n{traceback.format_exc()}\n"
                    )

        elapsed_folder = time.time() - start_folder
        click.echo(f"Successfully processed {rel_folder} in {elapsed_folder:.1f}s\n")

if __name__ == "__main__":
    main()
