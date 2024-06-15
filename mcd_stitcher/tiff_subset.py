import argparse
import os
import tifffile
import numpy as np
import xml.etree.ElementTree as ET
from typing import List, Union
from pathlib import Path
import traceback
from datetime import datetime


def read_ome_tiff(tiff_path: str) -> (np.ndarray, List[str]):
    with tifffile.TiffFile(tiff_path) as tif:
        image_data = tif.asarray()
        ome_metadata = tif.ome_metadata

    # Parse OME-XML metadata to extract channel names
    root = ET.fromstring(ome_metadata)
    namespace = {'ome': 'http://www.openmicroscopy.org/Schemas/OME/2016-06'}
    channel_elements = root.findall('.//ome:Channel', namespace)
    channel_names = [channel.get('Name') for channel in channel_elements]

    return image_data, channel_names

def write_ome_tiff(image_data: np.ndarray, channel_names: List[str], output_path: str):
    # Generate OME-XML metadata
    channels_xml = ''.join([f'<Channel ID="Channel:0:{i}" Name="{name}" SamplesPerPixel="1"/>' for i, name in enumerate(channel_names)])
    xml_metadata = f"""<?xml version="1.0" encoding="UTF-8"?>
    <OME xmlns="http://www.openmicroscopy.org/Schemas/OME/2016-06"
        xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
        xsi:schemaLocation="http://www.openmicroscopy.org/Schemas/OME/2016-06 http://www.openmicroscopy.org/Schemas/OME/2016-06/ome.xsd">
        <Image ID="Image:0" Name="{os.path.basename(output_path)}">
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
                    Type="uint16">
                <TiffData />
                {channels_xml}
            </Pixels>
        </Image>
    </OME>"""
    
    # Write OME-TIFF file
    tifffile.imwrite(output_path, image_data, description=xml_metadata, metadata={'axes': 'CYX'})

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
        options = dict(tile=tile_size, metadata={'axes': 'CYX', 'Channel': {'Name': channel_names}})

        for level, img in enumerate(pyramid_levels):
            if level == 0:
                # Write base level
                tif.write(img, subifds=levels-1, **options)
            else:
                # Write pyramid levels
                tif.write(img, subfiletype=1, **options)

def list_channels(tiff_path: str):
    image_data, channel_names = read_ome_tiff(tiff_path)
    print(f"Channels in {tiff_path}:")
    for idx, name in enumerate(channel_names):
        print(f"Channel {idx}: {name}")

def parse_channels(channel_str: str) -> List[int]:
    channels = []
    for part in channel_str.split(','):
        if '-' in part:
            start, end = map(int, part.split('-'))
            channels.extend(range(start, end + 1))
        else:
            channels.append(int(part))
    return channels

def subset_tiff(tiff_path: str, channels: Union[List[int], None], pyramid: bool, log_file: str):
    try:
        image_data, channel_names = read_ome_tiff(tiff_path)
        
        if channels is None:
            channels = [i for i, name in enumerate(channel_names) if
                        any(metal in name for metal in [f"{i}" for i in range(141, 194)])]
        
        # Subset the image data and channel names
        subset_image_data = image_data[channels, :, :]
        subset_channel_names = [channel_names[i] for i in channels]

        # Generate output path
        base, ext = os.path.splitext(tiff_path)
        output_path = f"{base}_filtered.ome.tiff"
        
        if pyramid:
            output_path = f"{base}_filtered_pyramid.ome.tiff"
            # Create and write pyramidal OME-TIFF
            write_pyramidal_tiff(subset_image_data, subset_channel_names, output_path)
        else:
            # Write regular OME-TIFF
            write_ome_tiff(subset_image_data, subset_channel_names, output_path)
        
        print(f"OME-TIFF file written to {output_path}")
    except Exception as e:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(log_file, 'a') as log:
            log.write(f"{timestamp} - Error processing {tiff_path}: {str(e)}\n")
            log.write(traceback.format_exc() + '\n')
        print(f"{timestamp} - Error processing {tiff_path}. Logged the error and continuing...")

def process_folder(folder_path: str, pyramid: bool, log_file: str):
    for root, dirs, files in os.walk(folder_path):
        for file in files:
            if file.endswith('.tiff') or file.endswith('.ome.tiff'):
                subset_tiff(os.path.join(root, file), None, pyramid, log_file)

def main():
    parser = argparse.ArgumentParser(description="""
    Subset OME-TIFF files.

    For more information on command usage, visit:
    https://github.com/PawanChaurasia/mcd_stitcher
    """)
    parser.add_argument("tiff_path", type=str, help="Path to the OME-TIFF file or directory.")
    parser.add_argument("-c", action="store_true", help="Lists all channels in the OME-TIFF file.")
    parser.add_argument("-f", type=str, nargs='?', const='', help="Filter and subset channels. Provide channels to subset, e.g., '0-5,7,10'. If no channels are provided, default filtering is applied.")
    parser.add_argument("-p", action="store_true", help="Create pyramidal-tiled OME-TIFF")

    args = parser.parse_args()

    log_file = os.path.join(args.tiff_path, "error_log.txt")

    if os.path.isdir(args.tiff_path):
        process_folder(args.tiff_path, args.p, log_file)
    else:
        if args.c:
            list_channels(args.tiff_path)
        elif args.f is not None:
            channels = parse_channels(args.f) if args.f else None
            subset_tiff(args.tiff_path, channels, args.p, log_file)
        else:
            print("No action specified. Use -c to list channels, -f to filter and subset channels, or -p to create a pyramidal OME-TIFF.")

if __name__ == "__main__":
    main()
