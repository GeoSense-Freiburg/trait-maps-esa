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
THEME_ID = "land"
THEME_TITLE = "Theme: Land"

# Disambiguate TRY traits whose short names would otherwise collide or be unclear.
SPECIAL_IDS = {
    "1080": "specific-root-length",
    "614": "specific-fine-root-length",
    "138": "seed-number-reproduction-unit",
    "351": "seed-number-dispersal-unit",
    "14": "leaf-nitrogen-content-mass",
    "50": "leaf-nitrogen-content-area",
    "3106": "plant-height-vegetative",
    "3107": "plant-height-generative",
    "3112": "leaf-area-leaf",
    "3113": "leaf-area-leaflet",
    "3114": "leaf-area-unspecified",
    "3117": "leaf-area-specific",
}

SPECIAL_TITLES = {
    "1080": "Specific Root Length",
    "614": "Specific Fine Root Length",
    "138": "Seed Number (Reproduction Unit)",
    "351": "Seed Number (Dispersal Unit)",
    "13": "Leaf Carbon Content",
    "14": "Leaf Nitrogen Content (Mass)",
    "15": "Leaf Phosphorus Content",
    "50": "Leaf Nitrogen Content (Area)",
    "3106": "Plant Height (Vegetative)",
    "3107": "Plant Height (Generative)",
    "3112": "Leaf Area (Leaf)",
    "3113": "Leaf Area (Leaflet)",
    "3114": "Leaf Area (Unspecified)",
    "3117": "Specific Leaf Area",
    "47": "Leaf Dry Matter Content",
    "4": "Stem Specific Density",
}

ACRONYM_REPLACEMENTS = {
    "Srl": "SRL",
    "Sla": "SLA",
    "Ldmc": "LDMC",
    "Ssd": "SSD",
    "Cdna": "cDNA",
    "15N": "15N",
    "C/N": "C/N",
}


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = re.sub(r"\([^)]*\)", "", text)
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def title_case_preserve_acronyms(text: str) -> str:
    title = text.strip().title()
    for old, new in ACRONYM_REPLACEMENTS.items():
        title = title.replace(old, new)
    return title


def parse_trait_list(path: Path) -> list[dict]:
    traits: list[dict] = []

    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = line.strip()
        if not line:
            continue

        parts = line.split("\t")
        if len(parts) != 4:
            raise ValueError(
                f"Expected 4 tab-separated columns on line {line_no}, got {len(parts)}: {line}"
            )

        try_id, short_name, long_name, unit = [p.strip() for p in parts]
        variable_id = SPECIAL_IDS.get(try_id, slugify(long_name))
        title = SPECIAL_TITLES.get(try_id, title_case_preserve_acronyms(short_name))

        traits.append(
            {
                "try_id": try_id,
                "short_name": short_name,
                "long_name": long_name,
                "unit": unit,
                "id": variable_id,
                "title": title,
            }
        )

    # Fail early if IDs still collide.
    ids = [t["id"] for t in traits]
    duplicates = sorted({x for x in ids if ids.count(x) > 1})
    if duplicates:
        raise ValueError(
            "Duplicate variable IDs generated. Add them to SPECIAL_IDS: " + ", ".join(duplicates)
        )

    return traits


def make_variable_catalog(trait: dict, updated: str) -> dict:
    description = (
        f"{trait['long_name']}. "
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
                "href": f"../../themes/{THEME_ID}/catalog.json",
                "type": "application/json",
                "title": THEME_TITLE,
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
                "concepts": [{"id": THEME_ID}],
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


def make_product_collection_related_link(trait: dict) -> dict:
    return {
        "rel": "related",
        "href": f"../../variables/{trait['id']}/catalog.json",
        "type": "application/json",
        "title": f"Variable: {trait['title']}",
    }


def make_variables_catalog_child_link(trait: dict) -> dict:
    return {
        "rel": "child",
        "href": f"./{trait['id']}/catalog.json",
        "type": "application/json",
        "title": trait["title"],
    }


def write_variable_catalogs(traits: list[dict], output_dir: Path, overwrite: bool, updated: str) -> tuple[list[Path], list[Path]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    skipped: list[Path] = []

    for trait in traits:
        variable_dir = output_dir / trait["id"]
        catalog_path = variable_dir / "catalog.json"

        if catalog_path.exists() and not overwrite:
            skipped.append(catalog_path)
            continue

        variable_dir.mkdir(parents=True, exist_ok=True)
        catalog = make_variable_catalog(trait, updated)
        catalog_path.write_text(
            json.dumps(catalog, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        written.append(catalog_path)

    return written, skipped


def make_snippet(traits: list[dict]) -> dict:
    return {
        "osc:variables": [trait["id"] for trait in traits],
        "links_to_add_prod_collection": [
            make_product_collection_related_link(trait) for trait in traits
        ],
        "links_to_add_var_catalog": [
            make_variables_catalog_child_link(trait) for trait in sorted(traits, key=lambda t: t["title"].lower())
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Generate OSC variable catalog.json files and a JSON snippet for "
            "the product collection plus variables root catalog."
        )
    )
    parser.add_argument(
        "--trait-list",
        type=Path,
        required=True,
        help="Tab-separated trait list: TRY_ID, short name, long name/description, unit.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Variable output directory, e.g. metadata/variables.",
    )
    parser.add_argument(
        "--snippet-output",
        type=Path,
        default=None,
        help="Optional file path for the generated snippet JSON. If omitted, prints to stdout.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing variable catalog.json files.",
    )
    args = parser.parse_args()

    updated = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    traits = parse_trait_list(args.trait_list)
    written, skipped = write_variable_catalogs(
        traits=traits,
        output_dir=args.output_dir,
        overwrite=args.overwrite,
        updated=updated,
    )
    snippet = make_snippet(traits)
    snippet_text = json.dumps(snippet, indent=2, ensure_ascii=False) + "\n"

    if args.snippet_output:
        args.snippet_output.parent.mkdir(parents=True, exist_ok=True)
        args.snippet_output.write_text(snippet_text, encoding="utf-8")
    else:
        print(snippet_text)

    print(f"Wrote {len(written)} variable catalogs.")
    print(f"Skipped {len(skipped)} existing catalogs.")
    print(f"Generated {len(snippet['osc:variables'])} osc:variables entries.")
    if args.snippet_output:
        print(f"Snippet written to: {args.snippet_output}")


if __name__ == "__main__":
    main()
