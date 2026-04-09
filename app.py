import streamlit as st
import requests
import pandas as pd
from datetime import date, timedelta
from io import BytesIO
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
)
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT

st.set_page_config(page_title="Pipeline Dashboard", layout="wide")


# ── PDF 생성 함수 ──────────────────────────────────────
def generate_pdf(row):
    import re
    buffer  = BytesIO()

    # 마진 상수 — 표 너비 계산에도 동일하게 사용
    L_MARGIN = 20 * mm
    R_MARGIN = 20 * mm
    T_MARGIN = 20 * mm
    B_MARGIN = 20 * mm   # 푸터 고정 영역 확보를 위해 넉넉하게
    PW, PH   = A4          # 210mm × 297mm
    W        = PW - L_MARGIN - R_MARGIN   # 실제 콘텐츠 너비

    # ── 푸터 콜백 (페이지 하단 고정) ────────────────────
    footer_text = (
        "Data sources: ClinicalTrials.gov · PubMed · Europe PMC · "
        "OpenAlex · bioRxiv / medRxiv  ·  For internal use only. Not for distribution."
    )
    MID_GRAY_F = colors.HexColor("#888888")
    ACCENT_F   = colors.HexColor("#0f6e56")

    def draw_footer(canvas, doc):
        canvas.saveState()
        # 하단 라인: 상단 초록 라인과 대칭 (bottomMargin 위치)
        footer_y = B_MARGIN
        canvas.setStrokeColor(MID_GRAY_F)
        canvas.setLineWidth(0.5)
        canvas.line(L_MARGIN, footer_y, PW - R_MARGIN, footer_y)
        # 텍스트: 라인 아래 6pt
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(MID_GRAY_F)
        canvas.drawCentredString(PW / 2, footer_y - 10, footer_text)
        canvas.restoreState()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=R_MARGIN,
        leftMargin=L_MARGIN,
        topMargin=T_MARGIN,
        bottomMargin=B_MARGIN + 18,   # 푸터 공간 확보
    )

    # 색상 정의
    DARK       = colors.HexColor("#1a1a2e")
    ACCENT     = colors.HexColor("#0f6e56")
    LIGHT_GRAY = colors.HexColor("#f5f5f5")
    MID_GRAY   = colors.HexColor("#888888")
    RED        = colors.HexColor("#c0392b")
    AMBER      = colors.HexColor("#d68910")
    GREEN      = colors.HexColor("#1e8449")

    def style(name, **kwargs):
        return ParagraphStyle(name, **kwargs)

    s_title    = style("s_title",    fontSize=18, textColor=DARK,
                       fontName="Helvetica-Bold", spaceAfter=0)
    s_subtitle = style("s_subtitle", fontSize=9,  textColor=MID_GRAY,
                       fontName="Helvetica", spaceAfter=4)
    s_section  = style("s_section",  fontSize=13, textColor=ACCENT,
                       fontName="Helvetica-Bold", spaceBefore=18,
                       spaceAfter=10, leftIndent=0)
    s_body     = style("s_body",     fontSize=9,  textColor=DARK,
                       fontName="Helvetica", spaceAfter=3, leading=14)
    s_small    = style("s_small",    fontSize=8,  textColor=MID_GRAY,
                       fontName="Helvetica", spaceAfter=2, leading=12)
    s_bold     = style("s_bold",     fontSize=9,  textColor=DARK,
                       fontName="Helvetica-Bold", spaceAfter=3)
    s_question = style("s_question", fontSize=9,  textColor=DARK,
                       fontName="Helvetica", spaceAfter=8,
                       leading=16, leftIndent=0)

    def conf_color(conf):
        if "Confirmed" in conf: return GREEN
        if "Partial"   in conf: return AMBER
        return RED

    def clean_phase(raw):
        text = re.sub(r'[^\x00-\x7F]+', '', raw).strip()
        text = re.sub(
            r'(?i)phase\s*(\d)',
            lambda m: f"Phase {m.group(1)}",
            text
        ).strip()
        return text or raw

    def clean_status(raw):
        return re.sub(r'[^\x00-\x7F]+', '', raw).strip() or raw

    elements   = []
    drug_name  = row.get("Drug") or row.get("NCT#", "")
    sponsor    = row.get("Lead Sponsor", "")
    nct        = row.get("NCT#", "")
    ct_link    = row.get("CT.gov Link", "")
    gen_date   = date.today().strftime("%Y-%m-%d")
    conf       = row.get("Confidence", "—")
    conf_color_= conf_color(conf)

    # ── 헤더 ──────────────────────────────────────────
    elements.append(Paragraph(drug_name, s_title))
    elements.append(Spacer(1, 14))
    elements.append(Paragraph(
        f"{sponsor}  ·  {nct}  ·  "
        f'<a href="{ct_link}" color="#0f6e56">View on CT.gov</a>  ·  '
        f"Generated {gen_date}",
        s_subtitle
    ))
    # HRFlowable width=W → 좌우 마진과 정확히 동일
    elements.append(HRFlowable(
        width=W, thickness=1.5, color=ACCENT, spaceAfter=10
    ))

    # ── 섹션 1: Trial Snapshot ─────────────────────────
    elements.append(Paragraph("Trial Snapshot", s_section))

    phase_clean  = clean_phase(row.get("Phase",  "—"))
    status_clean = clean_status(row.get("Status", "—"))

    # 왼쪽 컬럼 44mm, 오른쪽 컬럼 W-44mm → 합계 = W (초록 라인과 동일)
    COL1 = 44 * mm
    COL2 = W - COL1

    snap_data = [
        ["Field",              "Value"],
        ["NCT#",               nct],
        ["Trial Title",        row.get("Trial Title", "—")],
        ["Lead Sponsor",       row.get("Lead Sponsor", "—")],
        ["Collaborators",      row.get("Collaborators", "—")],
        ["Indication",         row.get("Indication", "—")],
        ["Phase",              phase_clean],
        ["Status",             status_clean],
        ["Primary Completion", row.get("Completion") or "—"],
    ]

    snap_table = Table(snap_data, colWidths=[COL1, COL2])
    snap_table.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0),  ACCENT),
        ("TEXTCOLOR",     (0, 0), (-1, 0),  colors.white),
        ("FONTNAME",      (0, 0), (-1, 0),  "Helvetica-Bold"),
        ("FONTSIZE",      (0, 0), (-1, 0),  9),
        ("BACKGROUND",    (0, 1), (0, -1),  LIGHT_GRAY),
        ("FONTNAME",      (0, 1), (0, -1),  "Helvetica-Bold"),
        ("FONTSIZE",      (0, 1), (-1, -1), 9),
        ("TEXTCOLOR",     (0, 1), (-1, -1), DARK),
        ("ROWBACKGROUNDS",(0, 2), (-1, -1), [colors.white, LIGHT_GRAY]),
        ("GRID",          (0, 0), (-1, -1), 0.3, colors.HexColor("#dddddd")),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING",   (0, 0), (-1, -1), 8),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
    ]))
    elements.append(snap_table)
    elements.append(Spacer(1, 6))

    # ── 섹션 2: Clinical Evidence Summary ─────────────
    peer      = row.get("peer_reviewed", [])
    preprints = row.get("preprints", [])

    elements.append(Paragraph("Clinical Evidence Summary", s_section))

    conf_hex   = conf_color_.hexval()
    peer_label = (
        f"<b>Peer-reviewed Publications ({len(peer)})</b>"
        f"&nbsp;&nbsp;&nbsp;"
        f'<font color="{conf_hex}" size="8">{conf}</font>'
    )
    elements.append(Paragraph(peer_label, s_bold))

    if peer:
        for i, p in enumerate(peer, 1):
            title  = p.get("title", "")[:150]
            source = p.get("source", "")
            url    = p.get("url", "")
            elements.append(Paragraph(
                f'{i}. <a href="{url}" color="#0f6e56">{title}</a> '
                f'<font color="#888888">[{source}]</font>',
                s_body
            ))
    else:
        elements.append(Paragraph(
            "No peer-reviewed publications found.", s_small
        ))

    if preprints:
        elements.append(Spacer(1, 4))
        elements.append(Paragraph(
            f"Preprints ({len(preprints)}) — not peer-reviewed, use with caution",
            ParagraphStyle("s_pre", fontSize=9, textColor=AMBER,
                           fontName="Helvetica-Bold", spaceAfter=3)
        ))
        for i, p in enumerate(preprints, 1):
            title  = p.get("title", "")[:150]
            source = p.get("source", "")
            url    = p.get("url", "")
            elements.append(Paragraph(
                f'{i}. <a href="{url}" color="#888888">{title}</a> '
                f'<font color="#888888">[{source}]</font>',
                s_small
            ))

    elements.append(Spacer(1, 6))

    # ── 섹션 3: Key Questions for Meeting ─────────────
    elements.append(Paragraph("Key Questions for Meeting", s_section))

    questions  = []
    status_raw = row.get("Status_raw", "")
    n_peer     = len(peer)

    if "NOT PUBLISHED" in conf:
        questions.append(
            "Trial is marked Completed but no peer-reviewed publications "
            "were found. What are the primary efficacy and safety outcomes, "
            "and why have results not been published?"
        )
    if "ONGOING" in conf and n_peer == 0:
        questions.append(
            "No publications available yet for this ongoing trial. "
            "What is the current enrollment status, "
            "and when are interim or top-line results expected?"
        )
    if "Partial" in conf:
        questions.append(
            "Only partial publication data is available. "
            "Are there additional data readouts planned, "
            "and what endpoints remain unreported?"
        )
    if "Terminated" in row.get("Status", "") or \
       "TERMINATED" in status_raw.upper():
        questions.append(
            "This trial appears to have been terminated. "
            "What was the reason for discontinuation, "
            "and are there plans to restart or modify the program?"
        )
    if row.get("Collaborators", "—") != "—":
        questions.append(
            f"This trial lists collaborators ({row['Collaborators']}). "
            "What is the nature of this collaboration — "
            "co-development, funding, or CRO engagement?"
        )

    questions += [
        "What are the next clinical milestones and expected timelines "
        "for this program?",
        "Are there any ongoing or planned combination studies "
        "involving this asset?",
        "What is the current competitive landscape, "
        "and how does this asset differentiate from existing therapies?",
    ]

    for i, q in enumerate(questions, 1):
        elements.append(Paragraph(f"{i}.  {q}", s_question))

    # ── 빌드 (푸터 콜백 등록) ─────────────────────────
    doc.build(elements, onFirstPage=draw_footer, onLaterPages=draw_footer)
    buffer.seek(0)
    return buffer


