"""Helpers to extract raster metadata from geospatial products.

This module provides a small, testable helper to read basic raster
information using :mod:`rasterio`.

Functions are intentionally small and raise clear errors when a file cannot
be opened so callers don't fail silently.
"""

from pathlib import Path
from typing import Any, Dict, Optional, Tuple, List

import rasterio
from rasterio.errors import RasterioIOError
from rasterio.warp import transform_bounds


def extract_raster_metadata(path: Path) -> Dict[str, Any]:
    """Open a raster and extract common metadata.

    Args:
        path: path to a raster file (GeoTIFF/COG etc.)

    Returns:
        dict: metadata with required fields:
            - path: absolute path as string
            - bbox: [minx, miny, maxx, maxy]
            - crs: EPSG code (int) when available, else CRS string
            - width: raster width in pixels
            - height: raster height in pixels
            - nodata: nodata value
            - dtype: data type of first band (e.g. "float32")
            - count: number of bands
        Optional field:
            - resolution: (pixel_width, pixel_height)

    Raises:
        RuntimeError: if the file cannot be opened or read.
    """
    path = Path(path)
    try:
        with rasterio.open(path) as src:
            b = src.bounds
            native_bbox = [b.left, b.bottom, b.right, b.top]

            # Prefer integer EPSG when available
            crs: Optional[Any]
            if src.crs:
                try:
                    epsg = src.crs.to_epsg()
                except Exception:
                    epsg = None
                crs = int(epsg) if epsg is not None else src.crs.to_string()
            else:
                crs = None

            dtype = src.dtypes[0] if getattr(src, "dtypes", None) else None

            metadata: Dict[str, Any] = {
                "path": str(path.resolve()),
                # native, projected bbox in the raster CRS
                "native_bbox": native_bbox,
                "crs": crs,
                "width": src.width,
                "height": src.height,
                "nodata": src.nodata,
                "dtype": dtype,
                "count": src.count,
            }

            # resolution is (xres, yres)
            try:
                res = tuple(src.res) if getattr(src, "res", None) else None
            except Exception:
                res = None

            if res:
                metadata["resolution"] = res

            # Attempt to compute a WGS84 bbox and simple polygon geometry. If
            # the raster has a valid CRS we try to transform bounds to EPSG:4326.
            try:
                if src.crs:
                    # transform_bounds accepts (left, bottom, right, top)
                    wgs_bbox = transform_bounds(src.crs, "EPSG:4326", *native_bbox, densify_pts=21)
                    # normalize to [minx, miny, maxx, maxy]
                    wgs_bbox_list: List[float] = [wgs_bbox[0], wgs_bbox[1], wgs_bbox[2], wgs_bbox[3]]
                    metadata["bbox"] = wgs_bbox_list
                    # simple GeoJSON Polygon in lon,lat order
                    minx, miny, maxx, maxy = wgs_bbox_list
                    geometry = {
                        "type": "Polygon",
                        "coordinates": [[
                            [minx, miny],
                            [minx, maxy],
                            [maxx, maxy],
                            [maxx, miny],
                            [minx, miny],
                        ]],
                    }
                    metadata["geometry"] = geometry
                else:
                    # no CRS — cannot compute WGS84 bbox/geometry
                    metadata["bbox"] = None
                    metadata["geometry"] = None
            except Exception:
                # Don't fail hard: if reprojection fails, leave WGS84 fields empty
                metadata["bbox"] = None
                metadata["geometry"] = None

            # dataset-level additional fields
            try:
                prof = src.profile or {}
                metadata["driver"] = src.driver
                metadata["dtypes"] = list(src.dtypes)
                metadata["compression"] = prof.get("compress") or prof.get("compression")
                metadata["tiled"] = bool(prof.get("tiled", False))
                metadata["block_shapes"] = getattr(src, "block_shapes", None)
                # overviews per band
                overviews = {}
                for i in range(1, src.count + 1):
                    try:
                        overviews[i] = src.overviews(i)
                    except Exception:
                        overviews[i] = []
                metadata["overviews"] = overviews
                # color interp and mask flags
                try:
                    metadata["colorinterp"] = [ci.name for ci in src.colorinterp]
                except Exception:
                    metadata["colorinterp"] = None
                try:
                    metadata["mask_flag_enums"] = [mf.name for mf in src.mask_flag_enums] if getattr(src, "mask_flag_enums", None) else None
                except Exception:
                    metadata["mask_flag_enums"] = None

                # tags
                try:
                    metadata["tags"] = src.tags() or {}
                except Exception:
                    metadata["tags"] = {}
                try:
                    metadata["image_structure_tags"] = src.tags(ns="IMAGE_STRUCTURE") or {}
                except Exception:
                    metadata["image_structure_tags"] = {}

                # band-level metadata
                band_list = []
                for i in range(1, src.count + 1):
                    bm: Dict[str, Any] = {}
                    bm["band_index"] = i
                    try:
                        bm["dtype"] = src.dtypes[i - 1]
                    except Exception:
                        bm["dtype"] = None
                    try:
                        bm["nodata"] = src.nodatavals[i - 1]
                    except Exception:
                        bm["nodata"] = None
                    try:
                        bm["unit"] = src.units[i - 1] if src.units and len(src.units) >= i else None
                    except Exception:
                        bm["unit"] = None
                    try:
                        bm["description"] = src.descriptions[i - 1] if src.descriptions and len(src.descriptions) >= i else None
                    except Exception:
                        bm["description"] = None
                    try:
                        bm["tags"] = src.tags(i) or {}
                    except Exception:
                        bm["tags"] = {}
                    try:
                        bm["overviews"] = src.overviews(i)
                    except Exception:
                        bm["overviews"] = []
                    # mask flags per band sometimes available; omit if not
                    bm["mask_flags"] = None
                    band_list.append(bm)
                metadata["bands"] = band_list
            except Exception:
                # best-effort: do not fail if these optional fields cannot be read
                pass

            return metadata
    except RasterioIOError as e:
        raise RuntimeError(f"Unable to open raster file '{path}': {e}") from e
    except Exception as e:
        raise RuntimeError(f"Error reading raster metadata from '{path}': {e}") from e


def is_cog(path: Path) -> bool:
    """Quick heuristic to decide whether a raster looks like a COG.

    This is a lightweight check and not a full validation. It returns True if
    the file has common COG characteristics such as internal tiling or
    overviews. It will return False when the file cannot be opened or the
    heuristic doesn't match.

    Args:
        path: path to raster

    Returns:
        bool: True when heuristic indicates a COG-like file, else False.
    """
    path = Path(path)
    try:
        with rasterio.open(path) as src:
            # has overviews for band 1?
            try:
                overviews = src.overviews(1)
            except Exception:
                overviews = []

            prof = getattr(src, "profile", {}) or {}
            tiled = bool(prof.get("tiled") or prof.get("blockxsize") or prof.get("blockysize"))

            return bool(overviews or tiled)
    except Exception:
        return False

