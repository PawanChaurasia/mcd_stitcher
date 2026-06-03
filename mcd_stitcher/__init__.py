from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("mcd_stitcher")
except PackageNotFoundError:
    __version__ = "2.3.0"

from .mcd_stitch import mcd_stitch
from .mcd_convert import mcd_convert
from .mcd_process import mcd_process
from .tiff_subset import tiff_subset

__all__ = [
    "mcd_stitch",
    "mcd_convert",
    "mcd_process",
    "tiff_subset",
]
