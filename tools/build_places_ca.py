#!/usr/bin/env python3
"""Build a Lastbook places.sqlite for a Canadian province or territory from an OSM map database.

  python3 tools/build_places_ca.py national.sqlite places.sqlite "Ontario"

The map database is the output of tools/build_map.py (feat, feat_idx, poi, meta). Named OSM
places and kept POIs become the place finder's rows; no USGS, Census or other US source is read.
"""
import sqlite3
import struct
import sys

SRC, DST, REGION = sys.argv[1], sys.argv[2], sys.argv[3]

src = sqlite3.connect(f'file:{SRC}?mode=ro', uri=True)
out = sqlite3.connect(DST)
out.executescript('''
  DROP TABLE IF EXISTS place;
  DROP TABLE IF EXISTS place_fts;
  CREATE TABLE place(id INTEGER PRIMARY KEY, name TEXT, kind TEXT, detail TEXT, lat REAL, lon REAL, rank INTEGER, source TEXT);
  CREATE VIRTUAL TABLE place_fts USING fts5(name, detail, content='place', content_rowid='id', tokenize='unicode61');
''')

insert = 'INSERT INTO place(name, kind, detail, lat, lon, rank, source) VALUES (?,?,?,?,?,?,?)'
seen = set()
n = 0


def add(name, kind, lat, lon, rank):
    global n
    if not name:
        return
    key = (name.casefold(), round(lat, 5), round(lon, 5))
    if key in seen:
        return
    seen.add(key)
    out.execute(insert, (name, kind, f'{REGION} (OpenStreetMap)', lat, lon, rank, 'OpenStreetMap'))
    n += 1


for cls, name, lon, lat in src.execute("SELECT cls, name, lon, lat FROM poi WHERE name IS NOT NULL AND name <> ''"):
    add(name, (cls or '').replace('_', ' '), lat, lon, 4)

for cls, name, geom in src.execute("SELECT cls, name, geom FROM feat WHERE layer='place' AND name IS NOT NULL"):
    try:
        _, _, x, y = struct.unpack_from('<iiii', geom)
    except struct.error:
        continue
    add(name, cls or 'place', y / 1e6, x / 1e6, 1)

out.execute("INSERT INTO place_fts(place_fts) VALUES ('rebuild')")
out.commit()
out.close()
print(f'places {n}')
