import os
import re
import psycopg2
import psycopg2.extras
from flask import Flask, render_template, request, jsonify, Response, abort
from functools import wraps
import csv
import io

app = Flask(__name__)

AUTH_USERNAME = os.environ.get("AUTH_USERNAME", "allotment")
AUTH_PASSWORD = os.environ.get("AUTH_PASSWORD", "fee_simple")

@app.before_request
def require_basic_auth():
    auth = request.authorization
    if not auth or auth.username != AUTH_USERNAME or auth.password != AUTH_PASSWORD:
        return Response(
            "Login required.", 401,
            {"WWW-Authenticate": 'Basic realm="Login Required"'}
        )

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "dbname=allotment_research user=cwm6W"
)

def get_db():
    conn = psycopg2.connect(DATABASE_URL)
    conn.set_client_encoding('UTF8')
    return conn


def slugify(name):
    """Convert tribe name to URL slug."""
    s = name.lower().strip()
    s = re.sub(r"[''']", "", s)
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def unslugify_tribe(slug):
    """Look up the original tribe name from a slug."""
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT tribe_identified FROM federal_register_claims ORDER BY tribe_identified")
        for (name,) in cur.fetchall():
            if slugify(name) == slug:
                return name
        return None
    finally:
        conn.close()


DOC_CLASS_MAP = {
    "Serial Land Patent": "SER",
    "State Land Patent": "STA",
    "Indian Allotment Patent": "IA",
    "Indian Allotment - General": "IA",
    "Indian Fee Patent": "IF",
    "Indian Trust Patent": "SER",
    "Indian Trust to Fee": "SER",
    "Indian Homestead Fee Patent": "SER",
    "Miscellaneous Volume Patent": "MV",
    "Sioux Scrip Patent": "SS",
    "Chippewas Treaty Patent": "CT",
}

def glo_url(accession, doc_class=None):
    """Build a GLO record URL from accession number and document class.
    doc_class can be a BLM code (SER, STA, IA) or an authority name
    (Serial Land Patent, State Land Patent, etc.) — both are mapped."""
    if not accession:
        return None
    # If doc_class is an authority name, map to code
    dc = DOC_CLASS_MAP.get(doc_class, doc_class) if doc_class else None
    # If still None or unrecognized, try the document_code directly or default to SER
    if not dc or len(dc) > 5:
        dc = "SER"
    return f"https://glorecords.blm.gov/details/patent/default.aspx?accession={accession}&docClass={dc}"


def linkify_remarks(text):
    """Turn patent number references in remarks into GLO links."""
    if not text:
        return text
    def make_link(accession):
        url = f"https://glorecords.blm.gov/details/patent/default.aspx?accession={accession}&docClass=SER"
        return f'<a href="{url}" target="_blank">{accession}</a>'
    # Match "NR XXXXXX" and also "AND XXXXXX" patterns
    text = re.sub(r'(?:NR\.?|AND)\s+(\d{4,})', lambda m: m.group(0).replace(m.group(1), make_link(m.group(1))), text)
    return text


def add_claim_type_filter(claim_type, conditions, params):
    """Add claim type filter, grouping variants together."""
    if claim_type:
        if claim_type == "ALL FORCED FEE":
            conditions.append("fr.claim_type ILIKE %s")
            params.append("%FORCED FEE%")
        elif claim_type == "TRESPASS":
            conditions.append("(fr.claim_type ILIKE %s OR fr.claim_type ILIKE %s OR fr.claim_type ILIKE %s)")
            params.extend(["%TRESPASS%", "%IN TRESPASS%", "%ENCROACHMENT%"])
        elif claim_type == "UNAPPROVED":
            conditions.append("(fr.claim_type ILIKE %s OR fr.claim_type ILIKE %s)")
            params.extend(["%UNAPPROVED%", "%WITHOUT APPROVAL%"])
        elif claim_type == "WELFARE":
            conditions.append("(fr.claim_type ILIKE %s AND fr.claim_type NOT ILIKE %s)")
            params.extend(["%WELFARE%", "%FORCED FEE%"])
        elif claim_type == "TIMBER":
            conditions.append("fr.claim_type ILIKE %s")
            params.append("%TIMBER%")
        elif claim_type == "RECOVERY":
            conditions.append("fr.claim_type ILIKE %s")
            params.append("%RECOVERY%")
        elif claim_type == "ALLOTMENT NEVER ISSUED":
            conditions.append("fr.claim_type ILIKE %s")
            params.append("%ALLOTMENT NEVER ISSUED%")
        else:
            conditions.append("fr.claim_type ILIKE %s")
            params.append(f"%{claim_type}%")


# ──────────────────────────────────────────────
# Routes
# ──────────────────────────────────────────────

@app.route("/")
def splash():
    """Splash / gateway page styled after the IATH main site."""
    return render_template("splash.html")


@app.route("/home")
def home():
    """Research overview page."""
    return render_template("home.html")


@app.route("/map")
def allotment_map():
    """Interactive allotment patent map (Leaflet + Esri Feature Service)."""
    return render_template("map.html")


@app.route("/claims")
def claims_search():
    """Claims search / browse page."""
    conn = get_db()
    try:
        cur = conn.cursor()
        # Get tribe list with counts for the dropdown
        cur.execute("""
            SELECT tribe_identified, COUNT(*) as cnt
            FROM federal_register_claims
            GROUP BY tribe_identified
            ORDER BY tribe_identified
        """)
        tribes = cur.fetchall()

        # Get states for filter dropdown
        cur.execute("""
            SELECT DISTINCT state
            FROM federal_register_claims
            WHERE state IS NOT NULL
            ORDER BY state
        """)
        states = [row[0] for row in cur.fetchall()]

        # Get claim counts by agency code for the TOC
        cur.execute("""
            SELECT bia_agency_code, COUNT(*) as cnt
            FROM federal_register_claims
            GROUP BY bia_agency_code
        """)
        agency_counts = dict(cur.fetchall())

        # Grouped claim type categories
        claim_types = [
            ("ALL FORCED FEE", "Forced Fee Patent (all variants)"),
            ("SECRETARIAL TRANSFER", "Secretarial Transfer (all variants)"),
            ("UNAPPROVED", "Unapproved Land Sale"),
            ("TAX FORFEITURE", "Tax Forfeiture"),
            ("TAXATION", "Taxation"),
            ("QUESTIONABLE CANCELLATION", "Questionable Cancellation of Patent"),
            ("TRESPASS", "Trespass (all types)"),
            ("LAND SOLD WITHOUT APPROVAL", "Land Sold Without Approval"),
            ("OLD AGE ASSISTANCE", "Old Age Assistance"),
            ("WELFARE", "Welfare Payments"),
            ("TIMBER", "Timber (wrongfully removed, trespass)"),
            ("ALLOTMENT NEVER ISSUED", "Allotment Never Issued"),
            ("RECOVERY", "Claim for Recovery of Trust Land"),
        ]

        # Federal Register Table of Contents — area offices, agencies, codes
        # Source: https://land-sales.iath.virginia.edu/federal_register-toc.php
        fr_toc = [
            ("Aberdeen", [
                ("Flandreau", "Santee Sioux", "A00007"),
                ("Cheyenne River", "Cheyenne River Sioux Indians", "A01304"),
                ("Cheyenne River", "Cheyenne River Sioux Indians", "A01340"),
                ("Fort Berthold", "Fort Berthold Indians", "A04301"),
                ("Fort Totten", "Devils Lake Indians", "A05303"),
                ("Pine Ridge", "Pine Ridge Sioux Indians", "A06344"),
                ("Rosebud", "Rosebud Sioux Indians", "A07345"),
                ("Yankton", "Yankton Sioux Indians", "A08346"),
                ("Sisseton", "Sisseton-Wahpeton Tribe of Sioux", "A09347"),
                ("Standing Rock", "Standing Rock Sioux Indians", "A10302"),
                ("Turtle Mountain", "Turtle Mountain Band of Chippewa Indians", "A11304"),
                ("Winnebago", "Omaha Indians of Nebraska", "A13380"),
                ("Winnebago", "Santee Sioux Indians of Nebraska", "A13382"),
                ("Winnebago", "Winnebago Indians of Nebraska", "A13383"),
                ("Crow Creek", "Crow Creek", "A14342"),
                ("Lower Brule", "Lower Brule", "A15343"),
            ]),
            ("Anadarko", [
                ("Horton", "Potawatomi (Wisconsin)", "B04434"),
                ("Horton", "Iowa Indians (Kansas and Nebraska)", "B04860"),
                ("Horton", "Kickapoo Indians (Kansas)", "B04861"),
                ("Horton", "Potawatomi Indians (Kansas)", "B04862"),
                ("Horton", "Sac and Fox Indians (Kansas and Nebraska)", "B04863"),
                ("Horton", "Shawnee Public Domain", "B04864"),
                ("Horton", "Wyandotte", "B04924"),
                ("Horton", "Peoria", "B04926"),
                ("Concho", "Cheyenne and Arapaho Indians", "B05801"),
                ("Anadarko", "Kiowa-Comanche and Apache Indians", "B06802"),
                ("Anadarko", "Fort Sill Apache Indians", "B06803"),
                ("Anadarko", "Wichita Indians", "B06804"),
                ("Anadarko", "Caddo-Wichita Indians", "B06806"),
                ("Anadarko", "Comanche Indians", "B06808"),
                ("Anadarko", "Apache Indians", "B06809"),
                ("Pawnee", "Otoe and Missouri Indians", "B07811"),
                ("Pawnee", "Pawnee Indians", "B07812"),
                ("Pawnee", "Ponca Indians", "B07813"),
                ("Pawnee", "Tonkawa Indians", "B07814"),
                ("Shawnee", "Absentee Shawnee Indians", "B08820"),
                ("Shawnee", "Citizen Band Potawatomi Indians (Oklahoma)", "B08821"),
                ("Shawnee", "Iowa Indians (Oklahoma)", "B08822"),
                ("Shawnee", "Mexican Kickapoo Indians (Oklahoma)", "B08823"),
                ("Shawnee", "Sac and Fox Indians (Oklahoma)", "B08824"),
                ("Shawnee", "Eastern Shawnee", "B08921"),
            ]),
            ("Billings", [
                ("Blackfeet", "Blackfeet Indians", "C51201"),
                ("Crow", "Crow Indians", "C52202"),
                ("Flathead", "Flathead Indians", "C53203"),
                ("Fort Belknap", "Fort Belknap Indians", "C55204"),
                ("Fort Belknap", "Turtle Mountain", "C55224"),
                ("Fort Peck", "Fort Peck Indians", "C56206"),
                ("Fort Peck", "Turtle Mountain", "C56226"),
                ("Northern Cheyenne", "Northern Cheyenne Indians", "C57207"),
                ("Northern Cheyenne", "Turtle Mountain", "C57277"),
                ("Wind River", "Arapaho Indians", "C58281"),
                ("Rocky Boys", "Rocky Boy Indians", "C59205"),
            ]),
            ("Eastern", [
                ("Eastern Area Office", "Catawba", "S50002"),
                ("Eastern Area Office", "Seneca (Allegany)", "S50004"),
                ("Eastern Area Office", "St. Regis", "S50007"),
                ("Eastern Area Office", "Seneca (Oil Springs)", "S50010"),
                ("Eastern Area Office", "Oneida", "S50011"),
                ("Eastern Area Office", "Cayuga", "S50013"),
                ("Eastern Area Office", "Gay Head Band of Wampanoag", "S50030"),
                ("Eastern Area Office", "Western Pequot", "S50031"),
                ("Eastern Area Office", "Schaghticoke", "S50032"),
                ("Eastern Area Office", "Mohegan", "S50033"),
                ("Eastern Area Office", "Shinnecock", "S50034"),
                ("Eastern Area Office", "Seminole", "S50035"),
                ("Eastern Area Office", "Chitimacha", "S50036"),
                ("Eastern Area Office", "Tunica Biloxi", "S50037"),
                ("Eastern Area Office", "Stockbridge Munsee", "S50038"),
            ]),
            ("Juneau", [
                ("Juneau Area Headquarters", "Juneau Area", "E00000"),
            ]),
            ("Minneapolis", [
                ("Great Lakes", "Menominee", "F50440"),
                ("Red Lake", "Red Lake Band of Chippewa", "F52409"),
                ("Minnesota", "Mille Lacs Indians\u2014Mississippi Band of Chippewa", "F53404"),
                ("Minnesota", "White Earth Indians", "F53405"),
                ("Minnesota", "Grand Portage Indians\u2014Lake Superior Bands of Chippewa", "F53406"),
                ("Minnesota", "Leech Lake Indians", "F53407"),
                ("Minnesota", "White Earth", "F53408"),
                ("Minnesota", "Mille Lacs", "F53410"),
                ("Minnesota", "Public Domain", "F53420"),
                ("Great Lakes", "Bad River Band of the Lake Superior Tribe of Chippewa", "F55430"),
                ("Great Lakes", "Lac Courte Oreilles Band of Lake Superior Chippewa", "F55431"),
                ("Great Lakes", "Lac du Flambeau Band of Lake Superior Chippewa", "F55432"),
                ("Great Lakes", "Oneida Tribe of Indians", "F55433"),
                ("Great Lakes", "Forest County Potawatomi Indians of Wisconsin", "F55434"),
                ("Great Lakes", "Red Cliff Band of Lake Superior Chippewa Indians", "F55435"),
                ("Great Lakes", "St. Croix Chippewa Indians of Wisconsin", "F55436"),
                ("Great Lakes", "Stockbridge Munsee Band of Mohican Indians", "F55438"),
                ("Great Lakes", "Wisconsin Winnebago Indians", "F55439"),
                ("Great Lakes", "Public Domain (Wisconsin)", "F55441"),
                ("Minneapolis", "Upper Sioux", "F57401"),
                ("Minneapolis", "Lower Sioux", "F57402"),
                ("Minneapolis", "Prairie Island", "F57403"),
                ("Minneapolis", "Prior Lake", "F57411"),
                ("Michigan", "Sault Ste. Marie", "F60469"),
                ("Michigan", "Bay Mills", "F60470"),
                ("Michigan", "Hannahville", "F60471"),
                ("Michigan", "Saginaw Chippewa", "F60472"),
                ("Michigan", "Keweenaw Bay", "F60473"),
                ("Michigan", "Ottawa & Chippewa", "F60474"),
                ("Michigan", "Ontonagon", "F60476"),
                ("Michigan", "Public Domain (Michigan)", "F60477"),
                ("Michigan", "Lac Vieux", "F60478"),
            ]),
            ("Muskogee", [
                ("Ardmore", "Chickasaw Indians", "G03906"),
                ("Miami", "Quapaw Indians", "G04920"),
                ("Miami", "Ottawa Bands of Blanchards Fork and Roche Deboeuf", "G04922"),
                ("Miami", "Seneca and Shawnee Indians", "G04923"),
                ("Miami", "Wyandotte Indians (Oklahoma and Kansas)", "G04924"),
                ("Miami", "Miami Tribe of Indians", "G04925"),
                ("Miami", "Peoria Tribe of Oklahoma", "G04926"),
                ("Osage", "Osage Indians", "G06930"),
                ("Okmulgee", "Creek Indians", "G07908"),
                ("Tahlequah", "Cherokee Indians", "G08905"),
                ("Talihina", "Choctaw Indians", "G09907"),
                ("Wewoka", "Seminole Indians", "G10909"),
            ]),
            ("Navajo", [
                ("Gallup Headquarters", "Navajo Indians", "N00780"),
            ]),
            ("Phoenix", [
                ("Colorado River", "Colorado River Indians", "H51603"),
                ("Colorado River", "Fort Mojave Indians", "H51604"),
                ("Fort Apache", "Fort Apache Indians", "H52607"),
                ("Nevada", "Duck Valley", "H53642"),
                ("Nevada", "Duck Valley", "H53662"),
                ("Papago", "Papago Indians", "H54610"),
                ("Salt River", "Salt River Indians", "H55615"),
                ("Pima", "Pima Indians (Gila River)", "H57614"),
                ("San Carlos", "San Carlos Apache Indians", "H58616"),
                ("Nevada", "Pyramid Lake Indians", "H61651"),
                ("Uintah/Ouray", "Summit Lake & Public Domain", "H62655"),
                ("Eastern Nevada", "Ruby Valley & Public Domain", "H64654"),
            ]),
            ("Portland", [
                ("Portland Headquarters", "Klamath Indians", "P00140"),
                ("Portland Area Office", "Celilo Village", "P00148"),
                ("Colville", "Colville Indians", "P03101"),
                ("Fort Hall", "Fort Hall Indians", "P04180"),
                ("Northern Idaho", "Coeur d\u2019Alene Indians", "P05181"),
                ("Northern Idaho", "Nez Perce Indians", "P05182"),
                ("Northern Idaho", "Kootenai Indians", "P05183"),
                ("Olympic Peninsula", "Hoh", "P06106"),
                ("Olympic Peninsula", "Makah", "P06108"),
                ("Olympic Peninsula", "Quileute", "P06116"),
                ("Olympic Peninsula", "Quinault", "P06117"),
                ("Olympic Peninsula", "Shoalwater", "P06118"),
                ("Olympic Peninsula", "Skokomish", "P06120"),
                ("Olympic Peninsula", "Lower Elwha", "P06125"),
                ("Olympic Peninsula", "Public Domain", "P06130"),
                ("Umatilla", "Umatilla Indians", "P07143"),
                ("Warm Springs", "Snake or Paiute Indians", "P09144"),
                ("Warm Springs", "Warm Springs Indians", "P09145"),
                ("Warm Springs", "Dalles Public Domain", "P09147"),
                ("Warm Springs", "Oregon Miscellaneous", "P09149"),
                ("Puget Sound", "Lummi", "P10107"),
                ("Puget Sound", "Muckleshoot Indians", "P10109"),
                ("Puget Sound", "Nisqually", "P10110"),
                ("Puget Sound", "Nooksack Indians", "P10111"),
                ("Puget Sound", "Ozette", "P10112"),
                ("Puget Sound", "Port Gamble Indians", "P10113"),
                ("Puget Sound", "Port Madison Indians", "P10114"),
                ("Puget Sound", "Skagit Indians", "P10119"),
                ("Puget Sound", "Swinomish Indians", "P10122"),
                ("Puget Sound", "Tulalip Indians", "P10123"),
                ("Puget Sound", "Snohomish Indians", "P10130"),
                ("Yakima", "Yakima Indians", "P11124"),
                ("Spokane", "Spokane Indians", "P12102"),
                ("Spokane", "Kalispel Indians", "P12103"),
            ]),
            ("Sacramento", [
                ("Sacramento Area", "California Indians", "J50500"),
                ("California", "Ft. Independence Indians", "J51525"),
                ("California", "Round Valley Indians", "J51540"),
                ("California", "Sulphur Bank Indians", "J51632"),
                ("Hoopa", "Rohnerville", "J52056"),
                ("Hoopa Area Field Office", "Hoopa Valley Indians", "J52561"),
                ("Hoopa Area Field Office", "Hoopa Extension Indians", "J52562"),
                ("Hoopa Area Field Office", "Hoopa Extension Indians", "J52652"),
                ("Southern California", "Sacramento Miscellaneous", "J54500"),
                ("Southern California", "Augustine Indians", "J54567"),
                ("Southern California", "Cabazon Indians", "J54568"),
                ("Southern California", "Cahuilla Indians", "J54569"),
                ("Southern California", "Campo Indians", "J54570"),
                ("Southern California", "Capitan Grande Indians", "J54571"),
                ("Southern California", "La Jolla Indians", "J54576"),
                ("Southern California", "La Posta Indians", "J54577"),
                ("Southern California", "Manzanita", "J54579"),
                ("Southern California", "Mesa Grande", "J54580"),
                ("Southern California", "Morongo Indians", "J54582"),
                ("Southern California", "Pala Indians", "J54583"),
                ("Southern California", "Pauma & Yuima", "J54585"),
                ("Southern California", "Pechanga Indians", "J54586"),
                ("Southern California", "Rincon Indians", "J54587"),
                ("Southern California", "Santa Ysabel Indians", "J54592"),
                ("Southern California", "Soboba Indians", "J54593"),
                ("Southern California", "Torres-Martinez Indians", "J54595"),
                ("Southern California", "Viejas (Baron Long) Indians", "J54599"),
            ]),
            ("Albuquerque", [
                ("Southern Pueblos", "Acoma Pueblo Indians", "M20703"),
                ("Southern Pueblos", "Cochiti Pueblo Indians", "M20704"),
                ("Southern Pueblos", "Isleta Pueblo Indians", "M20705"),
                ("Southern Pueblos", "Jemez Pueblo Indians", "M20706"),
                ("Southern Pueblos", "Laguna Pueblo Indians", "M20707"),
                ("Southern Pueblos", "Sandia Pueblo Indians", "M20711"),
                ("Southern Pueblos", "San Felipe Pueblo Indians", "M20712"),
                ("Southern Pueblos", "Santa Ana Pueblo Indians", "M20715"),
                ("Southern Pueblos", "Santo Domingo Pueblo Indians", "M20717"),
                ("Southern Pueblos", "Zia Pueblo Indians", "M20720"),
                ("Northern Pueblos", "Nambe Pueblo Indians", "M25708"),
                ("Northern Pueblos", "Picuris Pueblo Indians", "M25709"),
                ("Northern Pueblos", "Pojoaque Pueblo Indians", "M25710"),
                ("Northern Pueblos", "San Felipe", "M25712"),
                ("Northern Pueblos", "San Ildefonso Pueblo Indians", "M25713"),
                ("Northern Pueblos", "San Juan Pueblo Indians", "M25714"),
                ("Northern Pueblos", "Santa Clara Pueblo Indians", "M25716"),
                ("Northern Pueblos", "Taos Pueblo Indians", "M25718"),
                ("Northern Pueblos", "Tesuque Pueblo Indians", "M25719"),
                ("Ute Mountain", "Ute Mountain Indians", "M45751"),
                ("Mescalero", "Mescalero Apache Indians", "M60702"),
            ]),
        ]

        return render_template("index.html", tribes=tribes, claim_types=claim_types,
                               states=states, fr_toc=fr_toc, agency_counts=agency_counts, slugify=slugify)
    finally:
        conn.close()


