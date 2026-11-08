"""수면 단계(wake/rem/light/deep) 분류 베이스라인.

30초 구간 특징(심박·호흡·진폭·움직임) -> 수면 단계.
평가는 '시간 블록 교차검증': 같은 시간대의 인접 구간이 학습/시험에 섞이지 않도록
60분 단위 블록을 통째로 시험에 쓴다. (섞으면 점수가 부풀려진다)

실행: python ai/train_stage.py [session_id ...] [--save]
      세션을 여러 개 주면 합쳐서 학습한다.
"""
import sys

import numpy as np
import pandas as pd
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score
from sklearn.model_selection import GroupKFold

import features

FEATURES = ["hr_mean", "hr_std", "resp_mean", "resp_std", "amp_mean", "amp_std",
            "mov_mean", "mov_max"]
BLOCK_MIN = 60


def build_dataset(session_ids: list[str], window_s: int = 30):
    parts = []
    for sid in session_ids:
        f = features.window_features(features.load_vitals(sid), window_s)
        f["session"] = sid
        f["block"] = sid + "_" + ((f.index - f.index[0]).total_seconds() // (BLOCK_MIN * 60)).astype(int).astype(str)
        parts.append(f)
    d = pd.concat(parts)
    return d[FEATURES].fillna(0.0), d["stage"], d["block"]


def cross_validate(X, y, groups, make_model, n_splits=5):
    pred = pd.Series(index=y.index, dtype=object)
    for tr, te in GroupKFold(n_splits=min(n_splits, groups.nunique())).split(X, y, groups):
        m = make_model().fit(X.iloc[tr], y.iloc[tr])
        pred.iloc[te] = m.predict(X.iloc[te])
    return pred


def report(name, y, pred):
    labels = features.STAGES
    acc = accuracy_score(y, pred)
    f1 = f1_score(y, pred, labels=labels, average="macro")
    print(f"{name:<14} 정확도 {acc:.3f}   macro-F1 {f1:.3f}")
    return acc, f1


def main(argv):
    save = "--save" in argv
    sids = [a for a in argv if not a.startswith("--")] or ["20261103_s01"]
    X, y, groups = build_dataset(sids)
    print(f"세션 {sids} | 30초 구간 {len(X)}개 | 시간 블록 {groups.nunique()}개")
    print("단계 분포:", y.value_counts().to_dict(), "\n")

    report("다수 클래스", y, cross_validate(X, y, groups, lambda: DummyClassifier(strategy="most_frequent")))
    pred = cross_validate(X, y, groups, lambda: RandomForestClassifier(
        n_estimators=200, min_samples_leaf=3, class_weight="balanced", random_state=0, n_jobs=-1))
    report("RandomForest", y, pred)

    cm = pd.DataFrame(confusion_matrix(y, pred, labels=features.STAGES),
                      index=[f"실제 {s}" for s in features.STAGES],
                      columns=[f"예측 {s}" for s in features.STAGES])
    print("\n혼동행렬 (행=실제, 열=예측)")
    print(cm.to_string())

    final = RandomForestClassifier(n_estimators=200, min_samples_leaf=3, class_weight="balanced",
                                   random_state=0, n_jobs=-1).fit(X, y)
    imp = pd.Series(final.feature_importances_, index=FEATURES).sort_values(ascending=False)
    print("\n특징 중요도")
    print(imp.round(3).to_string())

    if save:
        import joblib
        from pathlib import Path
        out = Path(__file__).resolve().parent / "models"
        out.mkdir(exist_ok=True)
        joblib.dump({"model": final, "features": FEATURES, "window_s": 30}, out / "stage_rf.joblib")
        print(f"\n모델 저장: {out / 'stage_rf.joblib'}  (저장소에는 올리지 않는다)")


if __name__ == "__main__":
    main(sys.argv[1:])
