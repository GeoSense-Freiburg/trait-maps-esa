import json
import re
from pathlib import Path

import pystac


CATALOG_PATH = Path("stac_catalogs/stac_catalog_v1/catalog.json")
VARIABLES_PATH = Path("metadata_earth_code/variables")


def test_canonical_catalog_is_readable() -> None:
    catalog = pystac.Catalog.from_file(str(CATALOG_PATH))
    catalog.resolve_links()

    items = list(catalog.get_items(recursive=True))

    assert items
    assert all(item.assets for item in items)


def test_collection_resource_links_have_canonical_relations() -> None:
    collection = pystac.Collection.from_file(
        str(CATALOG_PATH.with_name("collection.json"))
    )
    links = {
        link.rel: (link.target, link.media_type, link.title)
        for link in collection.links
        if link.rel in {"describedby", "via", "about"}
    }

    assert links == {
        "describedby": (
            "https://doi.org/10.1038/s41467-026-68996-y",
            "text/html",
            "Scientific publication",
        ),
        "via": (
            "https://zenodo.org/records/14646322",
            "text/html",
            "Dataset on Zenodo",
        ),
        "about": (
            "https://geosense-freiburg.github.io/trait-maps-esa/",
            "text/html",
            "Interactive viewer",
        ),
    }


def test_trait_short_names_match_earthcode_variable_titles() -> None:
    titles_by_trait_id = {}
    for path in VARIABLES_PATH.glob("*/catalog.json"):
        variable = json.loads(path.read_text(encoding="utf-8"))
        match = re.search(r"TRY trait ID:\s*(\d+)", variable["description"])
        assert match, f"{path}: missing TRY trait ID"
        titles_by_trait_id[match.group(1)] = variable["title"]

    catalog = pystac.Catalog.from_file(str(CATALOG_PATH))
    catalog.resolve_links()
    for item in catalog.get_items(recursive=True):
        trait_id = item.properties["trait_id"]
        assert item.properties["trait_short_name"] == titles_by_trait_id[trait_id]
