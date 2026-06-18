#!/usr/bin/env python3
import json
import re
import unicodedata
from pathlib import Path


# links to go into our collection
def slugify(text):
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = re.sub(r"\([^)]*\)", "", text)
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


trait_list = Path("trait_list.txt")

variables = []
links = []
links_catalog = []

for line in trait_list.read_text(encoding="utf-8").splitlines():
    if not line.strip():
        continue

    try_id, short_name, long_name, unit = line.split("\t")

    variable_id = slugify(short_name)
    title = short_name.strip().title()

    variables.append(variable_id)
    links.append(
        {
            "rel": "related",
            "href": f"../../variables/{variable_id}/catalog.json",
            "type": "application/json",
            "title": f"Variable: {title}",
        }
    )

    links_catalog.append(
        {
            "rel": "child",
            "href": f"./{variable_id}/catalog.json",
            "type": "application/json",
            "title": f"{title}",
        }
    )


snippet = {
    "osc:variables": variables,
    "links_to_add_prod_collection": links,
    "links_to_add_var_catalog": links_catalog,
}

print(json.dumps(snippet, indent=2, ensure_ascii=False))



# links to go into variables catalog esa