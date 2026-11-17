#!/usr/bin/env python3
"""Merge a Canadian water.sqlite (dams/resources) into a US water.sqlite.

  python3 packaging/merge_ca_water.py --us /path/water.sqlite --ca water-ca.sqlite --out /path/water.sqlite
"""
import argparse
import json
import shutil
import sqlite3
import time
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--us', required=True)
    ap.add_argument('--ca', required=True)
    ap.add_argument('--out', required=True)
    a = ap.parse_args()
    us, ca, out = Path(a.us), Path(a.ca), Path(a.out)
    if not out.exists():
        shutil.copy2(us if us.exists() else ca, out)
    db = sqlite3.connect(out)
    db.execute('PRAGMA synchronous=OFF')
    db.execute('ATTACH DATABASE ? AS ca', (str(ca),))
    off = db.execute('SELECT COALESCE(MAX(id),0) FROM resource').fetchone()[0]
    db.execute('INSERT INTO resource SELECT id+?, source_id, kind, name, lat, lon, detail, source, origin FROM ca.resource', (off,))
    db.execute('INSERT INTO spatial SELECT id+?, minx, maxx, miny, maxy FROM ca.spatial', (off,))
    try:
        off_f = db.execute('SELECT COALESCE(MAX(id),0) FROM feat').fetchone()[0]
        db.execute('INSERT INTO feat SELECT id+?, layer, cls, name, minz, geom, origin FROM ca.feat', (off_f,))
        db.execute('INSERT INTO feat_idx SELECT id+?, minx, maxx, miny, maxy, minz, maxz FROM ca.feat_idx', (off_f,))
    except sqlite3.OperationalError:
        pass
    count = db.execute('SELECT count(*) FROM resource').fetchone()[0]
    ca_count = db.execute('SELECT count(*) FROM ca.resource').fetchone()[0]
    db.execute("INSERT OR REPLACE INTO meta VALUES ('odi', ?)", (json.dumps({'records': ca_count, 'built': time.strftime('%Y-%m-%dT%H:%M:%S')}),))
    db.execute("INSERT OR REPLACE INTO meta VALUES ('odi:source', ?)", ('Ontario Dam Inventory (ODI), OGL-Ontario',))
    db.commit()
    db.close()
    print(json.dumps({'resources': count, 'added': ca_count, 'out': str(out)}, indent=1))


if __name__ == '__main__':
    main()
