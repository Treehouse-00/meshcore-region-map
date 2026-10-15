#!/usr/bin/env python3
"""
Build Leaflet-ready MeshCore region GeoJSON from meshcore-settings places.

Top-level places become the default map layers. Nested places that claim county
outlines are also generated, but hidden by default.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import geopandas as gpd

ROOT = Path(__file__).resolve().parent.parent
TOOLS = Path(__file__).resolve().parent
OUT = ROOT / "public" / "regions"
COUNTY_INPUT = TOOLS / "census_california_counties.geojson"
STATE_INPUT = TOOLS / "census_california_state.geojson"
SOURCE = "U.S. Census Bureau 2024 cartographic boundary files"
SETTINGS_SOURCE = "meshcore-settings California region tree"

LEVEL_TYPES = {
    "region": "Region",
    "area": "Area",
    "local area": "Local Area",
}

# meshcore-settings leaves some counties only on local areas or nested outlines
# that would otherwise overlap a sibling. These extras are map-only.
OUTLINE_EXTRAS = {
    "cvsouth": ["Kern"],
}

OUTLINE_REMOVALS = {
    "goldcountry": ["Sierra"],
}

ID_OVERRIDES = {
    "oc": "orange",
    "orangecounty": "orange",
}

# Counties that a top-level region should own even when another region's
# outline or nested tree would claim them. These extras win first.
TOP_LEVEL_EXTRAS = {
    "sacramentofoothills": ["Butte", "Sierra", "Nevada"],
}


def adjusted_outline(code: str, names: list[str]) -> list[str]:
    outline = list(dict.fromkeys(names + OUTLINE_EXTRAS.get(code, [])))
    skip = set(OUTLINE_REMOVALS.get(code, []))
    return [name for name in outline if name not in skip]


def as_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return [str(item) for item in value]


def regions_json_path(explicit: Path | None) -> Path:
    candidates = []
    if explicit:
        candidates.append(explicit)
    candidates.extend(
        [
            ROOT.parent / "meshcore-settings" / "data" / "regions.json",
            ROOT / "data" / "regions.json",
        ]
    )
    for path in candidates:
        if path.is_file():
            return path
    raise FileNotFoundError(
        "Could not find regions.json. Pass --regions or keep a copy in data/regions.json."
    )


def load_tree(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data.get("places"), list):
        raise ValueError(f"{path} must contain a places array")
    return data


def level_name(tree: dict, depth: int, place: dict) -> str:
    if place.get("kind"):
        return str(place["kind"])
    levels = tree.get("levels") or []
    if depth < len(levels) and isinstance(levels[depth], dict):
        return str(levels[depth].get("name") or "place")
    return "place"


def region_type_for(kind: str) -> str:
    return LEVEL_TYPES.get(kind, kind.replace("_", " ").title() or "Place")


def flatten_places(tree: dict) -> list[dict]:
    places = []

    def walk(place: dict, ancestors: list[dict], depth: int) -> None:
        children = place.get("children") or []
        source_code = place["code"]
        code = ID_OVERRIDES.get(source_code, source_code)
        node = {
            "id": code,
            "name": place["name"],
            "short_name": place.get("short") or str(code).upper(),
            "blurb": place.get("blurb") or "",
            "outline": adjusted_outline(source_code, as_list(place.get("outline"))),
            "county": as_list(place.get("county")),
            "lat": place.get("lat"),
            "lon": place.get("lon"),
            "kind": level_name(tree, depth, place),
            "depth": depth,
            "ancestors": ancestors,
            "children": children,
        }
        places.append(node)
        parent = {
            "id": node["id"],
            "name": node["name"],
            "short_name": node["short_name"],
        }
        for child in children:
            walk(child, ancestors + [parent], depth + 1)

    for place in tree["places"]:
        walk(place, [], 0)
    return places


def counties_for(place: dict, top_level_counties: dict[str, list[str]] | None = None) -> list[str]:
    if place["depth"] == 0 and top_level_counties is not None:
        return list(top_level_counties.get(place["id"], []))
    return list(place["outline"])


def top_level_id(place: dict) -> str | None:
    if place["depth"] == 0:
        return place["id"]
    if place["ancestors"]:
        return place["ancestors"][0]["id"]
    return None


def assign_top_level_counties(places: list[dict]) -> dict[str, list[str]]:
    """Give each county to exactly one top-level region.

    Explicit parent outlines win, so nested places like Grass Valley (Nevada
    County) and Gold Country (Sierra County) cannot pull those counties out of
    North California. Unclaimed descendant outlines then fill regions with no
    parent outline, such as Bay Area, Central Valley, and SoCal.
    """
    top = [place for place in places if place["depth"] == 0]
    descendants = [place for place in places if place["depth"] > 0]
    claimed: dict[str, str] = {}
    assigned: dict[str, list[str]] = {place["id"]: [] for place in top}

    def claim(region_id: str, names: list[str]) -> None:
        for name in names:
            if name in claimed:
                continue
            claimed[name] = region_id
            assigned[region_id].append(name)

    for place in top:
        claim(place["id"], TOP_LEVEL_EXTRAS.get(place["id"], []))
    for place in top:
        claim(place["id"], place["outline"])
    for place in top:
        claim(
            place["id"],
            [
                name
                for child in descendants
                if top_level_id(child) == place["id"]
                for name in child["outline"]
            ],
        )
    for place in top:
        claim(
            place["id"],
            [
                name
                for child in descendants
                if top_level_id(child) == place["id"]
                for name in child["county"]
            ],
        )
    return assigned


def chain_for(place: dict, tree: dict) -> str:
    root = [item["code"] for item in tree.get("root") or []]
    ancestors = [item["id"] for item in place["ancestors"]]
    return " ".join(root + ancestors + [place["id"]])


def select_counties(counties: gpd.GeoDataFrame, names: list[str], region_id: str) -> gpd.GeoDataFrame:
    selected = counties[counties["NAME"].isin(names)][["geometry"]].copy()
    missing = set(names) - set(counties["NAME"])
    if missing:
        raise ValueError(f"{region_id} references missing California counties: {sorted(missing)}")
    if selected.empty:
        raise ValueError(f"{region_id} selected no county geometry")
    return selected


def dissolve(rows: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    geometry = rows.geometry.union_all()
    dissolved = gpd.GeoDataFrame(geometry=[geometry], crs=4326)
    dissolved["geometry"] = dissolved.geometry.make_valid()
    return dissolved


def write_geojson(gdf: gpd.GeoDataFrame, path: Path) -> None:
    gdf.to_file(path, driver="GeoJSON")


def polygon_record(place: dict, tree: dict, geometry: gpd.GeoDataFrame, county_names: list[str]) -> gpd.GeoDataFrame:
    region = geometry.copy()
    region["id"] = place["id"]
    region["name"] = place["name"]
    region["short_name"] = place["short_name"]
    region["kind"] = place["kind"]
    region["depth"] = place["depth"]
    region["region_type"] = region_type_for(place["kind"])
    region["boundary_basis"] = (
        "Non-overlapping California counties from meshcore-settings outlines"
        if place["depth"] == 0
        else "Counties named by meshcore-settings outline"
    )
    region["notes"] = place["blurb"]
    region["region_chain"] = chain_for(place, tree)
    region["counties"] = ", ".join(county_names)
    region["draft"] = False
    region["source"] = f"{SOURCE}; {SETTINGS_SOURCE}"
    region["coordinator"] = ""
    return region[
        [
            "id",
            "name",
            "short_name",
            "kind",
            "depth",
            "region_type",
            "boundary_basis",
            "notes",
            "region_chain",
            "counties",
            "draft",
            "source",
            "coordinator",
            "geometry",
        ]
    ]


def california_record(state: gpd.GeoDataFrame, tree: dict) -> gpd.GeoDataFrame:
    region = dissolve(state[["geometry"]])
    region["id"] = "california"
    region["name"] = "California"
    region["short_name"] = "CALIFORNIA"
    region["kind"] = "state_region"
    region["region_type"] = "State Region"
    region["boundary_basis"] = "Existing political boundary represented by a U.S. Census state boundary"
    region["notes"] = "Statewide umbrella for the meshcore-settings California tree."
    root = [item["code"] for item in tree.get("root") or [] if item.get("code")]
    region["region_chain"] = " ".join(root) if root else "california"
    region["counties"] = ""
    region["draft"] = False
    region["source"] = SOURCE
    region["coordinator"] = ""
    return region


def index_entry(place: dict, *, visible: bool, optional: bool = False, legend: bool = True) -> dict:
    status = "official_local" if place["id"] != "california" else "political_boundaries"
    entry = {
        "id": place["id"],
        "name": place["name"],
        "short_name": place["short_name"],
        "region_type": place.get("region_type") or region_type_for(place["kind"]),
        "coordination_status": status,
        "coordination_label": (
            "Political Boundaries" if status == "political_boundaries" else "Official Local Region"
        ),
        "file": f"{place['id']}.geojson",
    }
    if optional:
        entry["optional"] = True
    if not visible:
        entry["visible"] = False
    if not legend:
        entry["legend"] = False
    return entry


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--regions", type=Path, help="Path to meshcore-settings regions.json")
    args = parser.parse_args()

    if not COUNTY_INPUT.exists() or not STATE_INPUT.exists():
        raise FileNotFoundError("Run build_census_boundaries.py first")

    regions_path = regions_json_path(args.regions)
    tree = load_tree(regions_path)
    places = flatten_places(tree)
    counties = gpd.read_file(COUNTY_INPUT).to_crs(4326)
    state = gpd.read_file(STATE_INPUT).to_crs(4326)

    OUT.mkdir(parents=True, exist_ok=True)
    for old_output in OUT.glob("*.geojson"):
        old_output.unlink()

    index = {
        "title": "California MeshCore Region Map",
        "source": tree.get("source") or "meshcore-settings",
        "updated": tree.get("updated"),
        "regions": [],
    }

    california = california_record(state, tree)
    write_geojson(california, OUT / "california.geojson")
    index["regions"].append(
        index_entry(
            {
                "id": "california",
                "name": "California",
                "short_name": "CALIFORNIA",
                "kind": "state_region",
                "region_type": "State Region",
            },
            visible=False,
            optional=True,
            legend=False,
        )
    )

    top_level_counties = assign_top_level_counties(places)
    census_county_names = set(counties["NAME"])
    assigned_names = [name for names in top_level_counties.values() for name in names]
    duplicates = sorted({name for name in assigned_names if assigned_names.count(name) > 1})
    if duplicates:
        raise ValueError(f"Top-level regions overlap: {duplicates}")
    missing = sorted(census_county_names - set(assigned_names))
    extra = sorted(set(assigned_names) - census_county_names)
    if missing or extra:
        raise ValueError(
            "Top-level county assignment does not match California: "
            + ", ".join(
                part
                for part in (
                    f"unassigned: {missing}" if missing else "",
                    f"unknown: {extra}" if extra else "",
                )
                if part
            )
        )

    polygon_places = []
    for place in places:
        names = counties_for(place, top_level_counties)
        if not names:
            continue
        polygon_places.append((place, names))

    for place, names in polygon_places:
        geometry = dissolve(select_counties(counties, names, place["id"]))
        region = polygon_record(place, tree, geometry, names)
        write_geojson(region, OUT / f"{place['id']}.geojson")
        is_top_level = place["depth"] == 0
        index["regions"].append(
            index_entry(
                {
                    **place,
                    "region_type": region_type_for(place["kind"]),
                },
                visible=is_top_level,
                legend=is_top_level,
            )
        )

    (OUT / "index.json").write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")

    report = [
        "# California MeshCore region build",
        "",
        f"- Source: `{regions_path}`",
        f"- Places in tree: {len(places)}",
        f"- Polygon layers: {len(polygon_places) + 1}",
        "",
        "Top-level regions (non-overlapping):",
    ]
    for place in places:
        if place["depth"] == 0:
            names = top_level_counties.get(place["id"], [])
            report.append(f"- `{place['id']}` {place['name']} ({len(names)}): {', '.join(names)}")
    (TOOLS / "validation_report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    print(f"Wrote region GeoJSON to {OUT}")
    print(f"Read places from {regions_path}")


if __name__ == "__main__":
    main()
