"""보호자 앱용 아침 리포트 계산 (읽기 전용).

수치는 모두 DB 값으로 직접 계산한다. 문장은 규칙 기반 템플릿이며,
LLM API 연동 시 summarize() 만 교체하면 된다 (LLM에는 집계 수치와 가명 ID만 전달).
알림은 의학적 진단이 아닌 '관찰 대상'으로 표기한다.
"""
import os
import sqlite3
from pathlib import Path

DEFAULT_DB = Path(__file__).resolve().parent.parent / "solcare.db"
STAGE_KO = {"wake": "깸", "rem": "렘수면", "light": "얕은 수면", "deep": "깊은 수면"}
STAGE_ORDER = ["deep", "light", "rem", "wake"]
BED_EXIT_ALERT_S = 300


def db_path() -> Path:
    return Path(os.environ.get("SOLCARE_DB", DEFAULT_DB))


def db_exists() -> bool:
    return db_path().is_file()


def _con():
    con = sqlite3.connect(f"file:{db_path().as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def score_label(score: int) -> tuple[str, str]:
    if score >= 80:
        return "양호", "good"
    if score >= 60:
        return "보통", "normal"
    return "주의", "warn"


def list_sessions() -> list[dict]:
    with _con() as con:
        rows = con.execute(
            """SELECT s.session_id, s.bed_id, u.pseudo_id, s.start_time, s.end_time,
                      s.sleep_score, s.sleep_efficiency_pct, s.total_sleep_min, s.wake_min
               FROM sessions s JOIN users u ON u.user_id = s.patient_id
               ORDER BY s.start_time DESC"""
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["label"], d["tone"] = score_label(d["sleep_score"])
        out.append(d)
    return out


def build_report(session_id: str) -> dict | None:
    with _con() as con:
        s = con.execute(
            """SELECT s.*, u.pseudo_id FROM sessions s JOIN users u ON u.user_id = s.patient_id
               WHERE s.session_id = ?""", (session_id,)).fetchone()
        if s is None:
            return None
        s = dict(s)
        agg = con.execute(
            """SELECT AVG(heart_rate_bpm) AS hr, AVG(respiration_rate_bpm) AS resp, COUNT(*) AS n
               FROM vitals WHERE session_id = ? AND in_bed = 1 AND respiration_rate_bpm >= 1""",
            (session_id,)).fetchone()
        stages = {r["sleep_stage"]: r["n"] for r in con.execute(
            "SELECT sleep_stage, COUNT(*) AS n FROM vitals WHERE session_id = ? GROUP BY sleep_stage",
            (session_id,))}
        events = [dict(r) for r in con.execute(
            "SELECT * FROM events WHERE session_id = ? ORDER BY start_time", (session_id,))]

    total = sum(stages.values()) or 1
    stage_rows = [{"key": k, "name": STAGE_KO[k], "min": round(stages.get(k, 0) / 60),
                   "pct": round(stages.get(k, 0) / total * 100)} for k in STAGE_ORDER]

    apnea = [e for e in events if e["event_type"] == "apnea_suspected"]
    exits = [e for e in events if e["event_type"] == "bed_exit"]
    tosses = [e for e in events if e["event_type"] == "toss"]

    alerts = []
    for e in apnea:
        alerts.append({"time": e["start_time"][11:16], "level": "warn", "title": "무호흡 의심",
                       "text": f"약 {e['duration_s']}초간 호흡이 감지되지 않았어요. 진단이 아닌 관찰 대상이에요."})
    for e in exits:
        if e["duration_s"] >= BED_EXIT_ALERT_S:
            alerts.append({"time": e["start_time"][11:16], "level": "info", "title": "침대 이탈",
                           "text": f"약 {round(e['duration_s'] / 60)}분간 침대를 비웠다가 돌아오셨어요."})
    alerts.sort(key=lambda a: a["time"])

    label, tone = score_label(s["sleep_score"])
    report = {
        "session_id": session_id, "pseudo_id": s["pseudo_id"], "bed_id": s["bed_id"],
        "start": s["start_time"], "end": s["end_time"], "is_synthetic": bool(s["is_synthetic"]),
        "score": s["sleep_score"], "score_label": label, "tone": tone,
        "efficiency": s["sleep_efficiency_pct"],
        "total_h": round(s["total_sleep_min"] / 60, 1), "total_min": s["total_sleep_min"],
        "wake_min": s["wake_min"], "avg_hr": round(agg["hr"]) if agg["hr"] else None,
        "avg_resp": round(agg["resp"], 1) if agg["resp"] else None,
        "stages": stage_rows, "apnea_n": len(apnea), "exit_n": len(exits), "toss_n": len(tosses),
        "alerts": alerts,
    }
    report["summary"] = summarize(report)
    return report


def summarize(r: dict) -> str:
    """보호자용 요약 문장. (규칙 기반 임시 문구 — LLM 연동 시 이 함수만 교체)"""
    parts = [f"{r['start'][11:16]}에 누워 {r['end'][11:16]}까지 약 {r['total_h']}시간 주무셨고, "
             f"수면 점수는 {r['score']}점({r['score_label']})이에요."]
    if r["avg_hr"]:
        parts.append(f"침대에 있는 동안 평균 심박수는 {r['avg_hr']}bpm이었어요.")
    if r["apnea_n"]:
        parts.append(f"호흡이 잠시 감지되지 않은 구간이 {r['apnea_n']}번 있었어요(관찰 대상).")
    else:
        parts.append("호흡이 멈춘 의심 구간은 없었어요.")
    if r["exit_n"]:
        parts.append(f"밤사이 침대를 비운 적이 {r['exit_n']}번 있었어요.")
    return " ".join(parts)
