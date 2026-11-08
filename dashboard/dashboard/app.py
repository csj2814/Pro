"""SolCare 야간 돌봄 대시보드 (Streamlit).

실행:  streamlit run dashboard/app.py
DB:    python server/db/import_session.py solcare.db <vitals.csv> <events.csv> <meta.json>
"""
from datetime import timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

import db

st.set_page_config(page_title="SolCare 대시보드", page_icon="🌙", layout="wide")

EVENT_KO = {
    "sleep_onset": "입면",
    "toss": "뒤척임",
    "apnea_suspected": "무호흡 의심",
    "bed_exit": "침대 이탈",
    "final_wake": "기상",
}
STAGE_KO = {"wake": "깸", "light": "얕은 수면", "deep": "깊은 수면", "rem": "렘수면"}
STAGE_ORDER = ["wake", "rem", "light", "deep"]  # 위 → 아래
BED_EXIT_ALERT_S = 300  # 이 시간 이상 침대를 비우면 알림으로 표시

C_HR, C_RESP, C_MOVE = "#d1495b", "#2e86ab", "#7d7d7d"
C_WARN, C_INFO = "#e08e0b", "#5b8def"


# ---------------------------------------------------------------- 데이터 로드
@st.cache_data(ttl=60)
def load_sessions():
    return db.list_sessions()


@st.cache_data(ttl=60)
def load_vitals(sid):
    return db.get_vitals(sid)


@st.cache_data(ttl=60)
def load_events(sid):
    return db.get_events(sid)


def build_alerts(events: pd.DataFrame) -> pd.DataFrame:
    """이벤트에서 보호자가 봐야 할 알림만 뽑는다. (의학적 진단이 아닌 '관찰 대상')"""
    rows = []
    for e in events.itertuples():
        if e.event_type == "apnea_suspected":
            rows.append((e.start_time, "무호흡 의심", "주의", e.duration_s,
                         "의학적 진단이 아닌 추이 관찰 대상"))
        elif e.event_type == "bed_exit" and e.duration_s >= BED_EXIT_ALERT_S:
            rows.append((e.start_time, "침대 이탈", "참고", e.duration_s,
                         "복귀 여부 확인" if e.duration_s < 600 else "장시간 이탈"))
    return pd.DataFrame(rows, columns=["시각", "유형", "등급", "지속(초)", "메모"])


# ---------------------------------------------------------------- 사이드바
if not db.db_exists():
    st.error(f"DB 파일을 찾을 수 없습니다: `{db.db_path()}`")
    st.code(
        "python server/db/import_session.py solcare.db "
        "<vitals.csv> <events.csv> <meta.json>",
        language="bash",
    )
    st.stop()

sessions = load_sessions()
if sessions.empty:
    st.warning("적재된 세션이 없습니다. import_session.py로 먼저 데이터를 넣어 주세요.")
    st.stop()

with st.sidebar:
    st.header("설정")
    sid = st.selectbox(
        "세션", sessions["session_id"],
        format_func=lambda s: f"{s} (침대 {sessions.set_index('session_id').loc[s, 'bed_id']})",
    )
    interval = st.select_slider("그래프 간격(초)", options=[1, 5, 10, 30, 60], value=10)
    st.caption("간격이 짧을수록 정밀하지만 느려집니다.")

meta = sessions.set_index("session_id").loc[sid]
vitals = load_vitals(sid)
events = load_events(sid)
alerts = build_alerts(events)

# ---------------------------------------------------------------- 머리말
st.title("🌙 SolCare 야간 돌봄 대시보드")
st.caption(
    f"대상자 **{meta['pseudo_id']}** · 침대 {meta['bed_id']} · "
    f"{meta['start_time']} ~ {meta['end_time']}"
    + (" · 합성 샘플 데이터" if meta["is_synthetic"] else "")
)

# ---------------------------------------------------------------- 요약 지표
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("수면 점수", f"{meta['sleep_score']}점")
c2.metric("수면 효율", f"{meta['sleep_efficiency_pct']:.0f}%")
c3.metric("총 수면", f"{meta['total_sleep_min'] / 60:.1f}시간")
c4.metric("깨어 있던 시간", f"{meta['wake_min']}분")
n_apnea = int((events["event_type"] == "apnea_suspected").sum())
c5.metric("무호흡 의심", f"{n_apnea}회", help="의학적 진단이 아닌 관찰 대상입니다.")

# ---------------------------------------------------------------- 시점별 상태
st.subheader("시점별 상태")
t_min, t_max = vitals["ts"].min().to_pydatetime(), vitals["ts"].max().to_pydatetime()
sel = st.slider(
    "확인할 시각 (실시간 연동 전에는 기록 시점을 골라 봅니다)",
    min_value=t_min, max_value=t_max, value=t_min + timedelta(hours=4),
    step=timedelta(minutes=1), format="MM/DD HH:mm",
)
idx = (vitals["ts"] - pd.Timestamp(sel)).abs().idxmin()
now = vitals.loc[idx]
s1, s2, s3, s4, s5 = st.columns(5)
s1.metric("심박수 (bpm)", f"{now['heart_rate_bpm']:.0f}")
s2.metric("호흡수 (회/분)", f"{now['respiration_rate_bpm']:.1f}")
s3.metric("침대", "재실" if now["in_bed"] == 1 else "이탈")
s4.metric("수면 단계", STAGE_KO.get(now["sleep_stage"], now["sleep_stage"]))
s5.metric("움직임 지수", f"{now['movement_index']:.1f}")

