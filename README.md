<table>
<tr>
<td width="96" valign="middle">
<img src="https://raw.githubusercontent.com/PawanChaurasia/mcd_stitcher/main/docs/img/logo.png" width="80" alt="MCD Stitcher">
</td>
<td valign="middle">

# MCD Stitcher

Whole-slide conversion and stitching for Imaging Mass Cytometry.

</td>
</tr>
</table>

[![PyPI](https://img.shields.io/pypi/v/mcd_stitcher?label=PyPI&color=3fb950&style=flat-square)](https://pypi.org/project/mcd_stitcher/)
[![Python](https://img.shields.io/badge/Python-3.9%20%E2%80%93%203.13-blue?style=flat-square)](https://www.python.org/downloads/)
[![PyPI Downloads](https://img.shields.io/pypi/dm/mcd-stitcher?label=Downloads&color=238636&style=flat-square&v=1)](https://pypistats.org/packages/mcd-stitcher)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow?style=flat-square)](https://github.com/PawanChaurasia/mcd_stitcher/blob/main/LICENSE)
[![DOI](https://img.shields.io/badge/DOI-10.64898%2F2026.06.26.732348-B31B1B?style=flat-square)](https://doi.org/10.64898/2026.06.26.732348)

Reads Standard BioTools `.mcd` files and writes OME-TIFFs for [QuPath](https://qupath.github.io/), [Napari](https://napari.org/) and [Fiji](https://fiji.sc/).

- **Convert** — each region (ROI) becomes its own multi-channel OME-TIFF.
- **Stitch** — all regions onto one canvas, placed by recorded stage coordinates.
- **Post-process** — channel subsets, pyramidal copies, re-compression.

## 🚀 Quick start

Requires **Python 3.9+**.

```bash
pip install mcd_stitcher
```

Convert each region to its own OME-TIFF:

```bash
mcd_process "path/to/file.mcd" --convert
```

Stitch all regions into a single image:

```bash
mcd_process "path/to/file.mcd" --stitch --pyramid
```

> 💡 **Tip** — `--pyramid` adds tiled, multi-resolution copies that let large stitched files pan and zoom smoothly, especially on low-RAM systems.

Everything lands in `MCD_Processed/<file name>/`, next to your input.

---

## 🔬 What it does

![Ten per-region OME-TIFFs and the stitched canvas](https://raw.githubusercontent.com/PawanChaurasia/mcd_stitcher/main/docs/img/regions-to-canvas.webp)

<sub>Left: Ten regions from one <code>.mcd</code> file, shown to common scale. Right: the same ten placed on a single 7.0 × 4.6 mm canvas at 0.5 µm/px.</sub>

`--convert` writes each region to its own OME-TIFF and `--stitch` places them all on one canvas using the stage positions recorded in the file — no registration, no seam blending. Regions acquired at different step sizes are resampled onto the finest common grid.

<details>
<summary><b>Native resolution is preserved end to end</b></summary>

![Whole canvas beside a native-resolution crop](https://raw.githubusercontent.com/PawanChaurasia/mcd_stitcher/main/docs/img/canvas-and-detail.webp)

A 7.0 × 4.6 mm canvas at 0.5 µm/px still resolves single cells — stitching costs no detail. `--pyramid` adds the tiled copy that makes a canvas this size navigable.

</details>

## ⚡ Commands

```bash
mcd_process <input_path> [<output_path>] [OPTIONS]      # a .mcd file, or a folder of them
```

```bash
mcd_process "file.mcd" -m                     # inspect: regions, panoramas, channel indices
mcd_process "file.mcd" --convert              # one OME-TIFF per region
mcd_process "file.mcd" --stitch --pyramid     # one zoomable stitched canvas
mcd_process "folder/" --convert --stitch      # a whole batch, both outputs, single pass
```

<details>
<summary><b>🔧 All options, output layout and the Python API</b></summary>

| Option | What it does |
| --- | --- |
| `--convert` | One OME-TIFF per region. |
| `--stitch` | All regions onto one canvas. |
| `-p, --panorama` | Panorama overviews; large ones get region outlines. |
| `-m, --metadata` | Print regions, panoramas, indexed channels. Writes nothing. |
| `--roi_map IDX` | Region → panorama pixel map. Needs convert/stitch. |
| `-f, --filter "LIST"` | Keep only these channels, e.g. `"0-5,7"`. Indices from `-m`. |
| `--pyramid` | Also write a tiled, multi-resolution copy. |
| `-r, --roi "LIST"` | Only these regions, e.g. `"0-5,7"`. Indices from `-m`. Selection only — never changes layer order. |
| `-d, --output_type` | `uint16` (default) / `float32`. |
| `-c, --compression` | `zstd` (default) / `LZW` / `None`. |

`-f` and `--pyramid` are post-processing steps and need `--convert` or `--stitch`.

```
MCD_Processed/<file name>/
├── <region>.ome.tiff                       --convert
├── <file name>_stitched.ome.tiff           --stitch
├── <file name>_slide_0_pano_0.png          -p        (+ _overlay.png)
└── <file name>_slide_0_pano_0_roi_map.txt  --roi_map
```

`mcd_convert`, `mcd_stitch` and `tiff_subset` each do one step; `tiff_subset` works on existing OME-TIFFs.

```python
from mcd_stitcher import mcd_process
mcd_process(input_path="file.mcd", convert=True, stitch=True)
```

</details>

---

## 📄 Citation

> Chaurasia, P. (2026). *MCD Stitcher: An open-source tool for whole-slide stitching and conversion of Imaging Mass Cytometry data.* bioRxiv. https://doi.org/10.64898/2026.06.26.732348

<details>
<summary>BibTeX</summary>

```bibtex
@article{chaurasia2026mcdstitcher,
  title   = {MCD Stitcher: An open-source tool for whole-slide stitching and conversion of Imaging Mass Cytometry data},
  author  = {Chaurasia, Pawan},
  journal = {bioRxiv},
  year    = {2026},
  doi     = {10.64898/2026.06.26.732348}
}
```

</details>

## 📜 License, issues & changelog

MIT — see [LICENSE](https://github.com/PawanChaurasia/mcd_stitcher/blob/main/LICENSE). Report problems on the [issue tracker](https://github.com/PawanChaurasia/mcd_stitcher/issues); release notes are in the [changelog](https://github.com/PawanChaurasia/mcd_stitcher/blob/main/CHANGELOG.md).
