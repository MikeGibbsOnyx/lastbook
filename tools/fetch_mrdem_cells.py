#!/usr/bin/env python3
"""Cut NRCan MRDEM-30 DTM into Lastbook's 1-degree GeoTIFF cells.

  python3 tools/fetch_mrdem_cells.py --out /path/terrain-src --national national.sqlite --res-arcsec 3 --workers 8

The national database is used only as a land mask: a cell is skipped when no map feature
intersects it, which keeps ocean cells out. Each output is named like n45w080/floatn45w080_1.tif,
the layout tools/build_terrain.py already scans.
"""
import argparse
import math
import os
import sqlite3
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

SRC = '/vsicurl/https://canelevation-dem.s3.ca-central-1.amazonaws.com/mrdem-30/mrdem-30-dtm.tif'


def cell_name(top, left):
    return f"{'n' if top >= 0 else 's'}{abs(top):02d}{'e' if left >= 0 else 'w'}{abs(left):03d}"


def intersects(db, w, s, e, n):
    return db.execute(
        'SELECT 1 FROM feat_idx WHERE maxx>=? AND minx<=? AND maxy>=? AND miny<=? LIMIT 1',
        (w, e, s, n),
    ).fetchone() is not None


def run_cell(args):
    top, left, out, res = args
    name = cell_name(top, left)
    target = Path(out) / name / f'float{name}_1.tif'
    if target.exists() and target.stat().st_size > 1_000_000:
        return name, 'skip', 0
    target.parent.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.update({
        'GDAL_DISABLE_READDIR_ON_OPEN': 'EMPTY_DIR',
        'CPL_VSIL_CURL_USE_HEAD': 'YES',
        'GDAL_HTTP_MERGE_CONSECUTIVE_RANGES': 'YES',
        'GDAL_HTTP_MULTIPLEX': 'YES',
        'GDAL_HTTP_VERSION': '2',
        'VSI_CACHE': 'TRUE',
        'VSI_CACHE_SIZE': '500000000',
        'GDAL_HTTP_TIMEOUT': '120',
        'GDAL_HTTP_MAX_RETRY': '3',
    })
    cmd = [
        'gdalwarp', '-overwrite', '-q',
        '-t_srs', 'EPSG:4326',
        '-te', str(left), str(top - 1), str(left + 1), str(top),
        '-tr', str(res), str(res), '-tap', '-r', 'bilinear',
        '-srcnodata', '-32767', '-dstnodata', '-32767',
        '-co', 'COMPRESS=LZW', '-co', 'TILED=YES', '-co', 'PREDICTOR=2',
        '-of', 'GTiff', SRC, str(target),
    ]
    t0 = time.time()
    p = subprocess.run(cmd, env=env, capture_output=True, text=True)
    if p.returncode != 0 or not target.exists():
        return name, 'fail: ' + (p.stderr.strip().splitlines()[-1] if p.stderr.strip() else f'exit {p.returncode}'), time.time() - t0
    return name, 'ok', time.time() - t0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', required=True)
    ap.add_argument('--national', required=True)
    ap.add_argument('--res-arcsec', type=float, default=3.0, help='3 = about 90 m, 1 = about 30 m')
    ap.add_argument('--workers', type=int, default=8)
    ap.add_argument('--bounds', default='-141.1,41.52,-52.5,83.2')
    ap.add_argument('--limit', type=int, default=0)
    a = ap.parse_args()
    W, S, E, N = map(float, a.bounds.split(','))
    db = sqlite3.connect(f'file:{a.national}?mode=ro', uri=True)
    cells = []
    for top in range(math.ceil(S), math.floor(N) + 1):
        for left in range(math.floor(W), math.ceil(E)):
            if left + 1 <= W or left >= E or top < S or top - 1 > N:
                continue
            if not intersects(db, left, top - 1, left + 1, top):
                continue
            cells.append((top, left))
    db.close()
    if a.limit:
        cells = cells[:a.limit]
    print(f'{len(cells)} land cells to cut at {a.res_arcsec} arcsec', flush=True)
    res = a.res_arcsec / 3600.0
    jobs = [(top, left, a.out, res) for top, left in cells]
    ok = skip = fail = 0
    errors = []
    with ThreadPoolExecutor(a.workers) as pool:
        futs = {pool.submit(run_cell, j): j for j in jobs}
        for i, f in enumerate(as_completed(futs), 1):
            name, state, secs = f.result()
            if state == 'ok':
                ok += 1
            elif state == 'skip':
                skip += 1
            else:
                fail += 1
                errors.append((name, state))
                print(f'{name} {state}', flush=True)
            if i % 25 == 0 or i == len(jobs):
                print(f'{i}/{len(jobs)} cells: ok={ok} skip={skip} fail={fail}', flush=True)
    print(f'done ok={ok} skip={skip} fail={fail}', flush=True)
    if errors:
        print('errors:', errors[:20], flush=True)
        sys.exit(1)


if __name__ == '__main__':
    main()
