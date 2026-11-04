-- SolCare mmWave 수면/비접촉 모니터링 DB 스키마 v2 (SQLite 기준)
-- 근거: 20261103_s01 샘플 (vitals 1Hz CSV, events 라벨 CSV, session_meta JSON)
-- 개인정보: 실명 대신 가명 ID(pseudo_id)만 저장한다.
PRAGMA foreign_keys = ON;

-- 1. 사용자: 돌봄 대상자(patient)와 보호자(guardian)
CREATE TABLE users (
    user_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    pseudo_id   TEXT UNIQUE,                 -- 대상자 가명 ID (예: P001). 보호자는 NULL 가능
    name        TEXT,                        -- 보호자 표시용 이름. 대상자는 가명 사용 권장
    role        TEXT NOT NULL CHECK (role IN ('patient', 'guardian')),
    phone       TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- 2. 보호자 - 대상자 연결 (N:M)
CREATE TABLE guardian_links (
    link_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    guardian_id   INTEGER NOT NULL REFERENCES users(user_id),
    patient_id    INTEGER NOT NULL REFERENCES users(user_id),
    relationship  TEXT,
    notify_on     INTEGER NOT NULL DEFAULT 1,
    UNIQUE (guardian_id, patient_id)
);

-- 3. 침대/장치: bed_id 하나에 센서 하나
CREATE TABLE beds (
    bed_id        TEXT PRIMARY KEY,          -- 'A'
    device        TEXT,                      -- 'SolCare Sensor v0.1 (prototype)'
    frequency_ghz REAL,                      -- 60
    location      TEXT,
    installed_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- 4. 측정 세션: 한 밤(또는 한 번의 측정) 단위. session_meta.json 1개 = 1행
CREATE TABLE sessions (
    session_id            TEXT PRIMARY KEY,  -- '20261103_s01'
    bed_id                TEXT NOT NULL REFERENCES beds(bed_id),
    patient_id            INTEGER NOT NULL REFERENCES users(user_id),
    sampling_rate_hz      REAL NOT NULL,
    timezone              TEXT NOT NULL DEFAULT 'Asia/Seoul',
    start_time            TEXT NOT NULL,
    end_time              TEXT NOT NULL,
    -- 결과지(report_ref) 요약값
    report_generated_at   TEXT,
    sleep_score           INTEGER,
    sleep_efficiency_pct  REAL,
    total_sleep_min       INTEGER,
    wake_min              INTEGER,
    data_policy           TEXT,              -- 예: 합성 샘플 데이터
    is_synthetic          INTEGER NOT NULL DEFAULT 1
);

-- 5. 1Hz 측정값 (가장 많이 쌓이는 테이블: 세션당 약 3만 행)
CREATE TABLE vitals (
    session_id            TEXT    NOT NULL REFERENCES sessions(session_id),
    ts                    TEXT    NOT NULL,  -- 'YYYY-MM-DD HH:MM:SS' (KST)
    heart_rate_bpm        INTEGER,
    respiration_rate_bpm  REAL,              -- 무호흡 구간에서 0 가능
    breath_amplitude_pct  REAL,
    movement_index        REAL,
    in_bed                INTEGER NOT NULL CHECK (in_bed IN (0, 1)),
    sleep_stage           TEXT CHECK (sleep_stage IN ('wake', 'light', 'deep', 'rem')),
    PRIMARY KEY (session_id, ts)
) WITHOUT ROWID;

-- 6. 이벤트/라벨: 입면, 뒤척임, 무호흡 의심, 침대 이탈, 기상 등
CREATE TABLE events (
    event_id      INTEGER NOT NULL,
    session_id    TEXT    NOT NULL REFERENCES sessions(session_id),
    event_type    TEXT    NOT NULL,          -- sleep_onset / toss / apnea_suspected / bed_exit / final_wake
    start_time    TEXT    NOT NULL,
    end_time      TEXT    NOT NULL,
    duration_s    INTEGER NOT NULL,
    label_source  TEXT    NOT NULL,          -- sensor / model_v0.1 / (추후) manual
    note          TEXT,
    PRIMARY KEY (session_id, event_id)
);
CREATE INDEX idx_events_type_time ON events (event_type, start_time);

-- 7. 알림: 이벤트나 예측 결과에서 생성. 의학적 진단이 아니라 '관찰 대상' 수준으로 표기
CREATE TABLE alerts (
    alert_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id    INTEGER NOT NULL REFERENCES users(user_id),
    session_id    TEXT REFERENCES sessions(session_id),
    event_id      INTEGER,                   -- events.event_id (같은 session_id 안)
    alert_type    TEXT NOT NULL,             -- apnea_suspected / bed_exit_long / abnormal_hr 등
    severity      TEXT NOT NULL CHECK (severity IN ('info', 'warning', 'critical')),
    message       TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    resolved_at   TEXT
);
CREATE INDEX idx_alerts_patient_time ON alerts (patient_id, created_at);

-- 8. 알림 발송 기록 (보호자별 확인 여부)
CREATE TABLE alert_deliveries (
    delivery_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_id      INTEGER NOT NULL REFERENCES alerts(alert_id),
    guardian_id   INTEGER NOT NULL REFERENCES users(user_id),
    sent_at       TEXT NOT NULL DEFAULT (datetime('now')),
    read_at       TEXT
);
