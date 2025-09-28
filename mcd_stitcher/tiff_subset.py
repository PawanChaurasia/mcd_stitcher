import argparse
import os
import tifffile
import numpy as np
import xml.etree.ElementTree as ET
from typing import List, Union
import traceback
from datetime import datetime
from pathlib import Path


def read_ome_tiff(tiff_path: str) -> (np.ndarray, List[str]):
    with tifffile.TiffFile(tiff_path) as tif:
        image_data = tif.asarray()
        ome_metadata = tif.ome_metadata

    if ome_metadata is None:
        raise ValueError(f"No OME-XML metadata found in {tiff_path}.")

    root = ET.fromstring(ome_metadata)
    namespace = {'ome': 'http://www.openmicroscopy.org/Schemas/OME/2016-06'}
    channel_elements = root.findall('.//ome:Channel', namespace)
    channel_names = [channel.get('Name') for channel in channel_elements]

    return image_data, channel_names

def generate_ome_xml(image_data: np.ndarray, channel_names: List[str], base_name: str) -> str:
    channels_xml = ''.join([f'<Channel ID="Channel:0:{i}" Name="{name}" SamplesPerPixel="1"/>' for i, name in enumerate(channel_names)])
    xml_metadata = f"""<?xml version="1.0" encoding="UTF-8"?>
    <OME xmlns="http://www.openmicroscopy.org/Schemas/OME/2016-06"
         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
         xsi:schemaLocation="http://www.openmicroscopy.org/Schemas/OME/2016-06 http://www.openmicroscopy.org/Schemas/OME/2016-06/ome.xsd">
        <Image ID="Image:0" Name="{base_name}">
            <Pixels BigEndian="false"
                    DimensionOrder="XYCZT"
                    ID="Pixels:0"
                    Interleaved="false"
                    SizeC="{len(channel_names)}"
                    SizeT="1"
                    SizeX="{image_data.shape[2]}"
                    SizeY="{image_data.shape[1]}"
                    SizeZ="1"
                    PhysicalSizeX="1.0"
                    PhysicalSizeY="1.0"
                    Type="{image_data.dtype}">
                <TiffData />
                {channels_xml}
            </Pixels>
        </Image>
    </OME>"""
    return xml_metadata


def write_ome_tiff(image_data: np.ndarray, channel_names: List[str], output_path: str, use_zstd: bool):
    ome_xml = generate_ome_xml(image_data, channel_names, os.path.basename(output_path))
    compression = 'zstd' if use_zstd else None
    compressionargs = {'level': 15} if use_zstd else None

    tifffile.imwrite(
        output_path,
        image_data,
        description=ome_xml,
        metadata={'axes': 'CYX'},
        compression=compression,
        compressionargs=compressionargs
    )

def create_pyramid(image, levels=4):
    pyramid = [image]
    for level in range(1, levels):
        scale = 2 ** level
        downsampled = image[:, ::scale, ::scale]
        pyramid.append(downsampled)
    return pyramid

def write_pyramidal_tiff(image_data: np.ndarray, channel_names: List[str], output_path: str, use_zstd: bool):
    tile_size = (256, 256)
    levels = 4

    pyramid_levels = create_pyramid(image_data, levels=levels)

    compression = 'zstd' if use_zstd else None
    compressionargs = {'level': 15} if use_zstd else None

    with tifffile.TiffWriter(output_path, bigtiff=True) as tif:
        options = dict(
            tile=tile_size,
            compression=compression,
            compressionargs=compressionargs,
            metadata={'axes': 'CYX'}
        )
        ome_xml = generate_ome_xml(image_data, channel_names, os.path.basename(output_path))

        for i, level_data in enumerate(pyramid_levels):
            if i == 0:
                tif.write(level_data, subifds=levels - 1, description=ome_xml, **options)
            else:
                tif.write(level_data, subfiletype=1, **options)


def list_channels(tiff_path: str):
    _, channel_names = read_ome_tiff(tiff_path)
    print(f"Channels in {tiff_path}:")
    for idx, name in enumerate(channel_names):
        print(f"Channel {idx}: {name}")

def parse_channels(channel_str: str) -> List[int]:
    channels = []
    if not channel_str:
        return channels
    for part in channel_str.split(','):
        part = part.strip()
        if '-' in part:
            start, end = map(int, part.split('-'))
            channels.extend(range(start, end + 1))
        else:
            channels.append(int(part))
    return channels

