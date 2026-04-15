import os
import tempfile
import pandas as pd
import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
from calculator import evaluate_excel

st.set_page_config(
    page_title="건물 노후화 자동 평가 대시보드",
    page_icon="🏢",
    layout="wide",
)

# =========================
# 컬러
# =========================
BG = "#F6F8FB"
WHITE = "#FFFFFF"
CARD = "#FFFFFF"
CARD_SOFT = "#FCFCFD"
TEXT = "#191F28"
SUB = "#8B95A1"
LINE = "#E5E8EB"

# 건물별 고정 색상
BUILDING_COLORS = {
    "A동": "#8B80F9",  # 보라
    "B동": "#62C4A3",  # 민트
    "C동": "#F3A76F",  # 오렌지
    "D동": "#7DB2F8",  # 블루
}

# 부위별 색상
CATEGORY_COLORS = {
    "외벽": "#8B80F9",
    "창호": "#62C4A3",
    "배관": "#F3A76F",
    "설비": "#7DB2F8",
}

AGING_WEIGHTS_DISPLAY = {
    "외벽": 25,
    "창호": 15,
    "배관": 30,
    "설비": 30,
}

# =========================
# 카테고리 / 비용 추정 설정
# =========================
BUILDING_TYPE_OPTIONS = ["아파트", "학교", "병원", "데이터센터"]

# 발표용 대략 단가 모델 (원/㎡)
# 실제 실무 적용 시 표준품셈 + 표준시장단가 + 수량산출서 기준으로 조정
CATEGORY_BASE_COST_PER_M2 = {
    "아파트": {
        "외벽": 180000,
        "창호": 220000,
        "배관": 260000,
        "설비": 300000,
    },
    "학교": {
        "외벽": 200000,
        "창호": 240000,
        "배관": 290000,
        "설비": 330000,
    },
    "병원": {
        "외벽": 260000,
        "창호": 300000,
        "배관": 360000,
        "설비": 430000,
    },
    "데이터센터": {
        "외벽": 320000,
        "창호": 360000,
        "배관": 450000,
        "설비": 620000,
    },
}

# 간접비/일반관리비/부가가치세를 단순 반영한 계수
INDIRECT_COST_MULTIPLIER = 1.18

def safe_round(v):
    try:
        return round(float(v), 1)
    except Exception:
        return v

def format_krw(v):
    try:
        return f"{int(round(float(v))):,}원"
    except Exception:
        return "-"

def format_eok(v):
    try:
        v = float(v)
        if v >= 100000000:
            return f"{v / 100000000:.2f}억원"
        elif v >= 10000000:
            return f"{v / 10000000:.2f}천만원"
        else:
            return f"{int(round(v)):,}원"
    except Exception:
        return "-"

def aging_grade(score: float) -> str:
    if score >= 80:
        return "즉시 교체"
    elif score >= 50:
        return "보수 우선"
    elif score >= 25:
        return "관찰 필요"
    else:
        return "양호"

def urgency_grade(score: float) -> str:
    if score >= 80:
        return "긴급 보수"
    elif score >= 50:
        return "우선 보수"
    else:
        return "양호"

def badge_html(label: str) -> str:
    styles = {
        "즉시 교체": ("#FDEAEA", "#B42318"),
        "보수 우선": ("#FFF1E8", "#C2410C"),
        "관찰 필요": ("#FEF3C7", "#92400E"),
        "양호": ("#E8F5E9", "#2E7D32"),
        "긴급 보수": ("#FDEAEA", "#B42318"),
        "우선 보수": ("#FFF1E8", "#C2410C"),
    }
    bg, fg = styles.get(label, ("#EEF2FF", "#4338CA"))
    return f"""
    <span style="
        display:inline-block;
        padding:6px 12px;
        border-radius:999px;
        background:{bg};
        color:{fg};
        font-size:14px;
        font-weight:700;
        line-height:1;
    ">{label}</span>
    """

def part_badge_html(label: str) -> str:
    color = CATEGORY_COLORS.get(label, "#6B7280")
    return f"""
    <span style="
        display:inline-block;
        padding:6px 12px;
        border-radius:999px;
        background:#F4F6F8;
        color:{color};
        font-size:14px;
        font-weight:700;
        line-height:1;
        border:1px solid #E5E8EB;
    ">{label} 우선</span>
    """

def render_html_table(df: pd.DataFrame):
    headers = df.columns.tolist()
    rows_html = ""

    for _, row in df.iterrows():
        row_cells = []
        for col in headers:
            val = row[col]

            if col == "건물":
                color = BUILDING_COLORS.get(str(val), TEXT)
                cell = f'<td style="font-weight:700; color:{color};">{val}</td>'
            elif col == "등급":
                cell = f"<td>{badge_html(str(val))}</td>"
            elif col == "가장 시급":
                cell = f"<td>{part_badge_html(str(val))}</td>"
            else:
                cell = f"<td>{val}</td>"

            row_cells.append(cell)

        rows_html += "<tr>" + "".join(row_cells) + "</tr>"

    table_html = f"""
    <table class="custom-table">
        <thead>
            <tr>{''.join([f'<th>{h}</th>' for h in headers])}</tr>
        </thead>
        <tbody>
            {rows_html}
        </tbody>
    </table>
    """
    st.markdown(table_html, unsafe_allow_html=True)