# ---------------------------------------------------------------- 시계열 그래프
st.subheader("밤사이 변화")
v = db.resample_vitals(vitals, interval)
fig = make_subplots(
    rows=4, cols=1, shared_xaxes=True, vertical_spacing=0.04,
    row_heights=[0.28, 0.28, 0.22, 0.22],
    subplot_titles=("심박수 (bpm)", "호흡수 (회/분)", "움직임 지수", "수면 단계"),
)
fig.add_trace(go.Scatter(x=v["ts"], y=v["heart_rate_bpm"], line=dict(color=C_HR, width=1.2),
                         name="심박수"), row=1, col=1)
fig.add_trace(go.Scatter(x=v["ts"], y=v["respiration_rate_bpm"], line=dict(color=C_RESP, width=1.2),
                         name="호흡수"), row=2, col=1)
fig.add_trace(go.Scatter(x=v["ts"], y=v["movement_index"], line=dict(color=C_MOVE, width=1),
                         name="움직임"), row=3, col=1)
stage_y = vitals["sleep_stage"].map({s: i for i, s in enumerate(STAGE_ORDER)})
vs = vitals.assign(stage_y=stage_y).iloc[::interval]
fig.add_trace(go.Scatter(x=vs["ts"], y=vs["stage_y"], line=dict(color="#555", width=1.2, shape="hv"),
                         name="수면 단계", hovertext=vs["sleep_stage"].map(STAGE_KO),
                         hoverinfo="text+x"), row=4, col=1)
fig.update_yaxes(tickvals=list(range(len(STAGE_ORDER))),
                 ticktext=[STAGE_KO[s] for s in STAGE_ORDER], autorange="reversed", row=4, col=1)

for e in events.itertuples():
    if e.event_type == "bed_exit":
        fig.add_vrect(x0=e.start_time, x1=e.end_time, fillcolor=C_INFO, opacity=0.15, line_width=0)
    elif e.event_type == "apnea_suspected":
        fig.add_vrect(x0=e.start_time - timedelta(seconds=90), x1=e.end_time + timedelta(seconds=90),
                      fillcolor=C_WARN, opacity=0.35, line_width=0)
fig.add_vline(x=pd.Timestamp(sel), line=dict(color="#333", dash="dot", width=1))
fig.update_layout(height=640, showlegend=False, margin=dict(l=10, r=10, t=30, b=10),
                  hovermode="x unified")
st.plotly_chart(fig, use_container_width=True)
st.caption("주황 음영: 무호흡 의심 구간 · 파랑 음영: 침대 이탈 · 점선: 위에서 고른 시각")

# ---------------------------------------------------------------- 알림 / 이벤트
left, right = st.columns([3, 2])
with left:
    st.subheader("이상 알림")
    if alerts.empty:
        st.success("이 세션에는 알림이 없습니다.")
    else:
        for a in alerts.itertuples():
            msg = f"**{a.시각:%m/%d %H:%M:%S}** · {a.유형} · {a._4}초 — {a.메모}"
            (st.warning if a.등급 == "주의" else st.info)(msg)
    st.caption("알림은 진단이 아니라 보호자가 확인할 '관찰 대상'입니다.")

with right:
    st.subheader("수면 단계별 시간")
    sm = db.stage_minutes(vitals)
    bar = go.Figure(go.Bar(
        x=[sm.get(s, 0) for s in STAGE_ORDER],
        y=[STAGE_KO[s] for s in STAGE_ORDER], orientation="h",
        marker_color="#7a8fa6", text=[f"{sm.get(s, 0):.0f}분" for s in STAGE_ORDER],
    ))
    bar.update_layout(height=230, margin=dict(l=10, r=10, t=10, b=10),
                      yaxis=dict(autorange="reversed"), xaxis_title="분")
    st.plotly_chart(bar, use_container_width=True)

st.subheader("전체 이벤트")
kinds = sorted(events["event_type"].unique())
pick = st.multiselect("표시할 이벤트", kinds, default=kinds, format_func=lambda k: EVENT_KO.get(k, k))
table = events[events["event_type"].isin(pick)].copy()
table["유형"] = table["event_type"].map(lambda k: EVENT_KO.get(k, k))
st.dataframe(
    table[["start_time", "유형", "duration_s", "label_source", "note"]].rename(columns={
        "start_time": "시각", "duration_s": "지속(초)", "label_source": "라벨 출처", "note": "메모"}),
    use_container_width=True, hide_index=True,
)
