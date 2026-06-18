#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path


TRY_GLOSSARY_URL = "https://www.try-db.org/de/TraitGloss.php"
TRY_CITATION_URL = "https://onlinelibrary.wiley.com/doi/10.1111/j.1365-2486.2011.02451.x"

PRODUCT_ID = "global-plant-trait-maps"
PRODUCT_TITLE = "Global Plant Functional Trait Maps at 1 km Resolution"


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def parse_trait_list(path: Path) -> list[dict]:
    traits = []

    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue

        parts = line.split("\t")
        if len(parts) != 4:
            raise ValueError(f"Expected 4 tab-separated columns, got {len(parts)}: {line}")

        try_id, short_name, description, unit = parts
        trait_slug = slugify(description)
        variable_id = f"{trait_slug}"

        traits.append(
            {
                "try_id": try_id,
                "short_name": short_name,
                "description": description,
                "unit": unit,
                "id": variable_id,
                "title": short_name.title(),
            }
        )

    return traits


def make_variable_catalog(trait: dict, updated: str) -> dict:
    description = (
        f"{trait['description']}. "
        f"Unit: {trait['unit']}. "
        f"TRY trait ID: {trait['try_id']}."
    )

    return {
        "type": "Catalog",
        "id": trait["id"],
        "stac_version": "1.0.0",
        "description": description,
        "links": [
            {
                "rel": "self",
                "href": f"https://esa-earthcode.github.io/open-science-catalog-metadata/variables/{trait['id']}/catalog.json",
                "type": "application/json",
            },
            {
                "rel": "root",
                "href": "../../catalog.json",
                "type": "application/json",
                "title": "Open Science Catalog",
            },
            {
                "rel": "via",
                "href": TRY_GLOSSARY_URL,
                "type": "text/html",
                "title": "TRY Trait Glossary",
            },
            {
                "rel": "cite-as",
                "href": TRY_CITATION_URL,
                "type": "text/html",
                "title": "TRY Database reference",
            },
            {
                "rel": "parent",
                "href": "../catalog.json",
                "type": "application/json",
                "title": "Variables",
            },
            {
                "rel": "related",
                "href": "../../themes/land/catalog.json",
                "type": "application/json",
                "title": "Theme: Land",
            },
            {
                "rel": "child",
                "href": f"../../products/{PRODUCT_ID}/collection.json",
                "type": "application/json",
                "title": PRODUCT_TITLE,
            },
        ],
        "stac_extensions": [
            "https://stac-extensions.github.io/themes/v1.0.0/schema.json"
        ],
        "themes": [
            {
                "scheme": "https://github.com/stac-extensions/osc#theme",
                "concepts": [{"id": "land"}],
            }
        ],
        "updated": updated,
        "keywords": [
            "plant traits",
            "functional traits",
            "TRY",
            trait["short_name"],
            f"TRY {trait['try_id']}",
        ],
        "title": trait["title"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate OSC variable catalog.json files for plant traits."
    )
    parser.add_argument(
        "--trait-list",
        type=Path,
        required=True,
        help="Path to tab-separated trait list: TRY_ID, short name, description, unit.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Output directory, e.g. metadata/variables",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing catalog.json files.",
    )
    args = parser.parse_args()

    updated = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    traits = parse_trait_list(args.trait_list)

    args.output_dir.mkdir(parents=True, exist_ok=True)

    written = []
    skipped = []

    for trait in traits:
        variable_dir = args.output_dir / trait["id"]
        catalog_path = variable_dir / "catalog.json"

        if catalog_path.exists() and not args.overwrite:
            skipped.append(catalog_path)
            continue

        variable_dir.mkdir(parents=True, exist_ok=True)
        catalog = make_variable_catalog(trait, updated)

        catalog_path.write_text(
            json.dumps(catalog, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        written.append(catalog_path)

    print(f"Wrote {len(written)} variable catalogs.")
    print(f"Skipped {len(skipped)} existing catalogs.")

    if written:
        print("\nVariable IDs:")
        for path in written:
            print(f"- {path.parent.name}")


if __name__ == "__main__":
    main()