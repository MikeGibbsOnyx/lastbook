# Canadian regions — build plan and status

This is the implementation note for extending Lastbook's detailed maps outside the United States.
The design rationale and data-source survey live in [REGIONS.md](REGIONS.md) and
[regions-proposed.json](regions-proposed.json); this file records the build pipeline and what is done.

## Status (2026-11-17)

All 13 provinces and territories have a base map with roads, water, waterways, land, rail,
buildings and named places. The combined set is **CA-Canada**:

| | |
|---|---|
| Features | **42,724,133** |
| Named places | **128,426** |
| Addresses | **16,945,516** |
| Bounds | `-141.1,41.52,-52.5,83.2` |
| national.sqlite | 12.5 GB |
| addresses.sqlite | 1.76 GB |
| places.sqlite | 17.6 MB |

| # | Code | Region | Source | Features | Zip |
|---|---|---|---|---|---|
| 1 | `CA-ON` | Ontario | GPKG | 7,157,544 | 2.21 GB |
| 2 | `CA-NS` | Nova Scotia | GPKG | 645,168 | 185 MB |
| 3 | `CA-NB` | New Brunswick | GPKG | 489,339 | 142 MB |
| 4 | `CA-QC` | Quebec | GPKG | 8,551,094 | 2.39 GB |
| 5 | `CA-BC` | British Columbia | PBF | 6,752,638 | 1.99 GB |
| 6 | `CA-AB` | Alberta | GPKG | 2,830,235 | 780 MB |
| 7 | `CA-MB` | Manitoba | GPKG | 1,415,646 | 446 MB |
| 8 | `CA-SK` | Saskatchewan | GPKG | 1,076,819 | 285 MB |
| 9 | `CA-PE` | Prince Edward Island | GPKG | 127,586 | 27 MB |
| 10 | `CA-NL` | Newfoundland and Labrador | GPKG | 2,312,194 | 612 MB |
| 11 | `CA-YT` | Yukon | GPKG | 283,116 | 124 MB |
| 12 | `CA-NT` | Northwest Territories | GPKG | 2,219,785 | 759 MB |
| 13 | `CA-NU` | Nunavut | PBF | 8,862,969 | 2.46 GB |

Codes use the ISO 3166-2 style proposed in REGIONS.md. `CA` alone is already California.

## Pipeline

`packaging/build_ca_map.py` does one region at a time:

1. Unpack the Geofabrik `*-free.gpkg.zip` if needed.
2. `tools/build_map.py` → `derived/geo/national.sqlite` (`feat`, `feat_idx`, `poi`, `meta`).
   Buildings are included by default; `--skip-buildings` makes the lean base map.
3. `tools/build_map_pbf.py` for BC and Nunavut, which Geofabrik does not publish as free GPKGs.
4. `tools/build_places_ca.py` → `derived/geo/places.sqlite` from named OSM places and POIs.
5. Write `national-status.json`, `socal-cells.json`, and `map-set.json`.
6. Zip `Lastbook-Map-<code>.zip` with `map-set.json` at the top and `derived/geo/...` beside it.

`packaging/merge_ca_sets.py` combines the province sets into `CA-Canada` with offset feature and
place ids and a rebuilt place FTS index. `packaging/merge_ca_map.py` merges `CA-Canada` into a US
LastbookData map set, carrying the US water/terrain/buildings/crops files forward and appending
Canadian addresses to the US address index.

## Addresses

`tools/build_addresses.py --country CA` reads Overture Maps `theme=addresses` with DuckDB and keeps
the full six-character Canadian postal code (`M8W1T6`), unlike the US ZIP5 truncation. The build
produced 16,945,516 Canadian addresses in 268 seconds; the Toronto bbox test returned 1,028,275 rows.

Licence note: Overture's Canadian address records in the sampled Toronto data carry
`LicenseRef-Proprietary` via OpenAddresses `ca/countrywide`; confirm redistribution terms before
publishing an address pack. Local use is unaffected.

## Remaining layers

The following are researched and have exact sources, but are not yet built for Canada:

| Layer | Canadian source | Note |
|---|---|---|
| Terrain | NRCan MRDEM-30 DTM COG, `s3://canelevation-dem/mrdem-30/` | No 1° tile service; cut 1″ EPSG:4326 cells with `gdalwarp` over `/vsicurl/`. Ontario ≈ 8–13 GB, ~60 s/cell. OGL-Canada + Copernicus notice. |
| Water resources | Ontario Dam Inventory (1,892 points), OHN Waterbody (1.4M polygons) | OSM water is already in the national map; `water.sqlite` would add dams/resource pins. |
| Crops | AAFC Annual Crop Inventory 2025, Ontario 187 MB | EPSG:10820 Albers, not CDL EPSG:5070; class LUT 188 orchards, 190 vineyards, 182/183/185 berries. OGL-Canada. |
| Buildings | OSM buildings already included | StatCan ODB / Microsoft Canadian footprints would be an upgrade, not a blocker. |

## App integration

- The map set contract is unchanged: `map-set.json` lists each file and its byte size;
  `server.py` reads `national.sqlite` through `national_mapdb()` and serves `/api/map/*`.
- For a standalone Canada library, copy `CA-Canada/derived/geo/{national,places,addresses}.sqlite`
  and `map-set.json` into `LastbookData`.
- For a US+Canada library, run `merge_ca_map.py --us <LastbookData> --ca <CA-Canada> --out <merged>`.
- The setup picker still says “Choose your state”; province entries and country grouping are UI work.
- `engine/address_search.py` is US-only; Canadian postal codes and province names need handling
  before address search is offered in the app.

## Licences

OSM data is ODbL 1.0: credit “© OpenStreetMap contributors” and share the derived database under
the ODbL. Canadian federal/provincial sources use OGL–Canada, OGL–Ontario, OGL–British Columbia or
the Statistics Canada Open Licence; attribution sentences are in REGIONS.md. Add the new sources
to `THIRD_PARTY_NOTICES.md` when their layers land.
