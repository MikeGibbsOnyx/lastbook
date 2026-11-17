#!/usr/bin/env python3
"""Merge several Canadian province map sets into one Lastbook map set.

  python3 packaging/merge_ca_sets.py --out out/CA-Canada out/CA-ON-full out/CA-NS ...

The output has one national.sqlite and one places.sqlite covering every supplied province, with
feature/place ids offset so they do not collide. It is the set to merge into the US map later.
"""
import argparse
import json
import shutil
import sqlite3
from pathlib import Path


def geo_of(path):
    p = Path(path)
    return p / 'derived/geo' if (p / 'derived/geo').is_dir() else p


def bounds(db):
    row = db.execute("SELECT value FROM meta WHERE key='bounds'").fetchone()
    if not row:
        return None
    try:
        return [float(v) for v in row[0].split(',')]
    except (ValueError, TypeError):
        return None


def merge_one(national, places, src_geo):
    db = sqlite3.connect(national)
    db.execute('PRAGMA synchronous=OFF')
    db.execute('ATTACH DATABASE ? AS ca', (str(src_geo / 'national.sqlite'),))
    off_f = db.execute('SELECT COALESCE(MAX(id),0) FROM feat').fetchone()[0]
    db.execute('INSERT INTO feat SELECT id+?, layer, cls, name, minz, geom FROM ca.feat', (off_f,))
    db.execute('INSERT INTO feat_idx SELECT id+?, minx, maxx, miny, maxy, minz, maxz FROM ca.feat_idx', (off_f,))
    off_p = db.execute('SELECT COALESCE(MAX(id),0) FROM poi').fetchone()[0]
    db.execute('INSERT INTO poi SELECT id+?, cls, name, lon, lat FROM ca.poi', (off_p,))
    db.commit()
    db.close()

    pdb = sqlite3.connect(places)
    pdb.execute('PRAGMA synchronous=OFF')
    pdb.execute('ATTACH DATABASE ? AS ca', (str(src_geo / 'places.sqlite'),))
    off = pdb.execute('SELECT COALESCE(MAX(id),0) FROM place').fetchone()[0]
    pdb.execute('INSERT INTO place SELECT id+?, name, kind, detail, lat, lon, rank, source FROM ca.place', (off,))
    pdb.commit()
    pdb.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', required=True)
    ap.add_argument('sets', nargs='+')
    a = ap.parse_args()
    out = Path(a.out)
    geo = out / 'derived/geo'
    geo.mkdir(parents=True, exist_ok=True)
    sets = [geo_of(s) for s in a.sets]
    for name in ('national.sqlite', 'places.sqlite'):
        shutil.copy2(sets[0] / name, geo / name)
    for src in sets[1:]:
        merge_one(geo / 'national.sqlite', geo / 'places.sqlite', src)
    pdb = sqlite3.connect(geo / 'places.sqlite')
    pdb.execute("INSERT INTO place_fts(place_fts) VALUES ('rebuild')")
    pdb.commit()
    pdb.close()

    db = sqlite3.connect(geo / 'national.sqlite')
    bs = [bounds(db)]
    for src in sets[1:]:
        c = sqlite3.connect(f'file:{src / "national.sqlite"}?mode=ro', uri=True)
        bs.append(bounds(c))
        c.close()
    bs = [b for b in bs if b]
    if bs:
        merged = [min(b[0] for b in bs), min(b[1] for b in bs), max(b[2] for b in bs), max(b[3] for b in bs)]
        db.execute("UPDATE meta SET value=? WHERE key='bounds'", (','.join(f'{v:g}' for v in merged),))
    features = db.execute('SELECT count(*) FROM feat').fetchone()[0]
    db.execute("UPDATE meta SET value=? WHERE key='status'", (json.dumps({'state': 'complete', 'stage': 'ready', 'features': features}),))
    db.execute("UPDATE meta SET value=? WHERE key='source'", ('OpenStreetMap contributors (ODbL 1.0); Canadian provincial extracts via Geofabrik',))
    db.commit()
    db.close()
    (geo / 'national-status.json').write_text(json.dumps({'state': 'complete', 'stage': 'ready', 'features': features}), encoding='utf-8')
    (geo / 'socal-cells.json').write_text('[]', encoding='utf-8')
    files = {}
    for rel in ('derived/geo/national.sqlite', 'derived/geo/places.sqlite', 'derived/geo/national-status.json', 'derived/geo/socal-cells.json'):
        files[rel] = (out / rel).stat().st_size
    (out / 'map-set.json').write_text(json.dumps({'name': 'CA-Canada', 'files': files}, indent=1), encoding='utf-8')
    print(json.dumps({'features': features, 'sets': len(sets), 'out': str(out)}, indent=1))


if __name__ == '__main__':
    main()