# ── Sidebar ────────────────────────────────────────────
with st.sidebar:
    st.title("Pipeline Dashboard")
    st.caption(
        "ClinicalTrials.gov · PubMed · Europe PMC · "
        "OpenAlex · bioRxiv/medRxiv"
    )
    st.divider()

    st.subheader("Search")
    sponsor_input = st.text_input(
        "Sponsor / Lead Organization",
        placeholder="e.g. Agenus, Merck"
    )
    keyword_input = st.text_input(
        "Drug / Indication / Keyword",
        placeholder="e.g. nivolumab, NSCLC"
    )

    st.subheader("Filters")
    phase_filter = st.selectbox(
        "Phase",
        ["All", "Phase 1", "Phase 2", "Phase 3", "Phase 4"]
    )
    status_filter = st.selectbox(
        "Status",
        ["All", "RECRUITING", "ACTIVE_NOT_RECRUITING",
         "COMPLETED", "TERMINATED"]
    )

    st.subheader("Date range")
    st.caption(
        "Last update date. Narrower range = faster results. "
        "Widen if recent investigator-initiated trials are missing."
    )
    date_from = st.date_input(
        "From",
        value=date.today() - timedelta(days=365 * 5),
        min_value=date(2000, 1, 1),
        max_value=date.today(),
    )
    date_to = st.date_input(
        "To",
        value=date.today(),
        min_value=date(2000, 1, 1),
        max_value=date(2030, 12, 31),
    )

    st.divider()
    search_btn = st.button("Search", type="primary", use_container_width=True)
    download_placeholder = st.empty()