@app.route("/api/search")
def api_search():
    """JSON API for search results (used by DataTables)."""
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # DataTables parameters
        draw = request.args.get("draw", 1, type=int)
        start = request.args.get("start", 0, type=int)
        length = request.args.get("length", 25, type=int)
        search_value = request.args.get("search[value]", "").strip()

        # Custom filters
        tribe = request.args.get("tribe", "").strip()
        claim_type = request.args.get("claim_type", "").strip()
        agency_code = request.args.get("agency_code", "").strip()
        state = request.args.get("state", "").strip()
        name_search = request.args.get("name", "").strip()
        allotment_search = request.args.get("allotment", "").strip()
        date_from = request.args.get("date_from", "").strip()
        date_to = request.args.get("date_to", "").strip()

        # Order (support multi-column sort from DataTables)
        order_cols = ["fr.bia_agency_code", "fr.case_number", "fr.allottee_name", "fr.tribe_identified",
                      "fr.allotment_number", "fr.claim_type", "min_date", "on_map"]
        order_parts = []
        for i in range(len(order_cols)):
            col_idx = request.args.get(f"order[{i}][column]", type=int)
            col_dir = request.args.get(f"order[{i}][dir]", "")
            if col_idx is None:
                break
            col = order_cols[min(col_idx, len(order_cols) - 1)]
            if col_dir not in ("asc", "desc"):
                col_dir = "asc"
            order_parts.append(f"{col} {col_dir}")
        order_clause = ", ".join(order_parts) if order_parts else "fr.bia_agency_code asc, fr.case_number asc"

        conditions = []
        params = []

        if tribe:
            conditions.append("fr.tribe_identified = %s")
            params.append(tribe)
        if agency_code:
            conditions.append("fr.bia_agency_code = %s")
            params.append(agency_code)
        if state:
            conditions.append("fr.state = %s")
            params.append(state)
        add_claim_type_filter(claim_type, conditions, params)
        if name_search:
            conditions.append("fr.allottee_name ILIKE %s")
            params.append(f"%{name_search}%")
        if allotment_search:
            conditions.append("fr.allotment_number ILIKE %s")
            params.append(allotment_search)
        if search_value:
            conditions.append("""(
                fr.allottee_name ILIKE %s OR
                fr.case_number ILIKE %s OR
                fr.allotment_number ILIKE %s OR
                fr.tribe_identified ILIKE %s
            )""")
            sv = f"%{search_value}%"
            params.extend([sv, sv, sv, sv])
        if date_from:
            conditions.append("ffp.patents_signature_date >= %s")
            params.append(date_from)
        if date_to:
            conditions.append("ffp.patents_signature_date <= %s")
            params.append(date_to)

        where = "WHERE " + " AND ".join(conditions) if conditions else ""

        # Total records (unfiltered)
        cur.execute("SELECT COUNT(*) as cnt FROM federal_register_claims")
        total = cur.fetchone()["cnt"]

        # Filtered count
        count_sql = f"""
            SELECT COUNT(DISTINCT fr.id)
            FROM federal_register_claims fr
            LEFT JOIN forced_fee_patents_rails ffp
                ON LTRIM(fr.case_number, '0') = LTRIM(ffp.case_number, '0')
                AND fr.allottee_name = ffp.fedreg_allottee
            {where}
        """
        cur.execute(count_sql, params)
        filtered = cur.fetchone()["count"]

        # Main query
        data_sql = f"""
            SELECT
                fr.id,
                fr.bia_agency_code,
                fr.case_number,
                fr.allottee_name,
                fr.tribe_identified,
                fr.allotment_number,
                fr.claim_type,
                MIN(ffp.patents_signature_date) as min_date,
                COUNT(ffp.id) as patent_count,
                BOOL_OR(bap.objectid IS NOT NULL) as on_map
            FROM federal_register_claims fr
            LEFT JOIN forced_fee_patents_rails ffp
                ON LTRIM(fr.case_number, '0') = LTRIM(ffp.case_number, '0')
                AND fr.allottee_name = ffp.fedreg_allottee
            LEFT JOIN blm_allotment_patents bap
                ON ffp.patents_accession_number = bap.accession_number
            {where}
            GROUP BY fr.id, fr.bia_agency_code, fr.case_number, fr.allottee_name, fr.tribe_identified,
                     fr.allotment_number, fr.claim_type
            ORDER BY {order_clause}
            LIMIT %s OFFSET %s
        """
        cur.execute(data_sql, params + [length, start])
        rows = cur.fetchall()

        # Format for DataTables
        data = []
        for r in rows:
            sig_date = ""
            if r["min_date"]:
                sig_date = r["min_date"].strftime("%Y-%m-%d") if hasattr(r["min_date"], "strftime") else str(r["min_date"])
            data.append({
                "id": r["id"],
                "bia_agency_code": r["bia_agency_code"],
                "case_number": r["case_number"],
                "allottee_name": r["allottee_name"],
                "tribe": r["tribe_identified"],
                "tribe_slug": slugify(r["tribe_identified"]),
                "allotment_number": r["allotment_number"],
                "claim_type": r["claim_type"],
                "patent_date": sig_date,
                "patent_count": r["patent_count"],
                "on_map": bool(r["on_map"]),
            })

        return jsonify({
            "draw": draw,
            "recordsTotal": total,
            "recordsFiltered": filtered,
            "data": data,
        })
    finally:
        conn.close()


@app.route("/api/search/csv")
def api_search_csv():
    """CSV download of current search results."""
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        tribe = request.args.get("tribe", "").strip()
        claim_type = request.args.get("claim_type", "").strip()
        agency_code = request.args.get("agency_code", "").strip()
        state = request.args.get("state", "").strip()
        name_search = request.args.get("name", "").strip()
        allotment_search = request.args.get("allotment", "").strip()
        date_from = request.args.get("date_from", "").strip()
        date_to = request.args.get("date_to", "").strip()

        conditions = []
        params = []

        if tribe:
            conditions.append("fr.tribe_identified = %s")
            params.append(tribe)
        if agency_code:
            conditions.append("fr.bia_agency_code = %s")
            params.append(agency_code)
        if state:
            conditions.append("fr.state = %s")
            params.append(state)
        add_claim_type_filter(claim_type, conditions, params)
        if name_search:
            conditions.append("fr.allottee_name ILIKE %s")
            params.append(f"%{name_search}%")
        if allotment_search:
            conditions.append("fr.allotment_number ILIKE %s")
            params.append(allotment_search)
        if date_from:
            conditions.append("ffp.patents_signature_date >= %s")
            params.append(date_from)
        if date_to:
            conditions.append("ffp.patents_signature_date <= %s")
            params.append(date_to)

        where = "WHERE " + " AND ".join(conditions) if conditions else ""

        sql = f"""
            SELECT
                fr.bia_agency_code,
                fr.case_number,
                fr.allottee_name,
                fr.tribe_identified,
                fr.allotment_number,
                fr.claim_type,
                fr.document_source,
                fr.state,
                STRING_AGG(DISTINCT ffp.glo_patentees, '; ') as glo_patentees,
                STRING_AGG(DISTINCT ffp.patents_accession_number, '; ') as patents_accession_number,
                MIN(ffp.patents_signature_date)::text as patents_signature_date,
                STRING_AGG(DISTINCT ffp.patents_document_class, '; ') as patents_document_class
            FROM federal_register_claims fr
            LEFT JOIN forced_fee_patents_rails ffp
                ON LTRIM(fr.case_number, '0') = LTRIM(ffp.case_number, '0')
                AND fr.allottee_name = ffp.fedreg_allottee
            {where}
            GROUP BY fr.id, fr.bia_agency_code, fr.case_number, fr.allottee_name, fr.tribe_identified,
                     fr.allotment_number, fr.claim_type, fr.document_source, fr.state
            ORDER BY fr.bia_agency_code, fr.case_number
        """
        cur.execute(sql, params)
        rows = cur.fetchall()

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "BIA Agency Code", "Case Number", "Allottee Name", "Tribe", "Allotment Number",
            "Claim Type", "Document Source", "GLO Patentee(s)",
            "Accession Number", "Patent Date", "Document Class", "State"
        ])
        for r in rows:
            writer.writerow([
                r["bia_agency_code"], r["case_number"], r["allottee_name"], r["tribe_identified"],
                r["allotment_number"], r["claim_type"], r["document_source"],
                r["glo_patentees"], r["patents_accession_number"],
                r["patents_signature_date"], r["patents_document_class"],
                r["state"],
            ])

        return Response(
            output.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment; filename=federal_register_claims.csv"}
        )
    finally:
        conn.close()


