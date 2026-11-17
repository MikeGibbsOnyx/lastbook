#!/usr/bin/env python3
"""Build a Lastbook national map database directly from an OSM PBF.

Geofabrik publishes free GeoPackages for most Canadian provinces but only PBFs for British
Columbia and Nunavut. This reads the PBF with pyosmium and writes the same feat/feat_idx/poi/meta
schema as tools/build_map.py, so the rest of the pipeline is unchanged.

  python3 tools/build_map_pbf.py british-columbia-latest.osm.pbf national.sqlite \
      --bounds -139.22,48.14,-113.90,60.16
"""
import argparse
import math
import sqlite3
import struct
import time
from array import array

import osmium

Q = 1e6
ROAD_Z = {'motorway': 5, 'trunk': 6, 'motorway_link': 10, 'trunk_link': 10, 'primary': 8, 'primary_link': 12,
          'secondary': 10, 'secondary_link': 13, 'tertiary': 11, 'tertiary_link': 13, 'residential': 13,
          'unclassified': 13, 'living_street': 14, 'pedestrian': 14, 'busway': 14, 'service': 15,
          'track': 13, 'track_grade1': 13, 'track_grade2': 13, 'track_grade3': 13, 'track_grade4': 13, 'track_grade5': 13,
          'footway': 15, 'path': 14, 'cycleway': 14, 'steps': 16, 'bridleway': 14, 'unknown': 15}
LANDUSE_KEEP = {'park': 'park', 'forest': 'green', 'grass': 'green', 'meadow': 'green', 'scrub': 'green', 'heath': 'green',
                'recreation_ground': 'park', 'cemetery': 'park', 'allotments': 'farm', 'farmland': 'farm',
                'orchard': 'farm', 'vineyard': 'farm', 'farmyard': 'farm', 'residential': 'res', 'commercial': 'com',
                'retail': 'com', 'industrial': 'ind', 'military': 'ind', 'quarry': 'ind', 'landfill': 'ind'}
PLACE_Z = {'county': 7, 'city': 6, 'town': 9, 'suburb': 12, 'village': 11, 'hamlet': 14, 'locality': 14, 'island': 11,
           'farm': 15, 'region': 5}
POI_KEEP = {'hospital', 'clinic', 'doctors', 'pharmacy', 'chemist', 'dentist', 'veterinary', 'fire_station', 'police',
            'drinking_water', 'water_tower', 'water_works', 'fountain', 'toilet', 'shelter', 'community_centre',
            'town_hall', 'school', 'library', 'supermarket', 'convenience', 'doityourself', 'hardware', 'garden_centre',
            'post_office', 'camp_site', 'wastewater_plant', 'comms_tower', 'spring', 'park', 'courthouse', 'embassy',
            'nursing_home', 'kindergarten', 'college', 'university', 'bicycle_shop', 'car_repair', 'fuel', 'beach'}
POI_TAGS = ('amenity', 'shop', 'tourism', 'leisure', 'healthcare', 'man_made')


def simplify(flat, tol):
    if len(flat) <= 4 or tol <= 0:
        return flat
    out = [flat[0], flat[1]]
    px, py = flat[0], flat[1]
    for i in range(2, len(flat) - 2, 2):
        x, y = flat[i], flat[i + 1]
        if abs(x - px) > tol or abs(y - py) > tol:
            out += [x, y]
            px, py = x, y
    out += [flat[-2], flat[-1]]
    return out


def pack(parts):
    a = array('i', [len(parts)])
    for p in parts:
        n = len(p) // 2
        a.append(n)
        lx = ly = 0
        for i in range(n):
            x, y = int(round(p[2 * i] * Q)), int(round(p[2 * i + 1] * Q))
            a.append(x - lx); a.append(y - ly)
            lx, ly = x, y
    return a.tobytes()


def bbox(parts):
    xs = [v for p in parts for v in p[0::2]]
    ys = [v for p in parts for v in p[1::2]]
    return min(xs), max(xs), min(ys), max(ys)


def area_z(minx, maxx, miny, maxy, base):
    size = max(maxx - minx, maxy - miny)
    if size <= 0:
        return 17
    z = int(math.log2(360 / size)) - 4
    return max(base, min(16, z))


