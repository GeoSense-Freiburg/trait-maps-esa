#!/usr/bin/env python3
"""Validate remote raster assets referenced by the canonical static STAC."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from stac_catalog_utils import iter_tiff_assets


ROOT = Path("stac_catalogs/stac_catalog_v1/catalog.json")
REPORT = Path("build/eodash/asset-validation.json")
ORIGIN = "http://localhost:3000"
RANGE_END = 16383
PRACTICAL_FULL_FILE_LIMIT = 50 * 1024 * 1024


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--sample", type=int, default=None, metavar="N")
    group.add_argument("--all", action="store_true")
    group.add_argument("--asset-url")
    parser.add_argument("--catalog", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, default=REPORT)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--skip-gdal", action="store_true")
    args = parser.parse_args()
    if not args.all and args.sample is None and not args.asset_url:
        args.sample = 1
    if args.sample is not None and args.sample < 1:
        parser.error("--sample must be at least 1")
    return args


def discover_assets(args: argparse.Namespace) -> tuple[str, list[dict]]:
    if args.asset_url:
        return "explicit-url", [
            {
                "itemId": None,
                "itemPath": None,
                "item": {},
                "assetKey": "explicit-url",
                "asset": {"href": args.asset_url, "type": "image/tiff"},
            }
        ]
    backend = "json-fallback"
    discovered: list[dict] = []
    try:
        import pystac

        catalog = pystac.Catalog.from_file(str(args.catalog.resolve()))
        backend = f"pystac-{pystac.__version__}"
        for item in catalog.get_all_items():
            item_dict = item.to_dict()
            for asset_key, asset in item_dict.get("assets", {}).items():
                href = str(asset.get("href", ""))
                media_type = str(asset.get("type", "")).lower()
                if "tiff" not in media_type and not href.lower().split("?", 1)[0].endswith((".tif", ".tiff")):
                    continue
                discovered.append(
                    {
                        "itemId": item.id,
                        "itemPath": item.get_self_href(),
                        "item": item_dict,
                        "assetKey": asset_key,
                        "asset": asset,
                    }
                )
    except (ImportError, ModuleNotFoundError):
        for path, item, asset_key, asset in iter_tiff_assets(args.catalog):
            discovered.append(
                {
                    "itemId": item.get("id"),
                    "itemPath": str(path),
                    "item": item,
                    "assetKey": asset_key,
                    "asset": asset,
                }
            )
    discovered.sort(key=lambda value: (value["itemId"] or "", value["assetKey"]))
    if not args.all:
        discovered = discovered[: args.sample]
    return backend, discovered


def http_range_check(url: str, timeout: int) -> dict:
    request = Request(
        url,
        headers={
            "Range": f"bytes=0-{RANGE_END}",
            "Origin": ORIGIN,
            "User-Agent": "trait-maps-esa-stac-validator/1.0",
            "Accept-Encoding": "identity",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            sample = response.read(RANGE_END + 1)
            headers = {key.lower(): value for key, value in response.headers.items()}
            return {
                "reachable": True,
                "status": response.status,
                "finalUrl": response.geturl(),
                "bytesRead": len(sample),
                "contentRange": headers.get("content-range"),
                "acceptRanges": headers.get("accept-ranges"),
                "contentLength": int(headers["content-length"]) if headers.get("content-length", "").isdigit() else None,
                "contentType": headers.get("content-type"),
                "accessControlAllowOrigin": headers.get("access-control-allow-origin"),
                "tiffSignature": sample[:4].hex() in {"49492a00", "4d4d002a", "49492b00", "4d4d002b"},
                "error": None,
            }
    except HTTPError as error:
        return {
            "reachable": False,
            "status": error.code,
            "finalUrl": error.geturl(),
            "error": str(error),
        }
    except (URLError, TimeoutError, OSError) as error:
        return {"reachable": False, "status": None, "finalUrl": url, "error": str(error)}


def epsg_from_wkt(wkt: str | None) -> int | None:
    if not wkt:
        return None
    matches = re.findall(r'(?:AUTHORITY|ID)\["EPSG",[" ]?(\d+)', wkt)
    return int(matches[-1]) if matches else None


def gdal_check(url: str, timeout: int) -> dict:
    executable = shutil.which("gdalinfo")
    if not executable:
        return {"available": False, "error": "gdalinfo is not installed"}
    environment = os.environ.copy()
    environment.update(
        {
            "GDAL_HTTP_TIMEOUT": str(timeout),
            "GDAL_HTTP_CONNECTTIMEOUT": str(min(timeout, 15)),
            "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
            "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".tif,.tiff",
        }
    )
    try:
        process = subprocess.run(
            [executable, "-json", f"/vsicurl/{url}"],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=environment,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"available": True, "valid": False, "timeout": True, "error": f"gdalinfo exceeded {timeout}s"}
    if process.returncode != 0:
        return {
            "available": True,
            "valid": False,
            "timeout": False,
            "error": process.stderr.strip() or f"gdalinfo exited {process.returncode}",
        }
    try:
        info = json.loads(process.stdout)
    except json.JSONDecodeError as error:
        return {"available": True, "valid": False, "error": f"invalid gdalinfo JSON: {error}"}
    wkt = info.get("coordinateSystem", {}).get("wkt")
    bands = []
    for band in info.get("bands", []):
        bands.append(
            {
                "band": band.get("band"),
                "type": band.get("type"),
                "nodata": band.get("noDataValue"),
                "scale": band.get("scale"),
                "offset": band.get("offset"),
                "block": band.get("block"),
                "overviewSizes": [overview.get("size") for overview in band.get("overviews", [])],
            }
        )
    size = info.get("size")
    tiled = bool(
        size
        and bands
        and bands[0].get("block")
        and bands[0]["block"][0] < size[0]
        and bands[0]["block"][1] > 1
    )
    return {
        "available": True,
        "valid": True,
        "driver": info.get("driverShortName"),
        "size": size,
        "crsWkt": wkt,
        "epsg": epsg_from_wkt(wkt),
        "geoTransform": info.get("geoTransform"),
        "bandCount": len(bands),
        "bands": bands,
        "tiled": tiled,
        "hasOverviews": bool(bands and bands[0]["overviewSizes"]),
        "metadata": info.get("metadata", {}),
        "error": None,
    }


def projection_metadata(item: dict, asset: dict) -> dict:
    properties = item.get("properties", {})
    return {
        "code": asset.get("proj:code") or properties.get("proj:code"),
        "epsg": asset.get("proj:epsg") or properties.get("proj:epsg"),
        "bbox": asset.get("proj:bbox") or properties.get("proj:bbox"),
        "shape": asset.get("proj:shape") or properties.get("proj:shape"),
        "transform": asset.get("proj:transform") or properties.get("proj:transform"),
    }


def validate_entry(entry: dict, timeout: int, skip_gdal: bool) -> dict:
    item = entry["item"]
    asset = entry["asset"]
    url = asset.get("href")
    warnings: list[str] = []
    failures: list[str] = []
    media_type = asset.get("type")
    bands_metadata = asset.get("raster:bands", [])
    projection = projection_metadata(item, asset)
    metadata = {
        "hrefPresent": isinstance(url, str) and bool(url),
        "mediaType": media_type,
        "mediaTypeIsTiff": isinstance(media_type, str) and "tiff" in media_type.lower(),
        "assetKeyNonempty": bool(entry["assetKey"]),
        "itemHasBbox": bool(item.get("bbox")),
        "itemHasGeometry": bool(item.get("geometry")),
        "projection": projection,
        "rasterBands": bands_metadata,
        "styleLinks": [link for link in item.get("links", []) if "style" in link.get("rel", "")],
    }
    if not metadata["hrefPresent"]:
        failures.append("asset href is missing")
        http = {"reachable": False, "error": "no URL"}
        gdal = {"available": False, "valid": False, "error": "no URL"}
    else:
        if not metadata["mediaTypeIsTiff"]:
            warnings.append("asset media type does not resemble image/tiff or GeoTIFF")
        if entry["itemId"] is not None and (
            not metadata["itemHasBbox"] or not metadata["itemHasGeometry"]
        ):
            failures.append("item is missing bbox or geometry")
        if not projection["code"] and not projection["epsg"]:
            warnings.append("STAC projection code is not reported")
        if not bands_metadata:
            warnings.append("STAC raster:bands metadata is not reported")
        if not metadata["styleLinks"]:
            warnings.append("no item style link; viewer-side visualization config is required")
        http = http_range_check(url, timeout)
        if not http.get("reachable"):
            failures.append(f"asset is unreachable: {http.get('error')}")
        elif http.get("status") != 206:
            length = http.get("contentLength")
            if length is None or length > PRACTICAL_FULL_FILE_LIMIT:
                failures.append(f"server returned HTTP {http.get('status')} instead of 206 for a large remote TIFF")
            else:
                warnings.append(f"range request returned HTTP {http.get('status')} instead of 206")
        if http.get("reachable") and not http.get("tiffSignature"):
            failures.append("range response does not begin with a TIFF/BigTIFF signature")
        cors = http.get("accessControlAllowOrigin")
        if cors not in {"*", ORIGIN}:
            warnings.append("CORS is missing or does not explicitly allow the test origin")
        gdal = {"available": False, "valid": None, "error": "skipped"} if skip_gdal else gdal_check(http.get("finalUrl", url), timeout)
        if gdal.get("available") and not gdal.get("valid"):
            failures.append(f"gdalinfo could not open the remote GeoTIFF: {gdal.get('error')}")
        elif gdal.get("valid"):
            if not gdal.get("crsWkt") or not gdal.get("geoTransform"):
                failures.append("GeoTIFF is missing CRS or georeferencing")
            if not gdal.get("hasOverviews"):
                warnings.append("GeoTIFF has no internal overviews")
            if not gdal.get("tiled"):
                warnings.append("GeoTIFF does not use a tiled block structure")
            stac_code = projection.get("code") or projection.get("epsg")
            stac_epsg_match = re.search(r"(\d+)$", str(stac_code)) if stac_code else None
            stac_epsg = int(stac_epsg_match.group(1)) if stac_epsg_match else None
            if stac_epsg and gdal.get("epsg") and stac_epsg != gdal["epsg"]:
                failures.append(f"STAC projection EPSG:{stac_epsg} contradicts GeoTIFF EPSG:{gdal['epsg']}")
            metadata_text = json.dumps(gdal.get("metadata", {}))
            custom_codes = {int(value) for value in re.findall(r"EPSG[:= ]+(\d+)", metadata_text, re.I)}
            if gdal.get("epsg") and any(code != gdal["epsg"] for code in custom_codes):
                warnings.append(
                    f"non-authoritative TIFF metadata mentions {sorted(custom_codes)}, actual GeoTIFF CRS is EPSG:{gdal['epsg']}"
                )
        elif not gdal.get("available"):
            warnings.append(gdal.get("error", "gdalinfo unavailable"))
    likely_cog = bool(
        http.get("status") == 206
        and http.get("tiffSignature")
        and (not gdal.get("valid") or (gdal.get("tiled") and gdal.get("hasOverviews")))
    )
    return {
        "itemId": entry["itemId"],
        "itemPath": entry["itemPath"],
        "assetKey": entry["assetKey"],
        "href": url,
        "metadata": metadata,
        "http": http,
        "gdal": gdal,
        "cogDiagnostic": {
            "likelyBrowserCompatible": likely_cog,
            "definitive": False,
            "note": "Remote diagnostic from HTTP range access, TIFF structure, tiling, and overviews; not rio cogeo validate.",
        },
        "warnings": warnings,
        "blockingFailures": failures,
        "ok": not failures,
    }


def main() -> None:
    args = parse_args()
    backend, assets = discover_assets(args)
    results = []
    for index, entry in enumerate(assets, start=1):
        print(f"[{index}/{len(assets)}] {entry['itemId'] or 'explicit URL'} / {entry['assetKey']}")
        result = validate_entry(entry, args.timeout, args.skip_gdal)
        results.append(result)
        status = "PASS" if result["ok"] else "FAIL"
        http = result["http"]
        print(
            f"  {status}: HTTP {http.get('status')} range={http.get('contentRange')} "
            f"CORS={http.get('accessControlAllowOrigin')} likely-COG={result['cogDiagnostic']['likelyBrowserCompatible']}"
        )
        for warning in result["warnings"]:
            print(f"  WARNING: {warning}")
        for failure in result["blockingFailures"]:
            print(f"  ERROR: {failure}")
    report = {
        "catalog": str(args.catalog),
        "discoveryBackend": backend,
        "validatedAssetCount": len(results),
        "blockingFailureCount": sum(len(result["blockingFailures"]) for result in results),
        "warningCount": sum(len(result["warnings"]) for result in results),
        "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote JSON report to {args.output}")
    if report["blockingFailureCount"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
