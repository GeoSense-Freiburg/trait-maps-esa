from pathlib import Path
from pprint import pprint

import rasterio
from rasterio.warp import transform_bounds


tif_path = Path("data/global_trait_maps/experimental/X13_mean_Shrub_Tree_Grass_1km.tif")


with rasterio.open(tif_path) as src:

    print("\n==============================")
    print("GENERAL")
    print("==============================")
    print("Path:", tif_path)
    print("Driver:", src.driver)
    print("Name:", src.name)
    print("Mode:", src.mode)
    print("Closed:", src.closed)

    print("\n==============================")
    print("RASTER DIMENSIONS")
    print("==============================")
    print("Width:", src.width)
    print("Height:", src.height)
    print("Band count:", src.count)
    print("Shape:", (src.height, src.width))

    print("\n==============================")
    print("CRS / GEOREFERENCING")
    print("==============================")
    print("CRS:", src.crs)
    print("Transform:")
    print(src.transform)

    print("\nBounds (native CRS):")
    print(src.bounds)

    print("\nBounds (WGS84):")
    print(
        transform_bounds(
            src.crs,
            "EPSG:4326",
            *src.bounds,
            densify_pts=21,
        )
    )

    print("\nResolution:")
    print(src.res)

    print("\n==============================")
    print("PROFILE")
    print("==============================")
    pprint(src.profile)

    print("\n==============================")
    print("META")
    print("==============================")
    pprint(src.meta)

    print("\n==============================")
    print("IMAGE STRUCTURE TAGS")
    print("==============================")
    pprint(src.tags(ns="IMAGE_STRUCTURE"))

    print("\n==============================")
    print("TIFF TAGS")
    print("==============================")
    pprint(src.tags(ns="TIFF"))

    print("\n==============================")
    print("GENERAL TAGS")
    print("==============================")
    pprint(src.tags())

    print("\n==============================")
    print("SUBDATASETS")
    print("==============================")
    pprint(src.subdatasets)

    print("\n==============================")
    print("OVERVIEWS")
    print("==============================")
    for i in range(1, src.count + 1):
        print(f"Band {i} overviews:", src.overviews(i))

    print("\n==============================")
    print("COLOR INTERPRETATION")
    print("==============================")
    print(src.colorinterp)

    print("\n==============================")
    print("BLOCK SHAPES")
    print("==============================")
    print(src.block_shapes)

    print("\n==============================")
    print("MASK FLAGS")
    print("==============================")
    print(src.mask_flag_enums)

    print("\n==============================")
    print("GCPS")
    print("==============================")
    gcps, gcp_crs = src.gcps
    print("GCP CRS:", gcp_crs)
    print("GCP count:", len(gcps))

    print("\n==============================")
    print("BAND METADATA")
    print("==============================")

    for i in range(1, src.count + 1):

        print(f"\n--- BAND {i} ---")

        print("Dtype:", src.dtypes[i - 1])
        print("Nodata:", src.nodatavals[i - 1])
        print("Units:", src.units[i - 1])
        print("Descriptions:", src.descriptions[i - 1])

        print("\nBand tags:")
        pprint(src.tags(i))

        print("\nBand statistics:")
        try:
            stats = src.statistics(i, approx=False)
            pprint(stats)
        except Exception as e:
            print("Could not compute statistics:", e)

        print("\nBand overviews:")
        print(src.overviews(i))

    print("\n==============================")
    print("FULL DATASET OBJECT")
    print("==============================")
    print(src)