# ── Main header ────────────────────────────────────────
st.title("Partner Pipeline Intelligence")

with st.expander("How to read Confidence levels", expanded=False):
    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        st.markdown("**✅ Confirmed**")
        st.caption(
            "2+ peer-reviewed papers found, or 1 paper for a "
            "completed trial. Results are publicly validated."
        )
    with col2:
        st.markdown("**⚠️ Partial**")
        st.caption(
            "1 peer-reviewed paper found, but trial is still ongoing. "
            "May reflect interim data only."
        )
    with col3:
        st.markdown("**❌ Unverified · ONGOING**")
        st.caption(
            "Trial is active. No publications yet — expected. "
            "Monitor by completion date."
        )
    with col4:
        st.markdown("**❌ Unverified · NOT PUBLISHED**")
        st.caption(
            "Trial completed but no papers found. "
            "Confirm directly with the sponsor — priority flag."
        )
    with col5:
        st.markdown("**❌ Unverified**")
        st.caption(
            "Trial terminated or withdrawn with no publications. "
            "Investigate reason for discontinuation."
        )

# search_btn이 False여도 session_state에 결과 있으면 st.stop() 안 함
if not search_btn and st.session_state.get("results") is None:
    st.info(
        "Enter a sponsor name or keyword in the sidebar and click "
        "**Search** to begin.  \n"
        "**Tip:** If a recently registered investigator-initiated trial "
        "is missing, try widening the date range in the sidebar."
    )
    st.stop()


