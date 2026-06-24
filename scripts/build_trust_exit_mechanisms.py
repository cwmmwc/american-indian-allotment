#!/usr/bin/env python3
"""Build public.murray_trust_exit_mechanisms from iath.murray_p081_87_t12.

Murray Memorandum Table XII — "Volume of transactions, 1948-57, by the type
involved in the disposal of individual Indian lands from trust status, by agency."

This derives a clean, long-format WORKING table (one row per agency × reported
mechanism) from the raw `iath` source, applying the mechanism taxonomy agreed with
the historian (2026-06-22) and reusing the canonical agency→BLM-tribe mapping.

Source-data realities preserved, not hidden (see DATABASE.md / pending_work):
  - The ~34 raw labels are agency-chosen synonyms, folded into 10 families below.
  - The itemized columns do NOT cleanly reconcile to each agency's reported `total`
    (some over-, some under-itemized; columns are not a mutually-exclusive partition).
    Each row carries reported_total / itemized_total / reconciliation_gap so the viz
    can show the gap honestly.
  - Agencies that reported zero disposal (Hopi, Pima, Zuni, ...) are kept as rows
    with reported_total=0 and no mechanism — absence is a finding.

Layering: reads iath (raw source), writes public (app working table). Idempotent.
"""

import psycopg2
import psycopg2.extras
from map_murray_to_blm import MURRAY_TO_BLM  # reuse canonical agency→BLM-tribe map

# raw column label -> (family, set_apart, family_sort). Agreed taxonomy:
# fee patent / removal of restrictions / certificates of competency are SEPARATE
# families; inheritance/heirship is SET APART from the dispossession mechanisms.
TAXONOMY = {
    # Sale out of trust
    "sales_to_fee_status":                       ("Sale out of trust", False, 1),
    "sales_to_fee_status_or_nonindians":         ("Sale out of trust", False, 1),
    "public_domain_sales_to_fee_status":         ("Sale out of trust", False, 1),
    "supervised_sales":                          ("Sale out of trust", False, 1),
    "guardianship_sales":                        ("Sale out of trust", False, 1),
    # Fee patent (incl. forced fee)
    "patents_in_fee":                            ("Fee patent", False, 2),
    "fee_patents":                               ("Fee patent", False, 2),
    "fee_patents_or_unrestricted_deed":          ("Fee patent", False, 2),
    "public_domain_fee_patents":                 ("Fee patent", False, 2),
    "patent_issued_to_nonrestricted_interest":   ("Fee patent", False, 2),
    # Removal of restrictions
    "removal_of_restrictions":                   ("Removal of restrictions", False, 3),
    "public_domain_orders_removing_restrictions":("Removal of restrictions", False, 3),
    # Certificates of competency
    "certificates_of_competency":                ("Certificates of competency", False, 4),
    # Public taking / condemnation
    "takings_for_public_purposes":               ("Public taking / condemnation", False, 5),
    "condemnations":                             ("Public taking / condemnation", False, 5),
    "to_north_dakota_for_tb_sanatorium":         ("Public taking / condemnation", False, 5),
    "school_site_deeded_to_county":              ("Public taking / condemnation", False, 5),
    # Exchange
    "exchanges_to_fee_status":                   ("Exchange", False, 6),
    "to_fee_status_by_exchange":                 ("Exchange", False, 6),
    "exchange_deeds":                            ("Exchange", False, 6),
    # Partition
    "partitions":                                ("Partition", False, 7),
    "partitionment":                             ("Partition", False, 7),
    "to_fee_status_by_partition":                ("Partition", False, 7),
    # Gift
    "gift":                                      ("Gift", False, 8),
    "gift_deeds":                                ("Gift", False, 8),
    "to_fee_status_by_gift":                     ("Gift", False, 8),
    # Other / removal
    "unallotted":                                ("Other / removal", False, 9),
    "cancellation_of_allotment":                 ("Other / removal", False, 9),
    "escheat_to_tribe":                          ("Other / removal", False, 9),
    "removal_from_trust_status":                 ("Other / removal", False, 9),
    # Inheritance / heirship / probate — SET APART from dispossession mechanisms
    "heirship":                                  ("Inheritance / heirship / probate", True, 10),
    "to_fee_status_by_inheritance_or_devise":    ("Inheritance / heirship / probate", True, 10),
    "to_fee_status_by_inheritance":              ("Inheritance / heirship / probate", True, 10),
    "probates":                                  ("Inheritance / heirship / probate", True, 10),
}

