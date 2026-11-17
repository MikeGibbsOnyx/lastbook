# Canadian regions — build plan and status

This is the implementation note for extending Lastbook's detailed maps outside the United States.
The design rationale and data-source survey live in [REGIONS.md](REGIONS.md) and
[regions-proposed.json](regions-proposed.json); this file records the build pipeline and what is done.

## Order

| # | Code | Region | Geofabrik extract | Status |
|---|---|---|---|---|
| 1 | `CA-ON` | Ontario | `ontario-latest-free.gpkg.zip` | building |
| 2 | `CA-NS` | Nova Scotia | `nova-scotia-latest-free.gpkg.zip` | queued |
| 3 | `CA-NB` | New Brunswick | `new-brunswick-latest-free.gpkg.zip` | queued |
| 4 | `CA-QC` | Quebec | `quebec-latest-free.gpkg.zip` | queued |
| 5 | `CA-BC` | British Columbia | no GPKG; `british-columbia-latest.osm.pbf` | queued |
| 6 | `CA-AB` | Alberta | `alberta-latest-free.gpkg.zip` | queued |
| 7 | `CA-MB` | Manitoba | `manitoba-latest-free.gpkg.zip` | queued |
| 8 | `CA-SK` | Saskatchewan | `saskatchewan-latest-free.gpkg.zip` | queued |
| 9 | `CA-PE` | Prince Edward Island | `prince-edward-island-latest-free.gpkg.zip` | queued |
| 10 | `CA-NL` | Newfoundland and Labrador | `newfoundland-and-labrador-latest-free.gpkg.zip` | queued |
| 11 | `CA-YT` | Yukon | `yukon-latest-free.gpkg.zip` | queued |
| 12 | `CA-NT` | Northwest Territories | `northwest-territories-latest-free.gpkg.zip` | queued |
| 13 | `CA-NU` | Nunavut | no GPKG; `nunavut-latest.osm.pbf` | queued |

Codes use the ISO 3166-2 style proposed in REGIONS.md. `CA` alone is already California.

## Pipeline (base map)

`packaging/build_ca_map.py` does one region at a time:

1. Unpack the Geofabrik `*-free.gpkg.zip` if needed.
2. `tools/build_map.py` → `derived/geo/national.sqlite` (`feat`, `feat_idx`, `poi`, `meta`).
   `--skip-buildings` keeps the base map lean; buildings are a separate layer.
3. `tools/build_coast.py` for coastal provinces (Nova Scotia, New Brunswick, BC, PEI, Newfoundland).
4. `tools/build_places_ca.py` → `derived/geo/places.sqlite` from named OSM places and POIs.
5. Write `national-status.json`, `socal-cells.json`, and `map-set.json`.
6. Zip `Lastbook-Map-<code>.zip` with `map-set.json` at the top and `derived/geo/...` beside it.

The app's map set contract is unchanged: `map-set.json` lists each file and its byte size;
`server.py` reads `national.sqlite` through `national_mapdb()` and serves `/api/map/*`.

## Layers still to add

| Layer | US source | Canadian source | Work |
|---|---|---|---|
| Terrain | USGS 3DEP 1° GeoTIFF | NRCan MRDEM 30 m | new reader; COG tiles, reproject to terrain-RGB |
| Water resources | NHD + NID | NHN / Ontario Hydro Network / BC Freshwater Atlas; provincial dam inventories | new source adapters |
| Buildings | Microsoft US footprints | StatCan Open Database of Buildings; Microsoft Canadian footprints | country filter and tile bucket |
| Crops | USDA CDL | AAFC Annual Crop Inventory | class mapping |
| Addresses | Overture US | Overture Canada / StatCan National Address Register | country filter, postal-code parsing |
| Places | GNIS + Census | Canadian Geographical Names + StatCan + OSM | new place builder (OSM first) |

## App integration

- Add `maps` entries to the manifest with `id`, `title`, `kind: province`, `installed_bytes`,
  and the zip URL/size/SHA-256.
- Group the setup picker by country; today it says “Choose your state”.
- `engine/address_search.py` is US-only: Canadian postal codes (`A1A 1A1`), province names and
  French street types need handling before address search is offered.
- `web/map.js` labels some layers California-only; those stay empty outside the US.

## Licences

OSM data is ODbL 1.0: credit “© OpenStreetMap contributors” and share the derived database under
the ODbL. Canadian federal/provincial sources use OGL–Canada, OGL–Ontario, OGL–British Columbia or
the Statistics Canada Open Licence; attribution sentences are in REGIONS.md. Add the new sources
to `THIRD_PARTY_NOTICES.md` when their layers land.