# ── API 함수들 ─────────────────────────────────────────
@st.cache_data(ttl=3600)
def fetch_trials(sponsor, keyword, status, date_from, date_to):
    base_url = "https://clinicaltrials.gov/api/v2/studies"
    base_params = {
        "pageSize": 50,
        "format":   "json",
        "fields": (
            "NCTId,BriefTitle,OverallStatus,Phase,Condition,"
            "InterventionName,PrimaryCompletionDate,"
            "LeadSponsorName,CollaboratorName"
        ),
        "filter.advanced": (
            f"AREA[LastUpdatePostDate]RANGE["
            f"{date_from.strftime('%Y-%m-%d')},"
            f"{date_to.strftime('%Y-%m-%d')}]"
        ),
    }
    if status != "All":
        base_params["filter.overallStatus"] = status

    query_sets = []
    if sponsor and keyword:
        for kw_field in ["query.term", "query.intr", "query.cond"]:
            query_sets.append({"query.spons": sponsor, kw_field: keyword})
    elif sponsor:
        query_sets.append({"query.spons": sponsor})
    elif keyword:
        for kw_field in ["query.term", "query.intr", "query.cond"]:
            query_sets.append({kw_field: keyword})

    seen_ncts, all_studies = set(), []
    for q in query_sets:
        params = {**base_params, **q}
        try:
            r = requests.get(base_url, params=params, timeout=10)
            r.raise_for_status()
            for s in r.json().get("studies", []):
                nct = (
                    s.get("protocolSection", {})
                     .get("identificationModule", {})
                     .get("nctId", "")
                )
                if nct and nct not in seen_ncts:
                    seen_ncts.add(nct)
                    all_studies.append(s)
        except Exception as e:
            st.warning(f"Query failed ({list(q.keys())}): {e}")
            continue
    return all_studies


def search_pubmed(nct_id):
    try:
        r = requests.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
            params={"db": "pubmed", "term": nct_id,
                    "retmode": "json", "retmax": 5},
            timeout=8
        )
        ids = r.json()["esearchresult"]["idlist"]
        if not ids:
            return []
        r2 = requests.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi",
            params={"db": "pubmed", "id": ",".join(ids), "retmode": "json"},
            timeout=8
        )
        result = r2.json().get("result", {})
        return [
            {
                "title":  result[uid].get("title", ""),
                "url":    f"https://pubmed.ncbi.nlm.nih.gov/{uid}/",
                "source": "PubMed",
                "pmid":   uid,
                "doi":    "",
                "is_preprint": False,
            }
            for uid in ids if result.get(uid, {}).get("title")
        ]
    except:
        return []


def search_europepmc(nct_id):
    try:
        r = requests.get(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
            params={
                "query":      f"CLINICAL_TRIAL_ID:{nct_id}",
                "format":     "json",
                "pageSize":   5,
                "resultType": "core",
            },
            timeout=8
        )
        papers = []
        for item in r.json().get("resultList", {}).get("result", []):
            title = item.get("title", "")
            pmid  = item.get("pmid", "")
            doi   = item.get("doi", "")
            link  = (
                f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid
                else f"https://doi.org/{doi}" if doi else ""
            )
            if title and link:
                papers.append({
                    "title": title, "url": link, "source": "Europe PMC",
                    "pmid": pmid, "doi": doi, "is_preprint": False,
                })
        return papers
    except:
        return []


