"""
This tool processes OME-TIFF files to extract specific channels, with support for:
Supports processing both:
- Channel listing and inspection
- Stitched TIFFs created via `mcd_stitch`
- Metal channel filtering (mass cytometry data)
- ROI TIFFs exported from Zarr via `mcd_convert -> zarr2tiff`
- Custom channel selection
- Pyramidal TIFF generation for large images

Main capabilities:
- List channel names from OME metadata
- Subset TIFFs by channel indices
- Create pyramidal OME-TIFF outputs
- Batch process directories
"""

import argparse
import os
import tifffile
import numpy as np
import xml.etree.ElementTree as ET
from typing import List, Union
import traceback
from datetime import datetime
from pathlib import Path


# --------------------------
# Metadata & IO utilities
# --------------------------

def read_ome_tiff(tiff_path: str):
    """
    Read TIFF pixel data and key OME-XML fields commonly needed downstream.
    Returns:
      - image_data: np.ndarray (expected CYX)
      - channel_names: List[str]
      - psx: float (PhysicalSizeX, micrometers)
      - psy: float (PhysicalSizeY, micrometers)
      - size_x: int
      - size_y: int
      - dtype_str: str (NumPy dtype string)
      - dim_order: str (OME dimension order, e.g., 'XYCZT')
      - ome_xml: str (full original OME-XML)
    """
    with tifffile.TiffFile(tiff_path) as tif:
        image_data = tif.asarray()
        ome_xml = tif.ome_metadata

    if ome_xml is None:
        raise ValueError(f"No OME-XML metadata found in {tiff_path}.")

    root = ET.fromstring(ome_xml)
    ns = {'ome': 'http://www.openmicroscopy.org/Schemas/OME/2016-06'}

    # Channels
    channel_elements = root.findall('.//ome:Channel', ns)
    channel_names = [ch.get('Name') for ch in channel_elements]

    # Pixels node
    pixels = root.find('.//ome:Pixels', ns)
    if pixels is None:
        raise ValueError("OME-XML Pixels element missing.")

    dim_order = pixels.get('DimensionOrder', 'XYCZT')
    size_x = int(pixels.get('SizeX', image_data.shape[-1]))
    size_y = int(pixels.get('SizeY', image_data.shape[-2]))
    psx = float(pixels.get('PhysicalSizeX', '1.0'))
    psy = float(pixels.get('PhysicalSizeY', '1.0'))

    dtype_str = str(image_data.dtype)

    return image_data, channel_names, psx, psy, size_x, size_y, dtype_str, dim_order, ome_xml


