import shutil
import os
import zarr
import numpy as np
from datetime import datetime
from pathlib import Path
from skimage.io import imsave
from tifffile import imwrite
import argparse

class ZarrStitcher:
    def __init__(self, zarr_folder):
        self.zarr_folder = Path(zarr_folder)

    def extract_metadata(self, zarr_path):
        """Extract metadata from the Zarr file."""
        metadata = []
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
                            'file_path': zarr_path / group_key
                        }
                        metadata.append(roi_meta)
        return metadata

    def convert_timestamp_to_simple_format(self, timestamp):
        """Convert complex timestamp to a simple format."""
        dt = datetime.fromisoformat(timestamp.split("+")[0].split(".")[0])
        return dt.strftime('%Y-%m-%dT%H:%M:%S')

    def stitch_rois(self, rois, output_path):
        """Stitch ROIs into a single image and save as OME-TIFF."""
        min_x = min(roi['stage_x'] for roi in rois)
        min_y = min(roi['stage_y'] for roi in rois)
        max_x = max(roi['stage_x'] + roi['width'] for roi in rois)
        max_y = max(roi['stage_y'] + roi['height'] for roi in rois)

        stitched_width = int(max_x - min_x)
        stitched_height = int(max_y - min_y)

        # Determine the number of channels automatically
        sample_roi = rois[0]
        sample_zarr = zarr.open(sample_roi['file_path'], mode='r')
        num_channels = sample_zarr[sample_roi['file_path'].name][:].shape[0]

        stitched_image = np.zeros((num_channels, stitched_height, stitched_width), dtype=np.uint16)

        # Sort ROIs by timestamp in descending order
        rois = sorted(rois, key=lambda r: self.convert_timestamp_to_simple_format(r['timestamp']), reverse=True)

        for roi in rois:
            try:
                zarr_group = zarr.open(roi['file_path'], mode='r')
                image_key = list(zarr_group.keys())[0]
                image = zarr_group[image_key][:]  # Load all channels
                x_offset = int(roi['stage_x'] - min_x)
                y_offset = int(stitched_height - (roi['stage_y'] + roi['height'] - min_y))
                stitched_image[:, y_offset:y_offset + image.shape[1], x_offset:x_offset + image.shape[2]] = image
            except Exception as e:
                print(f"Error processing ROI ID: {roi['roi_id']}, Error: {e}")

        # Save the stitched image as an OME-TIFF file
        imwrite(output_path, stitched_image, photometric='minisblack', metadata={'axes': 'CYX'})
        print(f"Stitched image saved to {output_path}")

    def process_all_folders(self):
        """Process all Zarr folders."""
        zarr_folders = [d for d in self.zarr_folder.iterdir() if d.is_dir()]
        for zarr_folder in zarr_folders:
            print(f"Processing folder: {zarr_folder}")
            
            # Extract the folder name to use in output file name
            folder_name = zarr_folder.name

            output_filename = folder_name + "_stitched.ome.tiff"
            output_path = self.zarr_folder / output_filename

            # Extract metadata from the current Zarr file
            rois = self.extract_metadata(zarr_folder)

            # Stitch the ROIs and save the result
            self.stitch_rois(rois, output_path)

def main():
    parser = argparse.ArgumentParser(description="Stitch Zarr files into a single OME-TIFF file.")
    parser.add_argument("zarr_folder", type=str, help="Path to the Zarr folder")
    
    args = parser.parse_args()
    
    stitcher = ZarrStitcher(args.zarr_folder)
    stitcher.process_all_folders()

if __name__ == "__main__":
    main()
