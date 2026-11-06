"""규칙 기반 이상 탐지 베이스라인 + 라벨 대비 평가.

탐지 대상 (events 테이블의 event_type 과 같은 이름):
  apnea_suspected : 호흡수≈0 이고 호흡 진폭이 거의 없는 상태가 N초 이상 지속
  toss            : 침대에 있는 상태에서 움직임이 크게 튀는 구간
  bed_exit        : in_bed == 0 이 N초 이상 지속

결과는 '의학적 진단'이 아니라 보호자가 확인할 '관찰 대상'이다.

실행: python ai/rules.py [session_id]
"""
import sys

import pandas as pd

import features

# 임계값은 샘플 1세션을 보고 정한 초기값이다. 실측 데이터가 쌓이면 다시 맞춘다.
PARAMS = {
    "apnea": {"resp_lt": 1.0, "amp_lt": 10.0, "min_s": 5},
    "toss": {"roll_s": 5, "mov_gt": 35.0, "min_s": 5, "merge_gap_s": 5},
    "bed_exit": {"min_s": 60},
}


def _runs(mask: pd.Series, min_s: int, merge_gap_s: int = 0) -> list[tuple]:
    """True 가 이어지는 구간을 (시작, 끝) 으로 묶는다. 1Hz 가정.
    merge_gap_s 초 이하로 떨어진 구간은 하나로 합치고, min_s 초보다 짧은 구간은 버린다."""
    runs, start, prev = [], None, None
    for ts, on in mask.items():
        if on:
            if start is None:
                start = ts
            prev = ts
        elif start is not None:
            runs.append([start, prev])
            start = None
    if start is not None:
        runs.append([start, prev])
    merged = []
    for s, e in runs:
        if merged and (s - merged[-1][1]).total_seconds() <= merge_gap_s + 1:
            merged[-1][1] = e
        else:
            merged.append([s, e])
    return [(s, e) for s, e in merged if (e - s).total_seconds() + 1 >= min_s]


def _frame(kind: str, runs: list[tuple]) -> pd.DataFrame:
    return pd.DataFrame(
        [(kind, s, e, int((e - s).total_seconds()) + 1) for s, e in runs],
        columns=["event_type", "start_time", "end_time", "duration_s"],
    )


def detect_apnea(v: pd.DataFrame, p=PARAMS["apnea"]) -> pd.DataFrame:
    mask = (v["respiration_rate_bpm"] < p["resp_lt"]) & (v["breath_amplitude_pct"] < p["amp_lt"]) & (v["in_bed"] == 1)
    return _frame("apnea_suspected", _runs(mask, p["min_s"]))


def detect_toss(v: pd.DataFrame, p=PARAMS["toss"]) -> pd.DataFrame:
    smooth = v["movement_index"].rolling(p["roll_s"], center=True, min_periods=1).mean()
    mask = (smooth > p["mov_gt"]) & (v["in_bed"] == 1)
    return _frame("toss", _runs(mask, p["min_s"], p["merge_gap_s"]))


def detect_bed_exit(v: pd.DataFrame, p=PARAMS["bed_exit"]) -> pd.DataFrame:
    return _frame("bed_exit", _runs(v["in_bed"] == 0, p["min_s"]))


def detect_all(v: pd.DataFrame) -> pd.DataFrame:
    out = pd.concat([detect_apnea(v), detect_toss(v), detect_bed_exit(v)], ignore_index=True)
    return out.sort_values("start_time").reset_index(drop=True)


# ----------------------------------------------------------------- 평가
def _overlap(a_s, a_e, b_s, b_e) -> bool:
    return a_s <= b_e and b_s <= a_e


def evaluate(pred: pd.DataFrame, labels: pd.DataFrame, index: pd.DatetimeIndex) -> pd.DataFrame:
    """유형별 평가.
    - 이벤트 단위: 한 초라도 겹치면 맞춘 것으로 본다 (precision / recall)
    - 초 단위: 정답 구간과 예측 구간이 겹친 초의 정밀도·재현율·F1
    """
    rows = []
    for kind in ["apnea_suspected", "toss", "bed_exit"]:
        p = pred[pred.event_type == kind]
        t = labels[labels.event_type == kind]
        tp_p = sum(any(_overlap(r.start_time, r.end_time, l.start_time, l.end_time) for l in t.itertuples()) for r in p.itertuples())
        tp_t = sum(any(_overlap(l.start_time, l.end_time, r.start_time, r.end_time) for r in p.itertuples()) for l in t.itertuples())

        def to_mask(df):
            m = pd.Series(False, index=index)
            for r in df.itertuples():
                m[r.start_time:r.end_time] = True
            return m
        mp, mt = to_mask(p), to_mask(t)
        tp = int((mp & mt).sum()); fp = int((mp & ~mt).sum()); fn = int((~mp & mt).sum())
        prec_s = tp / (tp + fp) if tp + fp else float("nan")
        rec_s = tp / (tp + fn) if tp + fn else float("nan")
        f1_s = 2 * prec_s * rec_s / (prec_s + rec_s) if tp else 0.0
        rows.append({
            "유형": kind, "정답 수": len(t), "탐지 수": len(p),
            "이벤트 정밀도": tp_p / len(p) if len(p) else float("nan"),
            "이벤트 재현율": tp_t / len(t) if len(t) else float("nan"),
            "초단위 F1": f1_s,
        })
    return pd.DataFrame(rows)


if __name__ == "__main__":
    sid = sys.argv[1] if len(sys.argv) > 1 else "20261103_s01"
    v = features.load_vitals(sid)
    labels = features.load_events(sid)
    pred = detect_all(v)
    print(f"세션 {sid}: 탐지 {len(pred)}건")
    print(pred.to_string(index=False))
    print()
    print(evaluate(pred, labels, v.index).round(3).to_string(index=False))
