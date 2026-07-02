-- ORCHESTRATOR-OWNED TABLES ------------------------------------------------
CREATE TABLE IF NOT EXISTS sessions (
    session_id  TEXT PRIMARY KEY,
    user_id     TEXT,
    domain      TEXT,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS turns (
    turn_id      TEXT PRIMARY KEY,
    session_id   TEXT NOT NULL,
    turn_index   INTEGER NOT NULL,
    pm_query     TEXT NOT NULL,
    final_answer TEXT,
    timestamp    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_turns_session ON turns(session_id);

CREATE TABLE IF NOT EXISTS agent_calls (
    id         BIGSERIAL PRIMARY KEY,
    turn_id    TEXT NOT NULL,
    call_index INTEGER,
    agent      TEXT,
    activated  BOOLEAN,
    prompt     TEXT,
    raw_text   TEXT,
    success    BOOLEAN,
    error      TEXT,
    timestamp  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_agent_calls_turn ON agent_calls(turn_id);

-- REVIEWS_A-OWNED TABLE (app-store style) ----------------------------------
CREATE TABLE IF NOT EXISTS reviews_store (
    ext_id     TEXT PRIMARY KEY,
    source     TEXT NOT NULL,          -- 'app_store' | 'play_store'
    title      TEXT,
    body       TEXT NOT NULL,
    rating     REAL,                   -- 1..5
    author     TEXT,
    sentiment  TEXT NOT NULL,          -- positive|neutral|negative
    review_dt  TEXT,                   -- when customer wrote it (ISO-8601)
    domain_tag TEXT                    -- optional pre-tag: search|checkout|...
);

-- REVIEWS_B-OWNED TABLE (survey / support feedback) ------------------------
CREATE TABLE IF NOT EXISTS feedback_survey (
    ext_id      TEXT PRIMARY KEY,
    channel     TEXT NOT NULL,         -- 'survey' | 'support_ticket' | 'nps'
    body        TEXT NOT NULL,
    nps_score   INTEGER,               -- 0..10 (nullable)
    order_id    TEXT,
    sentiment   TEXT NOT NULL,
    feedback_dt TEXT,                  -- ISO-8601
    domain_tag  TEXT
);
