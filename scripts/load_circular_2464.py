#!/usr/bin/env python3
"""
Load the Circular 2464 corpus (Layer 1: Sonnet text) into allotment_research.

Reads:
  ~/projects/exhaustive-extraction-pipeline/circular_2464_extractions/extractions/sonnet/*.json
  (1,049 JSONs as of 2026-06-02)

Writes:
  allotment_research.circular_2464_documents
  allotment_research.circular_2464_records

Tribe resolution:
  At load time, each record's raw `Tribe/Reservation` label is resolved
  against `tribe_crosswalk`. The resolved value is stored on the record
  as `authoritative_tribe`. Labels that don't resolve (FRN, blank,
  geographic-only, "actual tribe unknown") stay NULL. Per
  TRIBE_NORMALIZATION_NOTES.md, this is the intended outcome — the LEFT
  JOIN in the materialized view correctly produces no BLM match for
  these, and the historian can triage them after the load.

Idempotent:
  Documents upserted on ON CONFLICT (document_id). Records upserted on
  ON CONFLICT (document_id, record_index). Most JSONs are 1:1 with a
  record (record_index=0); the Fort Berthold ledger pages and a handful
  of bundled affidavits/narratives are 1:N (one document, multiple
  records indexed 0..N-1 in source-document order). Safe to re-run.

Usage:
    python3 scripts/load_circular_2464.py
    python3 scripts/load_circular_2464.py --dry-run
    python3 scripts/load_circular_2464.py --source /alt/path/to/sonnet
"""
import argparse
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

import psycopg2
import psycopg2.extras


DB_NAME = os.environ.get("PGDATABASE", "allotment_research")
DEFAULT_SOURCE = Path.home() / "projects/exhaustive-extraction-pipeline/circular_2464_extractions/extractions/sonnet"

# Source JSON extraction key -> schema column
FIELD_MAP = {
    "Name":                            "name",
    "Tribe/Reservation":               "tribe_reservation",
    "Post Office Address":             "post_office_address",
    "Allotment number":                "allotment_number",
    "Cancelled":                       "cancelled",
    "Refused/Protested":               "refused_protested",
    "Recorded patent":                 "recorded_patent",
    "Sold/Mortgaged":                  "sold_mortgaged",
    "Buyer":                           "buyer",
    "Tax burden forced sale/Mortgage": "tax_burden",
    "Trust Patent Date":               "trust_patent_date",
    "Fee Patent Date":                 "fee_patent_date",
    "Gender":                          "gender",
    "Age":                             "age",
    "Occupation/Income":               "occupation_income",
    "Literate/Illiterate":             "literate_illiterate",
    "NOTES":                           "notes",
}

PART_RE = re.compile(r"^part(\d+)_", re.IGNORECASE)
TYPE_FROM_FILENAME_RE = re.compile(
    r"_(agency_narrative|questionnaire|affidavit|ledger(?:_page|_entry)?|shawnee)",
    re.IGNORECASE,
)


def parse_part_number(document_id: str) -> int | None:
    m = PART_RE.match(document_id or "")
    return int(m.group(1)) if m else None


def derive_type_from_id(document_id: str) -> str:
    m = TYPE_FROM_FILENAME_RE.search(document_id or "")
    if not m:
        return "unknown"
    raw = m.group(1).lower()
    # Collapse ledger_page / ledger_entry to "ledger"; everything else passes through.
    if raw.startswith("ledger"):
        return "ledger"
    return raw


