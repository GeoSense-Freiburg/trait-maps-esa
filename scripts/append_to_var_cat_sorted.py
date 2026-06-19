"""
import json

catalog_path = "/home/charlektra/Documents/uniFreiburg/Geosense/open-science-catalog-metadata/variables/catalog.json"
catalog_path_n = "/home/charlektra/Documents/uniFreiburg/Geosense/open-science-catalog-metadata/variables/catalog_new.json"

with open(catalog_path) as f:
    catalog = json.load(f)

links = catalog["links"]

static_links = [l for l in links if l.get("rel") != "child"]
child_links = [l for l in links if l.get("rel") == "child"]

child_links = sorted(
    child_links,
    key=lambda x: x.get("title", "").lower()
)

catalog["links"] = static_links + child_links

with open(catalog_path_n, "w") as f:
    json.dump(catalog, f, indent=2, ensure_ascii=False)

print(f"Sorted {len(child_links)} variable links.")


"""
#!/usr/bin/env python3
import json
from pathlib import Path

catalog_path = Path("metadata_earth_code/catalog_original_vars.json")
catalog_path_n = Path("/home/charlektra/Documents/uniFreiburg/Geosense/open-science-catalog-metadata/variables/catalog_new.json")

variables_dir = Path("metadata_earth_code/variables")

catalog = json.loads(catalog_path.read_text(encoding="utf-8"))

static_links = [l for l in catalog["links"] if l.get("rel") != "child"]
existing_child_links = [l for l in catalog["links"] if l.get("rel") == "child"]

# Read all variable subfolder catalog.json files
generated_child_links = []
for child_catalog_path in sorted(variables_dir.glob("*/catalog.json")):
    variable_catalog = json.loads(child_catalog_path.read_text(encoding="utf-8"))

    variable_id = variable_catalog["id"]
    title = variable_catalog["title"]

    generated_child_links.append(
        {
            "rel": "child",
            "href": f"./{variable_id}/catalog.json",
            "type": "application/json",
            "title": title
        }
    )

# Merge by href so existing links are not duplicated
links_by_href = {
    link["href"]: link
    for link in existing_child_links
}

for link in generated_child_links:
    links_by_href[link["href"]] = link

merged_child_links = sorted(
    links_by_href.values(),
    key=lambda l: l.get("title", "").lower(),
)

catalog["links"] = static_links + merged_child_links
catalog_path_n.write_text(
    json.dumps(catalog, indent=2, ensure_ascii=False) + "\n",
    encoding="utf-8",
)

print(f"Existing child links: {len(existing_child_links)}")
print(f"Variable folders found: {len(generated_child_links)}")
print(f"Final child links: {len(merged_child_links)}")