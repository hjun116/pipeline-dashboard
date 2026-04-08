import streamlit as st
import requests
import pandas as pd

st.set_page_config(page_title="Pipeline Dashboard", layout="wide")
st.title("Partner Pipeline Intelligence Dashboard")
st.caption("Data sources: ClinicalTrials.gov · PubMed · Europe PMC · OpenAlex · bioRxiv/medRxiv")

# ── Search inputs ──────────────────────────────────────
st.subheader("Search")

row1_col1, row1_col2 = st.columns([2, 2])
with row1_col1:
    sponsor_input = st.text_input(
        "Sponsor / Lead Organization",
        placeholder="e.g. Agenus, Merck, BioNTech"
    )
with row1_col2:
    keyword_input = st.text_input(
        "Drug name / Indication / Keyword",
        placeholder="e.g. nivolumab, NSCLC, PD-1"
    )

row2_col1, row2_col2, row2_col3 = st.columns([1, 1, 1])
with row2_col1:
    phase_filter = st.selectbox(
        "Phase",
        ["All", "Phase 1", "Phase 2", "Phase 3", "Phase 4"]
    )
with row2_col2:
    status_filter = st.selectbox(
        "Status",
        ["All", "RECRUITING", "ACTIVE_NOT_RECRUITING", "COMPLETED", "TERMINATED"]
    )
with row2_col3:
    st.write("")
    st.write("")
    search_btn = st.button("Search", type="primary", use_container_width=True)

# ── CT.gov API ─────────────────────────────────────────
def fetch_trials(sponsor, keyword, status):
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

# ── PubMed ─────────────────────────────────────────────
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
        papers = []
        for uid in ids:
            item  = result.get(uid, {})
            title = item.get("title", "")
            if not title:
                continue
            # 중복 제거 키: PMID 우선
            papers.append({
                "title":   title,
                "url":     f"https://pubmed.ncbi.nlm.nih.gov/{uid}/",
                "source":  "PubMed",
                "pmid":    uid,
                "doi":     "",
                "is_preprint": False,
            })
        return papers
    except:
        return []

# ── Europe PMC ─────────────────────────────────────────
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
                else f"https://doi.org/{doi}" if doi
                else ""
            )
            if title and link:
                papers.append({
                    "title":   title,
                    "url":     link,
                    "source":  "Europe PMC",
                    "pmid":    pmid,
                    "doi":     doi,
                    "is_preprint": False,
                })
        return papers
    except:
        return []

# ── OpenAlex ───────────────────────────────────────────
def search_openalex(nct_id):
    """
    OpenAlex에서 NCT# 기반 검색.
    clinical_trial_number 필드 우선, 없으면 full-text 검색 fallback.
    """
    try:
        # 1차: clinical_trial_number 필드 직접 매칭
        r = requests.get(
            "https://api.openalex.org/works",
            params={
                "filter":     f"clinical_trial_number:{nct_id}",
                "per_page":   5,
                "select":     "id,title,doi,pmid,primary_location",
            },
            headers={"User-Agent": "pipeline-dashboard your@email.com"},
            timeout=8
        )
        results = r.json().get("results", [])

        # 2차 fallback: abstract/title 텍스트 검색
        if not results:
            r2 = requests.get(
                "https://api.openalex.org/works",
                params={
                    "search":   nct_id,
                    "per_page": 5,
                    "select":   "id,title,doi,pmid,primary_location",
                },
                headers={"User-Agent": "pipeline-dashboard your@email.com"},
                timeout=8
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
                    "title":   title,
                    "url":     url,
                    "source":  "OpenAlex",
                    "pmid":    pmid,
                    "doi":     doi,
                    "is_preprint": False,
                })
        return papers
    except:
        return []

# ── bioRxiv / medRxiv ──────────────────────────────────
def search_biorxiv(nct_id):
    """
    bioRxiv/medRxiv API에서 NCT# 텍스트 검색.
    프리프린트이므로 is_preprint=True 플래그.
    """
    papers = []
    for server in ["biorxiv", "medrxiv"]:
        try:
            r = requests.get(
                f"https://api.biorxiv.org/details/{server}/{nct_id}/na/json",
                timeout=8
            )
            items = r.json().get("collection", [])
            for item in items:
                title = item.get("title", "")
                doi   = item.get("doi", "")
                if title and doi:
                    papers.append({
                        "title":   title,
                        "url":     f"https://doi.org/{doi}",
                        "source":  f"{'bioRxiv' if server == 'biorxiv' else 'medRxiv'}",
                        "pmid":    "",
                        "doi":     doi,
                        "is_preprint": True,
                    })
        except:
            continue
    return papers