def search_openalex(nct_id):
    headers = {"User-Agent": "pipeline-dashboard your@email.com"}
    try:
        r = requests.get(
            "https://api.openalex.org/works",
            params={
                "filter":   f"clinical_trial_number:{nct_id}",
                "per_page": 5,
                "select":   "id,title,doi,pmid,primary_location",
            },
            headers=headers, timeout=8
        )
        results = r.json().get("results", [])
        if not results:
            r2 = requests.get(
                "https://api.openalex.org/works",
                params={
                    "search":   nct_id,
                    "per_page": 5,
                    "select":   "id,title,doi,pmid,primary_location",
                },
                headers=headers, timeout=8
            )
            results = r2.json().get("results", [])
        papers = []
        for item in results:
            title = item.get("title", "")
            doi   = (item.get("doi") or "").replace("https://doi.org/", "")
            pmid  = str(item.get("pmid") or "")
            loc   = item.get("primary_location") or {}
            url   = loc.get("landing_page_url") or (
                f"https://doi.org/{doi}" if doi
                else f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid
                else ""
            )
            if title and url:
                papers.append({
                    "title": title, "url": url, "source": "OpenAlex",
                    "pmid": pmid, "doi": doi, "is_preprint": False,
                })
        return papers
    except:
        return []


def search_biorxiv(nct_id):
    papers = []
    for server in ["biorxiv", "medrxiv"]:
        try:
            r = requests.get(
                f"https://api.biorxiv.org/details/{server}/{nct_id}/na/json",
                timeout=8
            )
            for item in r.json().get("collection", []):
                title = item.get("title", "")
                doi   = item.get("doi", "")
                if title and doi:
                    papers.append({
                        "title":  title,
                        "url":    f"https://doi.org/{doi}",
                        "source": "bioRxiv" if server == "biorxiv" else "medRxiv",
                        "pmid":   "",
                        "doi":    doi,
                        "is_preprint": True,
                    })
        except:
            continue
    return papers


@st.cache_data(ttl=3600)
def get_all_papers(nct_id):
    all_raw = (
        search_pubmed(nct_id)
        + search_europepmc(nct_id)
        + search_openalex(nct_id)
        + search_biorxiv(nct_id)
    )
    seen_pmids, seen_dois, seen_titles = set(), set(), set()
    peer_reviewed, preprints = [], []

    for p in all_raw:
        pmid      = p.get("pmid", "").strip()
        doi       = p.get("doi",  "").strip().lower()
        title_key = p["title"][:60].lower()

        if pmid and pmid in seen_pmids:
            continue
        if doi  and doi  in seen_dois:
            continue
        if title_key in seen_titles:
            continue

        if pmid: seen_pmids.add(pmid)
        if doi:  seen_dois.add(doi)
        seen_titles.add(title_key)

        if p["is_preprint"]:
            preprints.append(p)
        else:
            peer_reviewed.append(p)

    return peer_reviewed, preprints


def get_confidence(peer_reviewed, status):
    n = len(peer_reviewed)
    if n >= 2 or (n == 1 and status == "COMPLETED"):
        return "✅ Confirmed"
    elif n == 1:
        return "⚠️ Partial"
    else:
        if status == "COMPLETED":
            return "❌ Unverified · NOT PUBLISHED"
        elif status in ["RECRUITING", "ACTIVE_NOT_RECRUITING"]:
            return "❌ Unverified · ONGOING"
        else:
            return "❌ Unverified"


def fmt_phase(p):
    icons = {
        "PHASE1": "🔬", "PHASE2": "🧪",
        "PHASE3": "🚀", "PHASE4": "✅"
    }
    key = p.upper().replace(" ", "").replace("_", "")
    return f"{icons.get(key, '')} {p}" if p != "N/A" else p


def fmt_status(s):
    mapping = {
        "COMPLETED":             "✅ Completed",
        "RECRUITING":            "🟢 Recruiting",
        "ACTIVE_NOT_RECRUITING": "🔵 Active",
        "TERMINATED":            "🔴 Terminated",
        "WITHDRAWN":             "⚫ Withdrawn",
    }
    return mapping.get(s.upper(), s)


