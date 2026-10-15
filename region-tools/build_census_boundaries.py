#!/usr/bin/env python3
"""Download California Census cartographic state and county boundaries."""

from __future__ import annotations

import io
import tempfile
import zipfile
from pathlib import Path

import geopandas as gpd
import requests

YEAR = 2024
RESOLUTION = "5m"
OUT = Path(__file__).resolve().parent
STATE_URL = f"https://www2.census.gov/geo/tiger/GENZ{YEAR}/shp/cb_{YEAR}_us_state_{RESOLUTION}.zip"
COUNTY_URL = f"https://www2.census.gov/geo/tiger/GENZ{YEAR}/shp/cb_{YEAR}_us_county_{RESOLUTION}.zip"
CALIFORNIA_FIPS = "06"


def download_and_extract(url: str, destination: Path) -> Path:
    response = requests.get(url, timeout=120)
    response.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
        zf.extractall(destination)
    return next(destination.glob("*.shp"))


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        source_root = Path(tmp)
        state_dir = source_root / "state_source"
        county_dir = source_root / "county_source"
        state_dir.mkdir()
        county_dir.mkdir()

        states = gpd.read_file(download_and_extract(STATE_URL, state_dir)).to_crs(4326)
        counties = gpd.read_file(download_and_extract(COUNTY_URL, county_dir)).to_crs(4326)

        state_cols = [c for c in ["STATEFP", "STUSPS", "NAME", "GEOID", "geometry"] if c in states.columns]
        county_cols = [
            c for c in ["STATEFP", "COUNTYFP", "NAME", "NAMELSAD", "GEOID", "geometry"] if c in counties.columns
        ]

        california = states[states["STATEFP"] == CALIFORNIA_FIPS][state_cols]
        california_counties = counties[counties["STATEFP"] == CALIFORNIA_FIPS][county_cols]
        if california.empty or california_counties.empty:
            raise RuntimeError("Census download did not include California")

        california.to_file(OUT / "census_california_state.geojson", driver="GeoJSON")
        california_counties.to_file(OUT / "census_california_counties.geojson", driver="GeoJSON")

    print(f"Wrote California Census GeoJSON to {OUT.resolve()}")


if __name__ == "__main__":
    main()
