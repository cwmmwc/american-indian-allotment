#!/usr/bin/env python3
"""Smoke test: recover Lizzie Anderson's 1919 patent (accession 715724) from
CadNSDI Intersected layer and insert into cadnsdi_recovered_patents.

The patent describes Lot 1 NE and Lot 3 NW of Section 26, T10N R3E,
Indian Meridian (PRINMERCD=17), Pottawatomie County, Oklahoma. Each
government lot may exist as multiple polygon rows in CadNSDI sharing the
same SECDIVID — those are dissolved by union before storage.
"""
import json
import urllib.parse
import urllib.request
import psycopg2

CADNSDI_URL = "https://gis.blm.gov/arcgis/rest/services/Cadastral/BLM_Natl_PLSS_CadNSDI/MapServer/3/query"

ACCESSION = "715724"
KEYS = {
    "PRINMERCD": "17",
    "TWNSHPNO":  "010",
    "TWNSHPDIR": "N",
    "RANGENO":   "003",
    "RANGEDIR":  "E",
    "FRSTDIVNO": "26",
}
LOTS = ["1", "3"]


def fetch_lot(govlot):
    where = " AND ".join(f"{k}='{v}'" for k, v in KEYS.items()) + f" AND GOVLOT='{govlot}'"
    params = {
        "where": where,
        "outFields": "SECDIVID,SECDIVNO,SECDIVSUF,SECDIVLAB,GOVLOT,SECDIVTYP",
        "returnGeometry": "true",
        "f": "geojson",
    }
    url = CADNSDI_URL + "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=30) as resp:
        return json.load(resp)


def polygon_ring_centroid(ring):
    """Centroid of a single closed ring (list of [lon, lat] points)."""
    n = len(ring)
    return (sum(p[0] for p in ring) / n, sum(p[1] for p in ring) / n)


def collect_polygons(feature_collection):
    """Return list of polygon rings from a FeatureCollection (handles Polygon and MultiPolygon)."""
    polys = []
    for f in feature_collection.get("features", []):
        g = f["geometry"]
        if g["type"] == "Polygon":
            polys.append(g["coordinates"])
        elif g["type"] == "MultiPolygon":
            for p in g["coordinates"]:
                polys.append(p)
    return polys


