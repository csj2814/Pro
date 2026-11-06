"""DB에서 세션을 읽어 모델용 특징을 만든다. (읽기 전용)

DB 위치: 환경변수 SOLCARE_DB, 없으면 저장소 루트의 solcare.db
"""
import os
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

DEFAULT_DB = Path(__file__).resolve().parent.parent / "solcare.db"
STAGES = ["wake", "rem", "light", "deep"]


def db_path() -> Path:
    return Path(os.environ.get("SOLCARE_DB", DEFAULT_DB))


def _connect():
    return sqlite3.connect(f"file:{db_path().as_posix()}?mode=ro", uri=True)


def load_vitals(session_id: str) -> pd.DataFrame:
    """1Hz 측정값. ts 를 인덱스로 둔다."""
    with _connect() as con:
        df = pd.read_sql_query(
            "SELECT * FROM vitals WHERE session_id=? ORDER BY ts",
            con, params=(session_id,), parse_dates=["ts"],
        )
    return df.set_index("ts")


def load_events(session_id: str) -> pd.DataFrame:
    with _connect() as con:
        return pd.read_sql_query(
            "SELECT * FROM events WHERE session_id=? ORDER BY start_time",
            con, params=(session_id,), parse_dates=["start_time", "end_time"],
        )


def window_features(v: pd.DataFrame, window_s: int = 30) -> pd.DataFrame:
    """window_s 초 구간별 통계 특징. 라벨(sleep_stage)은 특징에 쓰지 않는다.

    호흡수 0(무호흡 구간)은 호흡 통계를 왜곡하므로 NaN 으로 바꿔 제외한다.
    무호흡은 rules.py 에서 따로 탐지한다.
    """
    x = v[["heart_rate_bpm", "respiration_rate_bpm", "breath_amplitude_pct",
           "movement_index", "in_bed"]].copy()
    apnea_like = (x["respiration_rate_bpm"] < 1) | (x["breath_amplitude_pct"] < 10)
    x.loc[apnea_like, ["respiration_rate_bpm", "breath_amplitude_pct"]] = np.nan

    r = x.resample(f"{window_s}s")
    f = pd.DataFrame({
        "hr_mean": r["heart_rate_bpm"].mean(),
        "hr_std": r["heart_rate_bpm"].std(),
        "resp_mean": r["respiration_rate_bpm"].mean(),
        "resp_std": r["respiration_rate_bpm"].std(),
        "amp_mean": r["breath_amplitude_pct"].mean(),
        "amp_std": r["breath_amplitude_pct"].std(),
        "mov_mean": r["movement_index"].mean(),
        "mov_max": r["movement_index"].max(),
        "in_bed": r["in_bed"].mean(),
    })
    # 구간 라벨: 구간 안에서 가장 많이 나온 수면 단계 (정답 용도로만 사용)
    f["stage"] = v["sleep_stage"].resample(f"{window_s}s").agg(lambda s: s.mode().iat[0] if len(s) else None)
    return f.dropna(subset=["hr_mean", "resp_mean", "stage"])
