#!/usr/bin/env python3
"""Merge a Canadian terrain.sqlite into a US terrain.sqlite.

  python3 packaging/merge_ca_terrain.py --us terrain.sqlite --ca terrain-ca.sqlite --out terrain.sqlite
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
    before = db.execute('SELECT count(*) FROM tile').fetchone()[0]
    ca_count = db.execute('SELECT count(*) FROM ca.tile').fetchone()[0]
    db.execute('INSERT OR REPLACE INTO tile SELECT z,x,y,png FROM ca.tile')
    after = db.execute('SELECT count(*) FROM tile').fetchone()[0]
    db.execute("INSERT OR REPLACE INTO meta VALUES ('canada', ?)", (json.dumps({'tiles': ca_count, 'built': time.strftime('%Y-%m-%dT%H:%M:%S')}),))
    db.execute("INSERT OR REPLACE INTO meta VALUES ('canada:source', ?)", ('NRCan MRDEM-30 DTM, OGL-Canada; Copernicus WorldDEM-30 notice',))
    db.commit()
    db.close()
    print(json.dumps({'tiles_before': before, 'tiles_after': after, 'added': ca_count, 'out': str(out)}, indent=1))


if __name__ == '__main__':
    main()
