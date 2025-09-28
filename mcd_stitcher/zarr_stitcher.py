import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Union, List, Dict, Optional, Tuple
import concurrent.futures

import numpy as np
import tifffile
import xarray as xr
import xmltodict
import zarr
import click

logger = logging.getLogger(__name__)


class ZarrStitcher:
    def __init__(self, zarr_folder: Union[str, Path], stitch_folder: Union[str, Path], use_zstd: bool = False, max_workers: Optional[int] = None):
        self.zarr_folder = Path(zarr_folder)
        
        if not self.zarr_folder.exists():
            raise FileNotFoundError(f"Zarr folder does not exist: {zarr_folder}")
        if not self.zarr_folder.is_dir():
            raise ValueError(f"Path is not a directory: {zarr_folder}")
        
        self.stitch_folder = Path(stitch_folder)
        self.stitch_folder.mkdir(parents=True, exist_ok=True)
        
        self.use_zstd = use_zstd
        self.max_workers = max_workers or max(1, os.cpu_count() - 1)
        self.log_file = self.zarr_folder / "stitching_error_log.txt"

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
                                'roi_id': meta['q_id'],
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

    def stitch_rois(self, rois: List[Dict], output_path: Path, main_channel_labels: List[str]) -> None:
        if not rois:
            raise ValueError("No ROIs provided for stitching")
        
        # Calculate bounds
        min_x = min(roi['stage_x'] for roi in rois)
        min_y = min(roi['stage_y'] - roi['height'] for roi in rois)
        max_x = max(roi['stage_x'] + roi['width'] for roi in rois)
        max_y = max(roi['stage_y'] for roi in rois)

        stitched_width = int(max_x - min_x)
        stitched_height = int(max_y - min_y)
        
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

        # Sort by timestamp
        rois_sorted = sorted(rois, key=lambda r: self.convert_timestamp_to_simple_format(r['timestamp']), reverse=True)

        def load_and_prepare(roi):
            try:
                zarr_group = zarr.open(roi['file_path'], mode='r')
                image_key = list(zarr_group.keys())[0]
                image = zarr_group[image_key][:]
                
                if image.shape == (1, 1, 1):
                    logger.warning(f"Skipping empty ROI ID: {roi['roi_id']}")
                    return None
                
                x_offset = int(roi['stage_x'] - min_x)
                y_offset = abs(int(roi['stage_y'] - max_y))
                return (image, x_offset, y_offset, roi['roi_id'])
                
            except Exception as e:
                self.log_error(f"Error processing ROI ID: {roi['roi_id']}: {e}")
                return None

        # Parallel processing
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            results = list(executor.map(load_and_prepare, rois_sorted))

        # Place ROIs
        for result in results:
            if result is None:
                continue
            image, x_offset, y_offset, roi_id = result
            stitched_image[:, y_offset:y_offset + image.shape[1], x_offset:x_offset + image.shape[2]] = image

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
            'contiguous': True,
            'resolution': (25400, 25400),
            'resolutionunit': 'inch',
            **kwargs
        }
        
        if self.use_zstd:
            tiff_kwargs['compression'] = 'zstd'
            compressionargs={'level': 15}
        
        try:
            tifffile.imwrite(outpath, **tiff_kwargs)
        except Exception as e:
            logger.error(f"Failed to write OME-TIFF {outpath}: {e}")
            raise

    def process_all_folders(self) -> None:
        zarr_folders = [d for d in self.zarr_folder.iterdir() if d.is_dir()]
        
        if not zarr_folders:
            logger.warning("No subdirectories found to process")
            return
        
        for i, zarr_folder in enumerate(zarr_folders, 1):
            logger.info(f"Processing folder {i}/{len(zarr_folders)}: {zarr_folder.name}")
            
            try:
                schema_file = zarr_folder / "mcd_schema.xml"
                if not schema_file.exists():
                    logger.warning(f"Skipping {zarr_folder.name}: No mcd_schema.xml found")
                    continue
                
                folder_name = zarr_folder.name
                output_filename = f"{folder_name}_stitched.ome.tiff"
                output_path = self.stitch_folder / output_filename

                rois = self.extract_metadata(zarr_folder)
                if not rois:
                    self.log_error(f"No ROIs found in folder: {zarr_folder}")
                    continue

                channels_by_roi = self.channels_by_roi(zarr_folder, rois)
                main_channel_labels = self.compare_channels(channels_by_roi)

                if not main_channel_labels:
                    self.log_error(f"No valid channel labels found in folder: {zarr_folder}")
                    continue

                self.stitch_rois(rois, output_path, main_channel_labels)
                logger.info(f"Successfully stitched: {zarr_folder.name}")
                
            except Exception as e:
                self.log_error(f"Error processing folder {zarr_folder.name}: {e}")
                logger.error(f"Failed to process {zarr_folder.name}")


@click.command()
@click.argument("zarr_folder", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.argument("stitch_folder", type=click.Path(file_okay=False, path_type=Path), required=False)
@click.option("--zstd", is_flag=True, help="Enable zstd compression")
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose logging")
@click.option("--workers", "-w", type=int, help="Number of parallel workers")
def main(zarr_folder: Path, stitch_folder: Optional[Path], zstd: bool, verbose: bool, workers: Optional[int]) -> None:
    """CLI for stitching Zarr-converted MCD into OME-TIFFs."""
    if verbose:
        logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
    else:
        logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(message)s')
    
    try:
        if not stitch_folder:
            stitch_folder = zarr_folder.parent / "Zarr_stitched"
            
        stitcher = ZarrStitcher(str(zarr_folder), str(stitch_folder), use_zstd=zstd, max_workers=workers)
        stitcher.process_all_folders()
        click.echo(click.style("Stitching completed successfully!", fg='green'))
        
    except FileNotFoundError as e:
        click.echo(click.style(f"File not found: {e}", fg='red'), err=True)
        raise click.Abort()
    except ValueError as e:
        click.echo(click.style(f"Invalid input: {e}", fg='red'), err=True)
        raise click.Abort()
    except Exception as e:
        click.echo(click.style(f"Error: {str(e)}", fg='red'), err=True)
        if verbose:
            import traceback
            click.echo(traceback.format_exc(), err=True)
        raise click.Abort()


if __name__ == "__main__":
    main()