@app.route("/claim/<int:claim_id>")
def claim_detail(claim_id):
    """Individual claim page."""
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Get the claim
        cur.execute("""
            SELECT * FROM federal_register_claims WHERE id = %s
        """, (claim_id,))
        claim = cur.fetchone()
        if not claim:
            abort(404)

        # Get linked patents
        cur.execute("""
            SELECT
                ffp.*,
                fp.glo_url as fee_glo_url,
                fp.acres as fee_acres
            FROM forced_fee_patents_rails ffp
            LEFT JOIN fee_patents fp ON fp.accession_number = ffp.patents_accession_number
            WHERE LTRIM(ffp.case_number, '0') = LTRIM(%s, '0')
              AND ffp.fedreg_allottee = %s
            ORDER BY ffp.patents_signature_date
        """, (claim["case_number"], claim["allottee_name"]))
        patents = cur.fetchall()

        # Get parcels for linked patents (via allotment number + tribe)
        parcels = []
        if patents:
            # Use the first patent's tribe info to find parcels
            for p in patents:
                if p.get("patents_glo_tribe"):
                    cur.execute("""
                        SELECT DISTINCT
                            state, county, meridian,
                            township_number, township_direction,
                            range_number, range_direction,
                            section_number, aliquot_parts
                        FROM parcels_patents_by_tribe
                        WHERE glo_tribe_id = %s
                          AND indian_allotment_number = %s
                    """, (p["patents_glo_tribe"], p.get("fedreg_allotment", "")))
                    parcels.extend(cur.fetchall())

        # If no patent linkages found (e.g. secretarial transfers),
        # search rails_patents by allotment number + tribe
        allotment_patents = []
        if not patents and claim.get("allotment_number"):
            tribe = claim["tribe_identified"]
            allotment = claim["allotment_number"]
            cur.execute("""
                SELECT accession_number, signature_date, document_class,
                       indian_allotment_number, tribe_normalized, state,
                       total_acres as acres, remarks, NULL as glo_url,
                       CASE WHEN document_class IN (
                           'Indian Fee Patent', 'Indian Homestead Fee Patent',
                           'Serial Land Patent', 'State Land Patent'
                       ) THEN 'fee' ELSE 'trust' END as patent_type
                FROM rails_patents
                WHERE indian_allotment_number = %s
                  AND tribe_normalized = %s
                ORDER BY signature_date
            """, (allotment, tribe))
            allotment_patents = cur.fetchall()

        # Get trust-to-fee linkages if we have fee accession numbers
        trust_links = []
        for p in patents:
            if p.get("patents_accession_number"):
                cur.execute("""
                    SELECT * FROM trust_fee_linkages
                    WHERE fee_accession = %s
                """, (p["patents_accession_number"],))
                trust_links.extend(cur.fetchall())

        # Look up BLM patent objectids for cross-linking
        blm_patent_ids = {}
        for p in patents:
            acc = p.get("patents_accession_number")
            if acc:
                cur.execute("""
                    SELECT objectid FROM blm_allotment_patents
                    WHERE accession_number = %s LIMIT 1
                """, (acc,))
                row = cur.fetchone()
                if row:
                    blm_patent_ids[acc] = row["objectid"]

        # Name-based patent search: when no verified linkage and no allotment match,
        # search all_patents by the allottee's name to surface possible matches.
        name_matched_patents = []
        if not patents and not allotment_patents and claim.get("allottee_name"):
            fr_name = claim["allottee_name"].strip()
            if fr_name and len(fr_name) > 2 and fr_name not in ("TRIBAL", "NA", "N/A"):
                cur.execute("""
                    SELECT id, objectid, full_name, preferred_name,
                           indian_allotment_number, authority, accession_number,
                           signature_date, document_code, has_plss_geometry
                    FROM all_patents
                    WHERE full_name ILIKE %s
                    ORDER BY signature_date
                    LIMIT 20
                """, (f"%{fr_name}%",))
                name_matched_patents = cur.fetchall()
                # Add BLM objectids for name-matched patents
                for p in name_matched_patents:
                    acc = p.get("accession_number")
                    if acc and acc not in blm_patent_ids:
                        if p.get("objectid"):
                            blm_patent_ids[acc] = p["objectid"]

        return render_template(
            "claim.html",
            claim=claim,
            patents=patents,
            allotment_patents=allotment_patents,
            name_matched_patents=name_matched_patents,
            parcels=parcels,
            trust_links=trust_links,
            blm_patent_ids=blm_patent_ids,
            slugify=slugify,
            glo_url=glo_url,
            linkify_remarks=linkify_remarks,
        )
    finally:
        conn.close()


@app.route("/tribe/<tribe_slug>")
def tribe_detail(tribe_slug):
    """Tribe landing page."""
    tribe_name = unslugify_tribe(tribe_slug)
    if not tribe_name:
        abort(404)

    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Agency codes for this tribe
        cur.execute("""
            SELECT DISTINCT bia_agency_code
            FROM federal_register_claims
            WHERE tribe_identified = %s
            ORDER BY bia_agency_code
        """, (tribe_name,))
        agency_codes = [row["bia_agency_code"] for row in cur.fetchall()]

        # Summary stats
        cur.execute("""
            SELECT COUNT(*) as total_claims
            FROM federal_register_claims
            WHERE tribe_identified = %s
        """, (tribe_name,))
        stats = cur.fetchone()

        # Date range from linked patents
        cur.execute("""
            SELECT
                MIN(ffp.patents_signature_date) as earliest,
                MAX(ffp.patents_signature_date) as latest,
                COUNT(DISTINCT fr.id) as linked_count
            FROM federal_register_claims fr
            JOIN forced_fee_patents_rails ffp
                ON LTRIM(fr.case_number, '0') = LTRIM(ffp.case_number, '0')
                AND fr.allottee_name = ffp.fedreg_allottee
            WHERE fr.tribe_identified = %s
        """, (tribe_name,))
        date_info = cur.fetchone()

        # Timeline data: all fee patents by year + subset linked to FR claims
        cur.execute("""
            SELECT
                all_patents.yr,
                all_patents.total as total_patents,
                COALESCE(linked.linked_count, 0) as linked_to_claims
            FROM (
                SELECT EXTRACT(YEAR FROM signature_date::date)::int as yr,
                       COUNT(*) as total
                FROM fee_patents
                WHERE tribe_normalized = %s
                  AND signature_date IS NOT NULL AND signature_date != ''
                GROUP BY yr
            ) all_patents
            LEFT JOIN (
                SELECT
                    EXTRACT(YEAR FROM ffp.patents_signature_date)::int as yr,
                    COUNT(DISTINCT fr.id) as linked_count
                FROM federal_register_claims fr
                JOIN forced_fee_patents_rails ffp
                    ON LTRIM(fr.case_number, '0') = LTRIM(ffp.case_number, '0')
                    AND fr.allottee_name = ffp.fedreg_allottee
                WHERE fr.tribe_identified = %s
                  AND ffp.patents_signature_date IS NOT NULL
                GROUP BY yr
            ) linked ON all_patents.yr = linked.yr
            ORDER BY all_patents.yr
        """, (tribe_name, tribe_name))
        timeline_data = cur.fetchall()

        # Tribe-specific data notes
        tribe_notes = {}
        if tribe_name == "Omaha":
            tribe_notes["unlinked"] = """Of 889 Federal Register claims for the Omaha tribe, 358 are linked to BLM patent records and 531 are not.

<strong>Most unlinked claims are taxation cases, not forced fee patents.</strong> Of the 531 unlinked claims, 498 are TAXATION claims — cases where the allottee's land was seized or encumbered for unpaid property taxes. Only 22 are forced fee patents. The IATH hand-verification process that built the patent linkages focused on forced fee patent claims; taxation claims were largely not linked. Of 561 total Omaha taxation claims, only 63 (11%) have patent linkages.

<strong>The FR used Omaha-internal allotment suffixes the GLO did not.</strong> 514 of the 531 unlinked claims carry -N or -O suffixes on their allotment numbers (e.g., 103-O, 76-N). BLM patent records use the number without the suffix. The suffix convention was used by the FR publishers to distinguish multiple claims at the same allotment number — the Omaha Reservation had cases where different allottees held patents at the same numbered allotment for different parcels of land. The IATH reconciliation project has corrected 195 of these suffix mismatches; the remaining ~300 have not been crosswalked to GLO allotment numbers."""

        return render_template(
            "tribe.html",
            tribe_name=tribe_name,
            tribe_slug=tribe_slug,
            agency_codes=agency_codes,
            stats=stats,
            date_info=date_info,
            timeline_data=timeline_data,
            tribe_notes=tribe_notes,
            slugify=slugify,
        )
    finally:
        conn.close()


@app.route("/api/tribe/<tribe_slug>/claims")
def api_tribe_claims(tribe_slug):
    """JSON API for tribe claims table (DataTables)."""
    tribe_name = unslugify_tribe(tribe_slug)
    if not tribe_name:
        return jsonify({"error": "Tribe not found"}), 404

    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        draw = request.args.get("draw", 1, type=int)
        start = request.args.get("start", 0, type=int)
        length = request.args.get("length", 25, type=int)
        search_value = request.args.get("search[value]", "").strip()

        order_col_idx = request.args.get("order[0][column]", 0, type=int)
        order_dir = request.args.get("order[0][dir]", "asc")
        order_cols = ["fr.case_number", "fr.allottee_name", "fr.allotment_number",
                      "min_date", "patent_count"]
        order_col = order_cols[min(order_col_idx, len(order_cols) - 1)]
        if order_dir not in ("asc", "desc"):
            order_dir = "asc"

        conditions = ["fr.tribe_identified = %s"]
        params = [tribe_name]

        if search_value:
            conditions.append("""(
                fr.allottee_name ILIKE %s OR
                fr.case_number ILIKE %s OR
                fr.allotment_number ILIKE %s
            )""")
            sv = f"%{search_value}%"
            params.extend([sv, sv, sv])

        where = "WHERE " + " AND ".join(conditions)

        # Count
        cur.execute(f"""
            SELECT COUNT(*) as cnt FROM federal_register_claims fr {where}
        """, params[:1] if not search_value else params)
        total = cur.fetchone()["cnt"]

        cur.execute(f"""
            SELECT COUNT(DISTINCT fr.id)
            FROM federal_register_claims fr
            LEFT JOIN forced_fee_patents_rails ffp
                ON LTRIM(fr.case_number, '0') = LTRIM(ffp.case_number, '0')
                AND fr.allottee_name = ffp.fedreg_allottee
            {where}
        """, params)
        filtered = cur.fetchone()["count"]

        cur.execute(f"""
            SELECT
                fr.id,
                fr.case_number,
                fr.allottee_name,
                fr.allotment_number,
                MIN(ffp.patents_signature_date) as min_date,
                COUNT(ffp.id) as patent_count
            FROM federal_register_claims fr
            LEFT JOIN forced_fee_patents_rails ffp
                ON LTRIM(fr.case_number, '0') = LTRIM(ffp.case_number, '0')
                AND fr.allottee_name = ffp.fedreg_allottee
            {where}
            GROUP BY fr.id, fr.case_number, fr.allottee_name, fr.allotment_number
            ORDER BY {order_col} {order_dir}
            LIMIT %s OFFSET %s
        """, params + [length, start])
        rows = cur.fetchall()

        data = []
        for r in rows:
            sig_date = ""
            if r["min_date"]:
                sig_date = r["min_date"].strftime("%Y-%m-%d") if hasattr(r["min_date"], "strftime") else str(r["min_date"])
            data.append({
                "id": r["id"],
                "case_number": r["case_number"],
                "allottee_name": r["allottee_name"],
                "allotment_number": r["allotment_number"],
                "patent_date": sig_date,
                "patent_count": r["patent_count"],
            })

        return jsonify({
            "draw": draw,
            "recordsTotal": total,
            "recordsFiltered": filtered,
            "data": data,
        })
    finally:
        conn.close()


@app.route("/api/tribe/<tribe_slug>/csv")
def tribe_csv(tribe_slug):
    """CSV download for a tribe."""
    tribe_name = unslugify_tribe(tribe_slug)
    if not tribe_name:
        abort(404)

    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT
                fr.case_number, fr.allottee_name, fr.allotment_number,
                fr.claim_type, fr.document_source,
                ffp.glo_patentees, ffp.patents_accession_number,
                ffp.patents_signature_date, ffp.patents_document_class,
                ffp.patent_state
            FROM federal_register_claims fr
            LEFT JOIN forced_fee_patents_rails ffp
                ON LTRIM(fr.case_number, '0') = LTRIM(ffp.case_number, '0')
                AND fr.allottee_name = ffp.fedreg_allottee
            WHERE fr.tribe_identified = %s
            ORDER BY fr.case_number
        """, (tribe_name,))
        rows = cur.fetchall()

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "Case Number", "Allottee Name", "Allotment Number",
            "Claim Type", "Document Source", "GLO Patentee(s)",
            "Accession Number", "Patent Date", "Document Class", "State"
        ])
        for r in rows:
            writer.writerow([
                r["case_number"], r["allottee_name"], r["allotment_number"],
                r["claim_type"], r["document_source"], r["glo_patentees"],
                r["patents_accession_number"], r["patents_signature_date"],
                r["patents_document_class"], r["patent_state"],
            ])

        filename = f"{tribe_slug}_claims.csv"
        return Response(
            output.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
    finally:
        conn.close()


@app.route("/tribes")
def tribes_list():
    """List all tribes with claims."""
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT
                fr.tribe_identified,
                array_agg(DISTINCT fr.bia_agency_code ORDER BY fr.bia_agency_code) as agency_codes,
                COUNT(DISTINCT fr.id) as claim_count,
                COUNT(ffp.id) as patent_linkage_count,
                MIN(ffp.patents_signature_date) as earliest,
                MAX(ffp.patents_signature_date) as latest
            FROM federal_register_claims fr
            LEFT JOIN forced_fee_patents_rails ffp
                ON LTRIM(fr.case_number, '0') = LTRIM(ffp.case_number, '0')
                AND fr.allottee_name = ffp.fedreg_allottee
            GROUP BY fr.tribe_identified
            ORDER BY fr.tribe_identified
        """)
        tribes = cur.fetchall()
        return render_template("tribes.html", tribes=tribes, slugify=slugify)
    finally:
        conn.close()