def parse_trials(studies):
    rows = []
    for s in studies:
        proto       = s.get("protocolSection", {})
        id_mod      = proto.get("identificationModule", {})
        status_mod  = proto.get("statusModule", {})
        design_mod  = proto.get("designModule", {})
        cond_mod    = proto.get("conditionsModule", {})
        interv_mod  = proto.get("armsInterventionsModule", {})
        sponsor_mod = proto.get("sponsorCollaboratorsModule", {})

        nct        = id_mod.get("nctId", "")
        overall    = status_mod.get("overallStatus", "")
        phases     = design_mod.get("phases", [])
        phase_str  = ", ".join(phases) if phases else "N/A"
        conditions = cond_mod.get("conditions", [])
        intervs    = interv_mod.get("interventions", [])
        drug       = intervs[0].get("name", "") if intervs else ""
        lead       = sponsor_mod.get("leadSponsor", {}).get("name", "")
        collabs    = sponsor_mod.get("collaborators", [])
        collab_str = (
            ", ".join([c.get("name", "") for c in collabs[:2]])
            if collabs else "—"
        )
        completion = status_mod.get(
            "primaryCompletionDateStruct", {}
        ).get("date", "")
        brief      = id_mod.get("briefTitle", "")

        rows.append({
            "nct_id":        nct,
            "NCT#":          nct,
            "Lead Sponsor":  lead[:35],
            "Collaborators": collab_str[:45],
            "Drug":          drug[:35],
            "Indication":    (conditions[0] if conditions else "")[:40],
            "Phase":         fmt_phase(phase_str),
            "Status":        fmt_status(overall),
            "Status_raw":    overall,
            "Completion":    completion,
            "Trial Title":   brief[:80],
            "CT.gov Link":   f"https://clinicaltrials.gov/study/{nct}",
        })
    return rows


def apply_phase_filter(rows, phase):
    if phase == "All":
        return rows
    return [
        r for r in rows
        if phase.upper().replace(" ", "_")
        in r["Phase"].upper().replace(" ", "_")
    ]


# ── Session state 초기화 ───────────────────────────────
if "results" not in st.session_state:
    st.session_state.results    = None
    st.session_state.last_query = {}

current_query = {
    "sponsor":   sponsor_input,
    "keyword":   keyword_input,
    "status":    status_filter,
    "phase":     phase_filter,
    "date_from": str(date_from),
    "date_to":   str(date_to),
}

# ── 검색 실행 ──────────────────────────────────────────
if search_btn:
    if not sponsor_input and not keyword_input:
        st.warning("Please enter a sponsor name or keyword in the sidebar.")
        st.stop()

    if current_query != st.session_state.last_query:
        with st.spinner("Querying ClinicalTrials.gov..."):
            studies = fetch_trials(
                sponsor_input, keyword_input,
                status_filter, date_from, date_to
            )

        if not studies:
            st.warning(
                "No results found. Try a different keyword "
                "or widen the date range in the sidebar."
            )
            st.stop()

        rows = parse_trials(studies)
        rows = apply_phase_filter(rows, phase_filter)

        progress = st.progress(0, text="Matching publications...")
        for i, row in enumerate(rows):
            peer_reviewed, preprints = get_all_papers(row["nct_id"])
            row["peer_reviewed"] = peer_reviewed
            row["preprints"]     = preprints
            row["Confidence"]    = get_confidence(
                peer_reviewed, row["Status_raw"]
            )
            row["Pubs"]        = len(peer_reviewed)
            row["Preprints"]   = len(preprints)
            row["Pub Sources"] = (
                ", ".join(sorted({p["source"] for p in peer_reviewed}))
                or "—"
            )
            progress.progress(
                (i + 1) / len(rows),
                text=f"Matching publications... {i+1}/{len(rows)}"
            )
        progress.empty()

        st.session_state.results    = rows
        st.session_state.last_query = current_query

# 결과 없으면 중단
if st.session_state.results is None:
    st.stop()

# 세션에서 결과 불러오기
rows  = st.session_state.results
total = len(rows)

# ── 사이드바 CSV 다운로드 ──────────────────────────────
df_export = pd.DataFrame(rows)[[
    "NCT#", "Lead Sponsor", "Collaborators",
    "Drug", "Indication", "Phase", "Status",
    "Completion", "Confidence", "Pubs", "Preprints",
    "Pub Sources", "CT.gov Link"
]]
csv   = df_export.to_csv(index=False).encode("utf-8-sig")
label = sponsor_input or keyword_input
with download_placeholder:
    st.download_button(
        "Export CSV", csv,
        f"{label}_pipeline.csv",
        "text/csv",
        use_container_width=True
    )

# ── 요약 지표 ──────────────────────────────────────────
confirmed  = sum(1 for r in rows if "Confirmed"  in r["Confidence"])
partial    = sum(1 for r in rows if "Partial"    in r["Confidence"])
unverified = sum(1 for r in rows if "Unverified" in r["Confidence"])

