"""
Add a `reason_normalized` column to cancelled_patent_research and populate
it from the free-text `reason_for_cancellation` column.

Normalization rules (applied case-insensitively):
  - "1927 act" / "1927 cancellation act"        -> '1927_act'
  - "1931 act" / "1931 cancellation act"        -> '1931_act'
  - "1927 and 1931 act(s)"                       -> '1927_and_1931_acts'
  - "acceptance refused" / "refusal" / "acceptance of fee/patent refused"
                                                 -> 'acceptance_refused'
  - "issued w/o application" (no refusal phrase) -> 'issued_without_application'
  - "issued w/o application and acceptance refused"
                                                 -> 'issued_without_application_and_acceptance_refused'
  - "caster patent"                              -> 'caster_patent_letter'
  - "decree of court"                            -> 'court_decree'
  - "incompetent"                                -> 'incompetency_determination'
  - "canceled by order"                          -> 'individual_order'
  - anything else                                -> 'other'
  - NULL or empty                                -> NULL

Read+write on database.

Usage:
    ./venv/bin/python3 scripts/normalize_cancellation_reasons.py
"""
import os
import re
import psycopg2
import psycopg2.extras
from collections import Counter

DB_URL = os.environ.get("DATABASE_URL", "dbname=allotment_research user=cwm6W")


def normalize(reason):
    if not reason:
        return None
    r = reason.strip().lower()
    if not r:
        return None

    # Combined act references first (more specific than individual)
    if re.search(r"1927\s*and\s*1931\s*act", r):
        return "1927_and_1931_acts"

    # Issued without application variants
    has_no_app = "issued w/o application" in r or "issued without application" in r
    has_refusal = "refus" in r or "refused" in r
    if has_no_app and has_refusal:
        return "issued_without_application_and_acceptance_refused"
    if has_no_app:
        return "issued_without_application"

    if has_refusal:
        return "acceptance_refused"

    if "caster patent" in r:
        return "caster_patent_letter"
    if "decree of court" in r or "decree" in r:
        return "court_decree"
    if "incompetent" in r:
        return "incompetency_determination"

    # Individual acts
    if re.search(r"\b1927\b", r):
        return "1927_act"
    if re.search(r"\b1931\b", r):
        return "1931_act"

    if "canceled by order" in r or "cancelled by order" in r:
        return "individual_order"

    return "other"


def main():
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Add column if it doesn't already exist
    cur.execute("""
        ALTER TABLE cancelled_patent_research
        ADD COLUMN IF NOT EXISTS reason_normalized TEXT
    """)
    conn.commit()

    # Pull every row, normalize, write back
    cur.execute("SELECT id, reason_for_cancellation FROM cancelled_patent_research")
    rows = cur.fetchall()

    updates = []
    cat_counts = Counter()
    for r in rows:
        norm = normalize(r["reason_for_cancellation"])
        updates.append((norm, r["id"]))
        cat_counts[norm or "(NULL)"] += 1

    # Bulk update via execute_batch
    psycopg2.extras.execute_batch(
        cur,
        "UPDATE cancelled_patent_research SET reason_normalized = %s WHERE id = %s",
        updates,
        page_size=500,
    )
    conn.commit()

    print(f"Normalized {len(updates)} rows.")
    print()
    print("Normalized category counts:")
    for cat, n in cat_counts.most_common():
        print(f"  {n:4d}  {cat}")

    # Show samples of 'other' so we can see what didn't get categorized
    cur.execute("""
        SELECT reason_for_cancellation, COUNT(*) AS n
        FROM cancelled_patent_research
        WHERE reason_normalized = 'other'
        GROUP BY reason_for_cancellation
        ORDER BY n DESC
    """)
    other = cur.fetchall()
    if other:
        print()
        print("Reasons that fell into 'other' (for review):")
        for r in other:
            print(f"  {r['n']:4d}  {r['reason_for_cancellation']}")

    # Index for filtering by normalized category
    cur.execute("""
        CREATE INDEX IF NOT EXISTS cancelled_patent_research_reason_norm_idx
        ON cancelled_patent_research (reason_normalized)
    """)
    conn.commit()
    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
