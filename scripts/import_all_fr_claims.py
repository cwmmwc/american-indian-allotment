#!/usr/bin/env python3
"""
Import ALL Federal Register claims from the legacy PHP site.

Downloads CSV for each of the 259 BIA agency codes from
land-sales.iath.virginia.edu/federal_register-csv.php?tribe=CODE
and imports into the federal_register_claims table.

This replaces the previous partial import (10,976 forced fee + secretarial
transfer claims only) with the complete dataset (~30,000+ claims of all types).

Usage:
    python3 scripts/import_all_fr_claims.py [--dry-run] [--db DATABASE_URL]
"""

import csv
import io
import sys
import time
import argparse
import urllib.request
import urllib.error
import psycopg2
import psycopg2.extras

# All 259 BIA agency codes from the legacy site TOC
# Format: (code, tribe_name)
# Tribe names from https://land-sales.iath.virginia.edu/federal_register-toc.php
BIA_CODES = [
    # Aberdeen Region
    ("A00007", "Santee Sioux"),
    ("A00370", None),
    ("A01304", "Cheyenne River Sioux"),
    ("A01340", "Cheyenne River Sioux"),
    ("A04301", "Fort Berthold (Three Affiliated)"),
    ("A05303", "Devil's Lake / Spirit Lake"),
    ("A06344", "Pine Ridge (Oglala Sioux)"),
    ("A07345", "Rosebud Sioux"),
    ("A08346", "Yankton Sioux"),
    ("A09347", "Sisseton-Wahpeton"),
    ("A10302", "Standing Rock Sioux"),
    ("A11304", "Turtle Mountain Chippewa"),
    ("A13380", "Omaha"),
    ("A13382", "Santee Sioux (Nebraska)"),
    ("A13383", "Winnebago"),
    ("A14342", "Crow Creek Sioux"),
    ("A15343", "Lower Brule Sioux"),

    # Albuquerque Region
    ("M00000", None),
    ("M10000", None),
    ("M20000", None),
    ("M20703", "Acoma Pueblo"),
    ("M20704", "Cochiti Pueblo"),
    ("M20705", "Isleta Pueblo"),
    ("M20706", "Jemez Pueblo"),
    ("M20707", "Laguna Pueblo"),
    ("M20711", "Sandia Pueblo"),
    ("M20712", "San Felipe Pueblo"),
    ("M20715", "Santa Ana Pueblo"),
    ("M20717", "Santo Domingo Pueblo"),
    ("M20720", "Zia Pueblo"),
    ("M25000", None),
    ("M25708", "Nambe Pueblo"),
    ("M25709", "Picuris Pueblo"),
    ("M25710", "Pojoaque Pueblo"),
    ("M25712", "San Felipe Pueblo"),
    ("M25713", "San Ildefonso Pueblo"),
    ("M25714", "San Juan Pueblo"),
    ("M25716", "Santa Clara Pueblo"),
    ("M25718", "Taos Pueblo"),
    ("M25719", "Tesuque Pueblo"),
    ("M45751", "Ute Mountain"),
    ("M50001", None),
    ("M60702", "Mescalero Apache"),

    # Anadarko Region
    ("B04434", "Potawatomi (Wisconsin)"),
    ("B04860", "Iowa (Kansas/Nebraska)"),
    ("B04861", "Kickapoo (Kansas)"),
    ("B04862", "Potawatomi (Kansas)"),
    ("B04863", "Sac and Fox (Kansas/Nebraska)"),
    ("B04864", "Shawnee Public Domain"),
    ("B04924", "Wyandotte"),
    ("B04926", "Peoria"),
    ("B05801", "Cheyenne-Arapaho"),
    ("B06802", "Kiowa, Comanche, Apache"),
    ("B06803", "Fort Sill Apache"),
    ("B06804", "Wichita"),
    ("B06806", "Caddo-Wichita"),
    ("B06808", "Comanche"),
    ("B06809", "Apache"),
    ("B07811", "Otoe-Missouria"),
    ("B07812", "Pawnee"),
    ("B07813", "Ponca"),
    ("B07814", "Tonkawa"),
    ("B08820", "Absentee Shawnee"),
    ("B08821", "Citizen Potawatomi (OK)"),
    ("B08822", "Iowa (Oklahoma)"),
    ("B08823", "Mexican Kickapoo (Oklahoma)"),
    ("B08824", "Sac and Fox (Oklahoma)"),
    ("B08921", "Eastern Shawnee"),

    # Billings Region
    ("C0563", None),
    ("C51201", "Blackfeet"),
    ("C52201", None),
    ("C52202", "Crow"),
    ("C53203", "Flathead (Salish-Kootenai)"),
    ("C55204", "Fort Belknap (Gros Ventre-Assiniboine)"),
    ("C55224", "Turtle Mountain Chippewa"),
    ("C56106", None),
    ("C56206", "Fort Peck (Assiniboine-Sioux)"),
    ("C56226", "Turtle Mountain Chippewa"),
    ("C57207", "Northern Cheyenne"),
    ("C57257", None),
    ("C57277", "Turtle Mountain Chippewa"),
    ("C58281", "Arapaho"),
    ("C59205", "Rocky Boy"),

    # Eastern Region
    ("S50002", "Catawba"),
    ("S50004", "Seneca (Allegany)"),
    ("S50007", "St. Regis"),
    ("S50010", "Seneca (Oil Springs)"),
    ("S50011", "Oneida"),
    ("S50013", "Cayuga"),
    ("S50030", "Gay Head Wampanoag"),
    ("S50031", "Western Pequot"),
    ("S50032", "Schaghticoke"),
    ("S50033", "Mohegan"),
    ("S50034", "Shinnecock"),
    ("S50035", "Seminole"),
    ("S50036", "Chitimacha"),
    ("S50037", "Tunica Biloxi"),
    ("S50038", "Stockbridge Munsee"),
    ("S50039", None),
    ("S50041", None),
    ("S50042", None),
    ("S50043", None),
    ("S50045", None),
    ("S53035", None),
    ("S78980", None),

    # Juneau Region
    ("E00000", None),

    # Minneapolis Region
    ("F50440", "Menominee"),
    ("F52409", "Red Lake Chippewa"),
    ("F53404", "Mille Lacs Band Of Ojibwe"),
    ("F53405", "White Earth Chippewa"),
    ("F53406", "Grand Portage Band Of Lake Superior Chippewa"),
    ("F53407", "Leech Lake Band Of Ojibwe"),
    ("F53408", "White Earth Chippewa"),
    ("F53410", "Mille Lacs"),
    ("F53420", "Public Domain (Minnesota)"),
    ("F53430", None),
    ("F53431", None),
    ("F55430", "Bad River Chippewa"),
    ("F55431", "Lac Courte Oreilles Chippewa"),
    ("F55432", "Lac du Flambeau"),
    ("F55433", "Oneida"),
    ("F55434", "Forest County Potawatomi"),
    ("F55435", "Red Cliff Chippewa"),
    ("F55436", "St. Croix Chippewa"),
    ("F55438", "Stockbridge Munsee (Wisconsin)"),
    ("F55439", "Wisconsin Winnebago"),
    ("F55441", "Public Domain (Wisconsin)"),
    ("F57401", "Upper Sioux"),
    ("F57402", "Lower Sioux"),
    ("F57403", "Prairie Island"),
    ("F57411", "Prior Lake"),
    ("F60000", None),
    ("F60469", "Sault Ste. Marie"),
    ("F60470", "Bay Mills"),
    ("F60471", "Hannahville"),
    ("F60472", "Saginaw Chippewa"),
    ("F60473", "Keweenaw Bay"),
    ("F60474", "Ottawa-Chippewa"),
    ("F60476", "Ontonagon"),
    ("F60477", "Public Domain (Michigan)"),
    ("F60478", "Lac Vieux"),

    # Muskogee Region
    ("G03906", "Chickasaw"),
    ("G04920", "Quapaw"),
    ("G04921", None),
    ("G04922", "Ottawa (Blanchards Fork)"),
    ("G04923", "Seneca-Shawnee"),
    ("G04924", "Wyandotte"),
    ("G04925", "Miami"),
    ("G04926", "Peoria"),
    ("G06930", "Osage"),
    ("G07908", "Creek"),
    ("G08905", "Cherokee"),
    ("G09907", "Choctaw"),
    ("G10909", "Seminole (Oklahoma)"),

    # Navajo Region
    ("N00780", "Navajo"),

    # Phoenix Region
    ("H51603", "Colorado River"),
    ("H51604", "Fort Mojave"),
    ("H51695", None),
    ("H52607", "Fort Apache"),
    ("H53642", "Duck Valley"),
    ("H53662", "Duck Valley"),
    ("H54610", "Papago"),
    ("H55615", "Salt River Pima-Maricopa"),
    ("H57614", "Pima (Gila River)"),
    ("H58616", "San Carlos Apache"),
    ("H61651", "Pyramid Lake"),
    ("H61658", None),
    ("H61672", None),
    ("H62655", "Summit Lake"),
    ("H62687", None),
    ("H64642", None),
    ("H64643", None),
    ("H64654", "Ruby Valley"),
    ("H64658", None),
    ("H64662", None),
    ("H64664", None),
    ("H65617", None),
    ("H68601", None),
    ("H68605", None),
    ("H68606", None),
    ("H68674", None),

    # Portland Region
    ("P00000", None),
    ("P00140", "Klamath"),
    ("P00141", "Portland Area (unidentified)"),
    ("P00146", None),
    ("P00148", "Celilo Village"),
    ("P01142", "Portland Area (unidentified)"),
    ("P03101", "Colville"),
    ("P04180", "Fort Hall"),
    ("P05181", "Coeur d'Alene"),
    ("P05182", "Nez Perce"),
    ("P05183", "Kootenai"),
    ("P06000", None),
    ("P06106", "Hoh"),
    ("P06108", "Makah"),
    ("P06116", "Quileute"),
    ("P06117", "Quinault"),
    ("P06118", "Shoalwater"),
    ("P06120", "Skokomish"),
    ("P06121", None),
    ("P06125", "Lower Elwha"),
    ("P06129", None),
    ("P06130", "Public Domain (WA)"),
    ("P07143", "Umatilla"),
    ("P09144", "Snake / Paiute"),
    ("P09145", "Warm Springs"),
    ("P09147", "Dalles Public Domain"),
    ("P09149", "Oregon Miscellaneous"),
    ("P10000", None),
    ("P10107", "Lummi"),
    ("P10109", "Muckleshoot"),
    ("P10110", "Nisqually"),
    ("P10111", "Nooksack"),
    ("P10112", "Ozette"),
    ("P10113", "Port Gamble"),
    ("P10114", "Port Madison"),
    ("P10119", "Skagit"),
    ("P10122", "Swinomish"),
    ("P10123", "Tulalip"),
    ("P10130", "Snohomish"),
    ("P11124", "Yakama"),
    ("P12102", "Spokane"),
    ("P12103", "Kalispel"),
    ("P12151", None),
    ("P13203", None),

    # Sacramento Region
    ("J50500", "California Indians"),
    ("J50518", None),
    ("J50540", None),
    ("J50553", None),
    ("J50566", None),
    ("J50587", None),
    ("J50593", None),
    ("J51525", "Fort Independence"),
    ("J51540", "Round Valley"),
    ("J51632", "Sulphur Bank"),
    ("J52056", "Rohnerville"),
    ("J52561", "Hoopa Valley"),
    ("J52562", "Hoopa Extension"),
    ("J52652", "Hoopa Extension"),
    ("J54000", "Morongo-Cabazon"),
    ("J54500", "Sacramento Miscellaneous"),
    ("J54567", "Augustine"),
    ("J54568", "Cabazon"),
    ("J54569", "Cahuilla"),
    ("J54570", "Campo"),
    ("J54571", "Capitan Grande"),
    ("J54576", "La Jolla"),
    ("J54577", "La Posta"),
    ("J54579", "Manzanita"),
    ("J54580", "Mesa Grande"),
    ("J54582", "Morongo"),
    ("J54583", "Pala"),
    ("J54585", "Pauma-Yuima"),
    ("J54586", "Pechanga"),
    ("J54587", "Rincon"),
    ("J54592", "Santa Ysabel"),
    ("J54593", "Soboba"),
    ("J54595", "Torres Martinez"),
    ("J54599", "Viejas"),
]