@app.route("/timeline")
def timeline():
    """Timeline visualization page."""
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Get tribes for filter
        cur.execute("""
            SELECT DISTINCT tribe_identified
            FROM federal_register_claims
            ORDER BY tribe_identified
        """)
        tribes = [r["tribe_identified"] for r in cur.fetchall()]

        # Overall timeline data
        cur.execute("""
            SELECT
                EXTRACT(YEAR FROM ffp.patents_signature_date)::int as yr,
                COUNT(DISTINCT fr.id) as claim_count
            FROM federal_register_claims fr
            JOIN forced_fee_patents_rails ffp
                ON LTRIM(fr.case_number, '0') = LTRIM(ffp.case_number, '0')
                AND fr.allottee_name = ffp.fedreg_allottee
            WHERE ffp.patents_signature_date IS NOT NULL
            GROUP BY yr
            ORDER BY yr
        """)
        timeline_data = cur.fetchall()

        return render_template("timeline.html", tribes=tribes,
                               timeline_data=timeline_data, slugify=slugify)
    finally:
        conn.close()


@app.route("/api/timeline")
def api_timeline():
    """JSON API for timeline data, optionally filtered by tribe."""
    tribe = request.args.get("tribe", "").strip()

    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        conditions = ["ffp.patents_signature_date IS NOT NULL"]
        params = []
        if tribe:
            conditions.append("fr.tribe_identified = %s")
            params.append(tribe)

        where = "WHERE " + " AND ".join(conditions)

        cur.execute(f"""
            SELECT
                EXTRACT(YEAR FROM ffp.patents_signature_date)::int as yr,
                COUNT(DISTINCT fr.id) as claim_count
            FROM federal_register_claims fr
            JOIN forced_fee_patents_rails ffp
                ON LTRIM(fr.case_number, '0') = LTRIM(ffp.case_number, '0')
                AND fr.allottee_name = ffp.fedreg_allottee
            {where}
            GROUP BY yr
            ORDER BY yr
        """, params)
        data = cur.fetchall()

        return jsonify([{"year": r["yr"], "count": r["claim_count"]} for r in data])
    finally:
        conn.close()


@app.route("/patents")
def patents_index():
    """Browse / search all allotment patents (285,870 from Rails DB + BLM)."""
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT preferred_name FROM all_patents WHERE preferred_name IS NOT NULL AND preferred_name != '' ORDER BY preferred_name")
        tribes = [r[0] for r in cur.fetchall()]
        cur.execute("SELECT DISTINCT state FROM all_patents WHERE state IS NOT NULL AND state != '' ORDER BY state")
        states = [r[0] for r in cur.fetchall()]
        return render_template("patents.html", tribes=tribes, states=states)
    finally:
        conn.close()


FEE_AUTHORITIES = (
    'Indian Fee Patent', 'Indian Fee Patent (Heir)', 'Indian Fee Patent (IRA)',
    'Indian Fee Patent (Non-IRA)', 'Indian Fee Patent-Misc.',
    'Indian Fee Patent-Term or Non', 'Indian Homestead Fee Patent',
    'Indian Trust to Fee',
)

TRUST_AUTHORITIES = (
    'Indian Trust Patent', 'Indian Trust Patent (Wind R)',
    'Indian Homestead Trust', 'Indian Reissue Trust',
    'Indian Allotment - General', 'Indian Allotment in Nat. Forest',
    'Indian Allotment-Wyandotte', 'Indian Partition',
)


@app.route("/api/patents")
def api_patents():
    """JSON API for patent search (DataTables server-side). Queries all_patents (285,870)."""
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        draw = request.args.get("draw", 1, type=int)
        start = request.args.get("start", 0, type=int)
        length = request.args.get("length", 25, type=int)

        name_search = request.args.get("name", "").strip()
        allotment = request.args.get("allotment", "").strip()
        tribe = request.args.get("tribe", "").strip()
        state = request.args.get("state", "").strip()
        patent_type = request.args.get("patent_type", "").strip()
        date_from = request.args.get("date_from", "").strip()
        date_to = request.args.get("date_to", "").strip()
        mappable = request.args.get("mappable", "").strip()

        order_col_idx = request.args.get("order[0][column]", 0, type=int)
        order_dir = request.args.get("order[0][dir]", "asc")
        order_cols = ["full_name", "preferred_name", "state",
                      "indian_allotment_number", "authority", "signature_date", "forced_fee", "has_plss_geometry"]
        order_col = order_cols[min(order_col_idx, len(order_cols) - 1)]
        if order_dir not in ("asc", "desc"):
            order_dir = "asc"

        conditions = []
        params = []

        if name_search:
            conditions.append("full_name ILIKE %s")
            params.append(f"%{name_search}%")
        if allotment:
            conditions.append("indian_allotment_number ILIKE %s")
            params.append(allotment)
        if tribe:
            conditions.append("preferred_name = %s")
            params.append(tribe)
        if state:
            conditions.append("state = %s")
            params.append(state)
        if patent_type == "fee":
            conditions.append("authority IN %s")
            params.append(FEE_AUTHORITIES)
        elif patent_type == "trust":
            conditions.append("authority IN %s")
            params.append(TRUST_AUTHORITIES)
        elif patent_type == "forced":
            conditions.append("""accession_number IN (
                SELECT ffp.patents_accession_number FROM forced_fee_patents_rails ffp
                JOIN federal_register_claims fr
                  ON LTRIM(fr.case_number, '0') = LTRIM(ffp.case_number, '0')
                  AND fr.allottee_name = ffp.fedreg_allottee
                WHERE fr.claim_type ILIKE '%%FORCED FEE%%'
            )""")
        if date_from:
            conditions.append("signature_date >= %s")
            params.append(date_from)
        if date_to:
            conditions.append("signature_date <= %s")
            params.append(date_to)
        if mappable == "yes":
            conditions.append("has_plss_geometry = true")
        elif mappable == "no":
            conditions.append("has_plss_geometry = false")

        where = "WHERE " + " AND ".join(conditions) if conditions else ""

        cur.execute("SELECT COUNT(*) as cnt FROM all_patents")
        total = cur.fetchone()["cnt"]

        cur.execute(f"SELECT COUNT(*) as cnt FROM all_patents {where}", params)
        filtered = cur.fetchone()["cnt"]

        cur.execute(f"""
            SELECT id, objectid, full_name, preferred_name, state,
                   indian_allotment_number, authority, signature_date,
                   has_plss_geometry,
                   accession_number IN (
                       SELECT ffp.patents_accession_number FROM forced_fee_patents_rails ffp
                       JOIN federal_register_claims fr
                         ON LTRIM(fr.case_number, '0') = LTRIM(ffp.case_number, '0')
                         AND fr.allottee_name = ffp.fedreg_allottee
                       WHERE fr.claim_type ILIKE '%%FORCED FEE%%'
                   ) as is_forced_fee
            FROM all_patents
            {where}
            ORDER BY {order_col} {order_dir} NULLS LAST
            LIMIT %s OFFSET %s
        """, params + [length, start])
        rows = cur.fetchall()

        data = []
        for r in rows:
            sig_date = ""
            if r["signature_date"]:
                sig_date = r["signature_date"].strftime("%Y-%m-%d") if hasattr(r["signature_date"], "strftime") else str(r["signature_date"])
            data.append({
                "id": r["id"],
                "objectid": r["objectid"],
                "full_name": r["full_name"] or "",
                "preferred_name": r["preferred_name"] or "",
                "state": r["state"] or "",
                "allotment_number": r["indian_allotment_number"] or "",
                "authority": r["authority"] or "",
                "signature_date": sig_date,
                "forced_fee": r["is_forced_fee"],
                "has_plss_geometry": r["has_plss_geometry"],
            })

        return jsonify({
            "draw": draw,
            "recordsTotal": total,
            "recordsFiltered": filtered,
            "data": data,
        })
    finally:
        conn.close()


@app.route("/api/patents/csv")
def api_patents_csv():
    """CSV download of patent search results from all_patents (285,870)."""
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        name_search = request.args.get("name", "").strip()
        allotment = request.args.get("allotment", "").strip()
        tribe = request.args.get("tribe", "").strip()
        state = request.args.get("state", "").strip()
        patent_type = request.args.get("patent_type", "").strip()
        date_from = request.args.get("date_from", "").strip()
        date_to = request.args.get("date_to", "").strip()
        mappable = request.args.get("mappable", "").strip()

        conditions = []
        params = []

        if name_search:
            conditions.append("full_name ILIKE %s")
            params.append(f"%{name_search}%")
        if allotment:
            conditions.append("indian_allotment_number ILIKE %s")
            params.append(allotment)
        if tribe:
            conditions.append("preferred_name = %s")
            params.append(tribe)
        if state:
            conditions.append("state = %s")
            params.append(state)
        if patent_type == "fee":
            conditions.append("authority IN %s")
            params.append(FEE_AUTHORITIES)
        elif patent_type == "trust":
            conditions.append("authority IN %s")
            params.append(TRUST_AUTHORITIES)
        elif patent_type == "forced":
            conditions.append("""accession_number IN (
                SELECT ffp.patents_accession_number FROM forced_fee_patents_rails ffp
                JOIN federal_register_claims fr
                  ON LTRIM(fr.case_number, '0') = LTRIM(ffp.case_number, '0')
                  AND fr.allottee_name = ffp.fedreg_allottee
                WHERE fr.claim_type ILIKE '%%FORCED FEE%%'
            )""")
        if date_from:
            conditions.append("signature_date >= %s")
            params.append(date_from)
        if date_to:
            conditions.append("signature_date <= %s")
            params.append(date_to)
        if mappable == "yes":
            conditions.append("has_plss_geometry = true")
        elif mappable == "no":
            conditions.append("has_plss_geometry = false")

        where = "WHERE " + " AND ".join(conditions) if conditions else ""

        cur.execute(f"""
            SELECT accession_number, full_name, preferred_name, state, county,
                   indian_allotment_number, authority, signature_date, forced_fee,
                   document_class, total_acres, has_plss_geometry,
                   meridian, township_number, township_direction,
                   range_number, range_direction, section_number, aliquot_parts, remarks
            FROM all_patents
            {where}
            ORDER BY preferred_name, full_name
        """, params)
        rows = cur.fetchall()

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "Accession Number", "Full Name", "Tribe", "State", "County",
            "Allotment Number", "Authority", "Signature Date", "Forced Fee",
            "Document Class", "Acres", "Mappable",
            "Meridian", "Township", "Township Dir", "Range", "Range Dir",
            "Section", "Aliquot Parts", "Remarks"
        ])
        for r in rows:
            sig_date = ""
            if r["signature_date"]:
                sig_date = r["signature_date"].strftime("%Y-%m-%d") if hasattr(r["signature_date"], "strftime") else str(r["signature_date"])
            writer.writerow([
                r["accession_number"], r["full_name"], r["preferred_name"],
                r["state"], r["county"], r["indian_allotment_number"],
                r["authority"], sig_date, r["forced_fee"],
                r["document_class"], r["total_acres"],
                "Yes" if r["has_plss_geometry"] else "No",
                r["meridian"], r["township_number"], r["township_direction"],
                r["range_number"], r["range_direction"], r["section_number"],
                r["aliquot_parts"], r["remarks"],
            ])

        return Response(
            output.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment; filename=allotment_patents.csv"}
        )
    finally:
        conn.close()


