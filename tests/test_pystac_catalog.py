from pathlib import Path
import pystac

stac_dir = Path("outputs/stac_maps_test")

catalog = pystac.Catalog.from_file(str(stac_dir / "catalog.json"))
catalog.resolve_links()
catalog.validate_all()

items = list(catalog.get_all_items())

print(f"Items: {len(items)}")
for item in items[:5]:
    # datetime is authoritative in properties['datetime'] per pipeline rules
    pd = item.properties.get("datetime") if item.properties else None
    print(item.id, pd, item.assets["data"].href)

print("PASS: pystac can read and validate the catalog.")