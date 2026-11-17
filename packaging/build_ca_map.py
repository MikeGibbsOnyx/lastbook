#!/usr/bin/env python3
"""Build a Lastbook map set for a Canadian province or territory from Geofabrik OSM data.

  python3 packaging/build_ca_map.py --code CA-ON --gpkg sources/ontario-latest-free.gpkg.zip \
      --pbf sources/ontario-latest.osm.pbf --out out/CA-ON

Produces out/<code>/derived/geo/{national,places}.sqlite, national-status.json, socal-cells.json,
map-set.json, and Lastbook-Map-<code>.zip. The zip layout is the one Lastbook's setup accepts:
map-set.json at the top and derived/geo/... beside it (no LastbookData/ folder).

Ontario and other inland provinces skip the coastline step. Coastal provinces pass --coast and need
pyosmium installed for tools/build_coast.py.
"""
import argparse
import datetime
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / 'tools'

REGIONS = {
    'CA-ON': ('Ontario', '-95.31,41.52,-74.17,57.01', 'ontario'),
    'CA-NS': ('Nova Scotia', '-66.90,43.30,-59.60,47.20', 'nova-scotia'),
    'CA-NB': ('New Brunswick', '-69.10,44.40,-63.60,48.20', 'new-brunswick'),
    'CA-QC': ('Quebec', '-79.90,44.90,-57.00,63.10', 'quebec'),
    'CA-BC': ('British Columbia', '-139.22,48.14,-113.90,60.16', 'british-columbia'),
    'CA-AB': ('Alberta', '-120.10,48.90,-109.90,60.10', 'alberta'),
    'CA-MB': ('Manitoba', '-102.30,48.90,-88.90,60.10', 'manitoba'),
    'CA-SK': ('Saskatchewan', '-110.10,48.90,-101.30,60.10', 'saskatchewan'),
    'CA-PE': ('Prince Edward Island', '-64.60,45.90,-61.90,47.10', 'prince-edward-island'),
    'CA-NL': ('Newfoundland and Labrador', '-67.90,46.50,-52.50,60.50', 'newfoundland-and-labrador'),
    'CA-YT': ('Yukon', '-141.10,59.90,-123.70,69.70', 'yukon'),
    'CA-NT': ('Northwest Territories', '-136.50,60.00,-101.00,78.80', 'northwest-territories'),
    'CA-NU': ('Nunavut', '-120.00,51.00,-61.00,83.20', 'nunavut'),
}
COASTAL = {'CA-NS', 'CA-NB', 'CA-BC', 'CA-NL', 'CA-PE'}


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 24), b''):
            h.update(chunk)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--code', required=True, choices=sorted(REGIONS))
    ap.add_argument('--gpkg', required=True)
    ap.add_argument('--pbf')
    ap.add_argument('--out', required=True)
    ap.add_argument('--skip-buildings', action='store_true')
    ap.add_argument('--coast', action='store_true', help='add the ocean/coast polygon (coastal provinces)')
    ap.add_argument('--keep', action='store_true', help='keep the unpacked map set beside the zip')
    a = ap.parse_args()

    name, bounds, slug = REGIONS[a.code]
    out = Path(a.out)
    geo = out / 'derived/geo'
    geo.mkdir(parents=True, exist_ok=True)

    gpkg = Path(a.gpkg)
    if gpkg.suffix == '.zip':
        # build_map.py reads a GeoPackage, not the Geofabrik zip: unpack it beside the zip.
        unpack = out / 'gpkg'
        unpack.mkdir(parents=True, exist_ok=True)
        target = unpack / f'{slug}.gpkg'
        if not target.exists():
            import zipfile as zf
            with zf.ZipFile(gpkg) as z:
                member = next(n for n in z.namelist() if n.endswith('.gpkg'))
                with z.open(member) as src, open(target, 'wb') as dst:
                    shutil.copyfileobj(src, dst, 1 << 24)
        gpkg = target

    data_as_of = datetime.datetime.fromtimestamp(os.path.getmtime(gpkg), datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    source = f'OpenStreetMap contributors, via Geofabrik {slug}-latest-free.gpkg.zip (ODbL 1.0)'
    national = geo / 'national.sqlite'

    subprocess.run([
        sys.executable, str(TOOLS / 'build_map.py'), str(gpkg), str(national),
        '--source-label', source, '--bounds', bounds, '--data-as-of', data_as_of,
        *(['--skip-buildings'] if a.skip_buildings else []),
    ], check=True)

    if a.coast:
        if not a.pbf:
            sys.exit('--coast needs --pbf')
        subprocess.run([sys.executable, str(TOOLS / 'build_coast.py'), str(a.pbf), str(national)], check=True)

    subprocess.run([sys.executable, str(TOOLS / 'build_places_ca.py'), str(national), str(geo / 'places.sqlite'), name], check=True)

    db = sqlite3.connect(f'file:{national}?mode=ro', uri=True)
    features = db.execute('SELECT count(*) FROM feat').fetchone()[0]
    pois = db.execute('SELECT count(*) FROM poi').fetchone()[0]
    db.close()
    status = {'state': 'complete', 'stage': 'ready', 'features': features}
    (geo / 'national-status.json').write_text(json.dumps(status), encoding='utf-8')
    (geo / 'socal-cells.json').write_text('[]', encoding='utf-8')

    files = {}
    for rel in ('derived/geo/national.sqlite', 'derived/geo/places.sqlite',
                'derived/geo/national-status.json', 'derived/geo/socal-cells.json'):
        files[rel] = (out / rel).stat().st_size
    (out / 'map-set.json').write_text(json.dumps({'name': a.code, 'files': files}, indent=1), encoding='utf-8')

    zpath = out / f'Lastbook-Map-{a.code}.zip'
    with zipfile.ZipFile(zpath, 'w', allowZip64=True, compression=zipfile.ZIP_STORED) as z:
        z.write(out / 'map-set.json', 'map-set.json')
        for rel in files:
            z.write(out / rel, rel)

    summary = {
        'code': a.code, 'name': name, 'bounds': bounds, 'features': features, 'pois': pois,
        'zip': str(zpath), 'zip_bytes': zpath.stat().st_size, 'zip_sha256': sha256(zpath),
        'files': {k: v for k, v in files.items()},
    }
    (out / 'build.json').write_text(json.dumps(summary, indent=1), encoding='utf-8')
    print(json.dumps(summary, indent=1))

    if not a.keep:
        shutil.rmtree(out / 'gpkg', ignore_errors=True)


if __name__ == '__main__':
    main()