def build_tribe_resolver(conn) -> dict:
    """One query, cache the crosswalk as a Python dict for the rest of the
    run. Lookup matches the SQL in TRIBE_NORMALIZATION_NOTES.md:
        glo_name_normalized = UPPER(:label)  OR  authoritative_tribe = :label
    Returns a dict keyed by both forms. FRN entries are excluded — they
    correctly produce NULL.
    """
    by_glo_upper = {}
    by_auth = {}
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT glo_name_normalized, authoritative_tribe
            FROM tribe_crosswalk
            WHERE authoritative_tribe IS NOT NULL
              AND authoritative_tribe <> ''
              AND authoritative_tribe <> 'FRN'
            """
        )
        for glo_norm, auth in cur.fetchall():
            if glo_norm:
                by_glo_upper.setdefault(glo_norm, auth)
            if auth:
                by_auth.setdefault(auth, auth)
    return {"glo": by_glo_upper, "auth": by_auth}


def resolve_tribe(label: str, resolver: dict) -> str | None:
    if not label:
        return None
    label = label.strip()
    if not label or label.lower() in ("not stated", ""):
        return None
    # "Shawnee Indian Agency (actual tribe unknown)" and similar parentheticals
    # are explicit historian markers — don't resolve.
    if "(actual tribe unknown)" in label.lower():
        return None
    # Try authoritative_tribe form first (title-case modern labels written
    # during the 2026-05 cleanup campaign already match this).
    if label in resolver["auth"]:
        return resolver["auth"][label]
    # Fall back to glo_name_normalized (uppercased GLO-form labels).
    upper = label.upper()
    if upper in resolver["glo"]:
        return resolver["glo"][upper]
    return None


def load_jsons(source_dir: Path) -> list[dict]:
    files = sorted(source_dir.glob("*.json"))
    out = []
    for f in files:
        try:
            d = json.loads(f.read_text())
        except Exception as e:
            print(f"  ! skip {f.name}: {e}", file=sys.stderr)
            continue
        if not isinstance(d, dict):
            print(f"  ! skip {f.name}: top-level is not a dict", file=sys.stderr)
            continue
        d["__path"] = str(f)
        # 13 post-split JSONs (e.g. part1_agency_narrative_003a.json) lack
        # document_id and type at the top level; derive from the filename so
        # the loader treats them uniformly with the other 1,035 files.
        if not d.get("document_id"):
            d["document_id"] = f.stem
        if not d.get("type"):
            d["type"] = derive_type_from_id(d["document_id"])
        out.append(d)
    return out


def upsert_document(cur, rec: dict) -> int:
    cur.execute(
        """
        INSERT INTO circular_2464_documents (
            document_id, document_type, source_pdf, source_pages,
            part_number, extraction_model
        ) VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (document_id) DO UPDATE SET
            document_type    = EXCLUDED.document_type,
            source_pdf       = EXCLUDED.source_pdf,
            source_pages     = EXCLUDED.source_pages,
            part_number      = EXCLUDED.part_number,
            extraction_model = EXCLUDED.extraction_model
        RETURNING id
        """,
        (
            rec["document_id"],
            rec.get("type") or "unknown",
            rec.get("source_pdf"),
            rec.get("source_pages"),
            parse_part_number(rec["document_id"]),
            rec.get("model"),
        ),
    )
    return cur.fetchone()[0]


def iter_extractions(rec: dict):
    """Yield (record_index, extraction_dict) pairs.

    Most JSONs have a single dict at `extraction`; ledger pages and a few
    bundled docs have a list of dicts. Normalize both into the same shape
    so the rest of the loader doesn't branch.
    """
    ext = rec.get("extraction")
    if isinstance(ext, dict):
        yield 0, ext
    elif isinstance(ext, list):
        for i, item in enumerate(ext):
            if isinstance(item, dict):
                yield i, item
    # No extraction at all -> nothing to yield; document row still exists.


def upsert_record(cur, document_pk: int, record_index: int, extraction: dict,
                  rec: dict, resolver: dict) -> tuple[int, str | None, str | None]:
    cols = {col: extraction.get(src_key) for src_key, col in FIELD_MAP.items()}

    raw_tribe = cols.get("tribe_reservation")
    auth = resolve_tribe(raw_tribe, resolver)
    cols["authoritative_tribe"] = auth

    # recovery_notes lives on the top-level document. For 1:N docs every
    # child record carries the same audit trail — Phase 1 just duplicates it
    # to keep the per-row query simple. If this becomes noisy, move to a
    # separate circular_2464_recovery_notes table in Phase 2.
    recovery = rec.get("recovery_notes")
    cols["recovery_notes_json"] = json.dumps(recovery) if recovery else None

    cols["document_id"] = document_pk
    cols["record_index"] = record_index

    column_order = [
        "document_id", "record_index",
        "name", "tribe_reservation", "authoritative_tribe",
        "post_office_address", "allotment_number", "cancelled",
        "refused_protested", "recorded_patent", "sold_mortgaged", "buyer",
        "tax_burden", "trust_patent_date", "fee_patent_date", "gender",
        "age", "occupation_income", "literate_illiterate", "notes",
        "recovery_notes_json",
    ]
    values = [cols[c] for c in column_order]
    placeholders = ", ".join(["%s"] * len(column_order))
    update_assignments = ", ".join(
        f"{c} = EXCLUDED.{c}" for c in column_order
        if c not in ("document_id", "record_index")
    )

    sql = f"""
        INSERT INTO circular_2464_records ({", ".join(column_order)}, search_vector)
        VALUES ({placeholders},
            to_tsvector('english',
                COALESCE(%s, '') || ' ' ||
                COALESCE(%s, '') || ' ' ||
                COALESCE(%s, '') || ' ' ||
                COALESCE(%s, '')
            )
        )
        ON CONFLICT (document_id, record_index) DO UPDATE SET
            {update_assignments},
            search_vector = EXCLUDED.search_vector
        RETURNING id
    """
    fts_inputs = [cols["name"], cols["buyer"], cols["post_office_address"], cols["notes"]]
    cur.execute(sql, values + fts_inputs)
    record_id = cur.fetchone()[0]
    return record_id, raw_tribe, auth


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", type=Path, default=DEFAULT_SOURCE,
                    help=f"Directory of *.json files (default: {DEFAULT_SOURCE})")
    ap.add_argument("--dry-run", action="store_true",
                    help="Parse and resolve tribes but don't write to the DB")
    args = ap.parse_args()

    if not args.source.is_dir():
        print(f"error: source dir not found: {args.source}", file=sys.stderr)
        sys.exit(2)

    print(f"Source: {args.source}")
    print(f"DB:     {DB_NAME}")
    records = load_jsons(args.source)
    print(f"Read {len(records)} JSONs")

    conn = psycopg2.connect(dbname=DB_NAME)
    conn.autocommit = False
    try:
        resolver = build_tribe_resolver(conn)
        print(f"Loaded tribe_crosswalk: "
              f"{len(resolver['glo'])} glo_name keys, "
              f"{len(resolver['auth'])} authoritative_tribe keys")

        if args.dry_run:
            unresolved = Counter()
            resolved = Counter()
            record_count = 0
            for r in records:
                for _, extraction in iter_extractions(r):
                    record_count += 1
                    raw = extraction.get("Tribe/Reservation")
                    auth = resolve_tribe(raw, resolver)
                    if auth:
                        resolved[auth] += 1
                    else:
                        unresolved[(raw or "").strip()] += 1
            print(f"\nDRY RUN — no writes")
            print(f"documents (JSONs):     {len(records)}")
            print(f"records (allottees):   {record_count}")
            print(f"  resolved tribe:      {sum(resolved.values()):>5} across "
                  f"{len(resolved)} authoritative tribes")
            print(f"  unresolved (NULL):   {sum(unresolved.values()):>5} across "
                  f"{len(unresolved)} raw labels")
            print(f"\nTop unresolved labels:")
            for label, n in unresolved.most_common():
                print(f"  {n:4d}  {label!r}")
            return

        with conn.cursor() as cur:
            unresolved = Counter()
            resolved_count = 0
            record_count = 0
            for r in records:
                doc_pk = upsert_document(cur, r)
                for record_index, extraction in iter_extractions(r):
                    _, raw_tribe, auth = upsert_record(
                        cur, doc_pk, record_index, extraction, r, resolver
                    )
                    record_count += 1
                    if auth:
                        resolved_count += 1
                    else:
                        unresolved[(raw_tribe or "").strip()] += 1
        conn.commit()
        print(f"\nLoaded {len(records)} documents, {record_count} records")
        print(f"  resolved authoritative_tribe: {resolved_count}")
        print(f"  unresolved (NULL):            {sum(unresolved.values())}")

        print("\nUnresolved tribe labels (for historian triage):")
        for label, n in unresolved.most_common():
            print(f"  {n:4d}  {label!r}")

    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