@app.route("/patent/<int:objectid>")
def patent_detail(objectid):
    """Individual patent record page. Tries BLM objectid first, then rails_patents id."""
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Check if caller specified this is a rails-only patent (no BLM record)
        source = request.args.get("src", "")

        if source == "rails":
            # Go directly to all_patents by rails id — skip BLM lookup
            cur.execute("SELECT * FROM all_patents WHERE id = %s AND has_plss_geometry = false LIMIT 1", (objectid,))
            patent = cur.fetchone()
        else:
            cur.execute("SELECT * FROM blm_allotment_patents WHERE objectid = %s", (objectid,))
            patent = cur.fetchone()

            # BLM table lacks document_code; look it up from rails_patents for GLO link
            if patent and patent.get("accession_number"):
                cur.execute("SELECT document_code FROM rails_patents WHERE accession_number = %s LIMIT 1",
                            (patent["accession_number"],))
                dc_row = cur.fetchone()
                if dc_row and dc_row.get("document_code"):
                    patent = dict(patent)
                    patent["document_code"] = dc_row["document_code"]

            # If not found in BLM table, try as a rails_patents id
            if not patent:
                cur.execute("SELECT * FROM all_patents WHERE id = %s LIMIT 1", (objectid,))
                patent = cur.fetchone()
            if not patent:
                abort(404)

        # Cross-link: check if this patent's accession_number is in forced_fee_patents_rails
        linked_claim = None
        if patent.get("accession_number"):
            cur.execute("""
                SELECT fr.id, fr.allottee_name, fr.case_number, fr.tribe_identified
                FROM forced_fee_patents_rails ffp
                JOIN federal_register_claims fr
                    ON LTRIM(fr.case_number, '0') = LTRIM(ffp.case_number, '0')
                    AND fr.allottee_name = ffp.fedreg_allottee
                WHERE ffp.patents_accession_number = %s
                LIMIT 1
            """, (patent["accession_number"],))
            linked_claim = cur.fetchone()

        # Name-based claim search: when no verified linkage exists,
        # search federal_register_claims by the patentee's name.
        name_matched_claims = []
        if not linked_claim and patent.get("full_name"):
            pat_name = patent["full_name"].strip()
            if pat_name and len(pat_name) > 2:
                cur.execute("""
                    SELECT id, allottee_name, tribe_identified, allotment_number,
                           claim_type, case_number
                    FROM federal_register_claims
                    WHERE allottee_name ILIKE %s
                    ORDER BY allottee_name, allotment_number
                    LIMIT 10
                """, (f"%{pat_name}%",))
                name_matched_claims = cur.fetchall()

        # Cancelled-patent research metadata (legal authority, CCF, dates) from
        # the cancelled_patent_research table.
        cancelled_research = None
        if patent.get("accession_number"):
            cur.execute("""
                SELECT name, allotment_number, tribe_reservation, state,
                       reason_for_cancellation, reason_normalized,
                       cancellation_date, fee_patent_date, ccf_number,
                       gender, carlisle_yn, comments
                FROM cancelled_patent_research
                WHERE patent_number = %s
                LIMIT 1
            """, (patent["accession_number"],))
            cancelled_research = cur.fetchone()

        # BIA file references on this patent (from transcribed remarks). For each
        # ref also count how many OTHER patents share it -- that's the cluster size
        # users click through to.
        file_refs = []
        if patent.get("accession_number"):
            cur.execute("""
                SELECT
                    pfr.id            AS ref_id,
                    pfr.letter_number,
                    pfr.year,
                    pfr.year_raw,
                    pfr.nara_verified,
                    pfr.nara_url,
                    pfr.decimal_class,
                    pfr.agency,
                    pfrl.context_label,
                    pfrl.matched_text,
                    pfrl.source_table,
                    (
                        SELECT COUNT(DISTINCT patent_accession) - 1
                        FROM patent_file_ref_links
                        WHERE file_ref_id = pfr.id
                    ) AS other_patent_count
                FROM patent_file_ref_links pfrl
                JOIN patent_file_references pfr ON pfr.id = pfrl.file_ref_id
                WHERE pfrl.patent_accession = %s
                ORDER BY pfr.year, pfr.letter_number
            """, (patent["accession_number"],))
            file_refs = cur.fetchall()

        # Trust→fee linkages recovered from remarks regex parsing
        # (trust_fee_linkages_recovered, 57,019 rows). If this patent is the
        # TRUST side, show fee patents it points to. If it's the FEE side, show
        # the trust patent(s) it was recovered from.
        recovered_as_trust = []
        recovered_as_fee = []
        if patent.get("accession_number"):
            cur.execute("""
                SELECT tflr.fee_accession AS other_accession,
                       tflr.match_type, tflr.name_consistent,
                       tflr.date_gap_years, tflr.fee_date AS other_date,
                       tflr.fee_authority AS other_authority,
                       tflr.fee_state AS other_state,
                       tflr.extracted_raw,
                       tflr.source,
                       blm.objectid AS other_objectid,
                       rp.id AS other_rails_id,
                       COALESCE(blm.full_name, rp.full_name) AS other_full_name
                FROM trust_fee_linkages_recovered tflr
                LEFT JOIN blm_allotment_patents blm ON blm.accession_number = tflr.fee_accession
                LEFT JOIN rails_patents rp           ON rp.accession_number  = tflr.fee_accession
                WHERE tflr.trust_accession = %s
                  AND tflr.trust_accession IS DISTINCT FROM tflr.fee_accession
                ORDER BY tflr.fee_date NULLS LAST, tflr.fee_accession
            """, (patent["accession_number"],))
            recovered_as_trust = cur.fetchall()

            cur.execute("""
                SELECT tflr.trust_accession AS other_accession,
                       tflr.match_type, tflr.name_consistent,
                       tflr.date_gap_years, tflr.trust_date AS other_date,
                       NULL::text AS other_authority,
                       NULL::text AS other_state,
                       tflr.extracted_raw,
                       tflr.source,
                       blm.objectid AS other_objectid,
                       rp.id AS other_rails_id,
                       COALESCE(blm.full_name, rp.full_name) AS other_full_name
                FROM trust_fee_linkages_recovered tflr
                LEFT JOIN blm_allotment_patents blm ON blm.accession_number = tflr.trust_accession
                LEFT JOIN rails_patents rp           ON rp.accession_number  = tflr.trust_accession
                WHERE tflr.fee_accession = %s
                  AND tflr.trust_accession IS DISTINCT FROM tflr.fee_accession
                ORDER BY tflr.trust_date NULLS LAST, tflr.trust_accession
            """, (patent["accession_number"],))
            recovered_as_fee = cur.fetchall()

        return render_template(
            "patent.html",
            patent=patent,
            linked_claim=linked_claim,
            name_matched_claims=name_matched_claims,
            cancelled_research=cancelled_research,
            file_refs=file_refs,
            recovered_as_trust=recovered_as_trust,
            recovered_as_fee=recovered_as_fee,
            glo_url=glo_url,
            slugify=slugify,
        )
    finally:
        conn.close()


@app.route("/file_refs")
def file_refs_index():
    """Index of every BIA file reference parsed from patent remarks + BLM's
    structured CCF columns. Page chrome only — table data is loaded via the
    /api/file_refs JSON endpoint (server-side DataTables) because the corpus
    is ~66K refs and rendering them all server-side would be too heavy.
    """
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT
                COUNT(*) AS total_refs,
                COUNT(*) FILTER (WHERE nara_verified) AS verified_refs,
                COUNT(*) FILTER (WHERE io_labeled = 'yes')     AS io_yes,
                COUNT(*) FILTER (WHERE io_labeled = 'no')      AS io_no,
                COUNT(*) FILTER (WHERE io_labeled = 'mixed')   AS io_mixed,
                COUNT(*) FILTER (WHERE io_labeled = 'unknown') AS io_unknown,
                (SELECT MAX(patent_count) FROM patent_file_references)                       AS largest_cluster,
                (SELECT COUNT(DISTINCT patent_accession) FROM patent_file_ref_links)         AS distinct_patents
            FROM patent_file_references
        """)
        totals = cur.fetchone()
        return render_template("file_refs.html", totals=totals)
    finally:
        conn.close()


@app.route("/api/file_refs")
def api_file_refs():
    """JSON API for the file-refs DataTable (server-side). Reads pre-computed
    aggregate columns on patent_file_references (populated by
    scripts/compute_file_ref_aggregates.py) for fast paged lookups."""
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        draw     = request.args.get("draw", 1, type=int)
        start    = request.args.get("start", 0, type=int)
        length   = request.args.get("length", 50, type=int)
        if length <= 0 or length > 500:
            length = 50
        global_search = request.args.get("search[value]", "").strip()

        # Custom filters
        io_filter         = request.args.get("io_labeled", "").strip()      # yes|no|mixed|unknown|''
        era_filter        = request.args.get("era", "").strip()             # pre_1907|ccf_1907_1942|ccf_1943_1975|post_1975|''
        min_patents_str   = request.args.get("min_patents", "").strip()     # integer or ''
        tribe_or_state    = request.args.get("tribe_or_state", "").strip()  # free-text matched against state_list OR top_tribe

        # Sort column index → SQL column
        order_col_idx = request.args.get("order[0][column]", 2, type=int)
        order_dir     = request.args.get("order[0][dir]", "desc")
        order_cols = [
            "letter_number",        # 0: File Ref
            "year",                 # 1: Year
            "patent_count",         # 2: # Patents (default sort)
            "min_signature_date",   # 3: Date range
            "state_list",           # 4: States
            "top_tribe",            # 5: Top Tribe
            "io_labeled",           # 6: I.O. labeled
            "nara_verified",        # 7: NARA Verified
        ]
        order_col = order_cols[min(order_col_idx, len(order_cols) - 1)]
        if order_dir not in ("asc", "desc"):
            order_dir = "desc"

        conditions = []
        params = []

        if global_search:
            conditions.append(
                "(letter_number ILIKE %s OR year_raw ILIKE %s OR top_tribe ILIKE %s OR state_list ILIKE %s)"
            )
            needle = f"%{global_search}%"
            params += [needle, needle, needle, needle]

        if io_filter in ("yes", "no", "mixed", "unknown"):
            conditions.append("io_labeled = %s")
            params.append(io_filter)

        if era_filter == "pre_1907":
            conditions.append("year < 1907")
        elif era_filter == "ccf_1907_1942":
            conditions.append("year BETWEEN 1907 AND 1942")
        elif era_filter == "ccf_1943_1975":
            conditions.append("year BETWEEN 1943 AND 1975")
        elif era_filter == "post_1975":
            conditions.append("year > 1975")

        if min_patents_str:
            try:
                n = int(min_patents_str)
                if n > 0:
                    conditions.append("patent_count >= %s")
                    params.append(n)
            except ValueError:
                pass

        if tribe_or_state:
            conditions.append("(top_tribe ILIKE %s OR state_list ILIKE %s)")
            params += [f"%{tribe_or_state}%", f"%{tribe_or_state}%"]

        where = "WHERE " + " AND ".join(conditions) if conditions else ""

        cur.execute("SELECT COUNT(*) AS n FROM patent_file_references")
        records_total = cur.fetchone()["n"]

        cur.execute(f"SELECT COUNT(*) AS n FROM patent_file_references {where}", params)
        records_filtered = cur.fetchone()["n"]

        cur.execute(f"""
            SELECT id, letter_number, year, year_raw,
                   patent_count, state_list, top_tribe, top_context_label,
                   min_signature_date, max_signature_date,
                   io_labeled, nara_verified, nara_url
            FROM patent_file_references
            {where}
            ORDER BY {order_col} {order_dir} NULLS LAST, letter_number, year_raw
            LIMIT %s OFFSET %s
        """, params + [length, start])
        rows = cur.fetchall()

        data = []
        for r in rows:
            def fmt_date(d):
                if not d: return ""
                return d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d)
            data.append({
                "ref":               f"{r['letter_number']}-{r['year_raw']}",
                "letter_number":     r["letter_number"],
                "year_raw":          r["year_raw"],
                "year":              r["year"],
                "patent_count":      r["patent_count"] or 0,
                "state_list":        r["state_list"] or "",
                "top_tribe":         r["top_tribe"] or "",
                "top_context_label": r["top_context_label"] or "",
                "min_date":          fmt_date(r["min_signature_date"]),
                "max_date":          fmt_date(r["max_signature_date"]),
                "io_labeled":        r["io_labeled"] or "",
                "nara_verified":     bool(r["nara_verified"]),
                "nara_url":          r["nara_url"] or "",
            })

        return jsonify({
            "draw": draw,
            "recordsTotal":    records_total,
            "recordsFiltered": records_filtered,
            "data": data,
        })
    finally:
        conn.close()


@app.route("/linkages")
def linkages_index():
    """Index page for trust→fee linkages recovered from BLM remarks text
    (table: trust_fee_linkages_recovered, 57K rows). Page chrome only — the
    actual table loads via /api/linkages (server-side DataTables)."""
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT
                COUNT(*)                                                     AS total,
                COUNT(DISTINCT trust_accession)                              AS distinct_trust,
                COUNT(DISTINCT fee_accession)                                AS distinct_fee,
                COUNT(*) FILTER (WHERE name_consistent)                      AS name_consistent_n,
                COUNT(*) FILTER (WHERE match_type = 'exact')                 AS n_exact,
                COUNT(*) FILTER (WHERE match_type = 'normalized')            AS n_normalized,
                COUNT(*) FILTER (WHERE match_type LIKE 'fuzzy%%')            AS n_fuzzy,
                COUNT(*) FILTER (WHERE match_type = 'parcel_name')           AS n_parcel,
                COUNT(*) FILTER (WHERE source = 'remarks_regex_v2')          AS n_regex,
                COUNT(*) FILTER (WHERE source = 'parcel_match_v1')           AS n_parcel_src,
                COUNT(*) FILTER (WHERE source = 'vision_v5')                 AS n_vision,
                PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY date_gap_years)  AS median_gap_years
            FROM trust_fee_linkages_recovered
            WHERE trust_accession IS DISTINCT FROM fee_accession
        """)
        totals = cur.fetchone()
        return render_template("linkages.html", totals=totals)
    finally:
        conn.close()


@app.route("/api/linkages")
def api_linkages():
    """JSON API for the recovered-linkages DataTable (server-side)."""
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        draw    = request.args.get("draw", 1, type=int)
        start   = request.args.get("start", 0, type=int)
        length  = request.args.get("length", 50, type=int)
        if length <= 0 or length > 500:
            length = 50
        global_search = request.args.get("search[value]", "").strip()

        match_filter      = request.args.get("match_type", "").strip()       # exact|normalized|fuzzy|parcel_name|''
        state_filter      = request.args.get("state", "").strip()
        name_filter       = request.args.get("name_consistent", "").strip()  # yes|no|''
        source_filter     = request.args.get("source", "").strip()           # remarks_regex_v2|parcel_match_v1|''
        min_gap_str       = request.args.get("min_gap", "").strip()
        max_gap_str       = request.args.get("max_gap", "").strip()

        order_col_idx = request.args.get("order[0][column]", 4, type=int)
        order_dir     = request.args.get("order[0][dir]", "asc")
        order_cols = [
            "trust_accession",   # 0
            "trust_date",        # 1
            "fee_accession",     # 2
            "fee_date",          # 3
            "date_gap_years",    # 4 (default)
            "match_type",        # 5
            "name_consistent",   # 6
            "fee_authority",     # 7
            "fee_state",         # 8
            "source",            # 9
        ]
        order_col = order_cols[min(order_col_idx, len(order_cols) - 1)]
        if order_dir not in ("asc", "desc"):
            order_dir = "asc"

        # Defense-in-depth: never return self-references even if one sneaks
        # past the DB CHECK constraint. IS DISTINCT FROM keeps vision_v5 rows
        # (fee_accession IS NULL) visible — plain <> would silently drop them.
        conditions = ["trust_accession IS DISTINCT FROM fee_accession"]
        params     = []

        if global_search:
            conditions.append(
                "(trust_accession ILIKE %s OR fee_accession ILIKE %s OR extracted_raw ILIKE %s)"
            )
            needle = f"%{global_search}%"
            params += [needle, needle, needle]

        if match_filter == "exact":
            conditions.append("match_type = 'exact'")
        elif match_filter == "normalized":
            conditions.append("match_type = 'normalized'")
        elif match_filter == "fuzzy":
            conditions.append("match_type LIKE 'fuzzy%%'")
        elif match_filter == "parcel_name":
            conditions.append("match_type = 'parcel_name'")

        if source_filter in ("remarks_regex_v2", "parcel_match_v1", "vision_v5"):
            conditions.append("source = %s")
            params.append(source_filter)

        if state_filter:
            conditions.append("fee_state ILIKE %s")
            params.append(f"%{state_filter}%")

        if name_filter == "yes":
            conditions.append("name_consistent = true")
        elif name_filter == "no":
            conditions.append("(name_consistent = false OR name_consistent IS NULL)")

        if min_gap_str:
            try:
                conditions.append("date_gap_years >= %s")
                params.append(int(min_gap_str))
            except ValueError:
                pass
        if max_gap_str:
            try:
                conditions.append("date_gap_years <= %s")
                params.append(int(max_gap_str))
            except ValueError:
                pass

        where = "WHERE " + " AND ".join(conditions) if conditions else ""

        cur.execute("SELECT COUNT(*) AS n FROM trust_fee_linkages_recovered")
        records_total = cur.fetchone()["n"]

        cur.execute(f"SELECT COUNT(*) AS n FROM trust_fee_linkages_recovered {where}", params)
        records_filtered = cur.fetchone()["n"]

        # Note: every column in `where` belongs to trust_fee_linkages_recovered
        # only; none of the JOINed tables expose the same names, so bare
        # references resolve unambiguously here.
        cur.execute(f"""
            SELECT tflr.trust_accession, tflr.fee_accession, tflr.match_type,
                   tflr.name_consistent, tflr.date_gap_years,
                   tflr.trust_date, tflr.fee_date,
                   tflr.fee_authority, tflr.fee_state, tflr.extracted_raw,
                   tflr.source,
                   blm_t.objectid AS trust_objectid,  rp_t.id AS trust_rails_id,
                   blm_f.objectid AS fee_objectid,    rp_f.id AS fee_rails_id
            FROM trust_fee_linkages_recovered tflr
            LEFT JOIN blm_allotment_patents blm_t ON blm_t.accession_number = tflr.trust_accession
            LEFT JOIN rails_patents          rp_t ON rp_t.accession_number  = tflr.trust_accession
            LEFT JOIN blm_allotment_patents blm_f ON blm_f.accession_number = tflr.fee_accession
            LEFT JOIN rails_patents          rp_f ON rp_f.accession_number  = tflr.fee_accession
            {where}
            ORDER BY tflr.{order_col} {order_dir} NULLS LAST, tflr.trust_accession, tflr.fee_accession
            LIMIT %s OFFSET %s
        """, params + [length, start])
        rows = cur.fetchall()

        def fmt_date(d):
            if not d: return ""
            return d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d)

        data = []
        for r in rows:
            data.append({
                "trust_accession":    r["trust_accession"],
                "trust_objectid":     r["trust_objectid"],
                "trust_rails_id":     r["trust_rails_id"],
                "trust_date":         fmt_date(r["trust_date"]),
                "fee_accession":      r["fee_accession"],
                "fee_objectid":       r["fee_objectid"],
                "fee_rails_id":       r["fee_rails_id"],
                "fee_date":           fmt_date(r["fee_date"]),
                "date_gap_years":     r["date_gap_years"],
                "match_type":         r["match_type"] or "",
                "name_consistent":    bool(r["name_consistent"]),
                "fee_authority":      r["fee_authority"] or "",
                "fee_state":          r["fee_state"] or "",
                "extracted_raw":      r["extracted_raw"] or "",
                "source":             r["source"] or "",
            })

        return jsonify({
            "draw": draw,
            "recordsTotal":    records_total,
            "recordsFiltered": records_filtered,
            "data": data,
        })
    finally:
        conn.close()


