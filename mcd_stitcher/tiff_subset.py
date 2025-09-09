import argparse
import os
import tifffile
import numpy as np
import xml.etree.ElementTree as ET
from typing import List, Union
import traceback
from datetime import datetime


def read_ome_tiff(tiff_path: str) -> (np.ndarray, List[str]):
    with tifffile.TiffFile(tiff_path) as tif:
        image_data = tif.asarray()
        ome_metadata = tif.ome_metadata

    if ome_metadata is None:
        raise ValueError(f"No OME-XML metadata found in {tiff_path}.")

    # Parse OME-XML metadata to extract channel names
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
                    DimensionOrder="XYZCT"
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

def write_ome_tiff(image_data: np.ndarray, channel_names: List[str], output_path: str):
    ome_xml = generate_ome_xml(image_data, channel_names, os.path.basename(output_path))
    tifffile.imwrite(output_path, image_data, description=ome_xml, metadata={'axes': 'CYX'})

def create_pyramid(image, levels=4):
    """Create a list of downsampled images to form pyramid levels."""
    pyramid = [image]
    for level in range(1, levels):
        scale = 2 ** level
        downsampled = image[:, ::scale, ::scale]
        pyramid.append(downsampled)
    return pyramid

def write_pyramidal_tiff(image_data: np.ndarray, channel_names: List[str], output_path: str):
    tile_size = (256, 256)
    levels = 4
    
    pyramid_levels = create_pyramid(image_data, levels=levels)
    
    with tifffile.TiffWriter(output_path, bigtiff=True) as tif:
        options = dict(tile=tile_size, metadata={'axes': 'CYX'})
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
    if not channel_str: return channels
    for part in channel_str.split(','):
        part = part.strip()
        if '-' in part:
            start, end = map(int, part.split('-'))
            channels.extend(range(start, end + 1))
        else:
            channels.append(int(part))
    return channels

def subset_tiff(tiff_path: str, filter_str: Union[str, None], pyramid: bool, log_file: str):
    try:
        print(f"Processing {tiff_path}...")
        image_data, channel_names = read_ome_tiff(tiff_path)
        
        selected_channels = []
        
        if filter_str is None:
            selected_channels = list(range(len(channel_names)))
        elif filter_str == '':
            selected_channels = [i for i, name in enumerate(channel_names) if
                               any(metal in name for metal in [f"{i}" for i in range(141, 194)])]
        else:
            selected_channels = parse_channels(filter_str)

        # Validate channel indices
        max_channel_idx = len(channel_names) - 1
        valid_channels = [c for c in selected_channels if 0 <= c <= max_channel_idx]
        invalid_channels = [c for c in selected_channels if c not in valid_channels]
        if invalid_channels:
            print(f"Warning: Channel indices {invalid_channels} are out of bounds (max is {max_channel_idx}). They will be ignored.")

        if not valid_channels:
            print(f"No valid channels to process for {tiff_path}. Skipping.")
            return
        
        # Subset the image data and channel names
        subset_image_data = image_data[valid_channels, :, :]
        subset_channel_names = [channel_names[i] for i in valid_channels]

        # Generate output path
        base, _ = os.path.splitext(tiff_path)
        if base.endswith('.ome'): base = os.path.splitext(base)[0]
        
        # Determine output filename based on actions
        suffix = "_filtered" if filter_str is not None else ""
        if pyramid:
            suffix += "_pyramid"
        
        output_path = f"{base}{suffix}.ome.tiff"
        
        if pyramid:
            write_pyramidal_tiff(subset_image_data, subset_channel_names, output_path)
        else:
            write_ome_tiff(subset_image_data, subset_channel_names, output_path)
        
        print(f"Successfully wrote {output_path}")

    except Exception as e:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        error_message = f"{timestamp} - Error processing {tiff_path}: {str(e)}\n{traceback.format_exc()}\n"
        with open(log_file, 'a') as log:
            log.write(error_message)
        print(f"{timestamp} - Error processing {tiff_path}. See log for details. Continuing...")

def process_folder(folder_path: str, filter_str: Union[str, None], pyramid: bool, log_file: str):
    for root, _, files in os.walk(folder_path):
        for file in files:
            if file.lower().endswith(('.tiff', '.ome.tiff')):
                full_path = os.path.join(root, file)
                subset_tiff(full_path, filter_str, pyramid, log_file)

def main():
    parser = argparse.ArgumentParser(description="""
    Process and subset OME-TIFF files.

    For more information on command usage, visit:
    https://github.com/PawanChaurasia/mcd_stitcher
    """)
    parser.add_argument("tiff_path", type=str, help="Path to the OME-TIFF file or directory.")
    parser.add_argument("-c", "--list_channels", action="store_true", help="Lists all channels in the specified file (file only).")
    parser.add_argument("-f", "--filter", type=str, nargs='?', const='', default=None, help="Filter and subset channels. Provide channels as a comma-separated list, e.g., '0-5,7,10'. If flag is present but no channels are given, default filtering is applied.")
    parser.add_argument("-p", "--pyramid", action="store_true", help="Create a pyramidal (tiled) OME-TIFF as output.")

    args = parser.parse_args()

    log_file = os.path.join(args.tiff_path, "Tiff-subset_error_log.txt")

    #Check if input is file or folder
    is_file = os.path.isfile(args.tiff_path)

    if args.list_channels:
        if not is_file:
            print("Error: -c/--list_channels can only be used with a single file.")
        else:
            list_channels(args.tiff_path)
        return

    if args.filter is None and not args.pyramid:
        parser.print_help()
        print("\nError: No action specified. You must use -f to filter or -p to create a pyramid.")
        return

    if not is_file:
        process_folder(args.tiff_path, args.filter, args.pyramid, log_file)
    else:
        subset_tiff(args.tiff_path, args.filter, args.pyramid, log_file)

if __name__ == "__main__":
    main()
