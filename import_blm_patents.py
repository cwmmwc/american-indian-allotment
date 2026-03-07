#!/usr/bin/env python3
"""
Import all allotment patents from the BLM ArcGIS Feature Service
into the local allotment_research PostgreSQL database.

Source: https://services2.arcgis.com/8k2PygHqghVevhzy/arcgis/rest/services/
        tribal_land_patents_aliquot_20240304/FeatureServer/0

This creates a table `blm_allotment_patents` with ~240,000 records including
geometry (stored as GeoJSON text, or PostGIS geometry if available).

Usage:
    python3 import_blm_patents.py [--drop]       # full import
    python3 import_blm_patents.py --count-only    # just check remote count

Options:
    --drop        Drop and recreate the table (default: skip existing rows)
    --count-only  Only query the remote count, don't import
"""

import json
import sys
import time
import psycopg2
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ── Config ──
BASE_URL = 'https://services2.arcgis.com/8k2PygHqghVevhzy/arcgis/rest/services/tribal_land_patents_aliquot_20240304/FeatureServer/0/query'
DB_DSN = 'dbname=allotment_research'
TABLE = 'blm_allotment_patents'
BATCH_SIZE = 2000  # ArcGIS max per request for this service

# Persistent session with automatic retries
SESSION = requests.Session()
retry_strategy = Retry(
    total=5,
    backoff_factor=2,  # 2, 4, 8, 16, 32 seconds
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=['GET'],
)
SESSION.mount('https://', HTTPAdapter(max_retries=retry_strategy))

OUT_FIELDS = [
    'OBJECTID', 'accession_number', 'preferred_name', 'full_name',
    'signature_date', 'authority', 'state', 'county',
    'forced_fee', 'cancelled_doc',
    'aliquot_parts', 'section_number', 'township_number', 'range_number',
    'township_direction', 'range_direction',
    'meridian', 'meridian_code',
    'indian_allotment_number', 'remarks'
]


def query_arcgis(params):
    """Execute an ArcGIS REST query and return the JSON response."""
    resp = SESSION.get(BASE_URL, params=params, timeout=120)
    resp.raise_for_status()
    return resp.json()


def get_total_count(where='1=1'):
    """Get total record count from the feature service."""
    res = query_arcgis({'where': where, 'returnCountOnly': 'true', 'f': 'json'})
    return res.get('count', 0)


def has_postgis(cur):
    """Check if PostGIS extension is available."""
    try:
        cur.execute("SELECT PostGIS_Version()")
        return True
    except psycopg2.Error:
        cur.connection.rollback()
        return False


