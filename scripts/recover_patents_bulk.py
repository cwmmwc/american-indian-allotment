#!/usr/bin/env python3
"""Bulk recovery of allotment patents from BLM CadNSDI Intersected layer.

Generalizes recover_lizzie_smoke_test.py to ~15,168 accessions across two
input sources, with per-accession granularity tagging and a run log.

INPUT SOURCES
  A) Postgres parcels_patents_by_tribe — SER + STA records with allotment_no
     in any state. Filtered to unmappable (not in blm_allotment_patents) with
     real PLSS keys (section_nr and township_nr both populated).
  B) Box GLO Bulk Data — patent_data/<state>/<ST>_Land_Description.csv for
     OK, KS, NE, MN, WY. Filtered to STA records with NULL allotment_no.
     WI deferred (private claims need separate join logic).

PER-ACCESSION FLOW
  1. Collect all parcel rows (a patent can describe multiple parcels)
  2. For each parcel, pick a CadNSDI query strategy based on aliquot type:
       - 4-char aliquot (NESW): QQSEC=
       - 2-char quarter (NE):   QSEC=
       - Integer 1-16:          GOVLOT=
       - Anything else:         section-only fallback
  3. Combine returned geometry into a MultiPolygon
  4. Tag granularity:
       'parcel'  if every parcel row's query returned sub-section detail
       'section' if any parcel row fell back to section-only
  5. Insert into cadnsdi_recovered_patents (ON CONFLICT DO UPDATE)
  6. Append outcome row to data/cadnsdi_bulk_run_<ts>.csv

PARALLEL: ThreadPoolExecutor with default 6 workers. HTTP fetches happen
in workers; DB writes happen serially in the main thread to avoid
connection contention.

RESUME: ON CONFLICT DO UPDATE means re-runs are idempotent. By default the
script skips accessions already present in cadnsdi_recovered_patents (faster
re-runs). Use --force to re-process everything.
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Optional

import psycopg2
import psycopg2.extras


CADNSDI_URL = (
    "https://gis.blm.gov/arcgis/rest/services/Cadastral/"
    "BLM_Natl_PLSS_CadNSDI/MapServer/3/query"
)
CADNSDI_SECTION_URL = (
    "https://gis.blm.gov/arcgis/rest/services/Cadastral/"
    "BLM_Natl_PLSS_CadNSDI/MapServer/2/query"
)
BOX_PATENT_DATA = (
    "/Users/cwm6W/Library/CloudStorage/Box-Box/IATH/GLO Bulk Data/patent_data"
)
BOX_STATES = [
    ("OK", "oklahoma"),
    ("KS", "kansas"),
    ("NE", "nebraska"),
    ("MN", "minnesota"),
    ("WY", "wyoming"),
]

# ─── helpers ─────────────────────────────────────────────────────────

def pad(v, n):
    try:
        return str(int(float(v))).zfill(n)
    except (TypeError, ValueError):
        return ""


_aliquot_re_qqsec = re.compile(r"^[NSEW]{4}$")
_aliquot_re_qsec = re.compile(r"^[NSEW]{2}$")
_aliquot_re_int = re.compile(r"^\d+$")
_aliquot_re_int_dir = re.compile(r"^(\d+)[NSEW]{1,2}$")          # 1NE, 3NW, 2SE…
_aliquot_re_half_quarter = re.compile(r"^[NSEW]½([NSEW]{2})$")    # S½NE → quarter NE
_aliquot_re_half_qqsec = re.compile(r"^[NSEW]½([NSEW]{4})$")      # W½SWSE → QQ SWSE
_aliquot_re_half_section = re.compile(r"^[NSEW]½$")               # N½, E½ etc.


def classify_aliquot(a: Optional[str]):
    """Return (kind, value) for a parcels_patents_by_tribe.aliquot_parts string.

    kind         | value                  | CadNSDI query                  | granularity
    -------------|------------------------|--------------------------------|------------
    qqsec        | 'NESW'                 | QQSEC='NESW' on layer 3        | parcel
    qsec         | 'NE'                   | QSEC='NE' on layer 3 (returns  | parcel
                 |                        | 4 QQSECs, ~2× over for halves) |
    lot          | '12'                   | GOVLOT='12' on layer 3         | parcel
    large_lot    | '142'                  | section-only fallback          | section
    half_section | 'N½'                   | section-only fallback          | section
    partial      | 'N½N½SE' etc.          | section-only fallback          | section
    empty        | None                   | section-only fallback          | section
    """
    if not a:
        return ("empty", None)
    a = a.strip()
    if not a:
        return ("empty", None)

    # Standard government lot (integer 1-16) or special-survey large lot (17+)
    if _aliquot_re_int.match(a):
        n = int(a)
        return ("lot" if n <= 16 else "large_lot", a)

    # Lot+direction: "1NE" → lot 1 (direction is descriptive, GOVLOT key is just '1')
    m = _aliquot_re_int_dir.match(a)
    if m:
        n = int(m.group(1))
        return ("lot" if n <= 16 else "large_lot", str(n))

    # Quarter-quarter (NESW)
    if _aliquot_re_qqsec.match(a):
        return ("qqsec", a)

    # Quarter (NE)
    if _aliquot_re_qsec.match(a):
        return ("qsec", a)

    # Half-quarter (S½NE) → render the parent quarter (~2× over)
    m = _aliquot_re_half_quarter.match(a)
    if m:
        return ("qsec", m.group(1))

    # Half-of-quarter-quarter (W½SWSE) → render the parent QQ (~2× over)
    m = _aliquot_re_half_qqsec.match(a)
    if m:
        return ("qqsec", m.group(1))

    # Half section (N½)
    if _aliquot_re_half_section.match(a):
        return ("half_section", a)

    return ("partial", a)


def fetch_polygons(where, max_retries=3):
    """Query CadNSDI Intersected layer. Returns (features_list, error_str)."""
    params = {
        "where": where,
        "outFields": "SECDIVID,SECDIVNO,SECDIVSUF,SECDIVLAB,GOVLOT,QSEC,QQSEC,SURVTYP,SECDIVTYP",
        "returnGeometry": "true",
        "f": "geojson",
    }
    url = CADNSDI_URL + "?" + urllib.parse.urlencode(params)
    last_err = None
    for attempt in range(max_retries):
        try:
            with urllib.request.urlopen(url, timeout=45) as resp:
                d = json.load(resp)
            return d.get("features", []), None
        except Exception as e:
            last_err = str(e)
            time.sleep(0.5 * (2 ** attempt))
    return [], last_err


def construct_frstdivid(state, mer, twn, twd, rng, rgd, sec):
    """Construct CadNSDI FRSTDIVID for a section.

    Format: <STATE><PRINMERCD><TWNSHPNO 3-pad>0<TWNSHPDIR><RANGENO 3-pad>0<RANGEDIR>0SN<SEC 2-pad>0
    e.g. OK170100N0030E0SN260 for Section 26 of T10N R3E PM17 Oklahoma.
    """
    return f"{state}{mer}{twn}0{twd}{rng}0{rgd}0SN{sec.zfill(2)}0"


def fetch_section_perimeter_layer3(mer, twn, twd, rng, rgd, sec):
    """Tier-2 fallback: section perimeter polygon from layer 3 itself.
    Only present when the section isn't subdivided in layer 3's publication
    (e.g. KS sections under PM06 where the state steward didn't push
    sub-section detail to the national index).
    """
    where = (
        f"PRINMERCD='{mer}' AND TWNSHPNO='{twn}' AND TWNSHPDIR='{twd}' "
        f"AND RANGENO='{rng}' AND RANGEDIR='{rgd}' AND FRSTDIVNO='{sec}' "
        f"AND SECDIVTYP IS NULL AND SURVTYP IS NULL"
    )
    return fetch_polygons(where)


def fetch_section_perimeter_layer2(state, mer, twn, twd, rng, rgd, sec, max_retries=3):
    """Tier-3 fallback: section perimeter from layer 2 (PLSS Section).
    Covers subdivided sections where layer 3 has subdivisions but not a
    separate perimeter polygon (e.g. OK Indian PM heavily-subdivided
    sections).
    """
    frstdivid = construct_frstdivid(state, mer, twn, twd, rng, rgd, sec)
    params = {
        "where": f"FRSTDIVID='{frstdivid}'",
        "outFields": "FRSTDIVID,FRSTDIVNO,FRSTDIVLAB",
        "returnGeometry": "true",
        "f": "geojson",
    }
    url = CADNSDI_SECTION_URL + "?" + urllib.parse.urlencode(params)
    last_err = None
    for attempt in range(max_retries):
        try:
            with urllib.request.urlopen(url, timeout=45) as resp:
                d = json.load(resp)
            return d.get("features", []), None
        except Exception as e:
            last_err = str(e)
            time.sleep(0.5 * (2 ** attempt))
    return [], last_err


def has_subdivision(features):
    for f in features:
        p = f.get("properties", {})
        if p.get("QQSEC") or p.get("GOVLOT"):
            return True
    return False


def aliquot_filter_for(kind, val):
    if kind == "qqsec":
        return f"QQSEC='{val}'"
    if kind == "qsec":
        return f"QSEC='{val}'"
    if kind == "lot":
        return f"GOVLOT='{val}'"
    return None  # large_lot / partial / empty -> section-only


# ─── input loaders ───────────────────────────────────────────────────

def load_source_a(conn, skip_recovered=True):
    """Load all parcel rows for eligible accessions from parcels_patents_by_tribe.

    Returns: dict[accession_number] = {
        "rows": [parcel_row_dict, ...],
        "meta": {full_name, preferred_name, signature_date, authority, document_class,
                 state, county, indian_allotment_number},
        "source": "parcels_patents_by_tribe",
    }
    """
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    skip_clause = (
        "AND rp.accession_number NOT IN (SELECT accession_number FROM cadnsdi_recovered_patents)"
        if skip_recovered else ""
    )
    cur.execute(f"""
        SELECT rp.accession_number, rp.state, rp.indian_allotment_number,
               rp.signature_date, rp.full_name, rp.glo_tribe_name,
               rp.document_class, rp.authority,
               p.meridian_code, p.township_number, p.township_direction,
               p.range_number, p.range_direction, p.section_number,
               p.aliquot_parts, p.county
        FROM rails_patents rp
        LEFT JOIN blm_allotment_patents bap ON bap.accession_number = rp.accession_number
        JOIN parcels_patents_by_tribe p
          ON p.indian_allotment_number = rp.indian_allotment_number
         AND p.state = rp.state
         AND p.signature_date = rp.signature_date::text
         AND COALESCE(p.section_number,'') <> ''
         AND COALESCE(p.township_number,'') <> ''
        WHERE rp.document_class IN ('Serial Land Patent', 'State Land Patent')
          AND bap.accession_number IS NULL
          AND rp.indian_allotment_number IS NOT NULL
          AND rp.state IS NOT NULL
          {skip_clause}
    """)
    by_acc: dict[str, dict] = {}
    for r in cur.fetchall():
        acc = r["accession_number"]
        if acc not in by_acc:
            by_acc[acc] = {
                "rows": [],
                "meta": {
                    "full_name": r["full_name"],
                    "preferred_name": r["glo_tribe_name"],
                    "signature_date": r["signature_date"],
                    "authority": r["authority"],
                    "document_class": r["document_class"],
                    "state": r["state"],
                    "county": r["county"],
                    "indian_allotment_number": r["indian_allotment_number"],
                },
                "source": "parcels_patents_by_tribe",
            }
        # Normalize column names to match the Box bulk CSV column names so
        # downstream code can treat both sources uniformly.
        by_acc[acc]["rows"].append({
            "meridian_code": r["meridian_code"],
            "township_nr": r["township_number"],
            "township_dir": r["township_direction"],
            "range_nr": r["range_number"],
            "range_dir": r["range_direction"],
            "section_nr": r["section_number"],
            "aliquot_parts": r["aliquot_parts"],
        })
    cur.close()
    return by_acc


def load_source_b(conn, skip_recovered=True):
    """Load no-allotment STA accessions from rails_patents, join to Box bulk CSVs.

    Returns same shape as load_source_a.
    """
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    skip_clause = (
        "AND rp.accession_number NOT IN (SELECT accession_number FROM cadnsdi_recovered_patents)"
        if skip_recovered else ""
    )
    state_list = ",".join(f"'{s[0]}'" for s in BOX_STATES)
    cur.execute(f"""
        SELECT rp.accession_number, rp.state, rp.signature_date,
               rp.full_name, rp.glo_tribe_name, rp.document_class, rp.authority
        FROM rails_patents rp
        LEFT JOIN blm_allotment_patents bap ON bap.accession_number = rp.accession_number
        WHERE rp.document_class = 'State Land Patent'
          AND bap.accession_number IS NULL
          AND rp.indian_allotment_number IS NULL
          AND rp.state IN ({state_list})
          {skip_clause}
    """)
    rails_by_state: dict[str, dict] = {}
    for r in cur.fetchall():
        rails_by_state.setdefault(r["state"], {})[r["accession_number"]] = r
    cur.close()

    by_acc: dict[str, dict] = {}
    for st_abbr, st_dir in BOX_STATES:
        if st_abbr not in rails_by_state:
            continue
        wanted = rails_by_state[st_abbr]
        csv_path = os.path.join(BOX_PATENT_DATA, st_dir, f"{st_abbr}_Land_Description.csv")
        if not os.path.exists(csv_path):
            continue
        with open(csv_path) as f:
            reader = csv.DictReader(f)
            for row in reader:
                acc = row["accession_nr"]
                if acc not in wanted:
                    continue
                if acc not in by_acc:
                    meta = wanted[acc]
                    by_acc[acc] = {
                        "rows": [],
                        "meta": {
                            "full_name": meta["full_name"],
                            "preferred_name": meta["glo_tribe_name"],
                            "signature_date": meta["signature_date"],
                            "authority": meta["authority"],
                            "document_class": meta["document_class"],
                            "state": meta["state"],
                            "county": None,
                            "indian_allotment_number": None,
                        },
                        "source": f"box_bulk_{st_abbr}",
                    }
                by_acc[acc]["rows"].append({
                    "meridian_code": row["meridian_code"],
                    "township_nr": row["township_nr"],
                    "township_dir": row["township_dir"],
                    "range_nr": row["range_nr"],
                    "range_dir": row["range_dir"],
                    "section_nr": row["section_nr"],
                    "aliquot_parts": row["aliquot_parts"],
                })
    return by_acc


# ─── per-accession worker ────────────────────────────────────────────

def process_accession(acc, parcel_rows, source_label, state):
    """HTTP-only path: gather geometry + tag. Returns dict for DB insert + log."""
    # Deduplicate parcel rows by PLSS key tuple (parcels_patents_by_tribe has
    # ~6k duplicate rows; treating them independently bloats queries and
    # double-counts in the centroid).
    seen = set()
    unique_rows = []
    for row in parcel_rows:
        key = (
            (row.get("meridian_code") or ""),
            (row.get("township_nr") or ""),
            (row.get("township_dir") or ""),
            (row.get("range_nr") or ""),
            (row.get("range_dir") or ""),
            (row.get("section_nr") or ""),
            (row.get("aliquot_parts") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        unique_rows.append(row)

    geometries: list[list] = []
    queries_log: list[str] = []
    any_section_only = False
    any_polygons_found = False
    errors: list[str] = []

    for row in unique_rows:
        mer = pad(row.get("meridian_code"), 2)
        twn = pad(row.get("township_nr"), 3)
        twd = (row.get("township_dir") or "").strip()
        rng = pad(row.get("range_nr"), 3)
        rgd = (row.get("range_dir") or "").strip()
        sec = pad(row.get("section_nr"), 2)
        aliquot = (row.get("aliquot_parts") or "").strip()

        if not all([mer, twn, twd, rng, rgd, sec]):
            queries_log.append(f"SKIP missing_keys mer={mer!r} twn={twn!r} twd={twd!r} rng={rng!r} rgd={rgd!r} sec={sec!r}")
            any_section_only = True
            continue

        kind, val = classify_aliquot(aliquot)
        ali_filter = aliquot_filter_for(kind, val)

        feats: list = []
        used_section_fallback = False

        # First attempt: specific filter on MapServer/3 if we have one
        if ali_filter:
            base_where = (
                f"PRINMERCD='{mer}' AND TWNSHPNO='{twn}' AND TWNSHPDIR='{twd}' "
                f"AND RANGENO='{rng}' AND RANGEDIR='{rgd}' AND FRSTDIVNO='{sec}'"
            )
            where = base_where + f" AND {ali_filter}"
            feats, err = fetch_polygons(where)
            if err:
                errors.append(err)
                queries_log.append(f"ERR {where!r}: {err}")
                continue
            queries_log.append(f"aliquot={aliquot!r} kind={kind} → {where} → {len(feats)} features")

        # Tier 2: section perimeter from layer 3 (only present when section
        # isn't subdivided — e.g. KS PM06 sections).
        if not feats:
            sect_feats, err = fetch_section_perimeter_layer3(mer, twn, twd, rng, rgd, sec)
            if err:
                errors.append(err)
                queries_log.append(f"ERR layer3 section: {err}")
            elif sect_feats:
                feats = sect_feats
                used_section_fallback = True
                queries_log.append(f"section perimeter (layer 3) → {len(feats)} features")

        # Tier 3: section perimeter from layer 2 (covers subdivided sections
        # like OK PM17 S26 where layer 3 has subdivisions but not a perimeter).
        if not feats:
            sect_feats, err = fetch_section_perimeter_layer2(state, mer, twn, twd, rng, rgd, sec)
            if err:
                errors.append(err)
                queries_log.append(f"ERR layer2 section: {err}")
            elif sect_feats:
                feats = sect_feats
                used_section_fallback = True
                queries_log.append(f"section perimeter (layer 2) → {len(feats)} features")

        if not feats:
            continue

        any_polygons_found = True
        if used_section_fallback or not ali_filter:
            any_section_only = True
        # else: specific aliquot filter matched -> parcel-level contribution

        for f in feats:
            g = f["geometry"]
            if g["type"] == "Polygon":
                geometries.append(g["coordinates"])
            elif g["type"] == "MultiPolygon":
                for piece in g["coordinates"]:
                    geometries.append(piece)

    if errors and not any_polygons_found:
        return {
            "accession_number": acc,
            "source": source_label,
            "outcome": "http_error",
            "queries_log": " | ".join(queries_log),
            "error_msg": " ; ".join(errors)[:500],
        }

    if not any_polygons_found:
        return {
            "accession_number": acc,
            "source": source_label,
            "outcome": "no_polygons",
            "queries_log": " | ".join(queries_log),
        }

    # Centroid from concatenated outer rings
    cx = cy = 0.0
    n = 0
    for poly in geometries:
        ring = poly[0]
        m = len(ring)
        cx += sum(p[0] for p in ring) / m
        cy += sum(p[1] for p in ring) / m
        n += 1
    centroid_lon = cx / n
    centroid_lat = cy / n

    granularity = "section" if any_section_only else "parcel"

    return {
        "accession_number": acc,
        "source": source_label,
        "outcome": f"recovered_{granularity}",
        "geometry": {"type": "MultiPolygon", "coordinates": geometries},
        "centroid_lat": centroid_lat,
        "centroid_lon": centroid_lon,
        "granularity": granularity,
        "queries_log": " | ".join(queries_log),
        "n_polygons": len(geometries),
    }


# ─── main ────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=6, help="parallel HTTP workers")
    ap.add_argument("--limit", type=int, default=0, help="process at most N accessions (0 = no limit)")
    ap.add_argument("--source", choices=["a", "b", "both"], default="both")
    ap.add_argument("--force", action="store_true", help="re-process accessions already in cadnsdi_recovered_patents")
    ap.add_argument("--log-dir", default="data", help="directory for run log CSV")
    ap.add_argument("--dry-run", action="store_true", help="don't write to DB, just log")
    ap.add_argument("--shuffle", action="store_true", help="randomize accession processing order (for representative sampling with --limit)")
    ap.add_argument("--seed", type=int, default=42, help="random seed for --shuffle")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    timestamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    os.makedirs(args.log_dir, exist_ok=True)
    log_path = os.path.join(args.log_dir, f"cadnsdi_bulk_run_{timestamp}.csv")
    logging.info(f"Run log: {log_path}")

    conn = psycopg2.connect("dbname=allotment_research")
    logging.info("Loading input sources...")
    by_acc: dict[str, dict] = {}
    if args.source in ("a", "both"):
        a = load_source_a(conn, skip_recovered=not args.force)
        logging.info(f"  Source A (Postgres parcels): {len(a)} accessions")
        by_acc.update(a)
    if args.source in ("b", "both"):
        b = load_source_b(conn, skip_recovered=not args.force)
        logging.info(f"  Source B (Box bulk):         {len(b)} accessions")
        # Source A takes precedence on collision (Postgres is the cleaner ingest)
        for k, v in b.items():
            by_acc.setdefault(k, v)

    accs = sorted(by_acc.keys())
    if args.shuffle:
        import random
        random.Random(args.seed).shuffle(accs)
    if args.limit:
        accs = accs[:args.limit]
    logging.info(f"Total accessions to process: {len(accs)}")
    if not accs:
        logging.info("Nothing to do.")
        return

    log_fields = [
        "accession_number", "source", "outcome", "granularity",
        "n_polygons", "centroid_lat", "centroid_lon",
        "error_msg", "queries_log",
    ]
    log_fp = open(log_path, "w", newline="")
    log_writer = csv.DictWriter(log_fp, fieldnames=log_fields, extrasaction="ignore")
    log_writer.writeheader()
    log_fp.flush()

    cur = conn.cursor()

    insert_sql = """
        INSERT INTO cadnsdi_recovered_patents
          (accession_number, full_name, preferred_name, signature_date, authority,
           document_class, state, county, indian_allotment_number,
           centroid_lat, centroid_lon, geometry_geojson, cadnsdi_source,
           township_number, township_direction, range_number, range_direction,
           section_number, aliquot_parts, meridian_code,
           granularity, aliquot_query_used)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (accession_number) DO UPDATE SET
          geometry_geojson = EXCLUDED.geometry_geojson,
          centroid_lat = EXCLUDED.centroid_lat,
          centroid_lon = EXCLUDED.centroid_lon,
          granularity = EXCLUDED.granularity,
          aliquot_query_used = EXCLUDED.aliquot_query_used,
          cadnsdi_source = EXCLUDED.cadnsdi_source,
          created_at = now()
    """

    outcomes = {"recovered_parcel": 0, "recovered_section": 0, "no_polygons": 0, "http_error": 0}
    t0 = time.time()
    next_report = t0 + 30  # progress report every 30 sec

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(
                process_accession,
                acc,
                by_acc[acc]["rows"],
                by_acc[acc]["source"],
                by_acc[acc]["meta"]["state"],
            ): acc
            for acc in accs
        }
        for i, fut in enumerate(as_completed(futures), start=1):
            try:
                r = fut.result()
            except Exception as e:
                acc = futures[fut]
                r = {"accession_number": acc, "source": by_acc[acc]["source"], "outcome": "worker_exception", "error_msg": str(e)}

            outcomes[r["outcome"]] = outcomes.get(r["outcome"], 0) + 1

            # log line
            log_writer.writerow({
                "accession_number": r.get("accession_number"),
                "source": r.get("source"),
                "outcome": r.get("outcome"),
                "granularity": r.get("granularity"),
                "n_polygons": r.get("n_polygons"),
                "centroid_lat": r.get("centroid_lat"),
                "centroid_lon": r.get("centroid_lon"),
                "error_msg": r.get("error_msg"),
                "queries_log": r.get("queries_log"),
            })
            log_fp.flush()

            # DB insert for successful recoveries
            if r["outcome"].startswith("recovered_") and not args.dry_run:
                meta = by_acc[r["accession_number"]]["meta"]
                # Pull one representative parcel row for the PLSS columns on the stored record
                first = by_acc[r["accession_number"]]["rows"][0]
                aliquot_combined = "; ".join(
                    sorted({(row.get("aliquot_parts") or "").strip() for row in by_acc[r["accession_number"]]["rows"] if (row.get("aliquot_parts") or "").strip()})
                ) or None
                cur.execute(insert_sql, (
                    r["accession_number"],
                    meta["full_name"],
                    meta["preferred_name"],
                    meta["signature_date"],
                    meta["authority"],
                    meta["document_class"],
                    meta["state"],
                    meta["county"],
                    meta["indian_allotment_number"],
                    r["centroid_lat"],
                    r["centroid_lon"],
                    json.dumps(r["geometry"]),
                    f"BLM_Natl_PLSS_CadNSDI/MapServer/3 (bulk run {timestamp})",
                    first.get("township_nr"),
                    first.get("township_dir"),
                    first.get("range_nr"),
                    first.get("range_dir"),
                    first.get("section_nr"),
                    aliquot_combined,
                    first.get("meridian_code"),
                    r["granularity"],
                    r["queries_log"][:8000],  # safety cap
                ))
                conn.commit()

            if time.time() > next_report:
                elapsed = time.time() - t0
                rate = i / max(elapsed, 0.001)
                eta = (len(accs) - i) / max(rate, 0.001)
                summary = " | ".join(f"{k}={v}" for k, v in outcomes.items() if v)
                logging.info(f"  Progress {i}/{len(accs)} ({i/len(accs):.0%})  {rate:.1f}/s  ETA {eta/60:.1f} min  [{summary}]")
                next_report = time.time() + 30

    log_fp.close()
    cur.close()
    conn.close()

    elapsed = time.time() - t0
    logging.info(f"\nDONE — {len(accs)} accessions in {elapsed/60:.1f} min")
    logging.info("Outcomes:")
    for k, v in sorted(outcomes.items(), key=lambda x: -x[1]):
        logging.info(f"  {k}: {v}")
    logging.info(f"Run log: {log_path}")


if __name__ == "__main__":
    main()
