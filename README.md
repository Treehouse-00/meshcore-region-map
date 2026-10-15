# California MeshCore Region Map

Standalone Leaflet map of the California MeshCore region tree. It reuses the
[New England Mesh](https://newenglandme.sh/regions/map) region-map viewer and
builds polygons from the places in
[meshcore-settings](https://github.com/matkam/meshcore-settings).

The site is static HTML plus GeoJSON. Serve the `public/` folder locally, then
deploy that same folder later.

## Look at it locally

If `public/regions/` already contains `index.json` and GeoJSON files:

```bash
python3 -m http.server 8080 --directory public
```

Then open [http://localhost:8080/](http://localhost:8080/) or
[http://localhost:8080/regions/map.html](http://localhost:8080/regions/map.html).

Do not open `map.html` as a `file://` URL. The viewer fetches JSON, so it needs
an HTTP server.

## What is on the map

- **Top-level regions** (`norcal`, `sacramentofoothills`, `sierranevada`,
  `bayarea`, `centralcoast`, `centralvalley`, `socal`) are visible by default
  and do not overlap. Each California county belongs to exactly one of them.
- **Nested areas** that claim county outlines are in the layer control, hidden
  until you turn them on. Clicking the map still lists them.
- **California** is an optional statewide overlay.

Clicking the map lists every region polygon that contains that point and
reverse-geocodes the place name.

## Rebuild the data

The builder reads `meshcore-settings/data/regions.json` when that sibling repo
is present. Otherwise it uses the copy in `data/regions.json`.

```bash
cd region-tools
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python build_census_boundaries.py
python build_regions.py
```

Census county files are downloaded once into `region-tools/`. Region GeoJSON is
written to `public/regions/`.

To point at another tree:

```bash
python build_regions.py --regions /path/to/regions.json
```

## Deploy later

Host the contents of `public/` as a static site. GitHub Pages, Cloudflare
Pages, Netlify, or any object store with a public website will work. `public/`
already includes `.nojekyll` for GitHub Pages.

If this map and the GeoJSON files are on different origins, the GeoJSON host
must send CORS headers. See `public/regions/SCHEMA.md`.
