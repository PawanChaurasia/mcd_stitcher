# MCD STITCHER

Stitch rois from MCD files into OME-TIFFS.

## Install

```
pip install mcd_stitcher
```

### Requirements

* click
* numpy
* pandas
* python_dateutil
* xarray
* zarr

## Command line usage

*MCD to Zarr converter
]
imc2zarr <mcd_folder> <zarr_folder>

*Zarr dataset stitcher

zarr_stitch <zarr_folder>

*Composite MCD to Zarr to Stitch function

mcd_stitch <mcd_folder> <zarr_folder>

### Arguments
* mcd_folder:
  * the root folder of the IMC scan containing a single and/or multiple mcd files.
  
* zarr_folder: 
	*Storage location of converted MCD files in Zarr format and the starting point for stitching zarr files.