# ── Tab 구조 ───────────────────────────────────────────
tab1, tab2 = st.tabs(["Dashboard", "Deep Dive"])

# ══════════════════════════════════════════════════════
# Tab 1 — Dashboard
# ══════════════════════════════════════════════════════
with tab1:
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total trials",   total)
    m2.metric("✅ Confirmed",   confirmed)
    m3.metric("⚠️ Partial",    partial)
    m4.metric("❌ Unverified", unverified)

    st.divider()
    st.subheader("Pipeline Overview")

    max_pubs   = max((r["Pubs"] for r in rows), default=1) or 1
    df_display = pd.DataFrame(rows)[[
        "NCT#", "Lead Sponsor", "Collaborators",
        "Drug", "Indication", "Phase", "Status",
        "Completion", "Confidence", "Pubs", "Preprints",
        "Pub Sources", "CT.gov Link"
    ]]
    st.dataframe(
        df_display,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Pubs": st.column_config.ProgressColumn(
                "Pubs (peer-reviewed)",
                min_value=0,
                max_value=max_pubs,
                format="%d",
            ),
            "Preprints": st.column_config.NumberColumn("Preprints"),
            "CT.gov Link": st.column_config.LinkColumn(
                "CT.gov", display_text="Open ↗"
            ),
        }
    )

# ══════════════════════════════════════════════════════
# Tab 2 — Deep Dive
# ══════════════════════════════════════════════════════
with tab2:
    st.subheader("Publication Detail by Trial")
    st.caption(
        "Confidence is based on peer-reviewed sources only. "
        "Preprints are shown separately and excluded from scoring."
    )

    conf_filter = st.selectbox(
        "Filter by Confidence",
        ["All", "✅ Confirmed", "⚠️ Partial", "❌ Unverified"],
        key="conf_filter"
    )

    filtered_rows = rows if conf_filter == "All" else [
        r for r in rows
        if conf_filter.split()[1] in r["Confidence"]
    ]

    if not filtered_rows:
        st.info("No trials match the selected confidence filter.")
    else:
        for row in filtered_rows:
            header = (
                f"{row['NCT#']} · {row['Lead Sponsor']} · "
                f"{row['Drug'] or '—'} · "
                f"{row['Indication'][:30] or '—'} · "
                f"{row['Confidence']}"
            )
            with st.expander(header):
                col_a, col_b = st.columns([1, 1])
                with col_a:
                    st.caption(f"**Lead Sponsor:** {row['Lead Sponsor']}")
                    st.caption(f"**Collaborators:** {row['Collaborators']}")
                    st.caption(
                        f"**Phase:** {row['Phase']}  |  "
                        f"**Status:** {row['Status']}"
                    )
                    st.caption(f"**Completion:** {row['Completion'] or '—'}")
                with col_b:
                    st.caption(f"**Trial Title:** {row['Trial Title']}")
                    st.markdown(f"[View on CT.gov ↗]({row['CT.gov Link']})")

                # 피어리뷰 논문
                st.write("")
                st.markdown("**Peer-reviewed Publications**")
                if row["peer_reviewed"]:
                    for p in row["peer_reviewed"]:
                        st.markdown(
                            f"- **[{p['title'][:120]}]({p['url']})** "
                            f"`{p['source']}`"
                        )
                else:
                    st.caption("No peer-reviewed publications found.")

                # 프리프린트
                if row["preprints"]:
                    st.write("")
                    st.markdown(
                        "**Preprints** "
                        "_(not peer-reviewed — use with caution)_"
                    )
                    for p in row["preprints"]:
                        st.markdown(
                            f"- [{p['title'][:120]}]({p['url']}) "
                            f"`{p['source']}`"
                        )

                # ── PDF 추출 버튼 ──────────────────────
                st.write("")
                st.divider()
                pdf_buf  = generate_pdf(row)
                filename = (
                    f"{row['NCT#']}_"
                    f"{(row['Drug'] or 'briefing').replace(' ', '_')}"
                    f"_briefing.pdf"
                )
                st.download_button(
                    label="Export Briefing PDF",
                    data=pdf_buf,
                    file_name=filename,
                    mime="application/pdf",
                    key=f"pdf_{row['NCT#']}",
                )