def card_html(rank, building, score, grade, details, urgent_part):
    return f"""
    <div class="summary-card">
        <div class="rank-text">{rank}위</div>
        <div class="building-name">{building}</div>
        <div class="big-score">{score:.1f}</div>
        <div style="margin:10px 0 14px 0;">{badge_html(grade)}</div>
        <div class="detail-text">{details}</div>
        <div style="margin-top:14px;">{part_badge_html(urgent_part)}</div>
    </div>
    """

def cost_card_html(title, value, sub_text):
    return f"""
    <div class="cost-mini-card">
        <div class="cost-mini-title">{title}</div>
        <div class="cost-mini-value">{value}</div>
        <div class="cost-mini-sub">{sub_text}</div>
    </div>
    """

# =========================
# 비용 추정 함수
# =========================
def estimate_repair_scope_ratio(score: float, urgency: float) -> float:
    s = float(score)
    u = float(urgency)

    if s < 25:
        base = 0.04
    elif s < 50:
        base = 0.12
    elif s < 80:
        base = 0.26
    else:
        base = 0.45

    urgency_boost = 0.0
    if u >= 80:
        urgency_boost = 0.10
    elif u >= 50:
        urgency_boost = 0.05

    ratio = min(base + urgency_boost, 0.70)
    return ratio

def estimate_building_cost(category: str, area_m2: float, row_age, row_urg):
    unit_map = CATEGORY_BASE_COST_PER_M2[category]

    parts = {
        "외벽": {
            "score": float(row_age["외벽(100)"]),
            "urgency": float(row_urg["외벽 긴급도(100)"]),
        },
        "창호": {
            "score": float(row_age["창호(100)"]),
            "urgency": float(row_urg["창호 긴급도(100)"]),
        },
        "배관": {
            "score": float(row_age["배관(100)"]),
            "urgency": float(row_urg["배관 긴급도(100)"]),
        },
        "설비": {
            "score": float(row_age["설비(100)"]),
            "urgency": float(row_urg["설비 긴급도(100)"]),
        },
    }

    rows = []
    total_direct = 0.0

    for part, info in parts.items():
        score = info["score"]
        urgency = info["urgency"]
        unit_cost = unit_map[part]
        repair_ratio = estimate_repair_scope_ratio(score, urgency)

        direct_cost = area_m2 * unit_cost * repair_ratio
        total_direct += direct_cost

        rows.append({
            "부위": part,
            "노후도": round(score, 1),
            "긴급도": round(urgency, 1),
            "기준단가(원/㎡)": int(unit_cost),
            "보수범위비율": round(repair_ratio * 100, 1),
            "예상공사비(직접공사비)": direct_cost,
        })

    detail_df = pd.DataFrame(rows)
    total_cost = total_direct * INDIRECT_COST_MULTIPLIER
    cost_per_m2 = total_cost / area_m2 if area_m2 > 0 else 0.0

    return {
        "detail_df": detail_df,
        "direct_cost": total_direct,
        "total_cost": total_cost,
        "cost_per_m2": cost_per_m2,
    }

