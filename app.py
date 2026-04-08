import streamlit as st
import requests
import pandas as pd
from datetime import date, timedelta

st.set_page_config(page_title="Pipeline Dashboard", layout="wide")

# ── Sidebar: 모든 조작 UI ──────────────────────────────
with st.sidebar:
    st.title("Pipeline Dashboard")
    st.caption("ClinicalTrials.gov · PubMed · Europe PMC · OpenAlex · bioRxiv/medRxiv")
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
        ["All", "RECRUITING", "ACTIVE_NOT_RECRUITING", "COMPLETED", "TERMINATED"]
    )

    st.subheader("Date range")
    st.caption("Primary completion date. Narrower range = faster results.")
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

    # CSV 다운로드 버튼 자리 (검색 후 채워짐)
    download_placeholder = st.empty()

# ── 메인 영역 헤더 ─────────────────────────────────────
st.title("Partner Pipeline Intelligence")
if not search_btn:
    st.info(
        "Enter a sponsor name or keyword in the sidebar and click **Search** to begin. "
        "Tip: Narrowing the date range speeds up results significantly."
    )
    st.stop()

# ── API 함수들 ─────────────────────────────────────────
def fetch_trials(sponsor, keyword, status, date_from, date_to):
    url = "https://clinicaltrials.gov/api/v2/studies"
    terms = []
    if sponsor:
        terms.append(sponsor)
    if keyword:
        terms.append(keyword)
    query_term = " AND ".join(terms) if terms else ""
    params = {
        "query.term": query_term,
        "pageSize": 50,
        "format": "json",
        "fields": (
            "NCTId,BriefTitle,OverallStatus,Phase,Condition,"
            "InterventionName,PrimaryCompletionDate,"
            "LeadSponsorName,CollaboratorName"
        ),
        "filter.advanced": (
            f"AREA[PrimaryCompletionDate]RANGE[{date_from.strftime('%Y-%m-%d')},"
            f"{date_to.strftime('%Y-%m-%d')}]"
        )
    }
    if status != "All":
        params["filter.overallStatus"] = status
    try:
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        return r.json().get("studies", [])
    except Exception as e:
        st.error(f"CT.gov API error: {e}")
        return []

def search_pubmed(nct_id):
    try:
        r = requests.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
            params={"db": "pubmed", "term": nct_id, "retmode": "json", "retmax": 5},
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
                "title": result[uid].get("title", ""),
                "url":   f"https://pubmed.ncbi.nlm.nih.gov/{uid}/",
                "source": "PubMed",
                "pmid":  uid,
                "doi":   "",
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
                "resultType": "core"
            },
            timeout=8
        )
        items = r.json().get("resultList", {}).get("result", [])
        papers = []
        for item in items:
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
                params={"search": nct_id, "per_page": 5,
                        "select": "id,title,doi,pmid,primary_location"},
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
                else f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else ""
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
                        "title": title,
                        "url":   f"https://doi.org/{doi}",
                        "source": "bioRxiv" if server == "biorxiv" else "medRxiv",
                        "pmid": "", "doi": doi, "is_preprint": True,
                    })
        except:
            continue
    return papers

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
        if doi and doi in seen_dois:
            continue
        if title_key in seen_titles:
            continue
        if pmid:
            seen_pmids.add(pmid)
        if doi:
            seen_dois.add(doi)
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
    icons = {"PHASE1": "🔬", "PHASE2": "🧪", "PHASE3": "🚀", "PHASE4": "✅"}
    key = p.upper().replace(" ", "").replace("_", "")
    return f"{icons.get(key, '')} {p}" if p != "N/A" else p

def fmt_status(s):
    icons = {
        "COMPLETED":              "✅ Completed",
        "RECRUITING":             "🟢 Recruiting",
        "ACTIVE_NOT_RECRUITING":  "🔵 Active",
        "TERMINATED":             "🔴 Terminated",
        "WITHDRAWN":              "⚫ Withdrawn",
    }
    return icons.get(s.upper(), s)

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
        collab_str = ", ".join([c.get("name", "") for c in collabs[:2]]) if collabs else "—"
        completion = status_mod.get("primaryCompletionDateStruct", {}).get("date", "")
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
    return [r for r in rows if phase.upper().replace(" ", "_")
            in r["Phase"].upper().replace(" ", "_")]

