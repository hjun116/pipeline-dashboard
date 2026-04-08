import re
import streamlit as st
import requests
import pandas as pd

st.set_page_config(page_title="Pipeline Dashboard", layout="wide")
st.title("Partner Pipeline Intelligence Dashboard")
st.caption("Data sources: ClinicalTrials.gov · PubMed · Europe PMC · SEC EDGAR")

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

# ── PubMed search ──────────────────────────────────────
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
                "title":  result[uid].get("title", ""),
                "url":    f"https://pubmed.ncbi.nlm.nih.gov/{uid}/",
                "source": "PubMed"
            }
            for uid in ids if result.get(uid, {}).get("title")
        ]
    except:
        return []

# ── Europe PMC search ──────────────────────────────────
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
                papers.append({"title": title, "url": link, "source": "Europe PMC"})
        return papers
    except:
        return []

# ── Merge & deduplicate papers ─────────────────────────
def get_all_papers(nct_id):
    seen, merged = set(), []
    for p in search_pubmed(nct_id) + search_europepmc(nct_id):
        key = p["title"][:60].lower()
        if key not in seen:
            seen.add(key)
            merged.append(p)
    return merged

# ── EDGAR: CIK 조회 ────────────────────────────────────
def get_cik(sponsor_name):
    headers = {"User-Agent": "pipeline-dashboard your@email.com"}
    try:
        r = requests.get(
            "https://efts.sec.gov/LATEST/search-index",
            params={"q": f'"{sponsor_name}"', "forms": "10-K"},
            headers=headers,
            timeout=8
        )
        hits = r.json().get("hits", {}).get("hits", [])
        for hit in hits:
            src       = hit.get("_source", {})
            entity_id = src.get("entity_id", "")
            names     = src.get("display_names", [])
            name      = names[0] if names else ""
            if entity_id:
                return str(entity_id).zfill(10), name
    except:
        pass
    try:
        r = requests.get(
            "https://www.sec.gov/cgi-bin/browse-edgar",
            params={
                "company": sponsor_name, "CIK": "", "type": "10-K",
                "dateb": "", "owner": "include", "count": "5",
                "search_text": "", "action": "getcompany", "output": "atom"
            },
            headers=headers,
            timeout=8
        )
        ciks        = re.findall(r'CIK=(\d+)', r.text)
        names_found = re.findall(r'<company-name>(.*?)</company-name>', r.text)
        if ciks:
            return ciks[0].zfill(10), (names_found[0] if names_found else sponsor_name)
    except:
        pass
    return None, None

# ── EDGAR: 공시 검색 ───────────────────────────────────
def fetch_edgar_filings(sponsor_name, drug_name, filing_types=["8-K", "10-K"], max_results=5):
    headers    = {"User-Agent": "pipeline-dashboard your@email.com"}
    cik, entity_display = get_cik(sponsor_name)
    query_term = f'"{drug_name}"' if drug_name else f'"{sponsor_name}"'
    params = {
        "q":         query_term,
        "forms":     ",".join(filing_types),
        "dateRange": "custom",
        "startdt":   "2020-01-01",
    }
    if cik:
        params["entity"] = sponsor_name
    try:
        r = requests.get(
            "https://efts.sec.gov/LATEST/search-index",
            params=params, headers=headers, timeout=10
        )
        r.raise_for_status()
        hits = r.json().get("hits", {}).get("hits", [])
    except:
        return [], entity_display

    filings, seen = [], set()
    for hit in hits:
        src             = hit.get("_source", {})
        form            = src.get("form_type", "")
        filed           = src.get("file_date", "")
        accession       = src.get("accession_no", "")
        hit_cik         = str(src.get("entity_id", "")).zfill(10)
        names           = src.get("display_names", [])
        entity          = names[0] if names else sponsor_name
        period          = src.get("period_of_report", "")

        if not accession or accession in seen:
            continue
        seen.add(accession)
        if cik and hit_cik and hit_cik != cik:
            continue

        accession_nodash = accession.replace("-", "")
        if hit_cik and accession_nodash:
            viewer_url = (
                f"https://www.sec.gov/Archives/edgar/data/"
                f"{int(hit_cik)}/{accession_nodash}/{accession}-index.htm"
            )
        else:
            viewer_url = (
                f"https://efts.sec.gov/LATEST/search-index"
                f"?q={requests.utils.quote(query_term)}&forms={form}"
            )

        filings.append({
            "Form":   form,
            "Filed":  filed,
            "Entity": entity[:50],
            "Period": period,
            "url":    viewer_url,
        })
        if len(filings) >= max_results:
            break

    return filings, entity_display

