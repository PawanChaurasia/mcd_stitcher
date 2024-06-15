import zarr
import numpy as np
from datetime import datetime
from pathlib import Path
import argparse
import xarray as xr
import tifffile
import xmltodict
from typing import Union

class ZarrStitcher:
    def __init__(self, zarr_folder, use_lzw=False):
        self.zarr_folder = Path(zarr_folder)
        self.use_lzw = use_lzw
        self.log_file = self.zarr_folder / "error_log.txt"

    def log_error(self, message):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(self.log_file, "a") as f:
            f.write(f"{timestamp} - {message}\n")

    def extract_metadata(self, zarr_path):
        """Extract metadata from the Zarr file."""
        metadata = []
        try:
            zarr_file = zarr.open(str(zarr_path), mode='r')
            for group_key in zarr_file.keys():
                group = zarr_file[group_key]
                if 'meta' in group.attrs:
                    metas = group.attrs['meta']
                    for meta in metas:
                        if 'q_stage_x' in meta and 'q_stage_y' in meta and 'q_timestamp' in meta:
                            roi_meta = {
                                'stage_x': meta['q_stage_x'],
                                'stage_y': meta['q_stage_y'],
                                'timestamp': meta['q_timestamp'],
                                'width': meta['q_maxx'],
                                'height': meta['q_maxy'],
                                'roi_id': meta['q_id'],
                                'file_path': zarr_path / group_key,
                                'channels': meta.get('channels', [])  # Assuming 'channels' is in the metadata
                            }
                            metadata.append(roi_meta)
        except Exception as e:
            self.log_error(f"Error extracting metadata from {zarr_path}: {e}")
        return metadata
    
    def convert_timestamp_to_simple_format(self, timestamp):
        """Convert complex timestamp to a simple format."""
        dt = datetime.fromisoformat(timestamp.split("+")[0].split(".")[0])
        return dt.strftime('%Y-%m-%dT%H:%M:%S')
    
    def extract_channel_names(self, zarr_folder, acquisition_id):
        """Extract channel names for a specific acquisition ID from the mcd_schema.xml file in the Zarr folder."""
        schema_file = zarr_folder / "mcd_schema.xml"
        
        if not schema_file.exists():
            raise FileNotFoundError(f"Schema file not found: {schema_file}")
        
        with open(schema_file, 'r', encoding='utf-8') as file:
            xml_content = file.read()
            schema = xmltodict.parse(xml_content)
            
            channel_names = []
            for channel in schema['MCDSchema']['AcquisitionChannel']:
                if channel['AcquisitionID'] == str(acquisition_id):
                    channel_names.append(channel['ChannelLabel'])

            return channel_names
    
    def channels_by_roi(self, zarr_folder, rois):
        """Extract channel names for each ROI and return as a dictionary."""
        channels_by_roi = {}

        for roi in rois:
            try:
                channels = self.extract_channel_names(zarr_folder, roi['roi_id'])
                channels_by_roi[roi['roi_id']] = channels
            except Exception as e:
                self.log_error(f"Error extracting channels for ROI ID: {roi['roi_id']} in {roi['file_path']}, Error: {e}")

        return channels_by_roi

    def compare_channels(self, channels_by_roi):
        """Compare channel names across all ROIs and log any discrepancies."""
        main_channel_labels = None

        for roi_id, channels in channels_by_roi.items():
            if main_channel_labels is None:
                main_channel_labels = channels
            elif channels != main_channel_labels:
                self.log_error(f"Channel mismatch in ROI ID {roi_id}: {channels}")

        return main_channel_labels

    def stitch_rois(self, rois, output_path, main_channel_labels):
        """Stitch ROIs into a single image and save as OME-TIFF."""
        min_x = min(roi['stage_x'] for roi in rois)
        min_y = min(roi['stage_y'] - roi['height'] for roi in rois)
        max_x = max(roi['stage_x'] + roi['width'] for roi in rois)
        max_y = max(roi['stage_y'] for roi in rois)

        stitched_width  = int(max_x - min_x)
        stitched_height = int(max_y - min_y)
        
        # Determine the maximum number of channels
        max_channels = 0
        for roi in rois:
            try:
                sample_zarr = zarr.open(roi['file_path'], mode='r')
                num_channels = sample_zarr[roi['file_path'].name][:].shape[0]
                max_channels = max(max_channels, num_channels)
            except Exception as e:
                self.log_error(f"Error determining channels for ROI ID: {roi['roi_id']} in {roi['file_path']}, Error: {e}")

        stitched_image = np.zeros((max_channels, stitched_height, stitched_width), dtype=np.uint16)

        # Sort ROIs by timestamp in descending order
        rois = sorted(rois, key=lambda r: self.convert_timestamp_to_simple_format(r['timestamp']), reverse=True)

        for roi in rois:
            try:
                zarr_group = zarr.open(roi['file_path'], mode='r')
                image_key = list(zarr_group.keys())[0]
                image = zarr_group[image_key][:]  # Load all channels

                # Check if the image is empty (shape is (1, 1, 1))
                if image.shape == (1, 1, 1):
                    # print(f"Skipping empty ROI ID: {roi['roi_id']}")
                    continue

                x_offset = int(roi['stage_x'] - min_x)
                y_offset = abs(int(roi['stage_y'] - max_y))
                
                stitched_image[:, y_offset:y_offset + image.shape[1], x_offset:x_offset + image.shape[2]] = image
            except Exception as e:
                self.log_error(f"Error processing ROI ID: {roi['roi_id']} in {roi['file_path']}, Error: {e}")

        # Convert to xarray DataArray to use the write_ometiff function
        stitched_da = xr.DataArray(
            stitched_image,
            dims=("c", "y", "x"),
            coords={"c": main_channel_labels[:max_channels], "y": range(stitched_height), "x": range(stitched_width)}
        )

        # Save the stitched image as an OME-TIFF file
        self.write_ometiff(stitched_da, output_path)

    def write_ometiff(self, imarr: xr.DataArray, outpath: Union[Path, str], **kwargs) -> None:
        """Write DataArray to a multi-page OME-TIFF file with proper metadata."""
        outpath = Path(outpath)
        imarr = imarr.transpose("c", "y", "x")
        Nc, Ny, Nx = imarr.shape    
        # Generate standard OME-XML
        channels_xml = '\n'.join(
            [f"""<Channel ID="Channel:0:{i}" Name="{channel}" SamplesPerPixel="1" />"""
                for i, channel in enumerate(imarr.c.values)]
        )
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
        </OME>
        """
        outpath.parent.mkdir(parents=True, exist_ok=True)
        # Note resolution: 1 um/px = 25400 px/inch
        if self.use_lzw:
            tifffile.imwrite(outpath, data=imarr.values, description=xml, contiguous=True,
                            compression='lzw', resolution=(25400, 25400, "inch"), **kwargs)
        else:
            tifffile.imwrite(outpath, data=imarr.values, description=xml, contiguous=True,
                            resolution=(25400, 25400, "inch"), **kwargs)

    def process_all_folders(self):
        """Process all Zarr folders."""
        zarr_folders = [d for d in self.zarr_folder.iterdir() if d.is_dir()]
        for zarr_folder in zarr_folders:
            try:
                # Check for the presence of mcd_schema.xml
                schema_file = zarr_folder / "mcd_schema.xml"
                if not schema_file.exists():
                    print(f"Skipping {zarr_folder.name}: No mcd_schema.xml found.")
                    continue
                
                # Extract the folder name to use in output file name
                folder_name = zarr_folder.name

                output_filename = folder_name + "_stitched.ome.tiff"
                output_path = self.zarr_folder / output_filename

                # Extract metadata from the current Zarr file
                rois = self.extract_metadata(zarr_folder)

                if not rois:
                    self.log_error(f"No ROIs found in folder: {zarr_folder}")
                    continue

                # Extract channel names from the mcd_schema.xml file for each ROI
                channels_by_roi = self.channels_by_roi(zarr_folder, rois)
                
                # Compare channels and get main channel labels
                main_channel_labels = self.compare_channels(channels_by_roi)

                if not main_channel_labels:
                    self.log_error(f"No valid channel labels found in folder: {zarr_folder}")
                    continue

                # Stitch the ROIs and save the result
                self.stitch_rois(rois, output_path, main_channel_labels)
                
                print(f"Successfully stitched: {zarr_folder.name}")
            except Exception as e:
                self.log_error(f"Error processing folder {zarr_folder.name}: {e}")
                print(f"Error processing folder {zarr_folder.name}, check the log for details.")

def main():
    parser = argparse.ArgumentParser(description="""
    Stitch Zarr files into a single OME-TIFF file.
    
    For more information on command usage, visit:
    https://github.com/PawanChaurasia/mcd_stitcher
    """)
    parser.add_argument("zarr_folder", type=str, help="Path to the Zarr folder")
    parser.add_argument("--lzw", action="store_true", help="Enable LZW compression")
    
    args = parser.parse_args()
    
    stitcher = ZarrStitcher(args.zarr_folder, use_lzw=args.lzw)
    stitcher.process_all_folders()

if __name__ == "__main__":
    main()
