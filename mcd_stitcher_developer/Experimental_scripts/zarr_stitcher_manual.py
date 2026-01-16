"""
Manual Zarr Stitcher - Interactive ROI selection and ordering

This script processes a single Zarr folder at a time with manual control over:
- Which ROIs to include/exclude (skip corrupted ROIs)
- The exact order of stitching (controls overlap behavior)

Usage:
    python zarr_manual_stitcher.py /path/to/zarr_folder [output_folder] [--zstd] [--verbose]

The script will:
1. Read all ROIs from the Zarr folder
2. Display a summary table with indices, ROI IDs, timestamps, and coordinates
3. Show the default stitch order (newest first)
4. Prompt you to either:
   - Press Enter to accept the default order
   - Enter comma-separated indices to reorder/skip ROIs (e.g., "0,3,5,7,8")
5. Stitch only the selected ROIs in your specified order
"""

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Union, List, Dict, Optional

import math
import numpy as np
import tifffile
import xarray as xr
import xmltodict
import zarr
import click

logger = logging.getLogger(__name__)


class ManualZarrStitcher:
    def __init__(self, zarr_folder: Union[str, Path], stitch_folder: Union[str, Path], use_zstd: bool = False):
        self.zarr_folder = Path(zarr_folder)
        
        if not self.zarr_folder.exists():
            raise FileNotFoundError(f"Zarr folder does not exist: {zarr_folder}")
        if not self.zarr_folder.is_dir():
            raise ValueError(f"Path is not a directory: {zarr_folder}")
        
        self.stitch_folder = Path(stitch_folder)
        self.stitch_folder.mkdir(parents=True, exist_ok=True)
        
        self.use_zstd = use_zstd
        self.log_file = self.zarr_folder / "manual_stitching_error_log.txt"

    def log_error(self, message: str) -> None:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_message = f"{timestamp} - {message}"
        
        try:
            with open(self.log_file, "a", encoding='utf-8') as f:
                f.write(f"{log_message}\n")
        except Exception as e:
            logger.warning(f"Failed to write to log file: {e}")
        
        logger.error(message)

    def extract_metadata(self, zarr_path: Path) -> List[Dict]:
        if not zarr_path.exists():
            raise FileNotFoundError(f"Zarr path does not exist: {zarr_path}")
        
        metadata = []
        try:
            zarr_file = zarr.open(str(zarr_path), mode='r')
            
            if not zarr_file.keys():
                logger.warning(f"No groups found in Zarr file: {zarr_path}")
                return metadata
            
            for group_key in zarr_file.keys():
                group = zarr_file[group_key]
                if 'meta' in group.attrs:
                    metas = group.attrs['meta']
                    for meta in metas:
                        required_fields = ['q_stage_x', 'q_stage_y', 'q_timestamp', 'q_maxx', 'q_maxy', 'q_id']
                        if all(field in meta for field in required_fields):
                            roi_meta = {
                                'stage_x': float(meta['q_stage_x']),
                                'stage_y': float(meta['q_stage_y']),
                                'timestamp': meta['q_timestamp'],
                                'width': int(meta['q_maxx']),
                                'height': int(meta['q_maxy']),
                                'roi_id': meta.get('q_id'),  # keep for internal lookups/logging
                                'description': meta.get('q_description') or meta.get('description') or "",
                                'file_path': zarr_path / group_key,
                                'channels': meta.get('channels', [])
                            }
                            metadata.append(roi_meta)
                            
        except Exception as e:
            self.log_error(f"Error extracting metadata from {zarr_path}: {e}")
            
        return metadata
    
    def convert_timestamp_to_simple_format(self, timestamp: str) -> str:
        try:
            dt = datetime.fromisoformat(timestamp.split("+")[0].split(".")[0])
            return dt.strftime('%Y-%m-%dT%H:%M:%S')
        except Exception as e:
            logger.warning(f"Failed to parse timestamp {timestamp}: {e}")
            return timestamp
    
    def extract_channel_names(self, zarr_folder: Path, acquisition_id: int) -> List[str]:
        schema_file = zarr_folder / "mcd_schema.xml"
        
        if not schema_file.exists():
            raise FileNotFoundError(f"Schema file not found: {schema_file}")
        
        try:
            with open(schema_file, 'r', encoding='utf-8') as file:
                xml_content = file.read()
                schema = xmltodict.parse(xml_content)
        except Exception as e:
            raise ValueError(f"Failed to parse XML schema file {schema_file}: {e}")
        
        channel_names = []
        try:
            channels = schema['MCDSchema']['AcquisitionChannel']
            if isinstance(channels, list):
                for channel in channels:
                    if channel['AcquisitionID'] == str(acquisition_id):
                        channel_names.append(channel['ChannelLabel'])
            else:
                if channels['AcquisitionID'] == str(acquisition_id):
                    channel_names.append(channels['ChannelLabel'])
        except KeyError as e:
            raise ValueError(f"Invalid XML schema structure: missing {e}")
        
        return channel_names
    
    def channels_by_roi(self, zarr_folder: Path, rois: List[Dict]) -> Dict[int, List[str]]:
        channels_by_roi = {}

        for roi in rois:
            try:
                channels = self.extract_channel_names(zarr_folder, roi['roi_id'])
                channels_by_roi[roi['roi_id']] = channels
            except Exception as e:
                self.log_error(f"Error extracting channels for ROI ID: {roi['roi_id']} in {roi['file_path']}, Error: {e}")

        return channels_by_roi

    def compare_channels(self, channels_by_roi: Dict[int, List[str]]) -> Optional[List[str]]:
        if not channels_by_roi:
            return None
        
        main_channel_labels = None

        for roi_id, channels in channels_by_roi.items():
            if main_channel_labels is None:
                main_channel_labels = channels
            elif channels != main_channel_labels:
                self.log_error(f"Channel mismatch in ROI ID {roi_id}: {channels}")

        return main_channel_labels

    def print_roi_summary_and_get_order(self, rois: List[Dict]) -> List[Dict]:
        """
        Show a numbered summary of ROIs and prompt for an order like "0,3,5,7".
        - Default order: timestamp descending (newest first)
        - If user presses Enter: use default order
        - If user enters comma-list: validate and use that order, skipping unspecified ROIs
        Returns the list of ROI dicts in the chosen order.
        """
        if not rois:
            raise ValueError("No ROIs to summarize")

        # Build default order (newest first by timestamp)
        default_order = sorted(
            rois,
            key=lambda r: self.convert_timestamp_to_simple_format(r['timestamp']),
            reverse=True
        )

        # Print summary table
        print("\n" + "="*90)
        print("DETECTED ROIs")
        print("="*90)
        print(f"{'Idx':<4} | {'Description':<40} | {'Timestamp':<19} | {'StageX':<8} | {'StageY':<8} | {'Size (W×H)':<12}")
        print("-"*90)
        for idx, r in enumerate(default_order):
            ts = self.convert_timestamp_to_simple_format(r['timestamp'])
            desc = (r.get('description') or "").strip()
            if len(desc) > 40:
                desc = desc[:37] + "..."
            print(
                f"{idx:<4} | {desc:<40} | {ts:<19} | "
                f"{r['stage_x']:>8.1f} | {r['stage_y']:>8.1f} | {r['width']:>4} × {r['height']:<4}"
            )
        print("="*90)

        # Show default order indices for clarity
        default_indices = ",".join(str(i) for i in range(len(default_order)))
        print(f"\nDefault stitch order (newest first): {default_indices}")
        print("\nNote: Later ROIs in the order will overwrite earlier ones in overlapping regions.")

        # Prompt
        user = input('\nPress Enter to accept default, or enter comma-separated indices (e.g., "0,3,5,7,8"): ').strip()

        if user == "":
            print("✓ Using default order.")
            return default_order

        # Parse input indices
        try:
            parts = [p.strip() for p in user.split(",") if p.strip() != ""]
            indices = [int(p) for p in parts]
        except Exception:
            raise ValueError(f"Invalid input: '{user}'. Expected comma-separated integers, e.g., 0,3,5")

        # Validate indices
        max_idx = len(default_order) - 1
        invalid = [i for i in indices if i < 0 or i > max_idx]
        if invalid:
            raise ValueError(f"Invalid indices {invalid}. Valid range is 0..{max_idx}")

        # Deduplicate while keeping order
        seen = set()
        final_indices = []
        for i in indices:
            if i not in seen:
                seen.add(i)
                final_indices.append(i)

        selected_rois = [default_order[i] for i in final_indices]

        print(f"✓ Using custom order: {','.join(str(i) for i in final_indices)}")
        print(f"  ({len(selected_rois)} ROIs selected, {len(default_order) - len(selected_rois)} skipped)")
        return selected_rois

    def stitch_rois(self, rois: List[Dict], output_path: Path, main_channel_labels: List[str]) -> None:
        if not rois:
            raise ValueError("No ROIs provided for stitching")

        logger.info(f"Stitching {len(rois)} ROIs in specified order")

        # Calculate bounds (1 µm/px assumption)
        min_x = min(roi['stage_x'] for roi in rois)
        min_y = min(roi['stage_y'] - roi['height'] for roi in rois)
        max_x = max(roi['stage_x'] + roi['width'] for roi in rois)
        max_y = max(roi['stage_y'] for roi in rois)

        stitched_width  = int(math.ceil(max_x - min_x))
        stitched_height = int(math.ceil(max_y - min_y))
        
        logger.info(f"Canvas size: {stitched_width} × {stitched_height} pixels")

        # Determine max channels
        max_channels = 0
        for roi in rois:
            try:
                sample_zarr = zarr.open(roi['file_path'], mode='r')
                data_key = list(sample_zarr.keys())[0]
                num_channels = sample_zarr[data_key][:].shape[0]
                max_channels = max(max_channels, num_channels)
            except Exception as e:
                self.log_error(f"Error determining channels for ROI ID: {roi['roi_id']}: {e}")

        # Initialize stitched image
        stitched_image = np.zeros((max_channels, stitched_height, stitched_width), dtype=np.uint16)

        def load_and_prepare(roi):
            try:
                zarr_group = zarr.open(roi['file_path'], mode='r')
                image_key = list(zarr_group.keys())[0]
                image = zarr_group[image_key][:]
                
                if image.shape == (1, 1, 1):
                    logger.warning(f"Skipping empty ROI ID: {roi['roi_id']}")
                    return None
                
                x_offset = int(roi['stage_x'] - min_x)
                y_offset = int(max_y - roi['stage_y'])
                return (image, x_offset, y_offset, roi['roi_id'])
                
            except Exception as e:
                self.log_error(f"Error processing ROI ID: {roi['roi_id']}: {e}")
                return None

        # Load and place ROIs in the specified order
        for idx, roi in enumerate(rois):
            logger.info(f"Processing ROI {idx+1}/{len(rois)}: ID {roi['roi_id']}")
            result = load_and_prepare(roi)
            
            if result is None:
                continue
                
            image, x_offset, y_offset, roi_id = result
            try:
                stitched_image[:, y_offset:y_offset + image.shape[1], x_offset:x_offset + image.shape[2]] = image
            except Exception as e:
                self.log_error(f"Placement failed for ROI {roi_id} at offsets (x={x_offset}, y={y_offset}) "
                               f"with ROI size {image.shape[2]}×{image.shape[1]}: {e}")

        # Convert to xarray
        stitched_da = xr.DataArray(
            stitched_image,
            dims=("c", "y", "x"),
            coords={
                "c": main_channel_labels[:max_channels], 
                "y": range(stitched_height), 
                "x": range(stitched_width)
            }
        )

        self.write_ometiff(stitched_da, output_path)

    def write_ometiff(self, imarr: xr.DataArray, outpath: Union[Path, str], **kwargs) -> None:
        outpath = Path(outpath)
        imarr = imarr.transpose("c", "y", "x")
        Nc, Ny, Nx = imarr.shape
        
        channels_xml = '\n'.join([
            f'<Channel ID="Channel:0:{i}" Name="{channel}" SamplesPerPixel="1" />'
            for i, channel in enumerate(imarr.c.values)
        ])
        
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<OME xmlns="http://www.openmicroscopy.org/Schemas/OME/2016-06"
     xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
     xsi:schemaLocation="http://www.openmicroscopy.org/Schemas/OME/2016-06 http://www.openmicroscopy.org/Schemas/OME/2016-06/ome.xsd">
    <Image ID="Image:0" Name="{outpath.stem}">
        <Pixels BigEndian="false"
                DimensionOrder="XYZCT"
                ID="Pixels:0"
                Interleaved="false"
                SizeC="{Nc}"
                SizeT="1"
                SizeX="{Nx}"
                SizeY="{Ny}"
                SizeZ="1"
                PhysicalSizeX="1.0"
                PhysicalSizeY="1.0"
                Type="uint16">
            <TiffData />
            {channels_xml}
        </Pixels>
    </Image>
