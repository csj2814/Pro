"""세션 1개(vitals CSV + events CSV + meta JSON)를 SQLite DB에 적재한다.

사용법:
    python db/import_session.py <DB경로> <vitals.csv> <events.csv> <meta.json>
예:
    python db/import_session.py solcare.db 20261103_s01_bedA_vitals_1hz.csv \
        20261103_s01_bedA_events_labels.csv 20261103_s01_bedA_session_meta.json
"""
import csv, json, sqlite3, sys
from pathlib import Path

SCHEMA = Path(__file__).with_name("schema.sql")


def fnum(x, cast=float):
    return None if x in ("", None) else cast(x)


def main(db_path, vitals_csv, events_csv, meta_json):
    meta = json.loads(Path(meta_json).read_text(encoding="utf-8"))
    con = sqlite3.connect(db_path)
    con.execute("PRAGMA foreign_keys = ON")
    if not con.execute("SELECT name FROM sqlite_master WHERE name='sessions'").fetchone():
        con.executescript(SCHEMA.read_text(encoding="utf-8"))

    sid = meta["session_id"]
    if con.execute("SELECT 1 FROM sessions WHERE session_id=?", (sid,)).fetchone():
        sys.exit(f"이미 적재된 세션입니다: {sid}")

    with con:  # 하나의 트랜잭션: 실패하면 전부 롤백
        con.execute(
            "INSERT OR IGNORE INTO beds (bed_id, device, frequency_ghz) VALUES (?,?,?)",
            (meta["bed_id"], meta["device"], meta["frequency_band_ghz"]),
        )
        # 가명 ID로 대상자 찾기, 없으면 생성
        row = con.execute("SELECT user_id FROM users WHERE pseudo_id=?", (meta["pseudo_id"],)).fetchone()
        if row:
            pid = row[0]
        else:
            pid = con.execute(
                "INSERT INTO users (pseudo_id, role) VALUES (?, 'patient')", (meta["pseudo_id"],)
            ).lastrowid

        rep = meta.get("report_ref", {})
        con.execute(
            """INSERT INTO sessions (session_id, bed_id, patient_id, sampling_rate_hz, timezone,
                   start_time, end_time, report_generated_at, sleep_score, sleep_efficiency_pct,
                   total_sleep_min, wake_min, data_policy)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (sid, meta["bed_id"], pid, meta["sampling_rate_hz"], meta["timezone"],
             meta["window"]["start"].replace("T", " "), meta["window"]["end"].replace("T", " "),
             rep.get("report_generated_at"), rep.get("sleep_score"), rep.get("sleep_efficiency_pct"),
             rep.get("total_sleep_min"), rep.get("wake_min"), meta.get("data_policy")),
        )

        with open(vitals_csv, encoding="utf-8-sig", newline="") as f:
            con.executemany(
                "INSERT INTO vitals VALUES (?,?,?,?,?,?,?,?)",
                ((sid, r["timestamp_kst"], fnum(r["heart_rate_bpm"], int),
                  fnum(r["respiration_rate_bpm"]), fnum(r["breath_amplitude_pct"]),
                  fnum(r["movement_index"]), int(r["in_bed"]), r["sleep_stage"])
                 for r in csv.DictReader(f)),
            )

        with open(events_csv, encoding="utf-8-sig", newline="") as f:
            con.executemany(
                "INSERT INTO events VALUES (?,?,?,?,?,?,?,?)",
                ((int(r["event_id"]), sid, r["event_type"], r["start_time_kst"],
                  r["end_time_kst"], int(r["duration_s"]), r["label_source"], r["note"] or None)
                 for r in csv.DictReader(f)),
            )

    n_v = con.execute("SELECT COUNT(*) FROM vitals WHERE session_id=?", (sid,)).fetchone()[0]
    n_e = con.execute("SELECT COUNT(*) FROM events WHERE session_id=?", (sid,)).fetchone()[0]
    print(f"적재 완료: {sid} | vitals {n_v}행, events {n_e}행")


if __name__ == "__main__":
    if len(sys.argv) != 5:
        sys.exit(__doc__)
    main(*sys.argv[1:])