@app.route("/file_ref/<spec>")
def file_ref_detail(spec):
    """Cluster view: all patents that share a single BIA file reference (NNNNN-YY).

    URL form: /file_ref/6744-49  (letter-year, matching how refs appear in remarks).
    Accepts an integer alone too (the patent_file_references.id) as a fallback.
    """
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Parse spec
        if "-" in spec:
            letter, _, year_raw = spec.partition("-")
            cur.execute("""
                SELECT * FROM patent_file_references
                WHERE letter_number = %s AND year_raw = %s
                LIMIT 1
            """, (letter, year_raw))
        else:
            cur.execute("SELECT * FROM patent_file_references WHERE id = %s LIMIT 1", (spec,))
        ref = cur.fetchone()
        if not ref:
            abort(404)

        # Pull all patents linked to this ref, with BLM metadata where available.
        cur.execute("""
            SELECT
                pfrl.patent_accession,
                pfrl.context_label,
                pfrl.source_table,
                pfrl.matched_text,
                bap.objectid,
                bap.full_name,
                bap.preferred_name,
                bap.signature_date,
                bap.authority,
                bap.state,
                bap.county,
                bap.cancelled_doc,
                bap.forced_fee
            FROM patent_file_ref_links pfrl
            LEFT JOIN blm_allotment_patents bap
                ON bap.accession_number = pfrl.patent_accession
            WHERE pfrl.file_ref_id = %s
            ORDER BY bap.signature_date NULLS LAST, pfrl.patent_accession
        """, (ref["id"],))
        links = cur.fetchall()

        # Deduplicate by accession_number (one accession can have multiple labels)
        seen = set()
        patents = []
        label_counts = {}
        for r in links:
            label_counts[r["context_label"]] = label_counts.get(r["context_label"], 0) + 1
            if r["patent_accession"] in seen:
                continue
            seen.add(r["patent_accession"])
            patents.append(r)

        # Cohort aggregates
        from collections import Counter
        state_counts     = Counter((p["state"] or "—") for p in patents)
        tribe_counts     = Counter((p["preferred_name"] or "—") for p in patents)
        authority_counts = Counter((p["authority"] or "—") for p in patents)
        cancelled_count  = sum(1 for p in patents if p["cancelled_doc"] == "True")
        forced_count     = sum(1 for p in patents if p["forced_fee"] == "True")
        dates = [p["signature_date"] for p in patents if p["signature_date"]]
        date_range = (min(dates), max(dates)) if dates else (None, None)

        return render_template(
            "file_ref.html",
            ref=ref,
            patents=patents,
            n_patents=len(patents),
            label_counts=sorted(label_counts.items(), key=lambda kv: -kv[1]),
            state_counts=state_counts.most_common(),
            tribe_counts=tribe_counts.most_common(),
            authority_counts=authority_counts.most_common(),
            cancelled_count=cancelled_count,
            forced_count=forced_count,
            date_range=date_range,
            glo_url=glo_url,
        )
    finally:
        conn.close()


@app.route("/patents/timeline")
def patents_timeline():
    """Timeline of all fee patents from BLM dataset."""
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        cur.execute("SELECT DISTINCT preferred_name FROM blm_allotment_patents WHERE preferred_name IS NOT NULL ORDER BY preferred_name")
        tribes = [r["preferred_name"] for r in cur.fetchall()]

        cur.execute(f"""
            SELECT
                EXTRACT(YEAR FROM signature_date)::int as yr,
                COUNT(*) FILTER (WHERE authority IN {FEE_AUTHORITIES!r}) as fee_count,
                COUNT(*) FILTER (WHERE authority IN {TRUST_AUTHORITIES!r}) as trust_count,
                COUNT(*) FILTER (WHERE authority NOT IN {FEE_AUTHORITIES!r} AND authority NOT IN {TRUST_AUTHORITIES!r}) as other_count,
                COUNT(*) FILTER (WHERE forced_fee = 'True') as forced_count
            FROM blm_allotment_patents
            WHERE signature_date IS NOT NULL
            GROUP BY yr
            ORDER BY yr
        """)
        timeline_data = cur.fetchall()

        # Murray trust removal data (1948-1957)
        cur.execute("""
            SELECT year, SUM(acres_removed) as acres
            FROM murray_trust_removal
            WHERE area_office != 'Grand Total'
            GROUP BY year ORDER BY year
        """)
        murray_data = [{"year": r["year"], "acres_removed": float(r["acres"])} for r in cur.fetchall()]

        # Wilson annual land sales (1903-1934)
        cur.execute("""
            SELECT year, total_acres, total_tracts, total_proceeds,
                   original_acreage, inherited_acreage
            FROM wilson_annual_sales
            ORDER BY year
        """)
        wilson_data = [{"year": r["year"], "acres_sold": float(r["total_acres"]),
                        "tracts": int(r["total_tracts"]) if r["total_tracts"] else 0,
                        "proceeds": float(r["total_proceeds"]) if r["total_proceeds"] else 0,
                        "original_acres": float(r["original_acreage"]) if r["original_acreage"] else 0,
                        "inherited_acres": float(r["inherited_acreage"]) if r["inherited_acreage"] else 0,
                       } for r in cur.fetchall()]

        return render_template("patents_timeline.html", tribes=tribes,
                               timeline_data=timeline_data, murray_data=murray_data,
                               wilson_sales_data=wilson_data)
    finally:
        conn.close()


@app.route("/api/patents/timeline")
def api_patents_timeline():
    """JSON API for patent timeline, optionally filtered by tribe."""
    tribe = request.args.get("tribe", "").strip()

    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        conditions = ["signature_date IS NOT NULL"]
        params = []
        if tribe:
            conditions.append("preferred_name = %s")
            params.append(tribe)

        where = "WHERE " + " AND ".join(conditions)

        cur.execute(f"""
            SELECT
                EXTRACT(YEAR FROM signature_date)::int as yr,
                COUNT(*) FILTER (WHERE authority IN {FEE_AUTHORITIES!r}) as fee_count,
                COUNT(*) FILTER (WHERE authority IN {TRUST_AUTHORITIES!r}) as trust_count,
                COUNT(*) FILTER (WHERE authority NOT IN {FEE_AUTHORITIES!r} AND authority NOT IN {TRUST_AUTHORITIES!r}) as other_count,
                COUNT(*) FILTER (WHERE forced_fee = 'True') as forced_count
            FROM blm_allotment_patents
            {where}
            GROUP BY yr
            ORDER BY yr
        """, params)
        data = cur.fetchall()

        timeline = [{"year": r["yr"], "fee": r["fee_count"], "trust": r["trust_count"],
                      "other": r["other_count"], "forced": r.get("forced_count", 0)} for r in data]

        # Murray trust removal data (1948-1957) — acres removed from trust by year
        cur.execute("""
            SELECT year, SUM(acres_removed) as acres
            FROM murray_trust_removal
            WHERE area_office != 'Grand Total'
            GROUP BY year ORDER BY year
        """)
        murray = [{"year": r["year"], "acres_removed": float(r["acres"])} for r in cur.fetchall()]

        # Wilson annual land sales (1903-1934)
        cur.execute("""
            SELECT year, total_acres, total_tracts, total_proceeds,
                   original_acreage, inherited_acreage
            FROM wilson_annual_sales
            ORDER BY year
        """)
        wilson_sales = [{"year": r["year"], "acres_sold": float(r["total_acres"]),
                         "tracts": int(r["total_tracts"]) if r["total_tracts"] else 0,
                         "proceeds": float(r["total_proceeds"]) if r["total_proceeds"] else 0,
                         "original_acres": float(r["original_acreage"]) if r["original_acreage"] else 0,
                         "inherited_acres": float(r["inherited_acreage"]) if r["inherited_acreage"] else 0,
                        } for r in cur.fetchall()]

        return jsonify({"timeline": timeline, "murray": murray, "wilson_sales": wilson_sales})
    finally:
        conn.close()


@app.route("/sankey")
def sankey():
    """Sankey flow diagram: trust -> fee -> forced pathways."""
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT preferred_name FROM blm_allotment_patents WHERE preferred_name IS NOT NULL ORDER BY preferred_name")
        tribes = [r[0] for r in cur.fetchall()]
        return render_template("sankey.html", tribes=tribes)
    finally:
        conn.close()


