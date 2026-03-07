#!/usr/bin/env python3
"""Map Wilson Table VI reservation names to BLM patent preferred_names.

Strategy:
1. Extract the reservation name from Wilson's "Agency (A.): Reservation (R.)" format
2. Try exact and fuzzy matching against BLM preferred_name values
3. Apply manual overrides for known mismatches
4. Record the match method for transparency

This script populates the blm_tribe_name and match_method columns
in the wilson_table_vi table.
"""

import psycopg2
import re


# Manual mapping: Wilson reservation_name → BLM preferred_name
# These handle cases where the names are too different for automated matching
MANUAL_MAP = {
    # Sioux reservations
    "Pine Ridge (A. and R.)": "Oglala Lakota",
    "Rosebud (A. and R.)": "Rosebud Sioux",
    "Cheyenne River (A. and R.)": "Cheyenne River Sioux",
    "Standing Rock (A. and R.)": "Standing Rock Sioux",
    "Crow Creek (A. and R.)": "Crow Creek Sioux",
    "Crow Creek (A.): Lower Brule (R.)": "Lower Brulé Sioux",
    "Rosebud (A.): Yankton (R.)": "Yaknton Sioux Tribe",
    "Fort Totten (A.): Devils Lake (R.)": "Devil's Lake Sioux",
    "Sisseton (A. and R.)": "Sisseton–Wahpeton Oyate",

    # Montana
    "Crow (A. and R.)": "Crow",
    "Blackfeet (A. and R.)": "Blackfeet",
    "Flathead (A. and R.)": "Flathead",
    "Fort Belknap (A. and R.)": "Assiniboine And Gros Ventre",
    "Fort Peck (A. and R.)": "Assiniboine And Sioux",
    "Tongue River (A. and R.)": "Northern Cheyenne",
    "Rocky Boy's (A. and R.)": None,  # No BLM patents for Chippewa-Cree

    # Fort Berthold
    "Fort Berthold (A. and R.)": "Mandan, Hidatsa, Arikara",

    # Oklahoma
    "Cheyenne and Arapaho (A. and R.)": "Cheyenne Arapaho",
    "Kiowa (A. and R.)": "Comanche",  # Kiowa-Comanche-Apache reservation
    "Kiowa (A.): Wichita (R.)": "Wichita",
    "Pawnee (A. and R.)": "Pawnee",
    "Pawnee (A.): Kaw (R.)": None,  # Kaw Nation — few BLM patents
    "Pawnee (A.): Otoe (R.)": "Otoe And Missouria",
    "Pawnee (A.): Ponca (R.)": "Ponca",
    "Pawnee (A.): Tonkawa (R.)": "Tonkawa Tribe Of Oklahoma",
    "Quapaw (A. and R.)": "Quapaw",
    "Quapaw (A.): Eastern Shawnee (R.)": "Eastern Shawnee",
    "Quapaw (A.): Ottawa (R.)": "Ottawa",
    "Quapaw (A.): Seneca (R.)": "Seneca",
    "Quapaw (A.): Wyandotte (R.)": "Wyandotte",
    "Sac and Fox (A. and R.)": "Sac And Fox",
    "Shawnee (A.): Absente Shawnee (R.)": "Absentee Shawnee",
    "Shawnee (A.): Citizen Pottawatomie (R.)": "Citizen Potawatomi",
    "Shawnee (A.): Iowa (R.)": "Iowa",
    "Shawnee (A.): Mexican Kickapoo (R.)": "Mexican Kickapoo",
    "Shawnee (A.): Sac and Fox (R.)": "Sac And Fox",
    "Osage (A. and R.)": None,  # Osage had mineral rights, different system
    "Cherokee (A. and R.)": None,  # Five Civilized Tribes — different system
    "Chocktaw (A. and R.)": "Choctaw",
    "Five Civilized Tribes (A. and R.)": None,  # Aggregated — can't map
    "Seminole (A. and R.)": None,  # Few BLM patents

    # Chippewa/Ojibwe — Minnesota
    "Consolidated Chippewa (A.): White Earth (R.)": "White Earth Chippewa",
    "Consolidated Chippewa (A.): Leech Lake (R.)": "Leech Lake Band Of Ojibwe",
    "Consolidated Chippewa (A.): Mille Lac (R.)": "Mille Lacs Band Of Ojibwe",
    "Consolidated Chippewa (A.): Fond du Lac (R.)": "Fond Du Lac Band Of Lake Superior Chippewa",
    "Consolidated Chippewa (A.): Bois Fort (R.)": "Bois Forte Band Of Chippewa",
    "Consolidated Chippewa (A.): Grand Portage (R.)": "Grand Portage Band Of Lake Superior Chippewa",
    "Consolidated Chippewa (A.): Cass Lake (R.)": None,  # Part of Leech Lake
    "Consolidated Chippewa (A.): White Oak Point (R.)": None,  # Part of Mille Lacs
    "Red Lake (A. and R.)": None,  # Red Lake — closed reservation, few allotments

    # Chippewa — Wisconsin
    "Lac du Flambeau (A. and R.)": "Lac Du Flambeau Band Of Lake Suerior Chippewa",
    "Lac du Flambeau (A.): Bad River (R.)": "Bad River Band Of Lake Superior Chippewa",
    "Lac du Flambeau (A.): Lac Court Oreilles (R.)": "Lac Court Oreilles Band Of Lake Superior Chippewa",
    "Lac du Flambeau (A.): Red Cliff (R.)": None,  # Few BLM patents
    "Keshena (A.): Menominee (R.)": None,  # Menominee — terminated/restored
    "Pipestone (A. and R.)": None,  # Pipestone — school/quarry, not tribal

    # Nebraska/Wisconsin
    "Winnebago (A. and R.)": "Winnebago",
    "Winnebago (A.): Omaha (R.)": "Omaha",
    "Winnebago (A.): Santee and Ponca (R.)": "Santee Sioux",

    # North Dakota
    "Turtle Mountain (A. and R.)": "Turtle Mountain Band Of Chippewa Indians",

    # Idaho
    "Fort Hall (A. and R.)": "Shoshone And Bannock",
    "Coeur d'Alene (A. and R.)": "Coeur D'alene",
    "Coeur d'Alene (A.): Nez Perce (R.)": "Nez Perce",
    "Coeur d'Alene (A.): Kalispel (R.)": "Kalispel",
    "Coeur d'Alene (A.): Kootenai (R.)": "Kootenai",

    # Washington
    "Colville (A. and R.)": "Colville",
    "Colville (A.): Spokane (R.)": None,  # Spokane — separate from Colville in BLM
    "Tahola (A.): Quinaielt (R.)": "Quinault",
    "Tahola (A.): Makah (R.)": "Makah",
    "Tahola (A.): Chehalis (R.)": "Chehalis",
    "Tahola (A.): Skokomish (R.)": None,
    "Tahola (A.): Nisqually (R.)": None,
    "Tahola (A.): Squaxin Island (R.)": None,
    "Tahola (A.): Hoh (R.)": None,
    "Tahola (A.): Ozette (R.)": None,
    "Tahola (A.): Quillayute (R.)": "Quileute",
    "Tahola (A.): Shoal Water (R.)": None,
    "Tahola (A.): Unattached (R.)": None,
    "Tulalip (A. and R.)": None,  # Tulalip — few individual allotment patents
    "Tulalip (A.): Lummi (R.)": "Lummi",
    "Tulalip (A.): Muckleshoot (R.)": None,
    "Tulalip (A.): Port Madison (R.)": None,
    "Tulalip (A.): Puyallup (R.)": None,
    "Tulalip (A.): Swinomish (R.)": None,
    "Yakima (A. and R.)": "Yakama",

    # Oregon
    "Klamath (A. and R.)": "Klamath",
    "Umatillah (A. and R.)": "Umatilla",
    "Warm Springs (A. and R.)": None,  # BLM uses "Frn WARM SPRING"
    "Salem School (A.): Grand Ronde (R.)": "Confederated Tribes Of Grande Ronde",
    "Salem School (A.): Siletz (R.)": "Siletz",
    "Salem School (A.): Fourth Section Allottees (R.)": None,

    # California
    "Hoopa Valley (A. and R.)": "Hupa",
    "Hoopa Valley (A.): Rancheria (R.)": "Round Valley Indian Tribes",
    "Sacramento (A.): Rancherias (R.)": None,  # Multiple rancherias
    "Sacramento (A.): Fort Bidwell (R.)": None,
    "Sacramento (A.): Tule River (R.)": None,

    # Mission Indians (California)
    "Mission (A.): Torres-Martinez (R.)": "Torres Martinez Desert Cahuilla Indians",
    "Mission (A.): Pala (R.)": "Pala",
    "Mission (A.): Palm Springs (R.)": "Agua Caliente Band Of Cahuilla Indians",
    "Mission (A.): Pechanga (R.)": "Pechanga Band Of Luiseño Indians",
    "Mission (A.): Morongo (R.)": None,
    "Mission (A.): Soboba (R.)": None,
    "Mission (A.): Cabazon (R.)": "Cabazon Band Of Cahuilla Indians",
    "Mission (A.): Cahuilla (R.)": None,  # Cahuilla band — few BLM patents under this name
    "Mission (A.): Mission Creek (R.)": None,  # Not Cree
    "Mission (A.): Santa Rosa (R.)": None,  # Not Santa Ynez
    "Mission (A.): Santa Ynez (R.)": None,  # Tiny reservation
    "Mission (A.): Santa Ysabel (R.)": None,  # Not Santa Ynez
    "Mission (A.): Augustine (R.)": None,  # Tiny
    "Mission (A.): Campo (R.)": None,
    "Mission (A.): Capitan Grande (R.)": None,
    "Mission (A.): Cosmit (R.)": None,
    "Mission (A.): Cuyapaipe (R.)": None,
    "Mission (A.): Inaja (R.)": None,
    "Mission (A.): La Jolla (R.)": None,
    "Mission (A.): La Posta (R.)": None,
    "Mission (A.): Laguna (R.)": None,
    "Mission (A.): Los Coyotes (R.)": None,
    "Mission (A.): Manzanita (R.)": None,
    "Mission (A.): Mesa Grande (R.)": None,
    "Mission (A.): Pauma (R.)": None,
    "Mission (A.): Ramona (R.)": None,
    "Mission (A.): Rincon (R.)": None,
    "Mission (A.): San Manuel (R.)": None,
    "Mission (A.): San Pasqual (R.)": None,
    "Mission (A.): Sycuan (R.)": None,
    "Mission (A.): Twentynine Palms (R.)": None,

    # Wyoming
    "Shahone (A.): Wind River (R.)": "Shoshone",

    # Kansas
    "Haskell Institute (A.): Potwatomi (R.)": "Prairie Band Of Potawatami Nation",
    "Haskell Institute (A.): Kickapoo (R.)": "Kickapoo",
    "Haskell Institute (A.): Iowa (R.)": "Iowa",
    "Haskell Institute (A.): Sac and Fox (R.)": "Sac And Fox",

    # Utah
    "Unitah and Ouray (A. and R.)": "Uncompahgre Ute",
    "Consolidated Ute (A.): Southern Ute (R.)": None,
    "Consolidated Ute (A.): Ute Mountain (R.)": None,
    "Consolidated Ute (A.): Allen Canyon (R.)": None,

    # Nevada
    "Carson (A.): Pyramid Lake (R.)": None,
    "Carson (A.): Fort McDermitt (R.)": None,
    "Carson (A.): Nonreservation (R.)": None,
    "Carson (A.): Summit Lake (R.)": None,
    "Walker River (A. and R.)": None,
    "Walker River (A.): Fallon (R.)": None,
    "Walker River (A.): Mason and Smith Valleys (R.)": None,
    "Walker River (Bishop) (A.): Fort Independence (R.)": None,
    "Walker River (Bishop) (A.): Indian Homesites (R.)": None,
    "Walker River (Bishop) (A.): Scattered Bands (R.)": None,
    "Western Shoshone (A. and R.)": None,
    "Paiute (A. and R.)": "Paiute",
    "Paiute (A.): Goshute (R.)": None,  # Not Ute
    "Paiute (A.): Kaibab (R.)": None,
    "Paiute (A.): Kanosh (R.)": None,
    "Paiute (A.): Koosharem (R.)": None,
    "Paiute (A.): Moapa River (R.)": None,
    "Paiute (A.): Shivwitz (R.)": None,
    "Paiute (A.): Skull Valley (R.)": None,

    # Arizona
    "Fort Apache (A. and R.)": "Apache",
    "San Carlos (A. and R.)": None,
    "Colorado River (A. and R.)": None,
    "Colorado River (A.): Fort Mojave (R.)": None,
    "Fort Yuma (A.): Yuma (R.)": "Quechan",
    "Fort Yuma (A.): Cocopah (R.)": None,
    "Pima (A.): Gila River (R.)": None,
    "Pima (A.): Salt River (R.)": None,
    "Pima (A.): McDowell (R.)": None,
    "Phoenix (A.): Camp Verde (R.)": None,
    "Hopi (A.): Keams Canyon (R.)": None,
    "Sells (A.): Papago (R.)": None,
    "Sells (A.): San Xavier (Papago) (R.)": None,
    "Sells (A.): Gila Bend (R.)": None,
    "Truxton Canon (A.): Havasupai (R.)": None,
    "Truxton Canon (A.): Hualapai (R.)": None,

    # New Mexico
    "Jicarilla (A. and R.)": "Jicarilla Apache",
    "Mescalero (A. and R.)": None,
    "Zuni (A. and R.)": None,
    "Eastern Navajo (A. and R.)": "Navajo",

    # Navajo
    "Northern Navajo (A. and R.)": "Navajo",
    "Southern Navajo (A. and R.)": "Navajo",
    "Western Navajo (A. and R.)": "Navajo",
    "Leupp (A. and R.)": "Navajo",
    "Tuba City (A.):  W. Navajo (R.)": "Navajo",

    # Pueblos — communal land grants, not allotted through BLM
    "Northern Pueblo (A.): Nambe (R.)": None,
    "Northern Pueblo (A.): Picuris (R.)": None,
    "Northern Pueblo (A.): Pojuaque (R.)": None,
    "Northern Pueblo (A.): San Ildefonso (R.)": None,
    "Northern Pueblo (A.): San Juan (R.)": None,
    "Northern Pueblo (A.): Santa Clara (R.)": None,
    "Northern Pueblo (A.): Taos (R.)": None,
    "Northern Pueblo (A.): Tesuque (R.)": None,
    "Southern Pueblos (A.): Acoma (R.)": None,
    "Southern Pueblos (A.): Cochiti (R.)": None,
    "Southern Pueblos (A.): Jemez (R.)": None,
    "Southern Pueblos (A.): Laguna (R.)": None,
    "Southern Pueblos (A.): Sandia (R.)": None,
    "Southern Pueblos (A.): San Felipe (R.)": None,
    "Southern Pueblos (A.): Santa Ana (R.)": None,
    "Southern Pueblos (A.): Santo Domingo (R.)": None,
    "Southern Pueblos (A.): Sia (R.)": None,

    # Wisconsin Oneida
    "Tomah (A.): Oneida (R.)": "Oneida",

    # New York — state reservations, not allotted through BLM
    "New York (A.): Oneida (R.)": None,
    "New York (A.): Allegany (R.)": None,
    "New York (A.): Cattaraugas (R.)": None,
    "New York (A.): Oil Spring (R.)": None,
    "New York (A.): Onondaga (R.)": None,
    "New York (A.): St. Regis (R.)": None,
    "New York (A.): Tonawanda (R.)": None,
    "New York (A.): Tuscarora (R.)": None,
    "Stockbridge Munsee Band Of Mohican Indians": None,  # not in Wilson
}