# ── 중복 제거 통합 함수 ────────────────────────────────
def get_all_papers(nct_id):
    """
    우선순위: PubMed → Europe PMC → OpenAlex → bioRxiv/medRxiv
    중복 제거 키 우선순위: PMID → DOI → 제목 앞 60자
    피어리뷰 논문(is_preprint=False)과 프리프린트 분리 반환.
    """
    all_raw = (
        search_pubmed(nct_id)
        + search_europepmc(nct_id)
        + search_openalex(nct_id)
        + search_biorxiv(nct_id)
    )

    seen_pmids  = set()
    seen_dois   = set()
    seen_titles = set()

    peer_reviewed = []
    preprints     = []

    for p in all_raw:
        pmid  = p.get("pmid", "").strip()
        doi   = p.get("doi",  "").strip().lower()
        title_key = p["title"][:60].lower()

        # 중복 체크
        if pmid and pmid in seen_pmids:
            continue
        if doi and doi in seen_dois:
            continue
        if title_key in seen_titles:
            continue

        # seen에 등록
        if pmid:
            seen_pmids.add(pmid)
        if doi:
            seen_dois.add(doi)
        seen_titles.add(title_key)

        # 분류
        if p["is_preprint"]:
            preprints.append(p)
        else:
            peer_reviewed.append(p)

    return peer_reviewed, preprints

# ── Confidence scoring ─────────────────────────────────
def get_confidence(peer_reviewed, status):
    """
    Confidence 판정은 피어리뷰 논문만 기준.
    프리프린트는 별도 표기, 판정에 미포함.
    """
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
            "Phase":         phase_str,
            "Status":        overall,
            "Completion":    completion,
            "Trial Title":   brief[:80],
            "CT.gov Link":   f"https://clinicaltrials.gov/study/{nct}",
        })
    return rows

# ── Phase filter ───────────────────────────────────────
def apply_phase_filter(rows, phase):
    if phase == "All":
        return rows
    return [r for r in rows if phase.upper().replace(" ", "_")
            in r["Phase"].upper().replace(" ", "_")]

# ── Main ───────────────────────────────────────────────
if search_btn:
    if not sponsor_input and not keyword_input:
        st.warning("Please enter a sponsor name or keyword.")
    else:
        with st.spinner("Querying ClinicalTrials.gov..."):
            studies = fetch_trials(sponsor_input, keyword_input, status_filter)

        if not studies:
            st.warning("No results found. Try a different keyword.")
        else:
            rows  = parse_trials(studies)
            rows  = apply_phase_filter(rows, phase_filter)
            total = len(rows)

            progress = st.progress(0, text="Matching publications...")
            for i, row in enumerate(rows):
                peer_reviewed, preprints = get_all_papers(row["nct_id"])
                row["peer_reviewed"] = peer_reviewed
                row["preprints"]     = preprints
                row["Confidence"]    = get_confidence(peer_reviewed, row["Status"])
                row["Pubs"]          = len(peer_reviewed)
                row["Preprints"]     = len(preprints)
                row["Pub Sources"]   = (
                    ", ".join(sorted({p["source"] for p in peer_reviewed})) or "—"
                )
                progress.progress(
                    (i + 1) / total,
                    text=f"Matching publications... {i+1}/{total}"
                )
            progress.empty()

            # ── Summary metrics ────────────────────────
            confirmed  = sum(1 for r in rows if "Confirmed"  in r["Confidence"])
            partial    = sum(1 for r in rows if "Partial"    in r["Confidence"])
            unverified = sum(1 for r in rows if "Unverified" in r["Confidence"])

            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Total trials",   total)
            m2.metric("✅ Confirmed",   confirmed)
            m3.metric("⚠️ Partial",    partial)
            m4.metric("❌ Unverified", unverified)

            st.divider()

            # ── Pipeline table ─────────────────────────
            st.subheader("Pipeline Overview")
            df_linked = pd.DataFrame(rows)[[
                "NCT#", "Lead Sponsor", "Collaborators",
                "Drug", "Indication", "Phase", "Status",
                "Completion", "Confidence", "Pubs", "Preprints",
                "Pub Sources", "CT.gov Link"
            ]]
            st.dataframe(
                df_linked,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Pubs":      st.column_config.NumberColumn("Pubs (peer-reviewed)"),
                    "Preprints": st.column_config.NumberColumn("Preprints"),
                    "CT.gov Link": st.column_config.LinkColumn(
                        "CT.gov", display_text="Open ↗"
                    )
                }
            )

            # ── Publication detail ─────────────────────
            st.divider()
            st.subheader("Publication Detail by Trial")

            for row in rows:
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

                    # 프리프린트 — 별도 섹션, 경고 문구 포함
                    if row["preprints"]:
                        st.write("")
                        st.markdown("**Preprints** _(not peer-reviewed — use with caution)_")
                        for p in row["preprints"]:
                            st.markdown(
                                f"- [{p['title'][:120]}]({p['url']}) "
                                f"`{p['source']}`"
                            )

            # ── CSV export ─────────────────────────────
            df_export = pd.DataFrame(rows)[[
                "NCT#", "Lead Sponsor", "Collaborators",
                "Drug", "Indication", "Phase", "Status",
                "Completion", "Confidence", "Pubs", "Preprints",
                "Pub Sources", "CT.gov Link"
            ]]
            csv   = df_export.to_csv(index=False).encode("utf-8-sig")
            label = sponsor_input or keyword_input
            st.download_button(
                "Export CSV", csv, f"{label}_pipeline.csv", "text/csv"
            )
