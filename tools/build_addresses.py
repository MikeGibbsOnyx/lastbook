"""Street addresses for address search: derived/geo/addresses.sqlite, from Overture Maps' open address data.

  derived/buildenv/bin/python tools/build_addresses.py [--bbox us | --bbox W,S,E,N] [--release 2026-10-21.0]

Overture's address theme gathers official address points (in California from the counties, via OpenAddresses), with
open licences (mostly CDLA-Permissive / public domain; see the 'sources' column). Reads the GeoParquet files straight
from Overture's public S3 bucket with DuckDB, keeping the whole US (default) or a box, and streams them into SQLite.
OpenStreetMap had too few addresses (none at all on many coastal streets).
"""
import argparse, re, sqlite3, time
from pathlib import Path

import duckdb

HERE = Path(__file__).resolve().parent.parent
OUT = HERE / 'derived/geo/addresses.sqlite'
WORDS = {'boulevard': 'blvd', 'avenue': 'ave', 'av': 'ave', 'street': 'st', 'drive': 'dr', 'road': 'rd', 'place': 'pl', 'court': 'ct',
         'lane': 'ln', 'terrace': 'ter', 'circle': 'cir', 'highway': 'hwy', 'parkway': 'pkwy', 'square': 'sq', 'north': 'n', 'south': 's',
         'east': 'e', 'west': 'w', 'mount': 'mt', 'saint': 'st'}


def norm(street):
    """'Saint Mary Boulevard' -> 'st mary blvd' (game/serve.py uses the same rules on what people type)."""
    return ' '.join(WORDS.get(w, w) for w in re.sub(r'[^a-z0-9 ]+', ' ', street.lower()).split())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--bbox', default='us', help="'us', 'ca', or W,S,E,N")
    ap.add_argument('--country', default='US', choices=('US', 'CA'))
    ap.add_argument('--province', help='Canadian province code, e.g. ON (optional)')
    ap.add_argument('--release', default='2026-10-21.0')
    ap.add_argument('--out', help='output sqlite path (default addresses.sqlite / addresses_ca.sqlite)')
    a = ap.parse_args()
    out = Path(a.out) if a.out else (OUT if a.country == 'US' else OUT.with_name('addresses_ca.sqlite'))
    where = f"country = '{a.country}'"
    if a.province:
        where += f" AND address_levels[1].value = '{a.province}'"
    if a.bbox not in ('us', 'ca'):
        w, s_, e, n = map(float, a.bbox.split(','))
        where += f' AND bbox.xmin BETWEEN {w} AND {e} AND bbox.ymin BETWEEN {s_} AND {n}'
    postcode = "coalesce(left(postcode, 5), '')" if a.country == 'US' else "coalesce(postcode, '')"
    t0 = time.time()
    c = duckdb.connect()
    c.execute("INSTALL httpfs; LOAD httpfs; INSTALL spatial; LOAD spatial; SET s3_region='us-west-2';")
    cur = c.execute(f"""
        SELECT number, street, coalesce(postal_city, address_levels[2].value, ''), coalesce(address_levels[1].value, ''),
               {postcode}, round(ST_Y(geometry), 6), round(ST_X(geometry), 6)
        FROM read_parquet('s3://overturemaps-us-west-2/release/{a.release}/theme=addresses/type=address/*', hive_partitioning=1)
        WHERE {where} AND number IS NOT NULL AND street IS NOT NULL""")
    tmp = out.with_suffix('.tmp')
    tmp.unlink(missing_ok=True)
    db = sqlite3.connect(tmp)
    db.executescript('PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF;'
                     'CREATE TABLE addr(num TEXT, street TEXT, norm TEXT, city TEXT, state TEXT, zip TEXT, lat REAL, lon REAL);'
                     'CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);')
    total = 0
    while rows := cur.fetchmany(500_000):
        db.executemany('INSERT INTO addr VALUES (?,?,?,?,?,?,?,?)',
                       ((num.strip(), st.strip(), norm(st), city.title(), state.upper()[:2], z, la, lo) for num, st, city, state, z, la, lo in rows))
        total += len(rows)
        print(f'{total:,} addresses, {time.time() - t0:.0f}s', flush=True)
    print('indexing', flush=True)
    db.execute('CREATE INDEX addr_norm ON addr(norm, num)')
    db.executemany('INSERT INTO meta VALUES (?,?)', [('bbox', a.bbox), ('country', a.country), ('count', str(total)), ('built', time.strftime('%Y-%m-%dT%H:%M:%S')),
                                                    ('source', f'Overture Maps addresses {a.release} ({a.country})')])
    db.commit(); db.close()
    tmp.replace(out)
    print(f'done: {total:,} addresses in {time.time() - t0:.0f}s -> {out}', flush=True)


if __name__ == '__main__':
    main()