# ── 검색 실행 ──────────────────────────────────────────
if not sponsor_input and not keyword_input:
    st.warning("Please enter a sponsor name or keyword in the sidebar.")
    st.stop()

with st.spinner("Querying ClinicalTrials.gov..."):
    studies = fetch_trials(sponsor_input, keyword_input, status_filter, date_from, date_to)

if not studies:
    st.warning("No results found. Try a different keyword or widen the date range.")
    st.stop()

rows  = parse_trials(studies)
rows  = apply_phase_filter(rows, phase_filter)
total = len(rows)

progress = st.progress(0, text="Matching publications...")
for i, row in enumerate(rows):
    peer_reviewed, preprints  = get_all_papers(row["nct_id"])
    row["peer_reviewed"]      = peer_reviewed
    row["preprints"]          = preprints
    row["Confidence"]         = get_confidence(peer_reviewed, row["Status_raw"])
    row["Pubs"]               = len(peer_reviewed)
    row["Preprints"]          = len(preprints)
    row["Pub Sources"]        = (
        ", ".join(sorted({p["source"] for p in peer_reviewed})) or "—"
    )
    progress.progress(
        (i + 1) / total,
        text=f"Matching publications... {i+1}/{total}"
    )
progress.empty()

# ── 사이드바 CSV 다운로드 (결과 나온 후 채움) ──────────
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
        "Export CSV",
        csv,
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

# ═══════════════════════════════════════════════════════
# Tab 1 — Dashboard
# ═══════════════════════════════════════════════════════
with tab1:
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total trials",   total)
    m2.metric("✅ Confirmed",   confirmed)
    m3.metric("⚠️ Partial",    partial)
    m4.metric("❌ Unverified", unverified)

    st.divider()
    st.subheader("Pipeline Overview")

    # Pubs 최대값 (ProgressColumn max 설정용)
    max_pubs = max((r["Pubs"] for r in rows), default=1) or 1

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

# ═══════════════════════════════════════════════════════
# Tab 2 — Deep Dive
# ═══════════════════════════════════════════════════════
with tab2:
    st.subheader("Publication Detail by Trial")
    st.caption(
        "Select a trial below to view peer-reviewed publications and preprints. "
        "Confidence is based on peer-reviewed sources only."
    )

    # 필터: Confidence 수준으로 Deep Dive 범위 좁히기
    conf_filter = st.selectbox(
        "Filter by Confidence",
        ["All", "✅ Confirmed", "⚠️ Partial", "❌ Unverified"],
        key="conf_filter"
    )

    filtered_rows = rows if conf_filter == "All" else [
        r for r in rows if conf_filter.split()[1] in r["Confidence"]
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
                    st.caption(f"**Phase:** {row['Phase']}  |  **Status:** {row['Status']}")
                    st.caption(f"**Completion:** {row['Completion'] or '—'}")
                with col_b:
                    st.caption(f"**Trial Title:** {row['Trial Title']}")
                    st.markdown(f"[View on CT.gov ↗]({row['CT.gov Link']})")

                st.write("")
                st.markdown("**Peer-reviewed Publications**")
                if row["peer_reviewed"]:
                    for p in row["peer_reviewed"]:
                        st.markdown(
                            f"- **[{p['title'][:120]}]({p['url']})** `{p['source']}`"
                        )
                else:
                    st.caption("No peer-reviewed publications found.")

                if row["preprints"]:
                    st.write("")
                    st.markdown(
                        "**Preprints** _(not peer-reviewed — use with caution)_"
                    )
                    for p in row["preprints"]:
                        st.markdown(
                            f"- [{p['title'][:120]}]({p['url']}) `{p['source']}`"
                        )
