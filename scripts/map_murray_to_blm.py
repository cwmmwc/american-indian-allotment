#!/usr/bin/env python3
"""Map Murray Memorandum agency names to BLM preferred_name values.

Murray agencies are BIA jurisdictions that often cover multiple tribes.
Some map 1:1 to a BLM preferred_name; others are multi-tribe agencies
where we map to the primary/largest tribe or leave unmapped.

Adds blm_tribe_name column to murray_comparative, murray_agency_removal,
murray_transactions, and murray_lands_acquired tables.
"""

import psycopg2

# Murray agency → BLM preferred_name (or None if no clear mapping)
# Note: some Murray agencies cover multiple BLM tribes. We map to the
# primary tribe where possible. Multi-tribe agencies get mapped to the
# most prominent tribe in BLM data OR left NULL if truly multi-tribe.
MURRAY_TO_BLM = {
    # Direct or near-direct matches
    "Blackfeet": "Blackfeet",
    "Cheyenne River": "Cheyenne River Sioux",
    "Colville": "Colville",
    "Crow": "Crow",
    "Flathead": "Flathead",
    "Kiowa": "Kiowa",
    "Northern Cheyenne": "Northern Cheyenne",
    "Pawnee": "Pawnee",
    "Quapaw": "Quapaw",
    "Rosebud": "Rosebud Sioux",
    "Standing Rock": "Standing Rock Sioux",
    "Turtle Mountain": "Turtle Mountain Band Of Chippewa Indians",
    "Umatilla": "Umatilla",
    "Winnebago": "Winnebago",

    # Name variations
    "Cheyenne-Arapahoe": "Cheyenne Arapaho",
    "Cheyenne and Arapaho": "Cheyenne Arapaho",
    "Sisseton": "Sisseton–Wahpeton Oyate",
    "Yakima": "Yakama",
    "Pine Ridge": "Oglala Lakota",
    "Navaho": "Navajo",

    # Multi-tribe agencies → primary tribe
    "Fort Berthold": "Mandan, Hidatsa, Arikara",
    "Fort Belknap": "Assiniboine And Gros Ventre",
    "Fort Peck": "Assiniboine And Sioux",
    "Wind River": "Shoshone",  # Shoshone + Arapaho
    "Fort Hall": "Shoshone And Bannock",
    "Northern Idaho": "Nez Perce",  # Nez Perce + Coeur d'Alene
    "Consolidated Ute": "Ute",
    "Potawatomie": "Citizen Potawatomi",
    "Potawatomi": "Citizen Potawatomi",
    "Shawnee": "Absentee Shawnee",
    "Pima": "Pima And Maricopa",
    "Hoopa": "Hupa",
    "Jicarilla": "Jicarilla Apache",
    "Mescarelo": "Mescalero Apache",

    # Agency-level (covers many tribes/reservations) — can't map to single BLM tribe
    "Five Civilized Tribes": None,  # Cherokee, Choctaw, Chickasaw, Creek, Seminole
    "California": None,  # Many rancherias and small tribes
    "California Agency": None,
    "Great Lakes": None,  # Menominee, Oneida, Stockbridge-Munsee, etc.
    "Minnesota": None,  # Multiple Chippewa bands
    "Minnesota Chippewa": None,
    "Nevada": None,  # Multiple Paiute/Shoshone bands
    "Pierre": None,  # Crow Creek + Lower Brulé
    "Western Washington": None,  # Many tribes
    "Riverside": None,  # Many Mission Indian bands

    # Minimal/no individual allotments
    "Colorado River": None,
    "Fort Apache": "Apache",
    "Hopi": None,
    "Papago": None,  # Now Tohono O'odham
    "San Carlos": None,
    "Uintah and Ouray": None,
    "United Pueblo": None,
    "Zuni": None,
    "Warm Springs": None,  # BLM has "Frn WARM SPRING" but different entity
    "Choctaw": "Choctaw",
    "Seminole": None,
    "Osage": "Osage",

    # Alternate names that appear in transaction tables
    "Cheyenne Arapahoe": "Cheyenne Arapaho",
    "Chevenne River": "Cheyenne River Sioux",  # typo in original
    "Navajo": "Navajo",
    "Mescalero": "Mescalero Apache",
    "Osage 1": "Osage",
    "Yakima 1": "Yakama",
    "Seminole 1": None,
    "Hoopa area field office": "Hupa",
    "Riverside area field office": None,
    "California Agency": None,
    "Five Civilized Tribes Agency": None,
    "Quapaw area field office": "Quapaw",
    "Choctaw Agency": "Choctaw",
    "Seminole Agency": None,
    "Fort Belknap consolidated": "Assiniboine And Gros Ventre",
    "Turtle Mountain consolidated": "Turtle Mountain Band Of Chippewa Indians",
}


def main():
    conn = psycopg2.connect("dbname=allotment_research user=cwm6W")
    cur = conn.cursor()

    tables = [
        "murray_comparative",
        "murray_agency_removal",
        "murray_transactions",
        "murray_lands_acquired",
    ]

    for table in tables:
        # Add column if not exists
        cur.execute(f"""
            DO $$ BEGIN
                ALTER TABLE {table} ADD COLUMN blm_tribe_name TEXT;
            EXCEPTION WHEN duplicate_column THEN NULL;
            END $$;
        """)

        # Get distinct agency names
        cur.execute(f"SELECT DISTINCT agency FROM {table}")
        agencies = [r[0] for r in cur.fetchall()]

        mapped = 0
        skipped = 0
        unmapped = []
        for agency in agencies:
            blm_name = MURRAY_TO_BLM.get(agency)
            if blm_name is None and agency not in MURRAY_TO_BLM:
                unmapped.append(agency)
            if blm_name:
                cur.execute(
                    f"UPDATE {table} SET blm_tribe_name = %s WHERE agency = %s",
                    (blm_name, agency)
                )
                mapped += 1
            else:
                skipped += 1

        print(f"{table}: {mapped} mapped, {skipped} skipped")
        if unmapped:
            print(f"  UNMAPPED: {unmapped}")

    conn.commit()
    print("\n✓ All Murray tables updated with blm_tribe_name")

    # Verify
    cur.execute("""
        SELECT agency, blm_tribe_name, individual_acres_1947, individual_acres_1957, individual_decrease
        FROM murray_comparative
        WHERE blm_tribe_name IS NOT NULL
        ORDER BY individual_decrease DESC NULLS LAST
        LIMIT 15
    """)
    print("\nMapped comparative entries (top individual land losses):")
    for r in cur.fetchall():
        loss = f"-{r[4]:>10,.0f}" if r[4] else "      N/A"
        print(f"  {r[0]:<25} → {r[1]:<40} {loss}")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
