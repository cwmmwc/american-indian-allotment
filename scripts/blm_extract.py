"""
Shared BLM detail-page extraction logic.

Imported by:
  scripts/probe_blm_detail_structure.py  (Phase 0 — single-page validation)
  scripts/scrape_blm_volume.py           (Phase 1+ — full-volume scrape)

The BLM detail page exposes most fields by stable element IDs of the form
`glowebContent_patentDetails_<field>` (and a few outside that namespace like
`glowebContent_issueDate`). The state isn't a labeled field — it lives in
the first <td class="noRemarks"> inside the land-descriptions table.

Normalizers convert BLM's serving format (LAST, FIRST / M/D/YYYY / Title Case)
to rails_patents storage format (FIRST LAST / ISO date / UPPERCASE tribe and
remarks).
"""
import re
import datetime


# (output_field_name, element_id_under_glowebContent_)
ID_FIELDS = [
    ("full_name",                "patentDetails_names"),
    ("signature_date",           "issueDate"),
    ("authority",                "patentDetails_authority"),
    ("indian_allotment_number",  "patentDetails_indianAllotmentNr"),
    ("glo_tribe_name",           "patentDetails_tribe"),
    ("remarks",                  "patentDetails_generalRemarks"),
    ("land_office",              "patentDetails_landOffice"),
    ("document_number",          "patentDetails_documentNr"),
    ("misc_document_number",     "patentDetails_miscDocumentNr"),
    ("blm_serial_number",        "patentDetails_blmSerialNr"),
    ("total_acres",              "patentDetails_totalAcres"),
    ("survey_date",              "patentDetails_surveyDate"),
    ("geographic_name",          "patentDetails_geographicName"),
    ("metes_bounds",             "patentDetails_metesBounds"),
]


def extract_by_id(html, element_id):
    """Inner text of <td|div id="glowebContent_<element_id>" ...>VALUE</td|div>.

    The `names` div may contain multiple patentees separated by <br>; we join
    them with '; '. <img> tags are stripped. "---" is normalized to None.
    """
    full_id = f"glowebContent_{element_id}"
    pat = rf'id="{re.escape(full_id)}"[^>]*>(.*?)</(?:td|div)>'
    m = re.search(pat, html, flags=re.IGNORECASE | re.DOTALL)
    if not m:
        return None
    body = m.group(1)
    body = re.sub(r'<img[^>]*>', '', body)
    body = re.sub(r'<br\s*/?>', '|', body, flags=re.IGNORECASE)
    body = re.sub(r'<[^>]+>', '', body)
    parts = [re.sub(r'\s+', ' ', p).strip().rstrip(',').strip() for p in body.split('|')]
    parts = [p for p in parts if p]
    val = "; ".join(parts) if parts else None
    if val in (None, "", "---"):
        return None
    return val


def extract_state_from_land_descriptions(html):
    m = re.search(r'<td class="noRemarks">([A-Z]{2})</td>', html)
    return m.group(1) if m else None


def normalize_name(raw):
    """BLM 'LAST, FIRST' → rails 'FIRST LAST'. Per-segment; segments without a
    comma are left as-is. Multi-patentee strings use '; ' as separator."""
    if not raw:
        return None
    out = []
    for seg in raw.split("; "):
        seg = seg.strip()
        if not seg:
            continue
        parts = [p.strip() for p in seg.split(",", 1)]
        if len(parts) == 2 and parts[0] and parts[1]:
            out.append(f"{parts[1]} {parts[0]}")
        else:
            out.append(seg)
    return "; ".join(out) if out else None


def normalize_date(raw):
    """BLM M/D/YYYY or 'Month D, YYYY' → ISO YYYY-MM-DD."""
    if not raw:
        return None
    s = raw.strip()
    m = re.match(r'^(\d{1,2})/(\d{1,2})/(\d{4})$', s)
    if m:
        mo, dy, yr = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return f"{yr:04d}-{mo:02d}-{dy:02d}"
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%Y-%m-%d"):
        try:
            return datetime.datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return s


def normalize_upper(raw):
    if not raw:
        return None
    return raw.upper()


def extract_all(html, doc_class_param):
    """Run all ID-based extractors and normalizers; return a dict whose keys
    match rails_patents columns where applicable. doc_class_param comes from
    the URL (e.g. 'STA') because the page itself doesn't label document_class."""
    out = {}
    for field, eid in ID_FIELDS:
        out[field] = extract_by_id(html, eid)
    out["state"] = extract_state_from_land_descriptions(html)

    # Map docClass URL param → rails_patents document_class string + document_code
    DOC_CLASS_MAP = {
        "STA": ("State Land Patent",          "STA"),
        "SER": ("Serial Land Patent",         "SER"),
        "MV":  ("Miscellaneous Volume Patent","MV"),
        "IA":  ("Indian Allotment Patent",    "IA"),
        "CT":  ("Cash Entry Patent",          "CT"),
        "SS":  ("Supreme Court Patent",       "SS"),
    }
    dc_class, dc_code = DOC_CLASS_MAP.get(doc_class_param, (None, doc_class_param))
    out["document_class"] = dc_class
    out["document_code"]  = dc_code

    out["full_name"]      = normalize_name(out["full_name"])
    out["signature_date"] = normalize_date(out["signature_date"])
    out["glo_tribe_name"] = normalize_upper(out["glo_tribe_name"])
    out["remarks"]        = normalize_upper(out["remarks"])
    return out


def page_is_not_found(html):
    """BLM returns a 200 with an error message body when an accession doesn't
    exist; detect that so we can mark the row 'not_found' instead of 'ok'.

    The observed BLM message text (2026-05-26) is:
      "A document does not exist in our database that matches the current
       Accession number."
    The other patterns are defensive in case BLM uses different wording on
    some pages."""
    lo = html.lower()
    return ("a document does not exist in our database" in lo
            or "could not be located" in lo
            or "no records found" in lo
            or "Object reference not set" in html)
