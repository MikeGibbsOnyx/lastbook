#!/usr/bin/env python3
"""Merge a Canadian map set into an existing Lastbook map set.

  python3 packaging/merge_ca_map.py --us /path/to/LastbookData --ca out/CA-ON --out /path/to/merged

The US map set keeps its water, terrain, buildings, crops and address files. Canada contributes
national features and place-finder rows; feature and place ids are offset so nothing collides.
Run it repeatedly to add more provinces to the same merged map.
"""
import argparse
import json
import shutil
import sqlite3
from pathlib import Path


def bounds_of(db):
    row = db.execute("SELECT value FROM meta WHERE key='bounds'").fetchone()
    if not row:
        return None
    try:
        w, s, e, n = map(float, row[0].split(','))
        return [w, s, e, n]
    except (ValueError, TypeError):
        return None


def merge_national(us_path, ca_path):
    db = sqlite3.connect(us_path)
    db.execute('PRAGMA synchronous=OFF')
    db.execute('ATTACH DATABASE ? AS ca', (str(ca_path),))
    off_f = db.execute('SELECT COALESCE(MAX(id),0) FROM feat').fetchone()[0]
    db.execute('INSERT INTO feat SELECT id+?, layer, cls, name, minz, geom FROM ca.feat', (off_f,))
    db.execute('INSERT INTO feat_idx SELECT id+?, minx, maxx, miny, maxy, minz, maxz FROM ca.feat_idx', (off_f,))
    off_p = db.execute('SELECT COALESCE(MAX(id),0) FROM poi').fetchone()[0]
    db.execute('INSERT INTO poi SELECT id+?, cls, name, lon, lat FROM ca.poi', (off_p,))
    us_b, ca_b = bounds_of(db), None
    ca_db = sqlite3.connect(f'file:{ca_path}?mode=ro', uri=True)
    ca_b = bounds_of(ca_db)
    ca_db.close()
    if us_b and ca_b:
        merged = [min(us_b[0], ca_b[0]), min(us_b[1], ca_b[1]), max(us_b[2], ca_b[2]), max(us_b[3], ca_b[3])]
        db.execute("UPDATE meta SET value=? WHERE key='bounds'", (','.join(f'{v:g}' for v in merged),))
    features = db.execute('SELECT count(*) FROM feat').fetchone()[0]
    db.execute("UPDATE meta SET value=? WHERE key='status'", (json.dumps({'state': 'complete', 'stage': 'ready', 'features': features}),))
    db.execute("UPDATE meta SET value=? WHERE key='source'", ('OpenStreetMap contributors (ODbL 1.0); US and Canadian extracts via Geofabrik',))
    db.commit()
    db.close()
    return features


def merge_places(us_path, ca_path):
    db = sqlite3.connect(us_path)
    db.execute('PRAGMA synchronous=OFF')
    db.execute('ATTACH DATABASE ? AS ca', (str(ca_path),))
    off = db.execute('SELECT COALESCE(MAX(id),0) FROM place').fetchone()[0]
    db.execute('INSERT INTO place SELECT id+?, name, kind, detail, lat, lon, rank, source FROM ca.place', (off,))
    db.execute("INSERT INTO place_fts(place_fts) VALUES ('rebuild')")
    db.commit()
    n = db.execute('SELECT count(*) FROM place').fetchone()[0]
    db.close()
    return n


def merge_addresses(us_path, ca_path):
    if not ca_path.is_file():
        return 0
    if not us_path.is_file():
        shutil.copy2(ca_path, us_path)
        db = sqlite3.connect(f'file:{us_path}?mode=ro', uri=True)
        n = db.execute('SELECT count(*) FROM addr').fetchone()[0]
        db.close()
        return n
    db = sqlite3.connect(us_path)
    db.execute('PRAGMA synchronous=OFF')
    db.execute('ATTACH DATABASE ? AS ca', (str(ca_path),))
    db.execute('INSERT INTO addr(num,street,norm,city,state,zip,lat,lon) SELECT num,street,norm,city,state,zip,lat,lon FROM ca.addr')
    db.execute('CREATE INDEX IF NOT EXISTS addr_norm ON addr(norm, num)')
    n = db.execute('SELECT count(*) FROM addr').fetchone()[0]
    db.commit()
    db.close()
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--us', required=True, help='US LastbookData folder (or a folder holding derived/geo)')
    ap.add_argument('--ca', required=True, help='Canadian map set folder (the one holding derived/geo)')
    ap.add_argument('--out', required=True)
    a = ap.parse_args()

    us = Path(a.us)
    if (us / 'derived/geo').is_dir():
        us_geo = us / 'derived/geo'
    else:
        us_geo = us
    ca = Path(a.ca)
    ca_geo = ca / 'derived/geo'
    out = Path(a.out)
    out_geo = out / 'derived/geo'
    out_geo.mkdir(parents=True, exist_ok=True)

    for name in ('national.sqlite', 'places.sqlite'):
        if not (ca_geo / name).is_file():
            raise SystemExit(f'missing {ca_geo / name}')
        if not (out_geo / name).is_file():
            if not (us_geo / name).is_file():
                raise SystemExit(f'missing {us_geo / name}')
            shutil.copy2(us_geo / name, out_geo / name)

    # Carry the US map's other layers (water, terrain, buildings, crops, address indexes) forward.
    for p in us_geo.iterdir():
        if p.is_file() and p.name not in ('national.sqlite', 'places.sqlite') and not (out_geo / p.name).exists():
            shutil.copy2(p, out_geo / p.name)
    atlas = us / 'library-data/geography/resources/atlas.sqlite'
    if atlas.is_file():
        dest = out / 'library-data/geography/resources/atlas.sqlite'
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not dest.exists():
            shutil.copy2(atlas, dest)

    features = merge_national(out_geo / 'national.sqlite', ca_geo / 'national.sqlite')
    places = merge_places(out_geo / 'places.sqlite', ca_geo / 'places.sqlite')
    addresses = merge_addresses(out_geo / 'addresses.sqlite', ca_geo / 'addresses.sqlite')
    (out_geo / 'national-status.json').write_text(json.dumps({'state': 'complete', 'stage': 'ready', 'features': features}), encoding='utf-8')
    if not (out_geo / 'socal-cells.json').exists():
        (out_geo / 'socal-cells.json').write_text('[]', encoding='utf-8')

    # Keep every other US layer and the map-set file list; only the two merged files change size.
    if (us / 'map-set.json').is_file():
        ms = json.loads((us / 'map-set.json').read_text(encoding='utf-8'))
    else:
        ms = {'name': 'merged', 'files': {}}
    for rel in ('derived/geo/national.sqlite', 'derived/geo/places.sqlite', 'derived/geo/addresses.sqlite', 'derived/geo/national-status.json', 'derived/geo/socal-cells.json'):
        p = out / rel
        if p.is_file():
            ms['files'][rel] = p.stat().st_size
    (out / 'map-set.json').write_text(json.dumps(ms, indent=1), encoding='utf-8')
    print(json.dumps({'features': features, 'places': places, 'addresses': addresses, 'map_set': str(out / 'map-set.json')}, indent=1))


if __name__ == '__main__':
    main()