@app.route("/api/sankey")
def api_sankey():
    """JSON API returning node/link data for the Sankey diagram."""
    tribe = request.args.get("tribe", "").strip()

    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Build WHERE clause for BLM patents
        blm_where = ""
        blm_params = []
        if tribe:
            blm_where = "AND preferred_name = %s"
            blm_params = [tribe]

        # Patent categories by authority (ignore forced_fee BLM flag — use FR claims as ground truth)
        cur.execute(f"""
            SELECT
                COUNT(*) FILTER (WHERE authority IN %s) as trust_count,
                COUNT(*) FILTER (WHERE authority IN %s) as fee_count,
                COUNT(*) FILTER (WHERE authority NOT IN %s AND authority NOT IN %s) as other_count
            FROM blm_allotment_patents
            WHERE TRUE {blm_where}
        """, [TRUST_AUTHORITIES, FEE_AUTHORITIES, TRUST_AUTHORITIES, FEE_AUTHORITIES] + blm_params)
        counts = cur.fetchone()
        trust_count = counts["trust_count"]
        fee_count = counts["fee_count"]
        other_count = counts["other_count"]

        # Trust-to-fee linkages
        link_where = ""
        link_params = []
        if tribe:
            link_where = "WHERE tribe_normalized = %s"
            link_params = [tribe]

        # Trust patents that were later converted to fee
        cur.execute(f"""
            SELECT COUNT(DISTINCT trust_accession) as cnt FROM trust_fee_linkages {link_where}
        """, link_params)
        trust_converted = cur.fetchone()["cnt"]
        trust_remained = trust_count - trust_converted

        # Fee patents with a known trust origin
        cur.execute(f"""
            SELECT COUNT(DISTINCT fee_accession) as cnt FROM trust_fee_linkages {link_where}
        """, link_params)
        fee_with_trust_origin = cur.fetchone()["cnt"]
        fee_direct = fee_count - fee_with_trust_origin

        # Federal Register claims counts
        fr_where = ""
        fr_params = []
        if tribe:
            # Try matching tribe name between FR claims and BLM patents
            fr_where = "WHERE fr.tribe_identified = %s"
            fr_params = [tribe]

        cur.execute(f"""
            SELECT
                COUNT(*) FILTER (WHERE fr.claim_type ILIKE '%%FORCED FEE%%') as forced_claims,
                COUNT(*) FILTER (WHERE fr.claim_type ILIKE '%%SECRETARIAL%%') as sec_claims
            FROM federal_register_claims fr
            {fr_where}
        """, fr_params)
        fr_row = cur.fetchone()
        fr_forced_claims = fr_row["forced_claims"]
        fr_sec_claims = fr_row["sec_claims"]

        # Linked FR claims (matched to BLM patents)
        cur.execute(f"""
            SELECT COUNT(DISTINCT fr.id) as cnt
            FROM federal_register_claims fr
            JOIN forced_fee_patents_rails ffp
                ON LTRIM(fr.case_number, '0') = LTRIM(ffp.case_number, '0')
                AND fr.allottee_name = ffp.fedreg_allottee
            {fr_where}
        """, fr_params)
        fr_linked = cur.fetchone()["cnt"]
        fr_total = fr_forced_claims + fr_sec_claims
        fr_unlinked = fr_total - fr_linked

        # Conversion timing and acreage stats from trust_fee_linkages
        link_and = link_where.replace('WHERE', 'AND') if link_where else ''
        cur.execute(f"""
            SELECT
                COUNT(*) as cnt,
                AVG(years_to_conversion) as avg_years,
                PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY years_to_conversion) as median_years,
                MIN(years_to_conversion) as min_years,
                MAX(years_to_conversion) as max_years,
                COUNT(*) FILTER (WHERE years_to_conversion < 10) as fast_conversions,
                COUNT(*) FILTER (WHERE years_to_conversion >= 10 AND years_to_conversion < 25) as medium_conversions,
                COUNT(*) FILTER (WHERE years_to_conversion >= 25) as slow_conversions
            FROM trust_fee_linkages
            WHERE years_to_conversion IS NOT NULL
                AND years_to_conversion >= 0
                AND years_to_conversion < 200
                {link_and}
        """, link_params)
        timing = cur.fetchone()

        # Acreage totals
        cur.execute(f"""
            SELECT
                ROUND(SUM(trust_acres)::numeric) as trust_acres,
                ROUND(SUM(fee_acres)::numeric) as fee_acres,
                ROUND(AVG(trust_acres)::numeric, 1) as avg_trust_acres,
                ROUND(AVG(fee_acres)::numeric, 1) as avg_fee_acres,
                COUNT(*) FILTER (WHERE fee_acres < trust_acres) as shrunk,
                COUNT(*) FILTER (WHERE fee_acres = trust_acres) as same,
                COUNT(*) FILTER (WHERE fee_acres > trust_acres) as grew
            FROM trust_fee_linkages
            {link_where}
        """, link_params)
        acreage = cur.fetchone()

        # Acreage by conversion speed
        cur.execute(f"""
            SELECT
                CASE
                    WHEN years_to_conversion < 10 THEN 'fast'
                    WHEN years_to_conversion < 25 THEN 'medium'
                    ELSE 'slow'
                END as speed,
                COUNT(*) as cnt,
                ROUND(SUM(trust_acres)::numeric) as trust_acres,
                ROUND(SUM(fee_acres)::numeric) as fee_acres
            FROM trust_fee_linkages
            WHERE years_to_conversion IS NOT NULL
                AND years_to_conversion >= 0
                AND years_to_conversion < 200
                {link_and}
            GROUP BY 1
        """, link_params)
        acreage_by_speed = {}
        for row in cur.fetchall():
            acreage_by_speed[row["speed"]] = {
                "count": row["cnt"],
                "trust_acres": int(row["trust_acres"]) if row["trust_acres"] else 0,
                "fee_acres": int(row["fee_acres"]) if row["fee_acres"] else 0,
            }

        # Top tribes by fee acreage (land that left trust protection)
        cur.execute(f"""
            SELECT tribe_normalized,
                COUNT(*) as cnt,
                ROUND(SUM(trust_acres)::numeric) as trust_acres,
                ROUND(SUM(fee_acres)::numeric) as fee_acres
            FROM trust_fee_linkages
            WHERE tribe_normalized IS NOT NULL AND tribe_normalized != ''
                {link_and}
            GROUP BY tribe_normalized
            ORDER BY SUM(fee_acres) DESC
            LIMIT 10
        """, link_params)
        top_tribes_acreage = []
        for row in cur.fetchall():
            top_tribes_acreage.append({
                "tribe": row["tribe_normalized"],
                "conversions": row["cnt"],
                "trust_acres": int(row["trust_acres"]) if row["trust_acres"] else 0,
                "fee_acres": int(row["fee_acres"]) if row["fee_acres"] else 0,
            })

        # Wilson Report 1934 baseline (if tribe selected)
        wilson_data = None
        if tribe:
            cur.execute("""
                SELECT reservation_name, original_area_acres, allotment_acreage,
                    land_alienated_acres, total_allotments_made,
                    living_total_acres, deceased_total_acres,
                    tribal_total_acres
                FROM wilson_table_vi
                WHERE blm_tribe_name = %s
            """, [tribe])
            wrow = cur.fetchone()
            if wrow:
                wilson_data = {
                    "reservation": wrow["reservation_name"],
                    "original_acres": int(wrow["original_area_acres"]) if wrow["original_area_acres"] else 0,
                    "allotment_acreage": int(wrow["allotment_acreage"]) if wrow["allotment_acreage"] else 0,
                    "land_alienated": int(wrow["land_alienated_acres"]) if wrow["land_alienated_acres"] else 0,
                    "allotments_1934": int(wrow["total_allotments_made"]) if wrow["total_allotments_made"] else 0,
                }

        # Murray Memorandum 1947-1957 data (if tribe selected)
        murray_data = None
        if tribe:
            cur.execute("""
                SELECT agency, area_office,
                    individual_acres_1947, individual_acres_1957,
                    individual_increase, individual_decrease,
                    tribal_acres_1947, tribal_acres_1957,
                    tribal_increase, tribal_decrease
                FROM murray_comparative
                WHERE blm_tribe_name = %s
            """, [tribe])
            mrow = cur.fetchone()
            if mrow:
                murray_data = {
                    "agency": mrow["agency"],
                    "area_office": mrow["area_office"],
                    "individual_1947": int(mrow["individual_acres_1947"]) if mrow["individual_acres_1947"] else 0,
                    "individual_1957": int(mrow["individual_acres_1957"]) if mrow["individual_acres_1957"] else 0,
                    "individual_loss": int(mrow["individual_decrease"]) if mrow["individual_decrease"] else 0,
                    "individual_gain": int(mrow["individual_increase"]) if mrow["individual_increase"] else 0,
                    "tribal_1947": int(mrow["tribal_acres_1947"]) if mrow["tribal_acres_1947"] else 0,
                    "tribal_1957": int(mrow["tribal_acres_1957"]) if mrow["tribal_acres_1957"] else 0,
                }
                # Also get transaction count and total acres removed
                cur.execute("""
                    SELECT SUM(transaction_count) as total_transactions
                    FROM murray_transactions
                    WHERE blm_tribe_name = %s
                """, [tribe])
                txn = cur.fetchone()
                if txn and txn["total_transactions"]:
                    murray_data["transactions"] = int(txn["total_transactions"])
                cur.execute("""
                    SELECT acres_removed FROM murray_agency_removal
                    WHERE blm_tribe_name = %s
                """, [tribe])
                rem = cur.fetchone()
                if rem and rem["acres_removed"]:
                    murray_data["acres_removed"] = int(rem["acres_removed"])

        total = trust_count + fee_count + other_count

        # FR forced fee claims as sub-flow of Fee
        # Remaining fee = fee patents not accounted for by FR claims
        fee_other = fee_count - fr_forced_claims if fr_forced_claims < fee_count else 0

        # Build Sankey nodes and links
        nodes = [
            {"id": "all", "label": f"All Patents ({total:,})"},
            {"id": "trust", "label": f"Trust ({trust_count:,})"},
            {"id": "fee", "label": f"Fee ({fee_count:,})"},
            {"id": "other", "label": f"Other ({other_count:,})"},
            {"id": "trust_remained", "label": f"Remained in Trust ({trust_remained:,})"},
            {"id": "trust_converted", "label": f"Later Converted ({trust_converted:,})"},
            {"id": "fee_from_trust", "label": f"From Trust ({fee_with_trust_origin:,})"},
            {"id": "fee_direct", "label": f"Direct Fee ({fee_direct:,})"},
        ]

        links = [
            {"source": "all", "target": "trust", "value": trust_count},
            {"source": "all", "target": "fee", "value": fee_count},
            {"source": "all", "target": "other", "value": other_count},
            {"source": "trust", "target": "trust_remained", "value": trust_remained},
            {"source": "trust", "target": "trust_converted", "value": trust_converted},
            {"source": "fee", "target": "fee_from_trust", "value": fee_with_trust_origin},
            {"source": "fee", "target": "fee_direct", "value": fee_direct},
        ]

        # Add FR forced fee claims as sub-flow of Fee (if any)
        if fr_forced_claims > 0:
            nodes.append({"id": "fr_forced", "label": f"FR Forced Fee Claims ({fr_forced_claims:,})"})
            nodes.append({"id": "fee_other", "label": f"Other Fee ({fee_other:,})"})
            links.append({"source": "fee", "target": "fr_forced", "value": fr_forced_claims})
            links.append({"source": "fee", "target": "fee_other", "value": fee_other})

        # Remove zero-value links and their orphan nodes
        links = [l for l in links if l["value"] > 0]
        used_ids = set()
        for l in links:
            used_ids.add(l["source"])
            used_ids.add(l["target"])
        nodes = [n for n in nodes if n["id"] in used_ids]

        return jsonify({
            "nodes": nodes,
            "links": links,
            "stats": {
                "total": total,
                "trust": trust_count,
                "trust_remained": trust_remained,
                "trust_converted": trust_converted,
                "fee": fee_count,
                "fee_with_trust_origin": fee_with_trust_origin,
                "fee_direct": fee_direct,
                "other": other_count,
                "fr_total": fr_total,
                "fr_forced_claims": fr_forced_claims,
                "fr_sec_claims": fr_sec_claims,
                "fr_linked": fr_linked,
                "fr_unlinked": fr_unlinked,
                "timing": {
                    "count": timing["cnt"],
                    "avg_years": round(timing["avg_years"], 1) if timing["avg_years"] else None,
                    "median_years": round(timing["median_years"], 1) if timing["median_years"] else None,
                    "min_years": round(timing["min_years"], 1) if timing["min_years"] is not None else None,
                    "max_years": round(timing["max_years"], 1) if timing["max_years"] is not None else None,
                    "fast": timing["fast_conversions"],
                    "medium": timing["medium_conversions"],
                    "slow": timing["slow_conversions"],
                } if timing["cnt"] > 0 else None,
                "acreage": {
                    "trust_acres": int(acreage["trust_acres"]) if acreage["trust_acres"] else 0,
                    "fee_acres": int(acreage["fee_acres"]) if acreage["fee_acres"] else 0,
                    "avg_trust_acres": float(acreage["avg_trust_acres"]) if acreage["avg_trust_acres"] else 0,
                    "avg_fee_acres": float(acreage["avg_fee_acres"]) if acreage["avg_fee_acres"] else 0,
                    "shrunk": acreage["shrunk"],
                    "same": acreage["same"],
                    "grew": acreage["grew"],
                    "by_speed": acreage_by_speed,
                    "top_tribes": top_tribes_acreage,
                } if acreage["trust_acres"] else None,
                "wilson": wilson_data,
                "murray": murray_data,
            },
        })
    finally:
        conn.close()


@app.route("/claims-rate")
def claims_rate():
    """Forced fee claims vs fee patents by reservation."""
    return render_template("claims_rate.html")


@app.route("/api/claims-rate")
def api_claims_rate():
    """JSON API: per-tribe fee patents vs forced fee claims."""
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Build tribe name mapping from FR claims -> BLM preferred_name
        # using the linked patents as ground truth
        cur.execute("""
            SELECT fr.tribe_identified as fr_name,
                b.preferred_name as blm_name,
                COUNT(DISTINCT fr.id) as link_count
            FROM federal_register_claims fr
            JOIN forced_fee_patents_rails ffp
                ON LTRIM(fr.case_number, '0') = LTRIM(ffp.case_number, '0')
                AND fr.allottee_name = ffp.fedreg_allottee
            JOIN blm_allotment_patents b
                ON ffp.patents_accession_number = b.accession_number
            WHERE b.preferred_name IS NOT NULL
            GROUP BY fr.tribe_identified, b.preferred_name
            ORDER BY fr.tribe_identified, link_count DESC
        """)
        # For each FR tribe, pick the BLM name with most links
        fr_to_blm = {}
        for row in cur.fetchall():
            fr_name = row["fr_name"]
            if fr_name not in fr_to_blm:
                fr_to_blm[fr_name] = row["blm_name"]

        # Manual overrides for FR names that map to wrong/small BLM tribes
        fr_to_blm.update({
            "Potawatomi": "Citizen Potawatomi",
            "Citizen Potawatomi (OK)": "Citizen Potawatomi",
            "Kiowa, Comanche, Apache": "Comanche",  # combined reservation
            "Kiowa": "Kiowa",
            "Flandreau Santee Sioux": "Santee Sioux",
            "Fort Belknap (Gros Ventre-Assiniboine)": "Assiniboine And Gros Ventre",
            "Fort Peck (Assiniboine-Sioux)": "Assiniboine And Sioux",
            "Sisseton-Wahpeton": "Sisseton\u2013Wahpeton Oyate",
            "Mission Indians (CA)": None,  # skip — too fragmented
            "Michigan (other)": None,
        })

        # FR claims per tribe (using FR tribe names, mapped to BLM names)
        cur.execute("""
            SELECT tribe_identified,
                COUNT(*) as total_claims,
                COUNT(*) FILTER (WHERE claim_type ILIKE '%%FORCED FEE%%') as forced_claims,
                COUNT(*) FILTER (WHERE claim_type ILIKE '%%SECRETARIAL%%') as sec_claims
            FROM federal_register_claims
            GROUP BY tribe_identified
        """)
        fr_by_tribe = {}
        for row in cur.fetchall():
            blm_name = fr_to_blm.get(row["tribe_identified"], row["tribe_identified"])
            if blm_name is None:
                continue  # skip unmappable tribes
            if blm_name not in fr_by_tribe:
                fr_by_tribe[blm_name] = {"total_claims": 0, "forced_claims": 0,
                                         "sec_claims": 0, "fr_names": []}
            fr_by_tribe[blm_name]["total_claims"] += row["total_claims"]
            fr_by_tribe[blm_name]["forced_claims"] += row["forced_claims"]
            fr_by_tribe[blm_name]["sec_claims"] += row["sec_claims"]
            fr_by_tribe[blm_name]["fr_names"].append(row["tribe_identified"])

        # BLM patent counts per tribe
        cur.execute(f"""
            SELECT preferred_name,
                COUNT(*) as total_patents,
                COUNT(*) FILTER (WHERE authority IN %s OR forced_fee = 'True') as fee_patents,
                COUNT(*) FILTER (WHERE authority IN %s AND forced_fee = 'False') as trust_patents,
                COUNT(*) FILTER (WHERE forced_fee = 'True') as forced_fee_patents
            FROM blm_allotment_patents
            WHERE preferred_name IS NOT NULL
            GROUP BY preferred_name
        """, [FEE_AUTHORITIES, TRUST_AUTHORITIES])

        tribes = []
        for row in cur.fetchall():
            name = row["preferred_name"]
            fr = fr_by_tribe.get(name, {"total_claims": 0, "forced_claims": 0,
                                         "sec_claims": 0, "fr_names": []})
            fee = row["fee_patents"]
            if fee < 20:
                continue
            tribes.append({
                "tribe": name,
                "fr_names": fr["fr_names"],
                "total_patents": row["total_patents"],
                "trust_patents": row["trust_patents"],
                "fee_patents": fee,
                "forced_fee_patents": row["forced_fee_patents"],
                "forced_claims": fr["forced_claims"],
                "total_claims": fr["total_claims"],
                "claim_rate": min(round(fr["forced_claims"] / fee * 100, 1), 100.0) if fee > 0 else 0,
            })

        tribes.sort(key=lambda t: t["fee_patents"], reverse=True)

        return jsonify({"tribes": tribes})
    finally:
        conn.close()


@app.route("/wilson")
def wilson():
    """Wilson Report (1934) — original reservation acreage context."""
    return render_template("wilson.html")