# ── Confidence scoring ─────────────────────────────────
def get_confidence(papers, status):
    n = len(papers)
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
                papers            = get_all_papers(row["nct_id"])
                row["papers"]     = papers
                row["Confidence"] = get_confidence(papers, row["Status"])
                row["Pubs"]       = len(papers)
                row["Pub Sources"]= ", ".join(sorted({p["source"] for p in papers})) or "—"
                progress.progress((i + 1) / total,
                                  text=f"Matching publications... {i+1}/{total}")
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
                "Completion", "Confidence", "Pubs", "Pub Sources", "CT.gov Link"
            ]]
            st.dataframe(
                df_linked,
                use_container_width=True,
                hide_index=True,
                column_config={
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

                    st.write("")
                    st.markdown("**Publications**")
                    if row["papers"]:
                        for p in row["papers"]:
                            st.markdown(
                                f"- **[{p['title'][:120]}]({p['url']})** `{p['source']}`"
                            )
                    else:
                        st.caption("No publications found in PubMed or Europe PMC.")

            # ── SEC Filings (Sponsor 단위, 1회만 호출) ──
            st.divider()
            st.subheader("Recent SEC Filings")

            edgar_sponsor = sponsor_input if sponsor_input else keyword_input
            edgar_drug    = keyword_input  if keyword_input  else ""

            st.caption(
                f"Searching EDGAR for **{edgar_sponsor}** filings"
                + (f" mentioning **{edgar_drug}**" if edgar_drug else "")
                + " · Filing types: 8-K, 10-K"
            )

            with st.spinner("Fetching SEC filings from EDGAR..."):
                filings, entity_display = fetch_edgar_filings(edgar_sponsor, edgar_drug)

            if entity_display:
                st.caption(f"EDGAR matched entity: **{entity_display}**")

            if filings:
                df_filings = pd.DataFrame(filings)[["Form", "Filed", "Entity", "Period", "url"]]
                st.dataframe(
                    df_filings,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "url": st.column_config.LinkColumn(
                            "EDGAR Filing", display_text="Open ↗"
                        )
                    }
                )
            else:
                st.caption("No filings auto-matched.")

            # fallback: 직접 검색 링크 항상 표시
            edgar_fallback = (
                f"https://efts.sec.gov/LATEST/search-index"
                f"?q=%22{requests.utils.quote(edgar_drug or edgar_sponsor)}%22"
                f"&entity={requests.utils.quote(edgar_sponsor)}"
                f"&forms=8-K,10-K&dateRange=custom&startdt=2020-01-01"
            )
            st.markdown(
                f"Direct EDGAR search → "
                f"[{edgar_sponsor} · {edgar_drug or 'all filings'}]({edgar_fallback})"
            )

            # ── CSV export ─────────────────────────────
            df_export = pd.DataFrame(rows)[[
                "NCT#", "Lead Sponsor", "Collaborators",
                "Drug", "Indication", "Phase", "Status",
                "Completion", "Confidence", "Pubs", "Pub Sources", "CT.gov Link"
            ]]
            csv   = df_export.to_csv(index=False).encode("utf-8-sig")
            label = sponsor_input or keyword_input
            st.download_button("Export CSV", csv, f"{label}_pipeline.csv", "text/csv")
