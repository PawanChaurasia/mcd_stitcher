import logging

from .mcd_convert import main
from .mcd_stitch import main
from .tiff_subset import main

__version__ = "2.0.0"

logger = logging.getLogger(__name__)

__all__ = [
    "mcd_convert",
    "mcd_stitch",
    "tiff_subset",
    "__version__",
]