@app.route("/api/wilson")
def api_wilson():
    """JSON API: Wilson Table VI data joined with BLM patent stats."""
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Wilson data with BLM tribe mapping
        cur.execute("""
            SELECT
                w.reservation_name,
                w.date_established,
                w.original_area_acres,
                w.total_area_acres,
                w.total_reductions_acres,
                w.total_allotments_made,
                w.allotment_acreage,
                w.land_alienated_acres,
                w.living_allotments_num,
                w.living_total_acres,
                w.deceased_allotments_num,
                w.deceased_total_acres,
                w.tribal_total_acres,
                w.govt_total_acres,
                w.blm_tribe_name,
                w.match_method
            FROM wilson_table_vi w
            ORDER BY w.original_area_acres DESC NULLS LAST
        """)
        wilson_rows = cur.fetchall()

        # BLM patent counts per tribe (for matched reservations)
        cur.execute("""
            SELECT preferred_name,
                COUNT(*) as total_patents,
                COUNT(*) FILTER (WHERE authority IN %s OR forced_fee = 'True') as fee_patents,
                COUNT(*) FILTER (WHERE authority IN %s AND forced_fee = 'False') as trust_patents,
                COUNT(*) FILTER (WHERE forced_fee = 'True') as forced_fee_patents
            FROM blm_allotment_patents
            WHERE preferred_name IS NOT NULL
            GROUP BY preferred_name
        """, [FEE_AUTHORITIES, TRUST_AUTHORITIES])
        blm_stats = {}
        for row in cur.fetchall():
            blm_stats[row["preferred_name"]] = row

        # FR claims per BLM tribe (reuse claims-rate mapping logic)
        cur.execute("""
            SELECT fr.tribe_identified as fr_name,
                b.preferred_name as blm_name,
                COUNT(DISTINCT fr.id) as link_count
            FROM federal_register_claims fr
            JOIN forced_fee_patents_rails ffp
                ON LTRIM(fr.case_number, '0') = LTRIM(ffp.case_number, '0')
                AND fr.allottee_name = ffp.fedreg_allottee
            JOIN blm_allotment_patents b
                ON ffp.patents_accession_number = b.accession_number
            WHERE b.preferred_name IS NOT NULL
            GROUP BY fr.tribe_identified, b.preferred_name
            ORDER BY fr.tribe_identified, link_count DESC
        """)
        fr_to_blm = {}
        for row in cur.fetchall():
            if row["fr_name"] not in fr_to_blm:
                fr_to_blm[row["fr_name"]] = row["blm_name"]
        fr_to_blm.update({
            "Potawatomi": "Citizen Potawatomi",
            "Citizen Potawatomi (OK)": "Citizen Potawatomi",
            "Kiowa, Comanche, Apache": "Comanche",
            "Kiowa": "Kiowa",
            "Flandreau Santee Sioux": "Santee Sioux",
            "Fort Belknap (Gros Ventre-Assiniboine)": "Assiniboine And Gros Ventre",
            "Fort Peck (Assiniboine-Sioux)": "Assiniboine And Sioux",
            "Sisseton-Wahpeton": "Sisseton\u2013Wahpeton Oyate",
            "Mission Indians (CA)": None,
            "Michigan (other)": None,
        })

        cur.execute("""
            SELECT tribe_identified,
                COUNT(*) FILTER (WHERE claim_type ILIKE '%%FORCED FEE%%') as forced_claims
            FROM federal_register_claims
            GROUP BY tribe_identified
        """)
        fr_claims_by_blm = {}
        for row in cur.fetchall():
            blm_name = fr_to_blm.get(row["tribe_identified"])
            if blm_name:
                fr_claims_by_blm[blm_name] = fr_claims_by_blm.get(blm_name, 0) + row["forced_claims"]

        # Murray comparative data (1947-1957) keyed by BLM tribe name
        cur.execute("""
            SELECT blm_tribe_name, agency, area_office,
                individual_acres_1947, individual_acres_1957,
                individual_increase, individual_decrease,
                tribal_acres_1947, tribal_acres_1957
            FROM murray_comparative
            WHERE blm_tribe_name IS NOT NULL
        """)
        murray_by_blm = {}
        for row in cur.fetchall():
            murray_by_blm[row["blm_tribe_name"]] = row

        # Murray transaction counts
        cur.execute("""
            SELECT blm_tribe_name, SUM(transaction_count) as total
            FROM murray_transactions
            WHERE blm_tribe_name IS NOT NULL
            GROUP BY blm_tribe_name
        """)
        murray_txn_by_blm = {}
        for row in cur.fetchall():
            murray_txn_by_blm[row["blm_tribe_name"]] = int(row["total"])

        # Build response
        reservations = []
        for w in wilson_rows:
            blm_name = w["blm_tribe_name"]
            blm = blm_stats.get(blm_name, {}) if blm_name else {}

            original = w["original_area_acres"] or 0
            allotted = w["allotment_acreage"] or 0
            alienated = w["land_alienated_acres"] or 0
            allotments_1934 = w["total_allotments_made"] or 0
            living = w["living_allotments_num"] or 0
            deceased = w["deceased_allotments_num"] or 0
            # Use living+deceased as allottee count when it exceeds total_allotments_made,
            # since allotments were subdivided among heirs over time
            allottee_count = max(allotments_1934, living + deceased)

            blm_total = blm.get("total_patents", 0)
            blm_fee = blm.get("fee_patents", 0)
            blm_forced = blm.get("forced_fee_patents", 0)
            fr_claims = fr_claims_by_blm.get(blm_name, 0) if blm_name else 0

            # Alienation rate: land alienated as % of allotted
            alienation_rate = round(alienated / allotted * 100, 1) if allotted > 0 else None

            reservations.append({
                "reservation": w["reservation_name"],
                "date_established": w["date_established"],
                "original_acres": original,
                "allotment_acreage": allotted,
                "land_alienated": alienated,
                "alienation_rate": alienation_rate,
                "allotments_1934": allotments_1934,
                "allottee_count": allottee_count,
                "living_allotments": living,
                "living_acres": w["living_total_acres"] or 0,
                "deceased_allotments": w["deceased_allotments_num"] or 0,
                "deceased_acres": w["deceased_total_acres"] or 0,
                "tribal_acres": w["tribal_total_acres"] or 0,
                "govt_acres": w["govt_total_acres"] or 0,
                "blm_tribe": blm_name,
                "blm_total_patents": blm_total,
                "blm_fee_patents": blm_fee,
                "blm_forced_fee": blm_forced,
                "fr_forced_claims": fr_claims,
                "match_method": w["match_method"],
            })

            # Attach Murray data if available
            m = murray_by_blm.get(blm_name) if blm_name else None
            if m:
                reservations[-1]["murray"] = {
                    "agency": m["agency"],
                    "individual_1947": int(m["individual_acres_1947"]) if m["individual_acres_1947"] else 0,
                    "individual_1957": int(m["individual_acres_1957"]) if m["individual_acres_1957"] else 0,
                    "individual_loss": int(m["individual_decrease"]) if m["individual_decrease"] else 0,
                    "transactions": murray_txn_by_blm.get(blm_name, 0),
                }

        # Summary stats — both matched and all
        matched = [r for r in reservations if r["blm_tribe"]]
        all_original = sum(r["original_acres"] for r in reservations)
        all_allotted = sum(r["allotment_acreage"] for r in reservations)
        all_alienated = sum(r["land_alienated"] for r in reservations)
        matched_original = sum(r["original_acres"] for r in matched)
        matched_allotted = sum(r["allotment_acreage"] for r in matched)
        matched_alienated = sum(r["land_alienated"] for r in matched)

        # Murray summary
        cur.execute("""
            SELECT SUM(individual_acres_1947) as i47, SUM(individual_acres_1957) as i57,
                   SUM(COALESCE(individual_decrease, 0)) - SUM(COALESCE(individual_increase, 0)) as net_loss
            FROM murray_comparative
        """)
        msum = cur.fetchone()
        cur.execute("SELECT SUM(transaction_count) as total FROM murray_transactions")
        mtxn_total = cur.fetchone()["total"]
        cur.execute("SELECT COUNT(DISTINCT agency) as cnt FROM murray_comparative")
        magency_count = cur.fetchone()["cnt"]

        return jsonify({
            "reservations": reservations,
            "summary": {
                "total_reservations": len(reservations),
                "matched_reservations": len(matched),
                "all_original_acres": all_original,
                "all_allotted_acres": all_allotted,
                "all_alienated_acres": all_alienated,
                "matched_original_acres": matched_original,
                "matched_allotted_acres": matched_allotted,
                "matched_alienated_acres": matched_alienated,
                "overall_alienation_rate": round(all_alienated / all_allotted * 100, 1) if all_allotted > 0 else 0,
                "murray_agencies": magency_count,
                "murray_individual_1947": int(msum["i47"]) if msum["i47"] else 0,
                "murray_individual_1957": int(msum["i57"]) if msum["i57"] else 0,
                "murray_net_loss": int(msum["net_loss"]) if msum["net_loss"] else 0,
                "murray_transactions": int(mtxn_total) if mtxn_total else 0,
            }
        })
    finally:
        conn.close()


@app.route("/murray")
def murray():
    """Murray Memorandum (1947-1957) — trust removal during termination era."""
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Summary stats
        cur.execute("SELECT SUM(individual_acres_1947) as i47, SUM(individual_acres_1957) as i57, "
                     "SUM(individual_decrease) as loss FROM murray_comparative")
        comp_totals = cur.fetchone()
        cur.execute("SELECT SUM(transaction_count) as total FROM murray_transactions")
        txn_total = cur.fetchone()["total"]
        cur.execute("SELECT SUM(total_acreage) as total FROM murray_lands_acquired")
        acq_total = cur.fetchone()["total"]

        class Summary:
            individual_1947 = float(comp_totals["i47"])
            individual_1957 = float(comp_totals["i57"])
            individual_loss = float(comp_totals["loss"])
            total_transactions = int(txn_total)
            lands_acquired = float(acq_total)
        summary = Summary()

        # Removal by year (trust_removal aggregated)
        cur.execute("""
            SELECT year, SUM(acres_removed) as acres
            FROM murray_trust_removal
            GROUP BY year ORDER BY year
        """)
        removal_by_year = [{"year": r["year"], "acres": float(r["acres"])}
                           for r in cur.fetchall()]

        # Transactions by year
        cur.execute("""
            SELECT year, SUM(transaction_count) as count
            FROM murray_transactions
            GROUP BY year ORDER BY year
        """)
        txn_by_year = [{"year": r["year"], "count": int(r["count"])}
                       for r in cur.fetchall()]

        # Lands acquired (top agencies)
        cur.execute("""
            SELECT agency, total_acreage
            FROM murray_lands_acquired
            WHERE total_acreage > 0
            ORDER BY total_acreage DESC
        """)
        lands_acquired = [{"agency": r["agency"],
                           "acreage": float(r["total_acreage"])}
                          for r in cur.fetchall()]

        # Comparative 1947 vs 1957
        cur.execute("""
            SELECT agency,
                individual_acres_1947, individual_acres_1957,
                individual_decrease
            FROM murray_comparative
            WHERE individual_decrease IS NOT NULL AND individual_decrease > 0
            ORDER BY individual_decrease DESC
        """)
        comparative = [{"agency": r["agency"],
                        "acres_1947": float(r["individual_acres_1947"]) if r["individual_acres_1947"] else 0,
                        "acres_1957": float(r["individual_acres_1957"]) if r["individual_acres_1957"] else 0,
                        "loss": float(r["individual_decrease"]) if r["individual_decrease"] else 0}
                       for r in cur.fetchall()]

        # Agency removal with transaction counts
        cur.execute("""
            SELECT a.agency, a.acres_removed, a.blm_tribe_name,
                COALESCE(t.txn, 0) as transactions
            FROM murray_agency_removal a
            LEFT JOIN (
                SELECT agency, SUM(transaction_count) as txn
                FROM murray_transactions GROUP BY agency
            ) t ON t.agency = a.agency
            ORDER BY a.acres_removed DESC
        """)
        agency_removal = cur.fetchall()

        return render_template("murray.html", summary=summary,
                               removal_by_year=removal_by_year,
                               txn_by_year=txn_by_year,
                               lands_acquired=lands_acquired,
                               comparative=comparative,
                               agency_removal=agency_removal)
    finally:
        conn.close()


@app.route("/dubois")
def dubois():
    """Du Bois-inspired data visualizations."""
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT year, total_acres, total_tracts, total_proceeds,
                   original_acreage, inherited_acreage
            FROM wilson_annual_sales
            ORDER BY year
        """)
        wilson_sales = [{"year": r["year"],
                         "acres_sold": float(r["total_acres"]) if r["total_acres"] else 0,
                         "tracts": int(r["total_tracts"]) if r["total_tracts"] else 0,
                         "proceeds": float(r["total_proceeds"]) if r["total_proceeds"] else 0,
                         "original_acres": float(r["original_acreage"]) if r["original_acreage"] else 0,
                         "inherited_acres": float(r["inherited_acreage"]) if r["inherited_acreage"] else 0,
                        } for r in cur.fetchall()]

        # Forced fee claims by tribe (FR source only)
        cur.execute("""
            SELECT tribe_identified as tribe,
                COUNT(*) FILTER (WHERE claim_type ILIKE '%%FORCED FEE%%') as forced,
                COUNT(*) FILTER (WHERE claim_type ILIKE '%%SECRETARIAL%%') as secretarial,
                COUNT(*) as total
            FROM federal_register_claims
            GROUP BY tribe_identified
            ORDER BY COUNT(*) FILTER (WHERE claim_type ILIKE '%%FORCED FEE%%') DESC
        """)
        fr_by_tribe = [{"tribe": r["tribe"], "forced": r["forced"],
                        "secretarial": r["secretarial"], "total": r["total"]}
                       for r in cur.fetchall() if r["forced"] > 0]

        # Forced fee claims by year (signature date from linked BLM patents)
        cur.execute("""
            SELECT
                EXTRACT(YEAR FROM ffp.patents_signature_date)::int as yr,
                COUNT(DISTINCT fr.id) as cnt
            FROM federal_register_claims fr
            JOIN forced_fee_patents_rails ffp
                ON LTRIM(fr.case_number, '0') = LTRIM(ffp.case_number, '0')
                AND fr.allottee_name = ffp.fedreg_allottee
            WHERE ffp.patents_signature_date IS NOT NULL
                AND fr.claim_type ILIKE '%%FORCED FEE%%'
            GROUP BY yr
            ORDER BY yr
        """)
        fr_by_year = [{"year": r["yr"], "count": r["cnt"]}
                      for r in cur.fetchall()
                      if r["yr"] and 1900 <= r["yr"] <= 1935]

        return render_template("dubois.html", wilson_sales=wilson_sales,
                               fr_by_tribe=fr_by_tribe, fr_by_year=fr_by_year)
    finally:
        conn.close()


@app.route("/about")
def about():
    """About the Data page."""
    return render_template("about.html")


@app.route("/about/project")
def about_project():
    """About This Project page."""
    return render_template("about_project.html")


# ──────────────────────────────────────────────
# Error handlers
# ──────────────────────────────────────────────

@app.errorhandler(404)
def not_found(e):
    return render_template("404.html"), 404


if __name__ == "__main__":
    app.run(debug=True, port=5001)
