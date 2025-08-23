"""
OME-TIFF Channel Subsetting Tool - Development Version

This tool processes OME-TIFF files to extract specific channels, with support for:
- Channel listing and inspection
- Metal channel filtering (mass cytometry data)
- Custom channel selection
- Pyramidal TIFF generation for large images
- Batch processing of directories

Key Features:
- Preserves OME-XML metadata during channel subsetting
- Automatic metal channel detection (mass range 141-194)
- Multi-resolution pyramid generation for visualization
- Robust error handling with detailed logging
"""

import argparse
import os
import tifffile
import numpy as np
import xml.etree.ElementTree as ET
from typing import List, Union
from pathlib import Path
import traceback
from datetime import datetime


def read_ome_tiff(tiff_path: str) -> [np.ndarray, List[str]]:
    """
    Read OME-TIFF file and extract image data with channel metadata.
    
    Parses the OME-XML metadata to extract channel names, which are essential
    for maintaining proper channel identification during subsetting operations.
    
    Args:
        tiff_path: Path to the OME-TIFF file
        
    Returns:
        List of (image_data, channel_names) where:
        - image_data: numpy array with shape (channels, height, width)
        - channel_names: list of channel names from OME metadata
        
    Raises:
        Exception: If file cannot be read or OME metadata is invalid
    """
    with tifffile.TiffFile(tiff_path) as tif:
        # Load the full image stack
        image_data = tif.asarray()
        # Extract OME-XML metadata string
        ome_metadata = tif.ome_metadata

    # Parse OME-XML to extract channel information
    # Uses standard OME namespace for compatibility
    root = ET.fromstring(ome_metadata)
    namespace = {'ome': 'http://www.openmicroscopy.org/Schemas/OME/2016-06'}
    channel_elements = root.findall('.//ome:Channel', namespace)
    channel_names = [channel.get('Name') for channel in channel_elements]

    return image_data, channel_names


def write_ome_tiff(image_data: np.ndarray, channel_names: List[str], output_path: str):
    """
    Write image data to OME-TIFF format with proper metadata.
    
    Generates compliant OME-XML metadata that preserves channel information
    and spatial/dimensional properties. Critical for maintaining compatibility
    with imaging software like ImageJ, QuPath, and CellProfiler.
    
    Args:
        image_data: numpy array with shape (channels, height, width)
        channel_names: list of channel names to embed in metadata
        output_path: destination file path
    """
    # Generate channel XML elements for OME metadata
    # Each channel needs unique ID and proper attributes
    channels_xml = ''.join([
        f'<Channel ID="Channel:0:{i}" Name="{name}" SamplesPerPixel="1"/>' 
        for i, name in enumerate(channel_names)
    ])
    
    # Create complete OME-XML metadata following schema specification
    # Physical sizes set to 1.0 (micrometers assumed) - can be customized
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
    
    # Write with proper axis metadata for software compatibility
    tifffile.imwrite(output_path, image_data, description=xml_metadata, metadata={'axes': 'CYX'})


def create_pyramid(image, levels=4):
    """
    Create multi-resolution pyramid for large image visualization.
    
    Generates downsampled versions of the image at different scales (2x, 4x, 8x, etc.)
    This enables efficient viewing and navigation in imaging software, especially
    important for large mass cytometry datasets.
    
    Args:
        image: numpy array with shape (channels, height, width)
        levels: number of pyramid levels to generate
        
    Returns:
        List of numpy arrays, each representing a pyramid level
    """
    pyramid = [image]  # Level 0 is the original full-resolution image
    
    for level in range(1, levels):
        scale = 2 ** level  # 2x, 4x, 8x downsampling
        # Downsample by taking every nth pixel (simple but fast)
        downsampled = image[:, ::scale, ::scale]
        pyramid.append(downsampled)
    
    return pyramid


def write_pyramidal_tiff(image_data: np.ndarray, channel_names: List[str], output_path: str):
    """
    Write multi-resolution pyramidal TIFF for efficient large image handling.
    
    Creates a tiled, pyramidal TIFF structure that allows viewers to load
    only the resolution level needed for the current zoom level. Essential
    for large mass cytometry images that may be several GB in size.
    
    Args:
        image_data: numpy array with shape (channels, height, width)
        channel_names: list of channel names for metadata
        output_path: destination file path
    """
    tile_size = (256, 256)  # Standard tile size for efficient access
    levels = 4  # Number of pyramid levels

    # Generate all pyramid levels
    pyramid_levels = create_pyramid(image_data, levels=levels)
    
    # Use BigTIFF format for files >4GB
    with tifffile.TiffWriter(output_path, bigtiff=True) as tif:
        # Common options for all pyramid levels
        options = dict(
            tile=tile_size, 
            metadata={'axes': 'CYX', 'Channel': {'Name': channel_names}}
        )

        for level, img in enumerate(pyramid_levels):
            if level == 0:
                # Base level with SubIFDs for pyramid structure
                tif.write(img, subifds=levels-1, **options)
            else:
                # Pyramid levels marked as reduced resolution
                tif.write(img, subfiletype=1, **options)


def list_channels(tiff_path: str):
    """
    Display all available channels in the OME-TIFF file.
    
    Useful for inspecting channel content before subsetting, especially
    important for mass cytometry data where channel names indicate
    the measured proteins/markers.
    """
    image_data, channel_names = read_ome_tiff(tiff_path)
    print(f"Channels in {tiff_path}:")
    for idx, name in enumerate(channel_names):
        print(f"Channel {idx}: {name}")


