import streamlit as st
import requests
import pandas as pd

st.set_page_config(page_title="Pipeline Dashboard", layout="wide")
st.title("파트너사 파이프라인 임상 현황")

# ── 검색 입력 ──────────────────────────────────────────
col1, col2, col3 = st.columns([2, 1, 1])

with col1:
    sponsor = st.text_input("Sponsor명 / 약물명 / Indication 입력", placeholder="예: Agenus, nivolumab, NSCLC")
with col2:
    phase_filter = st.selectbox("Phase 필터", ["전체", "Phase 1", "Phase 2", "Phase 3", "Phase 4"])
with col3:
    status_filter = st.selectbox("Status 필터", ["전체", "RECRUITING", "ACTIVE_NOT_RECRUITING", "COMPLETED"])

search_btn = st.button("검색", type="primary")

# ── CT.gov API 쿼리 ────────────────────────────────────
def fetch_trials(query, phase, status):
    url = "https://clinicaltrials.gov/api/v2/studies"
    params = {
        "query.term": query,
        "pageSize": 50,
        "format": "json",
        "fields": "NCTId,BriefTitle,OverallStatus,Phase,Condition,InterventionName,PrimaryCompletionDate,LeadSponsorName"
    }
    if phase != "전체":
        params["filter.advanced"] = f'AREA[Phase]{phase.replace(" ", "_").upper()}'
    if status != "전체":
        params["filter.overallStatus"] = status

    try:
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        return r.json().get("studies", [])
    except Exception as e:
        st.error(f"CT.gov API 오류: {e}")
        return []

# ── PubMed 논문 매칭 ───────────────────────────────────
def check_pubmed(nct_id):
    url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
    params = {
        "db": "pubmed",
        "term": nct_id,
        "retmode": "json"
    }
    try:
        r = requests.get(url, params=params, timeout=8)
        count = int(r.json()["esearchresult"]["count"])
        return count > 0
    except:
        return False

# ── Confidence 판정 ────────────────────────────────────
def get_confidence(ct_found, pubmed_found, status):
    if ct_found and pubmed_found:
        return "✅ Confirmed"
    elif ct_found and not pubmed_found:
        if status == "COMPLETED":
            return "❌ Unverified (NOT PUBLISHED)"
        elif status in ["RECRUITING", "ACTIVE_NOT_RECRUITING"]:
            return "❌ Unverified (ONGOING)"
        else:
            return "⚠️ Partial"
    else:
        return "⚠️ Partial"

# ── 결과 파싱 ──────────────────────────────────────────
def parse_trials(studies):
    rows = []
    for s in studies:
        proto = s.get("protocolSection", {})
        id_mod = proto.get("identificationModule", {})
        status_mod = proto.get("statusModule", {})
        design_mod = proto.get("designModule", {})
        cond_mod = proto.get("conditionsModule", {})
        intervention_mod = proto.get("armsInterventionsModule", {})
        sponsor_mod = proto.get("sponsorCollaboratorsModule", {})

        nct = id_mod.get("nctId", "")
        title = id_mod.get("briefTitle", "")[:60]
        overall_status = status_mod.get("overallStatus", "")
        phases = design_mod.get("phases", ["N/A"])
        phase_str = ", ".join(phases) if phases else "N/A"
        conditions = cond_mod.get("conditions", [])
        condition_str = conditions[0] if conditions else ""
        interventions = intervention_mod.get("interventions", [])
        drug = interventions[0].get("name", "") if interventions else ""
        lead_sponsor = sponsor_mod.get("leadSponsor", {}).get("name", "")
        completion = status_mod.get("primaryCompletionDateStruct", {}).get("date", "")

        rows.append({
            "NCT#": nct,
            "약물명": drug[:30],
            "Indication": condition_str[:35],
            "Phase": phase_str,
            "Status": overall_status,
            "Sponsor": lead_sponsor[:25],
            "완료 예정": completion,
            "_nct_raw": nct,
            "_status_raw": overall_status,
        })
    return rows

# ── 메인 실행 ──────────────────────────────────────────
if search_btn and sponsor:
    with st.spinner("CT.gov 검색 중..."):
        studies = fetch_trials(sponsor, phase_filter, status_filter)

    if not studies:
        st.warning("검색 결과가 없어. 키워드를 바꿔서 다시 시도해봐.")
    else:
        rows = parse_trials(studies)

        with st.spinner("PubMed 논문 매칭 중..."):
            for row in rows:
                pubmed_hit = check_pubmed(row["_nct_raw"])
                row["Confidence"] = get_confidence(True, pubmed_hit, row["_status_raw"])
                row["PubMed"] = "있음" if pubmed_hit else "없음"

        # 표시용 컬럼만 추출
        df = pd.DataFrame(rows)
        display_cols = ["NCT#", "약물명", "Indication", "Phase", "Status", "완료 예정", "Confidence", "PubMed"]
        df_display = df[display_cols]

        # 요약 지표
        total = len(df)
        confirmed = sum(1 for r in rows if "Confirmed" in r["Confidence"])
        partial = sum(1 for r in rows if "Partial" in r["Confidence"])
        unverified = sum(1 for r in rows if "Unverified" in r["Confidence"])

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("전체", total)
        m2.metric("✅ Confirmed", confirmed)
        m3.metric("⚠️ Partial", partial)
        m4.metric("❌ Unverified", unverified)

        st.divider()
        st.dataframe(df_display, use_container_width=True, hide_index=True)

        # CSV 다운로드
        csv = df_display.to_csv(index=False).encode("utf-8-sig")
        st.download_button("CSV 내보내기", csv, f"{sponsor}_pipeline.csv", "text/csv")

elif search_btn and not sponsor:
    st.warning("검색어를 입력해줘.")
