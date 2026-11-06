"""대시보드용 DB 조회 모듈 (SQLite, 읽기 전용).

DB 파일 위치:
  - 환경변수 SOLCARE_DB 가 있으면 그 경로
  - 없으면 저장소 루트의 solcare.db  (server/db/import_session.py 로 생성)
"""
import os
import sqlite3
from pathlib import Path

import pandas as pd

DEFAULT_DB = Path(__file__).resolve().parent.parent / "solcare.db"


def db_path() -> Path:
    return Path(os.environ.get("SOLCARE_DB", DEFAULT_DB))


def _connect() -> sqlite3.Connection:
    # 읽기 전용으로 열어 대시보드가 실수로 데이터를 바꾸지 못하게 한다.
    return sqlite3.connect(f"file:{db_path().as_posix()}?mode=ro", uri=True)


def db_exists() -> bool:
    return db_path().is_file()


def list_sessions() -> pd.DataFrame:
    with _connect() as con:
        return pd.read_sql_query(
            """SELECT s.session_id, s.bed_id, u.pseudo_id, s.start_time, s.end_time,
                      s.sleep_score, s.sleep_efficiency_pct, s.total_sleep_min,
                      s.wake_min, s.is_synthetic, s.data_policy
               FROM sessions s JOIN users u ON u.user_id = s.patient_id
               ORDER BY s.start_time DESC""",
            con,
        )


def get_vitals(session_id: str) -> pd.DataFrame:
    with _connect() as con:
        df = pd.read_sql_query(
            "SELECT * FROM vitals WHERE session_id = ? ORDER BY ts",
            con, params=(session_id,), parse_dates=["ts"],
        )
    return df


def get_events(session_id: str) -> pd.DataFrame:
    with _connect() as con:
        return pd.read_sql_query(
            "SELECT * FROM events WHERE session_id = ? ORDER BY start_time",
            con, params=(session_id,), parse_dates=["start_time", "end_time"],
        )


def resample_vitals(vitals: pd.DataFrame, seconds: int) -> pd.DataFrame:
    """1Hz 원본을 N초 평균으로 줄여 그래프를 가볍게 만든다."""
    if seconds <= 1:
        return vitals
    v = vitals.set_index("ts")
    out = v[["heart_rate_bpm", "respiration_rate_bpm", "breath_amplitude_pct",
             "movement_index"]].resample(f"{seconds}s").mean()
    out["in_bed"] = v["in_bed"].resample(f"{seconds}s").min()
    out["sleep_stage"] = v["sleep_stage"].resample(f"{seconds}s").first()
    return out.reset_index()


def stage_minutes(vitals: pd.DataFrame) -> pd.Series:
    """수면 단계별 분 (1Hz 이므로 행 수 / 60)."""
    return (vitals.groupby("sleep_stage").size() / 60).round(1)