def generate_ome_xml(image_data: np.ndarray, channel_names: List[str], base_name: str, psx: float, psy: float) -> str:
    """
    Build a minimal OME-XML header string given image shape and channels.
    """
    channels_xml = ''.join([
        f'<Channel ID="Channel:0:{i}" Name="{name}" SamplesPerPixel="1"/>'
        for i, name in enumerate(channel_names)
    ])

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
                    PhysicalSizeX="{psx}"
                    PhysicalSizeY="{psy}"
                    Type="{image_data.dtype}">
                <TiffData />
                {channels_xml}
            </Pixels>
        </Image>
    </OME>"""
    return xml_metadata


def write_ome_tiff(image_data: np.ndarray, channel_names: List[str], output_path: str, use_zstd: bool, psx: float, psy: float):
    """
    Write a simple OME-TIFF with given channel subset.
    """
    ome_xml = generate_ome_xml(image_data, channel_names, os.path.basename(output_path), psx, psy)
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

# --------------------------
# Pyramid utilities
# --------------------------

def create_pyramid(image, levels=4):
    """
    Create a simple downsampled image pyramid (factor of 2 at each level).
    """
    pyramid = [image]
    for level in range(1, levels):
        scale = 2 ** level
        downsampled = image[:, ::scale, ::scale]
        pyramid.append(downsampled)
    return pyramid


def write_pyramidal_tiff(image_data: np.ndarray, channel_names: List[str], output_path: str, use_zstd: bool, psx: float, psy: float):
    """
    Write a tiled pyramid OME-TIFF (multi-resolution).
    """
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
        ome_xml = generate_ome_xml(image_data, channel_names, os.path.basename(output_path), psx, psy)

        for i, level_data in enumerate(pyramid_levels):
            if i == 0:
                # Base level with embedded OME-XML + sub-IFDs for other levels
                tif.write(level_data, subifds=levels - 1, description=ome_xml, **options)
            else:
                # Reduced-resolution levels
                tif.write(level_data, subfiletype=1, **options)


# --------------------------
# Channel handling
# --------------------------

def list_channels(tiff_path: str):
    """
    Utility to quickly list all channel names in a TIFF.
    """
    _, channel_names = read_ome_tiff(tiff_path)
    print(f"Channels in {tiff_path}:")
    for idx, name in enumerate(channel_names):
        print(f"Channel {idx}: {name}")


def parse_channels(channel_str: str) -> List[int]:
    """
    Parse CLI input like "0-5,7,10" into a list of channel indices.
    """
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


# --------------------------
# Subsetting
# --------------------------

def subset_tiff(tiff_path: str, filter_str: Union[str, None], pyramid: bool, log_file: str, root_path: str = None, use_zstd: bool = False):
    """
    Subset a single TIFF by channel list and/or write pyramid.
    Saves new OME-TIFF with suffix (_filtered, _pyramid).
    """
    try:
        # Print relative path if root folder is given
        if root_path:
            rel_path = os.path.relpath(tiff_path, root_path)
            print(f"Processing {rel_path}...")
        else:
            print(f"Processing {tiff_path}...")
            
        image_data, channel_names = read_ome_tiff(tiff_path)
        
        # Select channels
        if filter_str is None:
            selected_channels = list(range(len(channel_names)))   # default: all
        elif filter_str == '':
            # Default filter mode (metal channels only, 141–193)
            selected_channels = [
                i for i, name in enumerate(channel_names)
                if any(metal in name for metal in [f"{i}" for i in range(141, 194)])
            ]
        else:
            selected_channels = parse_channels(filter_str)

        # Validate channels
        max_channel_idx = len(channel_names) - 1
        valid_channels = [c for c in selected_channels if 0 <= c <= max_channel_idx]
        invalid_channels = [c for c in selected_channels if c not in valid_channels]
        if invalid_channels:
            print(f"Warning: Skipping invalid channel indices {invalid_channels} (max index = {max_channel_idx}).")

        if not valid_channels:
            print(f"No valid channels to process for {tiff_path}. Skipping.")
            return
        
        # Subset image & metadata
        subset_image_data = image_data[valid_channels, :, :]
        subset_channel_names = [channel_names[i] for i in valid_channels]

        # Build output filename
        base, _ = os.path.splitext(tiff_path)
        if base.endswith('.ome'):
            base = os.path.splitext(base)[0]
        
        suffix = "_filtered" if filter_str is not None else ""
        if pyramid:
            suffix += "_pyramid"
        
        output_path = f"{base}{suffix}.ome.tiff"
        
        # Write output
        if pyramid:
            write_pyramidal_tiff(subset_image_data, subset_channel_names, output_path, use_zstd, psx, psy)
        else:
            write_ome_tiff(subset_image_data, subset_channel_names, output_path, use_zstd, psx, psy)
        
        if root_path:
            rel_output = os.path.relpath(output_path, root_path)
            print(f"Successfully wrote {rel_output}")
        else:
            print(f"Successfully wrote {output_path}")

    except Exception as e:
        # Log errors to a timestamped file, continue batch
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        error_message = f"{timestamp} - Error processing {tiff_path}: {str(e)}\n{traceback.format_exc()}\n"
        with open(log_file, 'a') as log:
            log.write(error_message)
        print(f"{timestamp} - Error processing {tiff_path}. See log for details. Continuing...")


# --------------------------
# Batch processing
# --------------------------

def snapshot_tiff_files(folder_path: str) -> List[Path]:
    """
    Snapshot all TIFFs in a folder tree so we don't pick up files written mid-run.
    """
    folder_path = Path(folder_path)
    tiff_files = [
        f for f in folder_path.rglob("*")
        if f.is_file() and f.suffix.lower() in (".tiff", ".ome.tiff")
    ]
    return tiff_files


def process_folder(folder_path: str, filter_str: Union[str, None], pyramid: bool, log_file: str, use_zstd: bool):
    """
    Process all TIFF files in a directory (non-recursive by snapshot).
    """
    files_to_process = snapshot_tiff_files(folder_path)
    
    if not files_to_process:
        print("No TIFF files found to process.")
        return
    
    print(f"Found {len(files_to_process)} TIFF files to process.\n")
    
    for tiff_file in files_to_process:
        subset_tiff(str(tiff_file), filter_str, pyramid, log_file, folder_path, use_zstd)


# --------------------------
# CLI entrypoint
# --------------------------

def main():
    parser = argparse.ArgumentParser(description="""
    Process and subset OME-TIFF files.

    Supports:
    - Flat structure: stitched TIFFs from mcd_stitch
    - Nested structure: per-ROI TIFFs from mcd_convert -> zarr2tiff

    Examples:
    - List channels:           python tiff_subset.py file.ome.tiff -c
    - Keep all channels:       python tiff_subset.py file.ome.tiff -f
    - Subset specific:         python tiff_subset.py file.ome.tiff -f "0-5,7,10"
    - Create pyramids:         python tiff_subset.py folder/ -p
    - Combine filter+pyramid:  python tiff_subset.py folder/ -f "0-10" -p
    """)
    parser.add_argument("tiff_path", type=str, help="Path to an OME-TIFF file OR a directory of OME-TIFFs.")
    parser.add_argument("-c", "--list_channels", action="store_true", help="List channels in the specified file (file only).")
    parser.add_argument("-f", "--filter", type=str, nargs='?', const='', default=None,
                        help="Filter channels: comma list (e.g. '0-5,7,10'). "
                             "If flag present but empty, defaults to metal channels (141–193).")
    parser.add_argument("-p", "--pyramid", action="store_true", help="Create a pyramidal (tiled) OME-TIFF output.")
    parser.add_argument("--zstd", action="store_true", help="Enable Zstandard compression for output OME-TIFFs.")

    args = parser.parse_args()

    is_file = os.path.isfile(args.tiff_path)

    # Channel listing mode
    if args.list_channels:
        if not is_file:
            print("Error: --list_channels only valid for a single TIFF file.")
            return
        else:
            list_channels(args.tiff_path)
            return

    # Safety: if no filter nor pyramid → nothing to do
    if args.filter is None and not args.pyramid:
        parser.print_help()
        print("\nError: No action specified. Use -f to filter and/or -p to create pyramids.")
        return

    # Do work
    if is_file:
        log_file = os.path.join(os.path.dirname(args.tiff_path), "Tiff-subset_error_log.txt")
        subset_tiff(args.tiff_path, args.filter, args.pyramid, log_file, use_zstd=args.zstd)
    else:
        log_file = os.path.join(args.tiff_path, "Tiff-subset_error_log.txt")
        process_folder(args.tiff_path, args.filter, args.pyramid, log_file, use_zstd=args.zstd)


if __name__ == "__main__":
    main()