class Builder(osmium.SimpleHandler):
    def __init__(self, dst, source, bounds, data_as_of, skip_buildings=False, limit=0):
        super().__init__()
        self.db = sqlite3.connect(dst)
        self.db.executescript('''PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF;
          DROP TABLE IF EXISTS feat; DROP TABLE IF EXISTS feat_idx; DROP TABLE IF EXISTS poi; DROP TABLE IF EXISTS meta;
          CREATE TABLE feat(id INTEGER PRIMARY KEY, layer TEXT, cls TEXT, name TEXT, minz INTEGER, geom BLOB);
          CREATE VIRTUAL TABLE feat_idx USING rtree(id, minx, maxx, miny, maxy, minz, maxz);
          CREATE TABLE poi(id INTEGER PRIMARY KEY, cls TEXT, name TEXT, lon REAL, lat REAL);
          CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);''')
        self.source = source
        self.bounds = bounds
        self.data_as_of = data_as_of
        self.skip_buildings = skip_buildings
        self.limit = limit
        self.fid = 0
        self.pid = 0
        self.seen = 0
        self.t0 = time.time()

    def add(self, layer, cls, name, minz, parts):
        if not parts:
            return
        self.fid += 1
        bx = bbox(parts)
        self.db.execute('INSERT INTO feat VALUES (?,?,?,?,?,?)', (self.fid, layer, cls, name, minz, pack(parts)))
        self.db.execute('INSERT INTO feat_idx VALUES (?,?,?,?,?,?,?)', (self.fid, *bx, minz, 30))
        self.seen += 1
        if self.limit and self.seen >= self.limit:
            raise StopIteration

    @staticmethod
    def ring(ring):
        pts = []
        try:
            for n in ring:
                loc = n.location
                if not loc.valid():
                    return None
                pts += [loc.lon, loc.lat]
        except (osmium.InvalidLocationError, RuntimeError):
            return None
        return [pts] if len(pts) >= 6 else None

    def node(self, n):
        tags = n.tags
        try:
            loc = n.location
            if not loc.valid():
                return
        except (osmium.InvalidLocationError, RuntimeError):
            return
        place = tags.get('place')
        if place and tags.get('name'):
            z = PLACE_Z.get(place, 14)
            pop = tags.get('population', '')
            if place in ('city', 'town') and pop.isdigit() and int(pop) > 300000:
                z = 5
            self.add('place', place, tags.get('name'), z, [[loc.lon, loc.lat]])
            return
        for key in POI_TAGS:
            val = tags.get(key)
            if val in POI_KEEP:
                self.pid += 1
                self.db.execute('INSERT INTO poi VALUES (?,?,?,?,?)', (self.pid, val, tags.get('name'), loc.lon, loc.lat))
                break
        if tags.get('natural') == 'spring':
            self.pid += 1
            self.db.execute('INSERT INTO poi VALUES (?,?,?,?,?)', (self.pid, 'spring', tags.get('name'), loc.lon, loc.lat))

    def way(self, w):
        tags = w.tags
        if not tags:
            return
        try:
            pts = []
            for n in w.nodes:
                loc = n.location
                if not loc.valid():
                    return
                pts += [loc.lon, loc.lat]
        except (osmium.InvalidLocationError, RuntimeError):
            return
        if len(pts) < 4:
            return
        highway = tags.get('highway')
        if highway in ROAD_Z:
            self.add('road', highway, tags.get('name') or tags.get('ref'), ROAD_Z[highway], [pts])
            return
        waterway = tags.get('waterway')
        if waterway in ('river', 'stream', 'canal', 'drain', 'ditch'):
            self.add('waterway', waterway, tags.get('name'), 10 if waterway == 'river' else 13, [pts])
            return
        railway = tags.get('railway')
        if railway in ('rail', 'light_rail', 'subway', 'tram', 'narrow_gauge', 'monorail'):
            self.add('rail', railway, tags.get('name'), 10 if railway == 'rail' else 13, [pts])
            return
        if tags.get('building') and not self.skip_buildings and w.is_closed():
            self.add('bldg', tags.get('building') or '', None, 15, [simplify(pts, 0.000002)])

    def area(self, a):
        tags = a.tags
        if not tags:
            return
        parts = []
        try:
            for ring in a.outer_rings():
                p = self.ring(ring)
                if p:
                    parts.extend(p)
        except (osmium.InvalidLocationError, RuntimeError):
            return
        if not parts:
            return
        name = tags.get('name')
        if tags.get('building') and not self.skip_buildings:
            self.add('bldg', tags.get('building') or '', None, 15, [simplify(p, 0.000002) for p in parts])
            return
        natural = tags.get('natural')
        landuse = tags.get('landuse')
        if natural in ('water', 'bay') or tags.get('water') or landuse == 'reservoir':
            b = bbox(parts)
            self.add('water', tags.get('water') or natural or landuse or 'water', name, area_z(*b, 7),
                     [simplify(p, 0.00001) for p in parts])
        elif natural == 'wetland':
            b = bbox(parts)
            self.add('wet', natural, name, area_z(*b, 7), [simplify(p, 0.00001) for p in parts])
        elif natural in ('beach', 'sand'):
            b = bbox(parts)
            self.add('beach', natural, name, area_z(*b, 10), parts)
        elif landuse in LANDUSE_KEEP:
            b = bbox(parts)
            self.add('land', LANDUSE_KEEP[landuse], name, area_z(*b, 9), [simplify(p, 0.00001) for p in parts])
        elif tags.get('leisure') == 'park' or tags.get('boundary') == 'protected_area':
            b = bbox(parts)
            self.add('land', 'park', name, area_z(*b, 8), [simplify(p, 0.00002) for p in parts])

    def finish(self):
        self.db.execute('CREATE INDEX poi_cls ON poi(cls, lon, lat)')
        self.db.executemany('INSERT INTO meta VALUES (?,?)', [
            ('source', self.source),
            ('data_as_of', self.data_as_of),
            ('bounds', self.bounds),
            ('built', time.strftime('%Y-%m-%dT%H:%M:%S')),
        ])
        self.db.commit()
        print('done features', self.fid, 'pois', self.pid, round(time.time() - self.t0), 's', flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('src')
    ap.add_argument('dst')
    ap.add_argument('--source-label', default='OpenStreetMap contributors (ODbL 1.0)')
    ap.add_argument('--bounds', required=True)
    ap.add_argument('--data-as-of', default='')
    ap.add_argument('--skip-buildings', action='store_true')
    ap.add_argument('--limit', type=int, default=0, help='stop after N features (testing only)')
    a = ap.parse_args()
    b = Builder(a.dst, a.source_label, a.bounds, a.data_as_of, a.skip_buildings, a.limit)
    try:
        b.apply_file(a.src, locations=True)
    except StopIteration:
        pass
    b.finish()


if __name__ == '__main__':
    main()