def main():
    print(f"Fetching CadNSDI geometry for accession {ACCESSION}...")
    all_features = []
    for lot in LOTS:
        fc = fetch_lot(lot)
        feats = fc.get("features", [])
        print(f"  GOVLOT={lot}: {len(feats)} polygon rows returned")
        for f in feats:
            p = f["properties"]
            print(f"    SECDIVID={p.get('SECDIVID')} SECDIVSUF={p.get('SECDIVSUF')} SECDIVLAB={p.get('SECDIVLAB')!r}")
        all_features.extend(feats)

    if not all_features:
        raise SystemExit("No geometry returned from CadNSDI. Aborting.")

    # Build a single MultiPolygon containing all the lot polygons (no dissolution —
    # the renderer can handle MultiPolygon directly; logical lot membership is preserved
    # via SECDIVID grouping which we keep in the per-feature properties).
    multipoly_coords = []
    centroid_acc = [0.0, 0.0, 0]
    for f in all_features:
        g = f["geometry"]
        if g["type"] == "Polygon":
            multipoly_coords.append(g["coordinates"])
            lng, lat = polygon_ring_centroid(g["coordinates"][0])
            centroid_acc[0] += lng
            centroid_acc[1] += lat
            centroid_acc[2] += 1
        elif g["type"] == "MultiPolygon":
            for p in g["coordinates"]:
                multipoly_coords.append(p)
                lng, lat = polygon_ring_centroid(p[0])
                centroid_acc[0] += lng
                centroid_acc[1] += lat
                centroid_acc[2] += 1

    centroid_lng = centroid_acc[0] / centroid_acc[2]
    centroid_lat = centroid_acc[1] / centroid_acc[2]
    print(f"\nCombined centroid: lat={centroid_lat:.6f} lng={centroid_lng:.6f}")
    print(f"Total component polygons: {len(multipoly_coords)}")

    geometry = {"type": "MultiPolygon", "coordinates": multipoly_coords}

    # Pull the descriptive fields from existing tables so the popup matches the
    # rest of the map's records.
    conn = psycopg2.connect(dbname="allotment_research")
    cur = conn.cursor()
    cur.execute("""
        SELECT full_name, signature_date, authority, document_class, state, glo_tribe_name, indian_allotment_number
        FROM rails_patents WHERE accession_number = %s
    """, (ACCESSION,))
    row = cur.fetchone()
    if not row:
        raise SystemExit(f"Accession {ACCESSION} not in rails_patents.")
    full_name, sig_date, authority, doc_class, state, glo_tribe, allot = row

    cur.execute("""
        SELECT county, township_number, township_direction, range_number,
               range_direction, section_number, aliquot_parts, meridian_code
        FROM parcels_patents_by_tribe
        WHERE indian_allotment_number = %s AND state = %s AND signature_date = %s::text
        LIMIT 1
    """, (allot, state, sig_date.isoformat() if sig_date else None))
    parcel_row = cur.fetchone()
    if parcel_row:
        (county, twn, twn_dir, rng, rng_dir, sect, aliquot, mer) = parcel_row
    else:
        county = twn = twn_dir = rng = rng_dir = sect = aliquot = mer = None
    # Collapse all aliquot pieces from this allotment+state+date into a single label
    # so the popup reads like "Lot 1 NE; Lot 3 NW" rather than just one row's value.
    cur.execute("""
        SELECT STRING_AGG(aliquot_parts, '; ' ORDER BY aliquot_parts) AS combined
        FROM parcels_patents_by_tribe
        WHERE indian_allotment_number = %s AND state = %s AND signature_date = %s::text
          AND aliquot_parts IS NOT NULL AND aliquot_parts <> ''
    """, (allot, state, sig_date.isoformat() if sig_date else None))
    combined_aliquot = cur.fetchone()
    if combined_aliquot and combined_aliquot[0]:
        aliquot = combined_aliquot[0]

    # Authority on rails_patents was blank for Lizzie's 1919; the parcels table had it.
    if not authority:
        cur.execute("""
            SELECT authority FROM parcels_patents_by_tribe
            WHERE indian_allotment_number = %s AND state = %s AND signature_date = %s::text
              AND authority IS NOT NULL AND authority <> ''
            LIMIT 1
        """, (allot, state, sig_date.isoformat() if sig_date else None))
        a_row = cur.fetchone()
        if a_row:
            authority = a_row[0]

    cur.execute("""
        INSERT INTO cadnsdi_recovered_patents
          (accession_number, full_name, preferred_name, signature_date, authority,
           document_class, state, county, indian_allotment_number,
           centroid_lat, centroid_lon, geometry_geojson, cadnsdi_source,
           township_number, township_direction, range_number, range_direction,
           section_number, aliquot_parts, meridian_code)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (accession_number) DO UPDATE SET
          geometry_geojson = EXCLUDED.geometry_geojson,
          centroid_lat = EXCLUDED.centroid_lat,
          centroid_lon = EXCLUDED.centroid_lon,
          full_name = EXCLUDED.full_name,
          authority = EXCLUDED.authority,
          county = EXCLUDED.county,
          township_number = EXCLUDED.township_number,
          township_direction = EXCLUDED.township_direction,
          range_number = EXCLUDED.range_number,
          range_direction = EXCLUDED.range_direction,
          section_number = EXCLUDED.section_number,
          aliquot_parts = EXCLUDED.aliquot_parts,
          meridian_code = EXCLUDED.meridian_code,
          cadnsdi_source = EXCLUDED.cadnsdi_source,
          created_at = now()
    """, (
        ACCESSION, full_name, glo_tribe, sig_date, authority,
        doc_class, state, county, allot,
        centroid_lat, centroid_lng, json.dumps(geometry),
        "BLM_Natl_PLSS_CadNSDI/MapServer/3 GOVLOT=1,3 PM17 T010N R003E S26",
        twn, twn_dir, rng, rng_dir, sect, aliquot, mer
    ))
    conn.commit()
    print("\nInserted into cadnsdi_recovered_patents.")

    cur.execute("""
        SELECT accession_number, full_name, preferred_name, signature_date, authority,
               state, county, centroid_lat, centroid_lon,
               jsonb_array_length(geometry_geojson->'coordinates') AS poly_count
        FROM cadnsdi_recovered_patents WHERE accession_number = %s
    """, (ACCESSION,))
    print("Stored row:", cur.fetchone())
    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