NON_MECHANISM = {"id", "agency", "total", "annual_average",
                 "largest_volume_years", "largest_volume_amount", "footnotes"}

DDL = """
DROP TABLE IF EXISTS public.murray_trust_exit_mechanisms;
CREATE TABLE public.murray_trust_exit_mechanisms (
    id                 serial PRIMARY KEY,
    agency             text NOT NULL,
    blm_tribe_name     text,            -- NULL for multi-tribe / unmapped agencies
    mechanism_raw      text,            -- original Table XII column label; NULL = agency reported no breakdown
    mechanism_family   text,            -- agreed taxonomy family; NULL when mechanism_raw is NULL
    set_apart          boolean,         -- TRUE = inheritance/heirship (distinct from dispossession)
    family_sort        integer,
    transactions       integer,         -- count for this agency × raw mechanism
    reported_total     integer,         -- agency's Table XII `total` column (gross volume)
    itemized_total     integer,         -- sum of this agency's itemized mechanism columns
    reconciliation_gap integer,         -- reported_total - itemized_total (NULL if reported_total NULL)
    source             text NOT NULL DEFAULT 'Murray Memorandum Table XII (iath.murray_p081_87_t12)'
);
"""


def main():
    conn = psycopg2.connect("dbname=allotment_research user=cwm6W")
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cur.execute("SELECT * FROM iath.murray_p081_87_t12 ORDER BY id")
    rows = cur.fetchall()

    # sanity: every mechanism column present in the source is in the taxonomy
    src_cols = {c for c in rows[0].keys() if c not in NON_MECHANISM}
    missing = src_cols - set(TAXONOMY)
    if missing:
        raise SystemExit(f"ERROR: source mechanism columns not in taxonomy: {sorted(missing)}")

    out = []
    for r in rows:
        agency = (r["agency"] or "").strip()
        blm = MURRAY_TO_BLM.get(agency)
        reported_total = int(r["total"]) if r["total"] is not None else None
        itemized = sum(int(r[c]) for c in TAXONOMY if r[c] is not None)
        gap = (reported_total - itemized) if reported_total is not None else None

        mech_rows = [(c, int(r[c])) for c in TAXONOMY if r[c] is not None and int(r[c]) != 0]
        if mech_rows:
            for col, val in mech_rows:
                fam, set_apart, sort = TAXONOMY[col]
                out.append((agency, blm, col, fam, set_apart, sort, val,
                            reported_total, itemized, gap))
        else:
            # agency reported no mechanism breakdown (mostly genuine zeros)
            out.append((agency, blm, None, None, None, None, 0,
                        reported_total, itemized, gap))

    cur.execute(DDL)
    psycopg2.extras.execute_values(cur, """
        INSERT INTO public.murray_trust_exit_mechanisms
          (agency, blm_tribe_name, mechanism_raw, mechanism_family, set_apart,
           family_sort, transactions, reported_total, itemized_total, reconciliation_gap)
        VALUES %s
    """, out)
    cur.execute("CREATE INDEX ON public.murray_trust_exit_mechanisms (mechanism_family)")
    cur.execute("CREATE INDEX ON public.murray_trust_exit_mechanisms (blm_tribe_name)")
    conn.commit()

    print(f"Loaded {len(out)} rows from {len(rows)} agencies.")
    cur.execute("""
        SELECT mechanism_family, set_apart,
               SUM(transactions) AS txns, COUNT(DISTINCT agency) AS agencies
        FROM public.murray_trust_exit_mechanisms
        WHERE mechanism_family IS NOT NULL
        GROUP BY mechanism_family, set_apart, family_sort
        ORDER BY family_sort
    """)
    print("\nFamily totals:")
    for r in cur.fetchall():
        apart = "  [set apart]" if r["set_apart"] else ""
        print(f"  {r['mechanism_family']:<34} {int(r['txns']):>6,}  ({r['agencies']} agencies){apart}")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