# =========================
# CSS
# =========================
st.markdown(f"""
<style>
html, body, [data-testid="stAppViewContainer"] {{
    background: {BG} !important;
}}

body {{
    color: {TEXT};
}}

[data-testid="stHeader"] {{
    background: transparent !important;
    height: 0px !important;
}}

.block-container {{
    padding-top: 3rem !important;
    padding-bottom: 2.6rem;
    padding-left: 2.4rem;
    padding-right: 2.4rem;
    max-width: 100%;
}}

.main-title-wrap {{
    position: relative;
    z-index: 999;
    background: {BG};
    padding-top: 1.5rem;
    padding-bottom: 1.1rem;
    margin-bottom: 0.45rem;
    overflow: visible !important;
}}

.main-title {{
    font-size: 3rem;
    font-weight: 900;
    color: {TEXT} !important;
    line-height: 1.35 !important;
    letter-spacing: -0.045em;
    margin: 0;
    padding: 0;
    display: block;
    white-space: normal !important;
    word-break: keep-all;
    overflow: visible !important;
    -webkit-text-fill-color: {TEXT} !important;
}}

.sub-title {{
    font-size: 1.08rem;
    color: {SUB} !important;
    margin-top: 0.9rem;
    margin-bottom: 0.2rem;
    line-height: 1.6;
    -webkit-text-fill-color: {SUB} !important;
}}

.top-note {{
    font-size: 0.98rem;
    color: {SUB} !important;
    margin-bottom: 1.15rem;
    line-height: 1.6;
    -webkit-text-fill-color: {SUB} !important;
}}

div[data-baseweb="tab-list"] {{
    gap: 24px;
    border-bottom: 1px solid {LINE};
    margin-bottom: 1.5rem;
}}

button[data-baseweb="tab"] {{
    padding: 12px 0 16px 0 !important;
    color: {SUB} !important;
    font-weight: 700 !important;
    font-size: 1rem !important;
    background: transparent !important;
}}

button[aria-selected="true"] {{
    color: {TEXT} !important;
    border-bottom: 3px solid {TEXT} !important;
    border-radius: 0 !important;
}}

.soft-card {{
    background: {CARD_SOFT};
    border: 1px solid {LINE};
    border-radius: 28px;
    padding: 24px 26px;
    box-shadow: 0 3px 14px rgba(17, 24, 39, 0.04);
    margin-bottom: 24px;
}}

.summary-card {{
    background: {CARD};
    border: 1px solid {LINE};
    border-radius: 28px;
    padding: 24px 22px;
    text-align: center;
    min-height: 300px;
    box-shadow: 0 3px 14px rgba(17, 24, 39, 0.05);
}}

.rank-text {{
    color: #B0B8C1;
    font-size: 17px;
    margin-bottom: 6px;
}}

.building-name {{
    font-size: 18px;
    font-weight: 700;
    margin-bottom: 10px;
    color: {TEXT};
}}

.big-score {{
    font-size: 44px;
    font-weight: 800;
    line-height: 1.05;
    color: {TEXT};
}}

.detail-text {{
    color: {SUB};
    font-size: 14px;
    line-height: 1.8;
}}

.section-title {{
    font-size: 1.18rem;
    font-weight: 800;
    color: {TEXT};
    margin-bottom: 1rem;
    letter-spacing: -0.01em;
}}

.custom-table {{
    width: 100%;
    border-collapse: collapse;
    background: {CARD};
    border-radius: 20px;
    overflow: hidden;
}}

.custom-table thead tr {{
    border-bottom: 1px solid #EEF2F6;
}}

.custom-table th {{
    text-align: left;
    color: {SUB};
    font-weight: 700;
    padding: 14px 16px;
    font-size: 15px;
    background: #FBFCFD;
}}

.custom-table td {{
    padding: 14px 16px;
    border-bottom: 1px solid #F2F4F6;
    font-size: 15px;
    color: {TEXT};
}}

.custom-table tbody tr:last-child td {{
    border-bottom: none;
}}

div[data-testid="stPlotlyChart"] {{
    border-radius: 24px;
    overflow: hidden;
    background: transparent;
    margin-top: 6px;
    padding-top: 4px;
}}

.js-plotly-plot, .plotly, .plot-container {{
    border-radius: 24px !important;
    overflow: hidden !important;
}}

div[data-testid="stFileUploader"] {{
    background: {CARD};
    border: 1px solid {LINE};
    border-radius: 20px;
    padding: 10px 14px;
    margin-bottom: 0.7rem;
}}

.stRadio > div {{
    flex-direction: row;
    gap: 12px;
}}

div[data-testid="column"] > div {{
    height: 100%;
}}

div[data-testid="stProgressBar"] > div {{
    border-radius: 999px;
    overflow: hidden;
}}

div[data-testid="stProgressBar"] div[role="progressbar"] {{
    border-radius: 999px;
}}

[data-testid="stMarkdownContainer"] p {{
    color: {TEXT};
}}

.cost-mini-card {{
    background: {CARD};
    border: 1px solid {LINE};
    border-radius: 22px;
    padding: 18px 18px 16px 18px;
    min-height: 132px;
    box-shadow: 0 3px 14px rgba(17, 24, 39, 0.04);
}}

.cost-mini-title {{
    color: {SUB};
    font-size: 14px;
    margin-bottom: 8px;
    font-weight: 700;
}}

.cost-mini-value {{
    color: {TEXT};
    font-size: 28px;
    font-weight: 800;
    line-height: 1.2;
    margin-bottom: 8px;
}}

.cost-mini-sub {{
    color: {SUB};
    font-size: 13px;
    line-height: 1.6;
}}

.cost-note {{
    color: {SUB};
    font-size: 14px;
    line-height: 1.7;
    margin-top: 8px;
}}
</style>
""", unsafe_allow_html=True)