def parse_channels(channel_str: str) -> List[int]:
    """
    Parse channel specification string into list of channel indices.
    
    Supports flexible channel selection syntax:
    - Individual channels: "1,3,5"
    - Ranges: "0-10"
    - Mixed: "0-5,7,10-15"
    
    Args:
        channel_str: comma-separated channel specification
        
    Returns:
        List of channel indices (0-based)
        
    Example:
        parse_channels("0-2,5,7-9") -> [0, 1, 2, 5, 7, 8, 9]
    """
    channels = []
    for part in channel_str.split(','):
        if '-' in part:
            # Handle range specification (e.g., "0-5")
            start, end = map(int, part.split('-'))
            channels.extend(range(start, end + 1))
        else:
            # Handle individual channel (e.g., "7")
            channels.append(int(part))
    return channels


def subset_tiff(tiff_path: str, channels: Union[List[int], None], pyramid: bool, log_file: str):
    """
    Main processing function to subset channels from OME-TIFF file.
    
    Handles the complete workflow:
    1. Load original OME-TIFF with metadata
    2. Apply channel filtering (custom or default metal detection)
    3. Generate output filename based on processing options
    4. Write filtered data in requested format (regular or pyramidal)
    5. Log any errors for debugging
    
    Args:
        tiff_path: path to input OME-TIFF file
        channels: list of channel indices to keep (None for auto-detection)
        pyramid: whether to create pyramidal output
        log_file: path for error logging
    """
    try:
        # Load the original image and metadata
        image_data, channel_names = read_ome_tiff(tiff_path)
        
        # Apply channel filtering logic
        if channels is None:
            # Auto-detect metal channels for mass cytometry data
            # Looks for channels containing mass numbers 141-194 (typical metal range)
            channels = [i for i, name in enumerate(channel_names) if
                        any(metal in name for metal in [f"{i}" for i in range(141, 194)])]
        
        # Extract the requested channels and their metadata
        subset_image_data = image_data[channels, :, :]
        subset_channel_names = [channel_names[i] for i in channels]

        # Generate appropriate output filename
        base, ext = os.path.splitext(tiff_path)
        output_path = f"{base}_filtered.ome.tiff"
        
        if pyramid:
            output_path = f"{base}_filtered_pyramid.ome.tiff"
            # Create multi-resolution pyramidal TIFF
            write_pyramidal_tiff(subset_image_data, subset_channel_names, output_path)
        else:
            # Create standard OME-TIFF
            write_ome_tiff(subset_image_data, subset_channel_names, output_path)
        
        print(f"OME-TIFF file written to {output_path}")
        
    except Exception as e:
        # Comprehensive error logging for debugging
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(log_file, 'a') as log:
            log.write(f"{timestamp} - Error processing {tiff_path}: {str(e)}\n")
            log.write(traceback.format_exc() + '\n')
        print(f"{timestamp} - Error processing {tiff_path}. Logged the error and continuing...")


def process_folder(folder_path: str, pyramid: bool, log_file: str):
    """
    Batch process all OME-TIFF files in a directory tree.
    
    Recursively searches for TIFF files and applies default metal channel
    filtering to each. Useful for processing entire experiments or datasets
    with consistent channel filtering needs.
    
    Args:
        folder_path: root directory to search for TIFF files
        pyramid: whether to create pyramidal outputs
        log_file: path for error logging
    """
    # Walk through all subdirectories
    for root, dirs, files in os.walk(folder_path):
        for file in files:
            # Process both .tiff and .ome.tiff extensions
            if file.endswith('.tiff') or file.endswith('.ome.tiff'):
                # Apply default filtering (None triggers metal detection)
                subset_tiff(os.path.join(root, file), None, pyramid, log_file)


def main():
    """
    Command-line interface for OME-TIFF channel subsetting.
    
    Provides flexible options for different use cases:
    - Single file or batch directory processing
    - Channel inspection or filtering
    - Regular or pyramidal output formats
    """
    parser = argparse.ArgumentParser(description="""
    Subset OME-TIFF files by extracting specific channels.
    
    This tool is designed for mass cytometry data processing, with automatic
    detection of metal channels (mass 141-194) and support for large image
    pyramidal formats for efficient visualization.

    For more information on command usage, visit:
    https://github.com/PawanChaurasia/mcd_stitcher
    """)
    
    # Positional argument for input path
    parser.add_argument("tiff_path", type=str, 
                       help="Path to the OME-TIFF file or directory containing TIFF files.")
    
    # Optional flags for different operations
    parser.add_argument("-c", action="store_true", 
                       help="List all channels in the OME-TIFF file with their indices.")
    
    parser.add_argument("-f", type=str, nargs='?', const='', 
                       help="Filter and subset channels. Provide channel specification "
                            "(e.g., '0-5,7,10') or leave empty for automatic metal channel detection.")
    
    parser.add_argument("-p", action="store_true", 
                       help="Create pyramidal-tiled OME-TIFF for efficient large image viewing.")

    args = parser.parse_args()

    # Set up error logging in the same directory as input
    if os.path.isdir(args.tiff_path):
        log_file = os.path.join(args.tiff_path, "error_log.txt")
    else:
        log_file = os.path.join(os.path.dirname(args.tiff_path), "error_log.txt")

    # Route to appropriate processing function based on input type
    if os.path.isdir(args.tiff_path):
        # Batch processing mode
        process_folder(args.tiff_path, args.p, log_file)
    else:
        # Single file processing mode
        if args.c:
            # Channel listing mode
            list_channels(args.tiff_path)
        elif args.f is not None:
            # Channel filtering mode
            channels = parse_channels(args.f) if args.f else None
            subset_tiff(args.tiff_path, channels, args.p, log_file)
        else:
            # No operation specified - show help
            print("No action specified. Use -c to list channels, -f to filter and subset channels, or -p to create a pyramidal OME-TIFF.")


if __name__ == "__main__":
    main()
