import argparse
import os
import tifffile
import numpy as np
import xml.etree.ElementTree as ET
from typing import List, Union

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

def subset_tiff(tiff_path: str, channels: Union[List[int], None]):
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
    
    write_ome_tiff(subset_image_data, subset_channel_names, output_path)
    print(f"OME-TIFF file written to {output_path}")

def process_folder(folder_path: str, channels: Union[List[int], None]):
    for root, dirs, files in os.walk(folder_path):
        for file in files:
            if file.endswith('.tiff') or file.endswith('.ome.tiff'):
                subset_tiff(os.path.join(root, file), channels)
                
def main():
    parser = argparse.ArgumentParser(description="Subset OME-TIFF files.")
    parser.add_argument("tiff_path", type=str, help="Path to the OME-TIFF file or directory.")
    parser.add_argument("-c", "--channels", type=str, help="Channels to subset, e.g., '0-5,7,10'.")
    parser.add_argument("--list-channels", action="store_true", help="List channels in the OME-TIFF file.")

    args = parser.parse_args()

    channels = parse_channels(args.channels) if args.channels else None

    if os.path.isdir(args.tiff_path):
        process_folder(args.tiff_path, channels)
    else:
        if args.list_channels:
            list_channels(args.tiff_path)
        else:
            subset_tiff(args.tiff_path, channels)

if __name__ == "__main__":
    main()
