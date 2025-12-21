"""Get/set EXIF dates from photos"""

import logging
import typing

import piexif
from piexif._exceptions import InvalidImageDataError


def get_photo_exif(logger: logging.Logger, path: str) -> str | None:
    """Get EXIF date for a photo, return nothing if there is an error"""
    try:
        exif_dict: piexif.ExifIFD = piexif.load(path)
        return typing.cast(str | None, exif_dict.get("Exif").get(36867))
    except (ValueError, InvalidImageDataError):
        logger.debug("Error fetching EXIF data for %s", path)
        return None


def set_photo_exif(logger: logging.Logger, path: str, date: str | None, rating: int | None) -> None:
    """Set EXIF date and rating on a photo, do nothing if there is an error"""
    # Early return if nothing to set
    if date is None and rating is None:
        return
    
    try:
        exif_dict = piexif.load(path)
        
        # Set date if provided
        if date is not None:
            exif_dict.get("1st")[306] = date
            exif_dict.get("Exif")[36867] = date
            exif_dict.get("Exif")[36868] = date
        
        # Set rating if provided
        if rating is not None:
            # Windows-compatible Rating tag (0x4746 = 18246)
            if "0th" not in exif_dict:
                exif_dict["0th"] = {}
            exif_dict["0th"][18246] = rating
        
        exif_bytes = piexif.dump(exif_dict)
        piexif.insert(exif_bytes, path)
    except (ValueError, InvalidImageDataError):
        logger.debug("Error setting EXIF data for %s", path)
        return