BASE_URL = "https://land-sales.iath.virginia.edu/federal_register-csv.php?tribe="

# Map document field to publication_date and document_source
DOC_MAP = {
    "fedreg_1983_03_31": ("1983-03-31", "Federal Register, March 31, 1983"),
    "fedreg_1983_11_07": ("1983-11-07", "Federal Register, November 7, 1983"),
}


def download_csv(code):
    """Download CSV for a single BIA agency code. Returns list of dicts or None."""
    url = f"{BASE_URL}{code}"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8-sig")
            if not raw.strip() or "no results" in raw.lower():
                return []
            reader = csv.DictReader(io.StringIO(raw))
            return list(reader)
    except urllib.error.HTTPError as e:
        print(f"  HTTP {e.code} for {code}", file=sys.stderr)
        return []
    except Exception as e:
        print(f"  Error fetching {code}: {e}", file=sys.stderr)
        return []


def main():
    parser = argparse.ArgumentParser(description="Import all FR claims from legacy site")
    parser.add_argument("--dry-run", action="store_true", help="Download and count but don't insert")
    parser.add_argument("--db", default="dbname=allotment_research",
                        help="Database connection string")
    args = parser.parse_args()

    # Build code→tribe lookup
    code_to_tribe = {code: tribe for code, tribe in BIA_CODES}

    print(f"Downloading claims for {len(BIA_CODES)} BIA agency codes...")
    all_rows = []
    codes_with_data = 0
    codes_empty = 0

    for i, (code, tribe_name) in enumerate(BIA_CODES):
        rows = download_csv(code)
        if rows:
            codes_with_data += 1
            for row in rows:
                # Use tribe_name from our mapping, fall back to code
                tribe = tribe_name or f"Unidentified ({code})"
                doc_key = row.get("document", "").strip()
                pub_date, doc_source = DOC_MAP.get(doc_key, ("", doc_key))

                all_rows.append({
                    "bia_agency_code": code,
                    "tribe_identified": tribe,
                    "case_number": row.get("case", "").strip(),
                    "allottee_name": row.get("allottee", "").strip().strip('"'),
                    "allotment_number": row.get("allotment", "").strip(),
                    "claim_type": row.get("type_of_claim", "").strip(),
                    "document_source": doc_source,
                    "publication_date": pub_date,
                })
            print(f"  [{i+1}/{len(BIA_CODES)}] {code} ({tribe_name or '?'}): {len(rows)} claims")
        else:
            codes_empty += 1
            if (i + 1) % 20 == 0:
                print(f"  [{i+1}/{len(BIA_CODES)}] progress...")

        # Be polite to the legacy server
        time.sleep(0.2)

    print(f"\nDownload complete:")
    print(f"  {codes_with_data} codes with data, {codes_empty} empty")
    print(f"  {len(all_rows)} total claims")

    # Show claim type distribution
    type_counts = {}
    for row in all_rows:
        ct = row["claim_type"]
        type_counts[ct] = type_counts.get(ct, 0) + 1
    print(f"\nClaim types ({len(type_counts)} distinct):")
    for ct, cnt in sorted(type_counts.items(), key=lambda x: -x[1])[:20]:
        print(f"  {cnt:>6}  {ct}")
    if len(type_counts) > 20:
        print(f"  ... and {len(type_counts) - 20} more types")

    if args.dry_run:
        print("\n--dry-run: no database changes made.")
        return

    # Import into database
    print(f"\nConnecting to database...")
    conn = psycopg2.connect(args.db)
    cur = conn.cursor()

    # Back up existing data count
    cur.execute("SELECT COUNT(*) FROM federal_register_claims")
    old_count = cur.fetchone()[0]
    print(f"  Current records: {old_count}")

    # Truncate and re-import (clean slate)
    cur.execute("DELETE FROM federal_register_claims")
    print(f"  Deleted {old_count} existing records")

    # Reset sequence
    cur.execute("SELECT setval('federal_register_claims_id_seq', 1, false)")

    # Batch insert
    insert_sql = """
        INSERT INTO federal_register_claims
            (bia_agency_code, tribe_identified, case_number, allottee_name,
             allotment_number, claim_type, document_source, publication_date)
        VALUES (%(bia_agency_code)s, %(tribe_identified)s, %(case_number)s, %(allottee_name)s,
                %(allotment_number)s, %(claim_type)s, %(document_source)s, %(publication_date)s)
    """
    psycopg2.extras.execute_batch(cur, insert_sql, all_rows, page_size=500)

    conn.commit()

    cur.execute("SELECT COUNT(*) FROM federal_register_claims")
    new_count = cur.fetchone()[0]
    print(f"\nImport complete: {new_count} records (was {old_count})")

    # Show tribe counts
    cur.execute("""
        SELECT tribe_identified, COUNT(*) as cnt
        FROM federal_register_claims
        GROUP BY tribe_identified
        ORDER BY cnt DESC
        LIMIT 15
    """)
    print("\nTop 15 tribes by claim count:")
    for tribe, cnt in cur.fetchall():
        print(f"  {cnt:>6}  {tribe}")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