def extract_reservation_name(wilson_name):
    """Extract the core reservation name from Wilson's format.

    'Crow (A. and R.)' → 'Crow'
    'Coeur d'Alene (A.): Nez Perce (R.)' → 'Nez Perce'
    """
    # If format is "Agency (A.): Reservation (R.)", use the reservation part
    match = re.match(r'.+\(A\.\):\s*(.+?)\s*\(R\.\)', wilson_name)
    if match:
        return match.group(1).strip()
    # If format is "Name (A. and R.)", use the name part
    match = re.match(r'(.+?)\s*\(A\. and R\.\)', wilson_name)
    if match:
        return match.group(1).strip()
    return wilson_name


def fuzzy_match(wilson_name, blm_names):
    """Try to match Wilson reservation name to BLM preferred_name."""
    core = extract_reservation_name(wilson_name).lower()

    # Direct substring match
    for blm in blm_names:
        if core in blm.lower() or blm.lower() in core:
            return blm, "substring"

    # Try first word match (for multi-word names)
    first_word = core.split()[0] if core.split() else ""
    if len(first_word) >= 4:
        matches = [b for b in blm_names if b.lower().startswith(first_word)]
        if len(matches) == 1:
            return matches[0], "first_word"

    return None, None


def main():
    conn = psycopg2.connect("dbname=allotment_research user=cwm6W")
    cur = conn.cursor()

    # Get BLM names
    cur.execute("""
        SELECT preferred_name, COUNT(*) as cnt
        FROM blm_allotment_patents
        WHERE preferred_name IS NOT NULL
        GROUP BY preferred_name
        ORDER BY cnt DESC
    """)
    blm_names = {r[0]: r[1] for r in cur.fetchall()}

    # Get Wilson names
    cur.execute("SELECT id, reservation_name FROM wilson_table_vi ORDER BY id")
    wilson_rows = cur.fetchall()

    mapped = 0
    unmapped = 0
    skipped = 0

    for wid, wname in wilson_rows:
        blm_name = None
        method = None

        # Check manual mapping first
        if wname in MANUAL_MAP:
            blm_name = MANUAL_MAP[wname]
            method = "manual" if blm_name else "manual_skip"
        else:
            # Try automated matching
            blm_name, method = fuzzy_match(wname, blm_names)

        if blm_name and blm_name in blm_names:
            cur.execute("""
                UPDATE wilson_table_vi
                SET blm_tribe_name = %s, match_method = %s
                WHERE id = %s
            """, (blm_name, method, wid))
            mapped += 1
            patent_count = blm_names[blm_name]
            print(f"  ✓ {wname:<50} → {blm_name:<45} ({patent_count:,} patents) [{method}]")
        elif method == "manual_skip":
            cur.execute("""
                UPDATE wilson_table_vi
                SET blm_tribe_name = NULL, match_method = 'no_blm_match'
                WHERE id = %s
            """, (wid,))
            skipped += 1
            print(f"  – {wname:<50} → (no BLM equivalent) [manual_skip]")
        else:
            cur.execute("""
                UPDATE wilson_table_vi
                SET blm_tribe_name = NULL, match_method = 'unmatched'
                WHERE id = %s
            """, (wid,))
            unmapped += 1
            print(f"  ✗ {wname:<50} → NO MATCH")

    conn.commit()
    print(f"\nResults: {mapped} mapped, {skipped} skipped (no BLM equivalent), {unmapped} unmatched")

    # Show coverage
    cur.execute("""
        SELECT
            COUNT(*) as total,
            COUNT(blm_tribe_name) as matched,
            SUM(CASE WHEN match_method = 'no_blm_match' THEN 1 ELSE 0 END) as no_equiv,
            SUM(original_area_acres) FILTER (WHERE blm_tribe_name IS NOT NULL) as matched_acres,
            SUM(original_area_acres) as total_acres
        FROM wilson_table_vi
    """)
    row = cur.fetchone()
    print(f"\nCoverage: {row[1]}/{row[0]} reservations matched")
    if row[3] and row[4]:
        print(f"Acreage coverage: {row[3]:,} / {row[4]:,} acres ({row[3]/row[4]*100:.1f}%)")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