# =========================
# 상단 타이틀
# =========================
st.markdown(
    """
    <div class="main-title-wrap">
        <div class="main-title">건물 노후화 자동 평가 대시보드</div>
        <div class="sub-title">건물별 노후도, 긴급도, 상세 비교를 한 번에 볼 수 있는 분석 대시보드</div>
    </div>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    f"""
    <div class="top-note">
        외벽 {AGING_WEIGHTS_DISPLAY["외벽"]}% · 창호 {AGING_WEIGHTS_DISPLAY["창호"]}% ·
        배관 {AGING_WEIGHTS_DISPLAY["배관"]}% · 설비 {AGING_WEIGHTS_DISPLAY["설비"]}% 가중치 적용 —
        점수가 높을수록 노후화·긴급도 심각
    </div>
    """,
    unsafe_allow_html=True
)

# =========================
# 파일 업로드
# =========================
uploaded_file = st.file_uploader("엑셀 파일 업로드", type=["xlsx"])

if uploaded_file is None:
    st.info("평가 입력표 엑셀 파일을 업로드하세요.")
    st.stop()

with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
    tmp.write(uploaded_file.getbuffer())
    temp_path = tmp.name

try:
    result_df, ranking_df, urgency_df = evaluate_excel(temp_path)
except Exception as e:
    st.error(f"엑셀 계산 중 오류가 발생했습니다: {e}")
    st.stop()
finally:
    if os.path.exists(temp_path):
        os.remove(temp_path)

result_df = result_df.copy()
ranking_df = ranking_df.copy()
urgency_df = urgency_df.copy()

# =========================
# 긴급도 가공
# =========================
urg_cols = ["외벽 긴급도(100)", "창호 긴급도(100)", "배관 긴급도(100)", "설비 긴급도(100)"]
urgency_df["긴급도 최대값"] = urgency_df[urg_cols].max(axis=1)

def get_most_urgent_part(row):
    pairs = {
        "외벽": row["외벽 긴급도(100)"],
        "창호": row["창호 긴급도(100)"],
        "배관": row["배관 긴급도(100)"],
        "설비": row["설비 긴급도(100)"],
    }
    return max(pairs, key=pairs.get)

urgency_df["가장 시급"] = urgency_df.apply(get_most_urgent_part, axis=1)

summary_df = result_df[["건물명", "외벽(100)", "창호(100)", "배관(100)", "설비(100)", "노후도 종합(100)"]].copy()
summary_df = summary_df.merge(
    urgency_df[["건물명", "긴급도 최대값", "가장 시급"]],
    on="건물명",
    how="left"
)
summary_df = summary_df.sort_values("노후도 종합(100)", ascending=False).reset_index(drop=True)
summary_df["순위"] = summary_df.index + 1
summary_df["등급"] = summary_df["노후도 종합(100)"].apply(aging_grade)

# =========================
# 추가 설정: 건물 카테고리 / 연면적
# =========================
st.markdown('<div class="soft-card">', unsafe_allow_html=True)
st.markdown('<div class="section-title">카테고리 및 보수비 산정 기준</div>', unsafe_allow_html=True)

st.markdown(
    """
    <div class="cost-note">
        건물별 카테고리와 연면적을 입력하면, 노후도·긴급도 점수를 바탕으로 대략적인 보수비를 자동 추정합니다.
        기존 결과값 디자인은 유지하고, 견적 결과만 추가로 표시합니다.
    </div>
    """,
    unsafe_allow_html=True
)

building_settings = {}
for building in summary_df["건물명"].tolist():
    with st.expander(f"{building} 설정", expanded=(building == summary_df["건물명"].tolist()[0])):
        c1, c2 = st.columns(2)
        with c1:
            category = st.selectbox(
                f"{building} 카테고리",
                BUILDING_TYPE_OPTIONS,
                index=0,
                key=f"category_{building}",
            )
        with c2:
            area_m2 = st.number_input(
                f"{building} 연면적(㎡)",
                min_value=100.0,
                value=3000.0,
                step=100.0,
                key=f"area_{building}",
            )
        building_settings[building] = {
            "category": category,
            "area_m2": area_m2,
        }

st.markdown('</div>', unsafe_allow_html=True)

# =========================
# 비용 계산 결과 병합
# =========================
cost_rows = []
cost_detail_map = {}

for building in summary_df["건물명"].tolist():
    row_age = result_df[result_df["건물명"] == building].iloc[0]
    row_urg = urgency_df[urgency_df["건물명"] == building].iloc[0]

    category = building_settings[building]["category"]
    area_m2 = float(building_settings[building]["area_m2"])

    cost_result = estimate_building_cost(category, area_m2, row_age, row_urg)
    detail_df = cost_result["detail_df"].copy()

    cost_detail_map[building] = cost_result

    cost_rows.append({
        "건물명": building,
        "카테고리": category,
        "연면적(㎡)": area_m2,
        "예상 보수비(원)": cost_result["total_cost"],
        "㎡당 보수비(원/㎡)": cost_result["cost_per_m2"],
    })

cost_df = pd.DataFrame(cost_rows)
summary_df = summary_df.merge(cost_df, on="건물명", how="left")

# =========================
# 탭
# =========================
tab1, tab2, tab3, tab4 = st.tabs(["종합 개요", "노후화도", "긴급도", "건물별 상세"])

# =========================
# 1. 종합 개요
# =========================
with tab1:
    top_n = min(4, len(summary_df))
    cols = st.columns(top_n, gap="large")

    for idx, (_, row) in enumerate(summary_df.head(top_n).iterrows()):
        details = (
            f"외벽 {safe_round(row['외벽(100)'])} · 창호 {safe_round(row['창호(100)'])}<br>"
            f"배관 {safe_round(row['배관(100)'])} · 설비 {safe_round(row['설비(100)'])}"
        )
        with cols[idx]:
            st.markdown(
                card_html(
                    row["순위"],
                    row["건물명"],
                    float(row["노후도 종합(100)"]),
                    row["등급"],
                    details,
                    row["가장 시급"],
                ),
                unsafe_allow_html=True,
            )

    c1, c2 = st.columns([1.08, 1], gap="large")

    with c1:
        st.markdown('<div class="soft-card">', unsafe_allow_html=True)
        st.markdown('<div class="section-title">종합 노후도 순위</div>', unsafe_allow_html=True)

        fig_rank = go.Figure()
        fig_rank.add_trace(
            go.Bar(
                x=summary_df["건물명"],
                y=summary_df["노후도 종합(100)"],
                marker=dict(
                    color=[BUILDING_COLORS.get(x, "#8B80F9") for x in summary_df["건물명"]],
                    line=dict(width=0)
                ),
                text=summary_df["노후도 종합(100)"].round(1),
                textposition="outside",
                width=0.52,
                opacity=0.92,
                hovertemplate="%{x}<br>노후도: %{y:.1f}<extra></extra>",
            )
        )
        fig_rank.update_layout(
            height=380,
            margin=dict(l=20, r=20, t=10, b=20),
            paper_bgcolor=WHITE,
            plot_bgcolor=WHITE,
            bargap=0.34,
            barcornerradius=12,
            xaxis_title="",
            yaxis_title="",
            xaxis=dict(showgrid=False),
            yaxis=dict(
                range=[0, max(100, float(summary_df["노후도 종합(100)"].max()) + 12)],
                gridcolor="#EEF2F6",
                zeroline=False,
            ),
        )
        st.plotly_chart(fig_rank, use_container_width=True, config={"displaylogo": False})
        st.markdown('</div>', unsafe_allow_html=True)

    with c2:
        st.markdown('<div class="soft-card">', unsafe_allow_html=True)
        st.markdown('<div class="section-title">건물별 항목 레이더</div>', unsafe_allow_html=True)

        radar_categories = ["외벽", "창호", "배관", "설비"]
        fig_radar = go.Figure()

        for _, row in summary_df.iterrows():
            building = row["건물명"]
            values = [row["외벽(100)"], row["창호(100)"], row["배관(100)"], row["설비(100)"]]

            fig_radar.add_trace(
                go.Scatterpolar(
                    r=values + [values[0]],
                    theta=radar_categories + [radar_categories[0]],
                    fill="toself",
                    name=building,
                    opacity=0.22,
                    line=dict(
                        width=3,
                        color=BUILDING_COLORS.get(building, "#8B80F9")
                    ),
                    marker=dict(
                        color=BUILDING_COLORS.get(building, "#8B80F9")
                    ),
                    fillcolor=BUILDING_COLORS.get(building, "#8B80F9"),
                )
            )

        fig_radar.update_layout(
            height=380,
            margin=dict(l=20, r=20, t=10, b=20),
            paper_bgcolor=WHITE,
            polar=dict(
                bgcolor=WHITE,
                radialaxis=dict(visible=True, range=[0, 100], gridcolor="#EEF2F6"),
                angularaxis=dict(gridcolor="#EEF2F6"),
            ),
            legend=dict(orientation="h", y=1.12, x=0.5, xanchor="center"),
        )
        st.plotly_chart(fig_radar, use_container_width=True, config={"displaylogo": False})
        st.markdown('</div>', unsafe_allow_html=True)

    # 추가: 예상 보수비 비교
    st.markdown('<div class="soft-card">', unsafe_allow_html=True)
    st.markdown('<div class="section-title">예상 보수비 비교</div>', unsafe_allow_html=True)

    fig_cost = go.Figure()
    fig_cost.add_trace(
        go.Bar(
            x=summary_df["건물명"],
            y=summary_df["예상 보수비(원)"],
            marker=dict(
                color=[BUILDING_COLORS.get(x, "#8B80F9") for x in summary_df["건물명"]],
                line=dict(width=0)
            ),
            text=[format_eok(x) for x in summary_df["예상 보수비(원)"]],
            textposition="outside",
            width=0.52,
            opacity=0.92,
            hovertemplate="%{x}<br>예상 보수비: %{y:,.0f}원<extra></extra>",
        )
    )
    fig_cost.update_layout(
        height=380,
        margin=dict(l=20, r=20, t=10, b=20),
        paper_bgcolor=WHITE,
        plot_bgcolor=WHITE,
        bargap=0.34,
        barcornerradius=12,
        xaxis_title="",
        yaxis_title="",
        xaxis=dict(showgrid=False),
        yaxis=dict(gridcolor="#EEF2F6", zeroline=False),
    )
    st.plotly_chart(fig_cost, use_container_width=True, config={"displaylogo": False})

    cost_table_df = summary_df[["건물명", "카테고리", "연면적(㎡)", "예상 보수비(원)", "㎡당 보수비(원/㎡)"]].copy()
    cost_table_df = cost_table_df.rename(columns={"건물명": "건물"})
    cost_table_df["연면적(㎡)"] = cost_table_df["연면적(㎡)"].map(lambda x: f"{x:,.0f}")
    cost_table_df["예상 보수비(원)"] = cost_table_df["예상 보수비(원)"].map(format_eok)
    cost_table_df["㎡당 보수비(원/㎡)"] = cost_table_df["㎡당 보수비(원/㎡)"].map(format_krw)
    render_html_table(cost_table_df)

    st.markdown(
        """
        <div class="cost-note">
            ※ 본 견적은 대시보드용 개략 추정치입니다. 실제 공사비는 수량산출, 공법, 시공범위, 현장여건, 표준시장단가 적용 여부에 따라 달라질 수 있습니다.
        </div>
        """,
        unsafe_allow_html=True
    )
    st.markdown('</div>', unsafe_allow_html=True)

# =========================
# 2. 노후화도
# =========================
with tab2:
    c1, c2 = st.columns(2, gap="large")

    with c1:
        st.markdown('<div class="soft-card">', unsafe_allow_html=True)
        st.markdown('<div class="section-title">분야별 노후화도 비교</div>', unsafe_allow_html=True)

        long_aging = result_df.melt(
            id_vars="건물명",
            value_vars=["외벽(100)", "창호(100)", "배관(100)", "설비(100)"],
            var_name="분야",
            value_name="점수"
        )

        long_aging["분야"] = long_aging["분야"].map({
            "외벽(100)": "외벽",
            "창호(100)": "창호",
            "배관(100)": "배관",
            "설비(100)": "설비",
        })

        fig_group = px.bar(
            long_aging,
            x="분야",
            y="점수",
            color="건물명",
            barmode="group",
            color_discrete_map=BUILDING_COLORS,
            text_auto=".1f",
            category_orders={"분야": ["외벽", "창호", "배관", "설비"]},
        )

        fig_group.update_traces(
            width=0.18,
            marker_line_width=0,
            textposition="outside",
            hovertemplate="분야: %{x}<br>점수: %{y:.1f}<extra></extra>",
        )
        fig_group.update_layout(
            height=395,
            margin=dict(l=20, r=20, t=10, b=20),
            paper_bgcolor=WHITE,
            plot_bgcolor=WHITE,
            bargap=0.34,
            bargroupgap=0.18,
            barcornerradius=10,
            xaxis_title="",
            yaxis_title="",
            xaxis=dict(showgrid=False),
            yaxis=dict(range=[0, 110], gridcolor="#EEF2F6", zeroline=False),
            legend=dict(orientation="h", y=1.14, x=0.5, xanchor="center", title=None),
        )
        st.plotly_chart(fig_group, use_container_width=True, config={"displaylogo": False})
        st.markdown('</div>', unsafe_allow_html=True)

    with c2:
        st.markdown('<div class="soft-card">', unsafe_allow_html=True)
        st.markdown('<div class="section-title">노후도 히트맵</div>', unsafe_allow_html=True)

        heat_df = result_df[["건물명", "외벽(100)", "창호(100)", "배관(100)", "설비(100)"]].copy()
        heat_df = heat_df.rename(columns={
            "건물명": "건물",
            "외벽(100)": "외벽",
            "창호(100)": "창호",
            "배관(100)": "배관",
            "설비(100)": "설비",
        })

        fig_heat = go.Figure(
            data=go.Heatmap(
                z=heat_df[["외벽", "창호", "배관", "설비"]].values,
                x=["외벽", "창호", "배관", "설비"],
                y=heat_df["건물"],
                colorscale=[
                    [0.0, "#ECFDF3"],
                    [0.4, "#FEF3C7"],
                    [0.7, "#FFF1E8"],
                    [1.0, "#FDEAEA"],
                ],
                zmin=0,
                zmax=100,
                text=heat_df[["외벽", "창호", "배관", "설비"]].round(0).astype(int).values,
                texttemplate="%{text}",
                textfont={"size": 18},
                showscale=False,
                xgap=12,
                ygap=12,
                hovertemplate="건물: %{y}<br>부위: %{x}<br>점수: %{z}<extra></extra>",
            )
        )
        fig_heat.update_layout(
            height=395,
            margin=dict(l=20, r=20, t=10, b=20),
            paper_bgcolor=WHITE,
            plot_bgcolor=WHITE,
        )
        st.plotly_chart(fig_heat, use_container_width=True, config={"displaylogo": False})
        st.markdown('</div>', unsafe_allow_html=True)

    st.markdown('<div class="soft-card">', unsafe_allow_html=True)
    st.markdown('<div class="section-title">노후도 상세표</div>', unsafe_allow_html=True)

    aging_table_df = summary_df[["건물명", "외벽(100)", "창호(100)", "배관(100)", "설비(100)", "노후도 종합(100)", "등급"]].copy()
    aging_table_df = aging_table_df.rename(columns={
        "건물명": "건물",
        "외벽(100)": "외벽",
        "창호(100)": "창호",
        "배관(100)": "배관",
        "설비(100)": "설비",
        "노후도 종합(100)": "종합",
    })

    for col in ["외벽", "창호", "배관", "설비", "종합"]:
        aging_table_df[col] = aging_table_df[col].round(1)

    render_html_table(aging_table_df)
    st.markdown('</div>', unsafe_allow_html=True)

# =========================
# 3. 긴급도
# =========================
with tab3:
    c1, c2 = st.columns([1, 1.2], gap="large")

    with c1:
        st.markdown('<div class="soft-card">', unsafe_allow_html=True)
        st.markdown('<div class="section-title">가장 시급한 부위</div>', unsafe_allow_html=True)

        urgent_part_counts = urgency_df["가장 시급"].value_counts().reset_index()
        urgent_part_counts.columns = ["부위", "개수"]

        fig_donut = go.Figure(
            data=[
                go.Pie(
                    labels=urgent_part_counts["부위"],
                    values=urgent_part_counts["개수"],
                    hole=0.58,
                    marker=dict(colors=[CATEGORY_COLORS.get(x, "#3182F6") for x in urgent_part_counts["부위"]]),
                    textinfo="label",
                    sort=False,
                )
            ]
        )
        fig_donut.update_layout(
            height=390,
            margin=dict(l=20, r=20, t=10, b=10),
            paper_bgcolor=WHITE,
            showlegend=True,
            legend=dict(orientation="v", x=1.02, y=0.5),
        )
        st.plotly_chart(fig_donut, use_container_width=True, config={"displaylogo": False})
        st.markdown('</div>', unsafe_allow_html=True)

    with c2:
        st.markdown('<div class="soft-card">', unsafe_allow_html=True)
        st.markdown('<div class="section-title">노후도 VS 긴급도</div>', unsafe_allow_html=True)

        bubble_df = summary_df.copy()
        bubble_df["버블크기"] = bubble_df["긴급도 최대값"] + 20

        fig_bubble = px.scatter(
            bubble_df,
            x="노후도 종합(100)",
            y="긴급도 최대값",
            color="건물명",
            size="버블크기",
            size_max=28,
            text="건물명",
            color_discrete_map=BUILDING_COLORS,
        )
        fig_bubble.update_traces(textposition="top center")
        fig_bubble.update_layout(
            height=390,
            margin=dict(l=20, r=20, t=10, b=20),
            paper_bgcolor=WHITE,
            plot_bgcolor=WHITE,
            xaxis=dict(title="종합 노후화도", range=[0, 100], gridcolor="#EEF2F6", zeroline=False),
            yaxis=dict(title="최대 긴급도", range=[0, 100], gridcolor="#EEF2F6", zeroline=False),
            legend=dict(orientation="h", y=1.14, x=0.5, xanchor="center", title=None),
        )
        st.plotly_chart(fig_bubble, use_container_width=True, config={"displaylogo": False})
        st.markdown('</div>', unsafe_allow_html=True)

    st.markdown('<div class="soft-card">', unsafe_allow_html=True)
    st.markdown('<div class="section-title">긴급도 상세표</div>', unsafe_allow_html=True)

    urgency_table_df = urgency_df[["건물명", "외벽 긴급도(100)", "창호 긴급도(100)", "배관 긴급도(100)", "설비 긴급도(100)", "가장 시급"]].copy()
    urgency_table_df["등급"] = urgency_df["긴급도 최대값"].apply(urgency_grade)
    urgency_table_df = urgency_table_df.rename(columns={
        "건물명": "건물",
        "외벽 긴급도(100)": "외벽",
        "창호 긴급도(100)": "창호",
        "배관 긴급도(100)": "배관",
        "설비 긴급도(100)": "설비",
    })

    for col in ["외벽", "창호", "배관", "설비"]:
        urgency_table_df[col] = urgency_table_df[col].round(1)

    render_html_table(urgency_table_df)
    st.markdown('</div>', unsafe_allow_html=True)

# =========================
# 4. 건물별 상세
# =========================
with tab4:
    buildings = result_df["건물명"].tolist()

    selected_building = st.radio(
        "건물 선택",
        buildings,
        horizontal=True,
        label_visibility="collapsed",
    )

    row_age = result_df[result_df["건물명"] == selected_building].iloc[0]
    row_urg = urgency_df[urgency_df["건물명"] == selected_building].iloc[0]

    selected_aging = float(row_age["노후도 종합(100)"])
    selected_urg = float(row_urg["긴급도 최대값"])
    selected_age_grade = aging_grade(selected_aging)
    selected_urg_grade = urgency_grade(selected_urg)

    selected_category = building_settings[selected_building]["category"]
    selected_area = float(building_settings[selected_building]["area_m2"])
    selected_cost_result = cost_detail_map[selected_building]
    selected_total_cost = selected_cost_result["total_cost"]
    selected_cost_per_m2 = selected_cost_result["cost_per_m2"]

    c1, c2 = st.columns(2, gap="large")

    with c1:
        st.markdown('<div class="soft-card">', unsafe_allow_html=True)
        st.markdown('<div class="section-title">노후화도</div>', unsafe_allow_html=True)
        st.markdown(
            f"""
            <div style="font-size:56px; font-weight:800; color:{TEXT}; line-height:1;">{selected_aging:.1f}</div>
            <div style="margin:6px 0 14px 0;">{badge_html(selected_age_grade)}</div>
            <div style="color:{SUB}; font-size:16px;">종합 노후화도 — 외벽 25% · 창호 15% · 배관 30% · 설비 30%</div>
            """,
            unsafe_allow_html=True,
        )

        detail_parts_age = {
            "외벽": row_age["외벽(100)"],
            "창호": row_age["창호(100)"],
            "배관": row_age["배관(100)"],
            "설비": row_age["설비(100)"],
        }

        for part, val in detail_parts_age.items():
            st.markdown(f"<div style='margin-top:18px; font-weight:700; color:{TEXT};'>{part}</div>", unsafe_allow_html=True)
            st.progress(int(val))
            st.markdown(f"<div style='text-align:right; color:{SUB}; margin-top:-6px;'>{float(val):.1f}</div>", unsafe_allow_html=True)

        st.markdown('</div>', unsafe_allow_html=True)

    with c2:
        st.markdown('<div class="soft-card">', unsafe_allow_html=True)
        st.markdown('<div class="section-title">긴급도</div>', unsafe_allow_html=True)
        st.markdown(
            f"""
            <div style="font-size:56px; font-weight:800; color:{TEXT}; line-height:1;">{selected_urg:.1f}</div>
            <div style="margin:6px 0 14px 0;">{badge_html(selected_urg_grade)}</div>
            <div style="color:{SUB}; font-size:16px;">최고 긴급도 — 가장 시급한 부위: <span style="color:{CATEGORY_COLORS[row_urg['가장 시급']]}; font-weight:700;">{row_urg['가장 시급']}</span></div>
            """,
            unsafe_allow_html=True,
        )

        detail_parts_urg = {
            "외벽": row_urg["외벽 긴급도(100)"],
            "창호": row_urg["창호 긴급도(100)"],
            "배관": row_urg["배관 긴급도(100)"],
            "설비": row_urg["설비 긴급도(100)"],
        }

        for part, val in detail_parts_urg.items():
            st.markdown(f"<div style='margin-top:18px; font-weight:700; color:{TEXT};'>{part}</div>", unsafe_allow_html=True)
            st.progress(int(val))
            st.markdown(f"<div style='text-align:right; color:{SUB}; margin-top:-6px;'>{float(val):.1f}</div>", unsafe_allow_html=True)

        st.markdown('</div>', unsafe_allow_html=True)

    # 추가: 카테고리 / 예상 보수비
    st.markdown('<div class="soft-card">', unsafe_allow_html=True)
    st.markdown('<div class="section-title">카테고리별 예상 보수비</div>', unsafe_allow_html=True)

    cc1, cc2, cc3 = st.columns(3, gap="large")
    with cc1:
        st.markdown(
            cost_card_html(
                "건물 카테고리",
                selected_category,
                f"연면적 {selected_area:,.0f}㎡ 기준"
            ),
            unsafe_allow_html=True
        )
    with cc2:
        st.markdown(
            cost_card_html(
                "예상 총 보수비",
                format_eok(selected_total_cost),
                "간접비·일반관리비·부가세 단순 반영"
            ),
            unsafe_allow_html=True
        )
    with cc3:
        st.markdown(
            cost_card_html(
                "㎡당 예상 보수비",
                format_krw(selected_cost_per_m2),
                "카테고리별 기준단가 + 점수 반영"
            ),
            unsafe_allow_html=True
        )

    detail_cost_df = selected_cost_result["detail_df"].copy()
    detail_cost_df["기준단가(원/㎡)"] = detail_cost_df["기준단가(원/㎡)"].map(lambda x: f"{int(x):,}")
    detail_cost_df["보수범위비율"] = detail_cost_df["보수범위비율"].map(lambda x: f"{x:.1f}%")
    detail_cost_df["예상공사비(직접공사비)"] = detail_cost_df["예상공사비(직접공사비)"].map(format_eok)

    render_html_table(detail_cost_df.rename(columns={"부위": "건물"}).rename(columns={"건물": "부위"}))

    st.markdown(
        """
        <div class="cost-note">
            ※ 이 값은 발표용 개략 견적입니다. 실제 공사비는 현장조사, 수량산출, 자재사양, 장비투입, 공정계획, 표준시장단가 적용 여부에 따라 달라집니다.
        </div>
        """,
        unsafe_allow_html=True
    )

    st.markdown('</div>', unsafe_allow_html=True)