def subset_tiff(tiff_path: str, filter_str: Union[str, None], pyramid: bool, log_file: str, root_path: str = None, use_zstd: bool = False):
    try:
        if root_path:
            rel_path = os.path.relpath(tiff_path, root_path)
            print(f"Processing {rel_path}...")
        else:
            print(f"Processing {tiff_path}...")

        image_data, channel_names = read_ome_tiff(tiff_path)

        if filter_str is None:
            selected_channels = list(range(len(channel_names)))
        elif filter_str == '':
            selected_channels = [i for i, name in enumerate(channel_names) if any(metal in name for metal in [f"{i}" for i in range(141, 194)])]
        else:
            selected_channels = parse_channels(filter_str)

        max_channel_idx = len(channel_names) - 1
        valid_channels = [c for c in selected_channels if 0 <= c <= max_channel_idx]
        invalid_channels = [c for c in selected_channels if c not in valid_channels]
        if invalid_channels:
            print(f"Warning: Channel indices {invalid_channels} are out of bounds (max is {max_channel_idx}). They will be ignored.")

        if not valid_channels:
            print(f"No valid channels to process for {tiff_path}. Skipping.")
            return

        subset_image_data = image_data[valid_channels, :, :]
        subset_channel_names = [channel_names[i] for i in valid_channels]

        base, _ = os.path.splitext(tiff_path)
        if base.endswith('.ome'):
            base = os.path.splitext(base)[0]

        suffix = "_filtered" if filter_str is not None else ""
        if pyramid:
            suffix += "_pyramid"

        output_path = f"{base}{suffix}.ome.tiff"

        if pyramid:
            write_pyramidal_tiff(subset_image_data, subset_channel_names, output_path, use_zstd)
        else:
            write_ome_tiff(subset_image_data, subset_channel_names, output_path, use_zstd)

        if root_path:
            rel_output = os.path.relpath(output_path, root_path)
            print(f"Successfully wrote {rel_output}")
        else:
            print(f"Successfully wrote {output_path}")

    except Exception as e:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        error_message = f"{timestamp} - Error processing {tiff_path}: {str(e)}\n{traceback.format_exc()}\n"
        with open(log_file, 'a') as log:
            log.write(error_message)
        print(f"{timestamp} - Error processing {tiff_path}. See log for details. Continuing...")

def snapshot_tiff_files(folder_path: str) -> List[Path]:
    folder_path = Path(folder_path)
    tiff_files = [
        f for f in folder_path.rglob("*")
        if f.is_file() and f.suffix.lower() in (".tiff", ".ome.tiff")
    ]
    return tiff_files

def process_folder(folder_path: str, filter_str: Union[str, None], pyramid: bool, log_file: str, use_zstd: bool):
    files_to_process = snapshot_tiff_files(folder_path)

    if not files_to_process:
        print("No TIFF files found to process.")
        return

    print(f"Found {len(files_to_process)} TIFF files to process.")

    for tiff_file in files_to_process:
        subset_tiff(str(tiff_file), filter_str, pyramid, log_file, folder_path, use_zstd)


def main():
    parser = argparse.ArgumentParser(description="""
    Process and subset OME-TIFF files.

    Supports both:
    - Flat structure: stitched TIFFs from mcd_stitch
    - Nested structure: per-ROI TIFFs from mcd_convert -> zarr2tiff

    For more information on command usage, visit:
    https://github.com/PawanChaurasia/mcd_stitcher
    """)
    parser.add_argument("tiff_path", type=str, help="Path to the OME-TIFF file or directory.")
    parser.add_argument("-c", "--list_channels", action="store_true", help="Lists all channels in the specified file (file only).")
    parser.add_argument("-f", "--filter", type=str, nargs='?', const='', default=None, help="Filter and subset channels. Provide channels as a comma-separated list, e.g., '0-5,7,10'. If flag is present but no channels are given, default filtering is applied.")
    parser.add_argument("-p", "--pyramid", action="store_true", help="Create a pyramidal (tiled) OME-TIFF as output.")
    parser.add_argument("--zstd", action="store_true", help="Enable Zstandard compression for output OME-TIFFs.")

    args = parser.parse_args()

    is_file = os.path.isfile(args.tiff_path)

    if args.list_channels:
        if not is_file:
            print("Error: -c/--list_channels can only be used with a single file.")
            return
        else:
            list_channels(args.tiff_path)
            return

    if args.filter is None and not args.pyramid:
        parser.print_help()
        print("\nError: No action specified. You must use -f to filter or -p to create a pyramid.")
        return

    if is_file:
        log_file = os.path.join(os.path.dirname(args.tiff_path), "Tiff-subset_error_log.txt")
        subset_tiff(args.tiff_path, args.filter, args.pyramid, log_file, use_zstd=args.zstd)
    else:
        log_file = os.path.join(args.tiff_path, "Tiff-subset_error_log.txt")
        process_folder(args.tiff_path, args.filter, args.pyramid, log_file, use_zstd=args.zstd)


if __name__ == "__main__":
    main()