def create_table(cur, use_postgis):
    """Create the blm_allotment_patents table."""
    geom_col = 'geom geometry(Geometry, 4326)' if use_postgis else 'geom_geojson text'

    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS {TABLE} (
            objectid integer PRIMARY KEY,
            accession_number text,
            preferred_name text,
            full_name text,
            signature_date timestamp,
            authority text,
            state text,
            county text,
            forced_fee text,
            cancelled_doc text,
            aliquot_parts text,
            section_number text,
            township_number text,
            range_number text,
            township_direction text,
            range_direction text,
            meridian text,
            meridian_code text,
            indian_allotment_number text,
            remarks text,
            centroid_lon double precision,
            centroid_lat double precision,
            {geom_col}
        )
    """)

    # Indexes for common queries
    cur.execute(f"CREATE INDEX IF NOT EXISTS idx_blm_accession ON {TABLE} (accession_number)")
    cur.execute(f"CREATE INDEX IF NOT EXISTS idx_blm_tribe ON {TABLE} (preferred_name)")
    cur.execute(f"CREATE INDEX IF NOT EXISTS idx_blm_state ON {TABLE} (state)")
    cur.execute(f"CREATE INDEX IF NOT EXISTS idx_blm_forced ON {TABLE} (forced_fee)")
    cur.execute(f"CREATE INDEX IF NOT EXISTS idx_blm_authority ON {TABLE} (authority)")
    cur.execute(f"CREATE INDEX IF NOT EXISTS idx_blm_date ON {TABLE} (signature_date)")
    cur.execute(f"CREATE INDEX IF NOT EXISTS idx_blm_allotment ON {TABLE} (indian_allotment_number)")

    if use_postgis:
        cur.execute(f"CREATE INDEX IF NOT EXISTS idx_blm_geom ON {TABLE} USING gist (geom)")


def insert_batch(cur, features, use_postgis):
    """Insert a batch of features into the database."""
    rows = []
    for f in features:
        attrs = f.get('attributes', {})
        geom = f.get('geometry')
        centroid = f.get('centroid')

        # Parse signature_date from epoch milliseconds
        sig_date = None
        if attrs.get('signature_date'):
            try:
                sig_date = time.strftime('%Y-%m-%d', time.gmtime(attrs['signature_date'] / 1000))
            except (ValueError, OSError):
                pass

        # Centroid coordinates
        clon = centroid.get('x') if centroid else None
        clat = centroid.get('y') if centroid else None

        # Geometry as GeoJSON
        geom_json = None
        if geom:
            if 'rings' in geom:
                geom_json = json.dumps({
                    'type': 'Polygon',
                    'coordinates': geom['rings']
                })
            elif 'x' in geom and 'y' in geom:
                geom_json = json.dumps({
                    'type': 'Point',
                    'coordinates': [geom['x'], geom['y']]
                })

        rows.append((
            attrs.get('OBJECTID'),
            attrs.get('accession_number'),
            attrs.get('preferred_name'),
            attrs.get('full_name'),
            sig_date,
            attrs.get('authority'),
            attrs.get('state'),
            attrs.get('county'),
            attrs.get('forced_fee'),
            attrs.get('cancelled_doc'),
            attrs.get('aliquot_parts'),
            attrs.get('section_number'),
            attrs.get('township_number'),
            attrs.get('range_number'),
            attrs.get('township_direction'),
            attrs.get('range_direction'),
            attrs.get('meridian'),
            attrs.get('meridian_code'),
            attrs.get('indian_allotment_number'),
            attrs.get('remarks'),
            clon, clat,
            geom_json
        ))

    if use_postgis:
        cur.executemany(f"""
            INSERT INTO {TABLE} (
                objectid, accession_number, preferred_name, full_name,
                signature_date, authority, state, county,
                forced_fee, cancelled_doc,
                aliquot_parts, section_number, township_number, range_number,
                township_direction, range_direction, meridian, meridian_code,
                indian_allotment_number, remarks,
                centroid_lon, centroid_lat, geom
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326)
            ) ON CONFLICT (objectid) DO NOTHING
        """, rows)
    else:
        cur.executemany(f"""
            INSERT INTO {TABLE} (
                objectid, accession_number, preferred_name, full_name,
                signature_date, authority, state, county,
                forced_fee, cancelled_doc,
                aliquot_parts, section_number, township_number, range_number,
                township_direction, range_direction, meridian, meridian_code,
                indian_allotment_number, remarks,
                centroid_lon, centroid_lat, geom_geojson
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            ) ON CONFLICT (objectid) DO NOTHING
        """, rows)

    return len(rows)


def main():
    drop_table = '--drop' in sys.argv
    count_only = '--count-only' in sys.argv

    # Check remote count
    print('Querying ArcGIS feature service...')
    total = get_total_count()
    print(f'Remote records: {total:,}')

    if count_only:
        return

    # Connect to database
    conn = psycopg2.connect(DB_DSN)
    conn.autocommit = False
    cur = conn.cursor()

    # Check PostGIS
    use_postgis = has_postgis(cur)
    if use_postgis:
        cur.execute("CREATE EXTENSION IF NOT EXISTS postgis")
        conn.commit()
        print('PostGIS available — storing native geometry')
    else:
        print('PostGIS not available — storing geometry as GeoJSON text')
        print('  (install postgis and re-run to upgrade)')

    # Create or recreate table
    if drop_table:
        cur.execute(f"DROP TABLE IF EXISTS {TABLE}")
        conn.commit()
        print(f'Dropped existing {TABLE} table')

    create_table(cur, use_postgis)
    conn.commit()

    # Check how many we already have
    cur.execute(f"SELECT count(*) FROM {TABLE}")
    existing = cur.fetchone()[0]
    if existing > 0 and not drop_table:
        print(f'Table already has {existing:,} rows (use --drop to reimport)')
        if existing >= total * 0.95:
            print('Looks complete — skipping import.')
            conn.close()
            return

    # Fetch and insert in batches
    offset = 0
    inserted = 0
    start_time = time.time()

    print(f'Importing {total:,} records in batches of {BATCH_SIZE}...')
    print()

    while offset < total:
        params = {
            'where': '1=1',
            'outFields': ','.join(OUT_FIELDS),
            'outSR': 4326,
            'returnGeometry': 'true',
            'returnCentroid': 'true',
            'resultRecordCount': BATCH_SIZE,
            'resultOffset': offset,
            'f': 'json'
        }

        try:
            res = query_arcgis(params)
        except Exception as e:
            print(f'\n  Error at offset {offset}: {e}')
            print('  Retrying in 5 seconds...')
            time.sleep(5)
            try:
                res = query_arcgis(params)
            except Exception as e2:
                print(f'  Failed again: {e2}. Skipping batch.')
                offset += BATCH_SIZE
                continue

        features = res.get('features', [])
        if not features:
            break

        count = insert_batch(cur, features, use_postgis)
        conn.commit()
        inserted += count
        offset += len(features)

        elapsed = time.time() - start_time
        rate = inserted / elapsed if elapsed > 0 else 0
        eta = (total - offset) / rate if rate > 0 else 0
        pct = offset / total * 100

        print(f'\r  {pct:5.1f}%  {inserted:>7,} / {total:,}  '
              f'({rate:.0f} rec/sec, ~{eta/60:.1f} min remaining)', end='', flush=True)

    elapsed = time.time() - start_time
    print(f'\n\nDone. {inserted:,} records imported in {elapsed:.1f} seconds.')

    # Final count
    cur.execute(f"SELECT count(*) FROM {TABLE}")
    final = cur.fetchone()[0]
    print(f'Table {TABLE} now has {final:,} rows.')

    # Summary stats
    cur.execute(f"""
        SELECT
            count(*) as total,
            count(DISTINCT preferred_name) as tribes,
            count(DISTINCT state) as states,
            sum(CASE WHEN forced_fee = 'True' THEN 1 ELSE 0 END) as forced,
            min(signature_date) as earliest,
            max(signature_date) as latest
        FROM {TABLE}
    """)
    row = cur.fetchone()
    print(f'\nSummary:')
    print(f'  Total patents: {row[0]:,}')
    print(f'  Tribes: {row[1]}')
    print(f'  States: {row[2]}')
    print(f'  Forced fee: {(row[3] or 0):,}')
    print(f'  Date range: {row[4]} to {row[5]}')

    conn.close()


if __name__ == '__main__':
    main()
