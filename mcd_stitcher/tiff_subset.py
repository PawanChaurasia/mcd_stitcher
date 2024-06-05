import argparse
import os
import tifffile
import numpy as np
import xml.etree.ElementTree as ET
from typing import List, Union
from pathlib import Path

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

def create_pyramid(image, levels):
    """Create a list of downsampled images to form pyramid levels."""
    pyramid = [image]
    for level in range(1, levels):
        scale = 2 ** level
        downsampled = image[:, ::scale, ::scale]
        pyramid.append(downsampled)
    return pyramid

def write_pyramidal_tiff(input_path, tile_size=(256, 256), levels=4):
    with tifffile.TiffFile(input_path) as tif:
        image_data = tif.asarray()
        ome_metadata = tif.ome_metadata

    # Parse OME-XML metadata
    root = ET.fromstring(ome_metadata)
    metadata_dict = {elem.tag: elem.text for elem in root.iter()}
    
    pyramid_levels = create_pyramid(image_data, levels=levels)  # 1 base level + 3 additional levels
    
    base, ext = os.path.splitext(input_path)
    output_path = f"{base}_pyramidal.ome.tiff"

    with tifffile.TiffWriter(output_path, bigtiff=True) as tif:
        options = dict(tile=tile_size, metadata=metadata_dict)

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

def subset_tiff(tiff_path: str, channels: Union[List[int], None], pyramid: bool, tile_size: tuple, levels: int):
    image_data, channel_names = read_ome_tiff(tiff_path)
    
    if channels is None:
        channels = [i for i, name in enumerate(channel_names) if 'X' not in name and 'Y' not in name and 'Z' not in name and
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
        with tifffile.TiffWriter(output_path, bigtiff=True) as tif:
            options = dict(tile=tile_size, metadata={'axes': 'CYX'})
            pyramid_levels = create_pyramid(subset_image_data, levels=levels)

            for level, img in enumerate(pyramid_levels):
                if level == 0:
                    tif.write(img, subifds=levels-1, **options)
                else:
                    tif.write(img, subfiletype=1, **options)
    else:
        # Write regular OME-TIFF
        write_ome_tiff(subset_image_data, subset_channel_names, output_path)
    
    print(f"OME-TIFF file written to {output_path}")

def process_folder(folder_path: str, pyramid: bool, tile_size: tuple, levels: int):
    for root, dirs, files in os.walk(folder_path):
        for file in files:
            if file.endswith('.tiff') or file.endswith('.ome.tiff'):
                subset_tiff(os.path.join(root, file), None, pyramid, tile_size, levels)

def main():
    parser = argparse.ArgumentParser(description="Subset OME-TIFF files.")
    parser.add_argument("tiff_path", type=str, help="Path to the OME-TIFF file or directory.")
    parser.add_argument("-c", "--channels", type=str, help="Channels to subset, e.g., '0-5,7,10'.")
    parser.add_argument("--list-channels", action="store_true", help="List channels in the OME-TIFF file.")
    parser.add_argument("--pyramid", action="store_true", help="Create pyramidal OME-TIFF with tiling.")
    parser.add_argument("--tile-size", type=int, nargs=2, default=(256, 256), help="Tile size for pyramidal OME-TIFF.")
    parser.add_argument("--levels", type=int, default=4, help="Number of pyramid levels.")

    args = parser.parse_args()

    if os.path.isdir(args.tiff_path):
        process_folder(args.tiff_path, args.pyramid, tuple(args.tile_size), args.levels)
    else:
        if args.list_channels:
            list_channels(args.tiff_path)
        else:
            channels = parse_channels(args.channels) if args.channels else None
            subset_tiff(args.tiff_path, channels, args.pyramid, tuple(args.tile_size), args.levels)

if __name__ == "__main__":
    main()
