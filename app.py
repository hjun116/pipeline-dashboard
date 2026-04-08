import streamlit as st
import requests
import pandas as pd

st.set_page_config(page_title="Pipeline Dashboard", layout="wide")
st.title("Partner Pipeline Intelligence Dashboard")
st.caption("Data sources: ClinicalTrials.gov · PubMed · Europe PMC")

# ── Search inputs ──────────────────────────────────────
col1, col2, col3 = st.columns([2, 1, 1])

with col1:
    query = st.text_input(
        "Search",
        placeholder="Sponsor name, drug name, or indication (e.g. Agenus, nivolumab, NSCLC)"
    )
with col2:
    phase_filter = st.selectbox(
        "Phase",
        ["All", "Phase 1", "Phase 2", "Phase 3", "Phase 4"]
    )
with col3:
    status_filter = st.selectbox(
        "Status",
        ["All", "RECRUITING", "ACTIVE_NOT_RECRUITING", "COMPLETED", "TERMINATED"]
    )

search_btn = st.button("Search", type="primary")

# ── CT.gov API ─────────────────────────────────────────
def fetch_trials(query, phase, status):
    url = "https://clinicaltrials.gov/api/v2/studies"
    params = {
        "query.term": query,
        "pageSize": 50,
        "format": "json",
        "fields": "NCTId,BriefTitle,OverallStatus,Phase,Condition,InterventionName,PrimaryCompletionDate,LeadSponsorName"
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

# ── PubMed search ──────────────────────────────────────
def search_pubmed(nct_id):
    """Return list of {title, url} matched by NCT# in PubMed."""
    search_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
    fetch_url  = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
    try:
        r = requests.get(search_url, params={
            "db": "pubmed", "term": nct_id, "retmode": "json", "retmax": 5
        }, timeout=8)
        ids = r.json()["esearchresult"]["idlist"]
        if not ids:
            return []
        r2 = requests.get(fetch_url, params={
            "db": "pubmed", "id": ",".join(ids), "retmode": "json"
        }, timeout=8)
        result = r2.json().get("result", {})
        papers = []
        for uid in ids:
            item = result.get(uid, {})
            title = item.get("title", "")
            if title:
                papers.append({
                    "title": title,
                    "url": f"https://pubmed.ncbi.nlm.nih.gov/{uid}/",
                    "source": "PubMed"
                })
        return papers
    except:
        return []

# ── Europe PMC search ──────────────────────────────────
def search_europepmc(nct_id):
    """Return list of {title, url} matched by NCT# in Europe PMC."""
    url = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
    try:
        r = requests.get(url, params={
            "query": f"CLINICAL_TRIAL_ID:{nct_id}",
            "format": "json",
            "pageSize": 5,
            "resultType": "core"
        }, timeout=8)
        items = r.json().get("resultList", {}).get("result", [])
        papers = []
        for item in items:
            title = item.get("title", "")
            pmid  = item.get("pmid", "")
            doi   = item.get("doi", "")
            if pmid:
                link = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
            elif doi:
                link = f"https://doi.org/{doi}"
            else:
                link = ""
            if title and link:
                papers.append({"title": title, "url": link, "source": "Europe PMC"})
        return papers
    except:
        return []

# ── Merge & deduplicate papers ─────────────────────────
def get_all_papers(nct_id):
    pubmed_papers = search_pubmed(nct_id)
    epmc_papers   = search_europepmc(nct_id)
    seen_titles   = set()
    merged = []
    for p in pubmed_papers + epmc_papers:
        key = p["title"][:60].lower()
        if key not in seen_titles:
            seen_titles.add(key)
            merged.append(p)
    return merged

# ── Confidence scoring ─────────────────────────────────
def get_confidence(papers, status):
    n = len(papers)
    sources = {p["source"] for p in papers}
    if n >= 2 or (n == 1 and len(sources) >= 1 and status == "COMPLETED"):
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

# ── Parse CT.gov response ──────────────────────────────
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
        sponsor    = sponsor_mod.get("leadSponsor", {}).get("name", "")
        completion = status_mod.get("primaryCompletionDateStruct", {}).get("date", "")

        rows.append({
            "nct_id":     nct,
            "Drug":       drug[:35],
            "Indication": (conditions[0] if conditions else "")[:40],
            "Phase":      phase_str,
            "Status":     overall,
            "Sponsor":    sponsor[:30],
            "Completion": completion,
        })
    return rows

# ── Phase filter (client-side) ─────────────────────────
def apply_phase_filter(rows, phase):
    if phase == "All":
        return rows
    return [r for r in rows if phase.upper().replace(" ", "_") in r["Phase"].upper().replace(" ", "_")]

# ── Main ───────────────────────────────────────────────
if search_btn and query:
    with st.spinner("Querying ClinicalTrials.gov..."):
        studies = fetch_trials(query, phase_filter, status_filter)

    if not studies:
        st.warning("No results found. Try a different keyword.")
    else:
        rows = parse_trials(studies)
        rows = apply_phase_filter(rows, phase_filter)

        progress = st.progress(0, text="Matching publications...")
        total = len(rows)

        for i, row in enumerate(rows):
            papers = get_all_papers(row["nct_id"])
            row["papers"]     = papers
            row["Confidence"] = get_confidence(papers, row["Status"])
            row["Publications"] = len(papers)
            row["Sources"]    = ", ".join(sorted({p["source"] for p in papers})) if papers else "—"
            progress.progress((i + 1) / total, text=f"Matching publications... {i+1}/{total}")

        progress.empty()

        # ── Summary metrics ────────────────────────────
        confirmed  = sum(1 for r in rows if "Confirmed"  in r["Confidence"])
        partial    = sum(1 for r in rows if "Partial"    in r["Confidence"])
        unverified = sum(1 for r in rows if "Unverified" in r["Confidence"])

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Total trials",    total)
        m2.metric("✅ Confirmed",    confirmed)
        m3.metric("⚠️ Partial",     partial)
        m4.metric("❌ Unverified",  unverified)

        st.divider()

        # ── Pipeline table ─────────────────────────────
        st.subheader("Pipeline Overview")

        df_display = pd.DataFrame([{
            "NCT#":         r["nct_id"],
            "Drug":         r["Drug"],
            "Indication":   r["Indication"],
            "Phase":        r["Phase"],
            "Status":       r["Status"],
            "Completion":   r["Completion"],
            "Confidence":   r["Confidence"],
            "Publications": r["Publications"],
            "Sources":      r["Sources"],
        } for r in rows])

        st.dataframe(df_display, use_container_width=True, hide_index=True)

        # ── Publication detail ─────────────────────────
        st.divider()
        st.subheader("Publication Detail by Trial")

        for row in rows:
            nct   = row["nct_id"]
            drug  = row["Drug"] or nct
            conf  = row["Confidence"]
            papers = row["papers"]

            with st.expander(f"{nct} · {drug} · {conf}"):
                if papers:
                    for p in papers:
                        st.markdown(f"- **[{p['title'][:120]}]({p['url']})** `{p['source']}`")
                else:
                    st.caption("No publications found in PubMed or Europe PMC.")

        # ── CSV export ─────────────────────────────────
        csv = df_display.to_csv(index=False).encode("utf-8-sig")
        st.download_button(
            "Export CSV",
            csv,
            f"{query}_pipeline.csv",
            "text/csv"
        )

elif search_btn and not query:
    st.warning("Please enter a search term.")