</OME>"""

        outpath.parent.mkdir(parents=True, exist_ok=True)
        
        tiff_kwargs = {
            'data': imarr.values,
            'description': xml,
            'metadata': {'axes': 'CYX'},
            'bigtiff': True,
            'tile': (256, 256),
            'resolution': (25400, 25400),
            'resolutionunit': 'inch',
            **kwargs
        }
        
        if self.use_zstd:
            tiff_kwargs['compression'] = 'zstd'
            tiff_kwargs['compressionargs'] = {'level': 15}
        
        try:
            tifffile.imwrite(outpath, **tiff_kwargs)
            logger.info(f"Successfully wrote: {outpath}")
        except Exception as e:
            logger.error(f"Failed to write OME-TIFF {outpath}: {e}")
            raise

    def process_folder(self) -> None:
        logger.info(f"Processing folder: {self.zarr_folder.name}")

        schema_file = self.zarr_folder / "mcd_schema.xml"
        if not schema_file.exists():
            raise FileNotFoundError(f"Missing mcd_schema.xml in {self.zarr_folder}")

        output_filename = f"{self.zarr_folder.name}_manual_stitched.ome.tiff"
        output_path = self.stitch_folder / output_filename

        # Extract ROI metadata
        rois = self.extract_metadata(self.zarr_folder)
        if not rois:
            raise ValueError(f"No ROIs found in folder: {self.zarr_folder}")

        # Extract and validate channels
        channels_by_roi = self.channels_by_roi(self.zarr_folder, rois)
        main_channel_labels = self.compare_channels(channels_by_roi)
        if not main_channel_labels:
            raise ValueError(f"No valid channel labels found in folder: {self.zarr_folder}")

        # Interactive order selection
        ordered_rois = self.print_roi_summary_and_get_order(rois)

        # Stitch in the chosen order
        self.stitch_rois(ordered_rois, output_path, main_channel_labels)
        
        print("\n" + "="*90)
        print(f"✓ STITCHING COMPLETE")
        print(f"  Output: {output_path}")
        print("="*90)


@click.command()
@click.argument("zarr_folder", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.argument("stitch_folder", type=click.Path(file_okay=False, path_type=Path), required=False)
@click.option("--zstd", is_flag=True, help="Enable zstd compression for output TIFF")
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose logging")
def main(zarr_folder: Path, stitch_folder: Optional[Path], zstd: bool, verbose: bool) -> None:
    """
    Manual Zarr Stitcher - Interactive ROI selection and ordering
    
    ZARR_FOLDER: Path to a single Zarr folder to process
    STITCH_FOLDER: Optional output folder (defaults to parent/Zarr_manual_stitched)
    
    Examples:
        python zarr_manual_stitcher.py /data/sample1_zarr
        python zarr_manual_stitcher.py /data/sample1_zarr /output --zstd
    """
    if verbose:
        logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
    else:
        logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(message)s')
    
    try:
        if not stitch_folder:
            stitch_folder = zarr_folder.parent / "Zarr_manual_stitched"
            
        stitcher = ManualZarrStitcher(str(zarr_folder), str(stitch_folder), use_zstd=zstd)
        stitcher.process_folder()
        
    except FileNotFoundError as e:
        click.echo(click.style(f"✗ File not found: {e}", fg='red'), err=True)
        raise click.Abort()
    except ValueError as e:
        click.echo(click.style(f"✗ Invalid input: {e}", fg='red'), err=True)
        raise click.Abort()
    except KeyboardInterrupt:
        click.echo(click.style("\n✗ Cancelled by user", fg='yellow'), err=True)
        raise click.Abort()
    except Exception as e:
        click.echo(click.style(f"✗ Error: {str(e)}", fg='red'), err=True)
        if verbose:
            import traceback
            click.echo(traceback.format_exc(), err=True)
        raise click.Abort()


if __name__ == "__main__":
    main()


