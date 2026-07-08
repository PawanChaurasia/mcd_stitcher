# MCD Stitcher

[![PyPI](https://img.shields.io/pypi/v/mcd_stitcher?label=PyPI&color=3fb950&style=flat-square)](https://pypi.org/project/mcd_stitcher/)
[![Python](https://img.shields.io/badge/Python-3.9%20%E2%80%93%203.13-blue?style=flat-square)](https://www.python.org/downloads/)
[![PyPI Downloads](https://img.shields.io/pypi/dm/mcd-stitcher?label=Downloads&color=238636&style=flat-square&v=1)](https://pypistats.org/packages/mcd-stitcher)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow?style=flat-square)](LICENSE)
[![DOI](https://img.shields.io/badge/DOI-10.64898%2F2026.06.26.732348-B31B1B?style=flat-square)](https://doi.org/10.64898/2026.06.26.732348)

**MCD Stitcher** turns raw Imaging Mass Cytometry (IMC) `.mcd` files from Standard BioTools instruments into ordinary image files you can open in **[QuPath](https://qupath.github.io/)**, **[Napari](https://napari.org/)**, or **[Fiji](https://fiji.sc/)**.

It can:
- **Convert** each region (ROI) in an `.mcd` file into its own OME-TIFF.
- **Stitch** all regions back together into a single whole-slide OME-TIFF.
- **Tidy up** OME-TIFFs afterwards — keep only the channels you want, shrink them for fast viewing, or re-compress them.

> 📄 **Using MCD Stitcher in your research?** Please [cite the preprint](#-citation).

## 🚀 Quick Start

MCD Stitcher needs **Python 3.9 or newer**:

```bash
pip install mcd_stitcher
```

Then point **`mcd_process`** at a single `.mcd` file (or a whole folder of them):

```bash
# Convert every region to its own OME-TIFF AND stitch them into one whole-slide OME-TIFF
mcd_process "path/to/file.mcd" --convert --stitch
```

Results land in a `MCD_Processed/<file name>/` folder next to your input:

```
MCD_Processed/<file name>/
├── <region>.ome.tiff                       # one per region          --convert
├── <file name>_stitched.ome.tiff           # whole-slide mosaic      --stitch
├── <file name>_slide_0_pano_0.png          # panorama overview       -p
├── <file name>_slide_0_pano_0_overlay.png  # panorama + ROI outlines -p
└── <file name>_slide_0_pano_0_roi_map.txt  # region → panorama px     --roi_map
```

Post-processing adds `<name>_filtered.ome.tiff` (`-f`) and `<name>_pyramid.ome.tiff` (`--pyramid`) alongside the originals.

## ⚡ Commands

`mcd_process` is the one command you need — a `.mcd` file (or a folder of them) in, your OME-TIFFs out. Everything below is `mcd_process`; the single-purpose tools are optional.

### I want to…

| Goal | Command |
| --- | --- |
| See what's in a file first | `mcd_process "file.mcd" -m` |
| Get per-region OME-TIFFs | `mcd_process "file.mcd" --convert` |
| Get one whole-slide image | `mcd_process "file.mcd" --stitch` |
| Both, in one pass | `mcd_process "file.mcd" --convert --stitch` |
| Overview PNGs with ROI outlines | `mcd_process "file.mcd" -p` |
| A fast, zoomable whole slide | `mcd_process "file.mcd" --stitch --pyramid` |
| Only a few regions | `mcd_process "file.mcd" --convert -r "0-5,7"` |
| A whole folder at once | `mcd_process "path/to/folder" --convert` |

### Every option

```bash
mcd_process <input_path> [<output_path>] [OPTIONS]
```

| Option | What it does |
| --- | --- |
| `--convert` | Save each region as its own OME-TIFF. |
| `--stitch` | Stitch regions into one whole-slide OME-TIFF. |
| `-p, --panorama` | Export all panorama overviews (large ones get ROI outlines). On/off. |
| `-m, --metadata` | Print a summary — writes nothing. |
| `--roi_map IDX` | Region → panorama pixel map for panorama `IDX` (`0`, `1,3-5`). Needs convert/stitch. |
| `-f, --filter "LIST"` | Post-process: keep only these channels, e.g. `"0-5,7"`. Needs convert/stitch. |
| `--pyramid` | Post-process: also write a tiled, multi-resolution copy. Needs convert/stitch. |
| `-r, --roi "LIST"` | Limit to specific regions, e.g. `"0-5,7,10"`. Single file only. |
| `-d, --output_type` | `uint16` (default) / `float32`. |
| `-c, --compression` | `zstd` (default) / `LZW` / `None`. |

### 🔧 Single-purpose commands & Python API

Only need one step? `mcd_stitch` and `mcd_convert` do exactly that. `tiff_subset` works on **existing** OME-TIFFs (channels / pyramids / `--list-channels`).

```bash
mcd_stitch  <input_path> [<output_path>] [-d TYPE] [-c MODE] [-r "LIST"]
mcd_convert <input_path> [<output_path>] [-d TYPE] [-c MODE]
tiff_subset <input_path> [<output_path>] [-l | -f "LIST" | -p]
```

Single `.mcd` in for the first two (folders are batched by `mcd_process`). `tiff_subset` takes a `.tiff` or a directory; directory mode scans `*.tiff` recursively and logs per-file failures to `ome_subset_errors.log`.

```python
from pathlib import Path
from mcd_stitcher import mcd_stitch, mcd_convert, mcd_process

mcd_process(input_path=Path("file.mcd"), convert=True, stitch=True, panorama="all")
```

`from mcd_stitcher import __version__` returns the installed package version.

## 📄 Citation

If you use MCD Stitcher in your research, please cite:

> Chaurasia, P. (2026). *MCD Stitcher: An open-source tool for whole-slide stitching and conversion of Imaging Mass Cytometry data.* bioRxiv. https://doi.org/10.64898/2026.06.26.732348

<details>
<summary>BibTeX</summary>

```bibtex
@article{chaurasia2026mcdstitcher,
  title   = {MCD Stitcher: An open-source tool for whole-slide stitching and conversion of Imaging Mass Cytometry data},
  author  = {Chaurasia, Pawan},
  journal = {bioRxiv},
  year    = {2026},
  doi     = {10.64898/2026.06.26.732348},
  url     = {https://doi.org/10.64898/2026.06.26.732348}
}
```

</details>

## 📜 License

Distributed under the **MIT License**. See [LICENSE](LICENSE).

## 💬 Issues & Changelog

If you run into issues, have a feature suggestion, or want to share feedback, please open a ticket on the [issue tracker](https://github.com/PawanChaurasia/mcd_stitcher/issues). Release notes for every version are in the [changelog](CHANGELOG.md).
