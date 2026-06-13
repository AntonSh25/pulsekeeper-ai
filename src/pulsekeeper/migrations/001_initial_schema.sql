CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS gateway_accounts (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    gateway TEXT NOT NULL CHECK (gateway IN ('telegram')),
    external_user_id TEXT NOT NULL,
    external_chat_id TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (gateway, external_user_id)
);

CREATE TABLE IF NOT EXISTS health_entries (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (kind IN ('food', 'weight', 'workout', 'sleep', 'symptom', 'medication', 'note')),
    note TEXT,
    value REAL,
    unit TEXT,
    logged_at TEXT NOT NULL,
    source TEXT NOT NULL CHECK (source IN ('telegram', 'cli', 'import', 'manual')),
    metadata_json TEXT,
    schema_version INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deleted_at TEXT
);

CREATE VIRTUAL TABLE IF NOT EXISTS health_entries_fts USING fts5(
    note,
    metadata_text,
    content='health_entries',
    content_rowid='id'
);

CREATE TRIGGER IF NOT EXISTS health_entries_fts_insert AFTER INSERT ON health_entries BEGIN
    INSERT INTO health_entries_fts(rowid, note, metadata_text)
    VALUES (new.id, new.note, new.metadata_json);
END;

CREATE TRIGGER IF NOT EXISTS health_entries_fts_delete AFTER DELETE ON health_entries BEGIN
    INSERT INTO health_entries_fts(health_entries_fts, rowid, note, metadata_text)
    VALUES ('delete', old.id, old.note, old.metadata_json);
END;

CREATE TRIGGER IF NOT EXISTS health_entries_fts_update AFTER UPDATE ON health_entries BEGIN
    INSERT INTO health_entries_fts(health_entries_fts, rowid, note, metadata_text)
    VALUES ('delete', old.id, old.note, old.metadata_json);
    INSERT INTO health_entries_fts(rowid, note, metadata_text)
    VALUES (new.id, new.note, new.metadata_json);
END;

CREATE TABLE IF NOT EXISTS user_profile_facts (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    key TEXT NOT NULL,
    value_json TEXT NOT NULL,
    confidence REAL,
    source TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (user_id, key)
);

CREATE TABLE IF NOT EXISTS preferences (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    key TEXT NOT NULL,
    value_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (user_id, key)
);

CREATE TABLE IF NOT EXISTS conversation_state (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    state_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    expires_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (user_id, state_type)
);

CREATE TABLE IF NOT EXISTS summary_memory (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    period_start TEXT NOT NULL,
    period_end TEXT NOT NULL,
    kind TEXT NOT NULL,
    text TEXT NOT NULL,
    metadata_json TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE VIRTUAL TABLE IF NOT EXISTS summary_memory_fts USING fts5(
    text,
    content='summary_memory',
    content_rowid='id'
);

CREATE TRIGGER IF NOT EXISTS summary_memory_fts_insert AFTER INSERT ON summary_memory BEGIN
    INSERT INTO summary_memory_fts(rowid, text)
    VALUES (new.id, new.text);
END;

CREATE TRIGGER IF NOT EXISTS summary_memory_fts_delete AFTER DELETE ON summary_memory BEGIN
    INSERT INTO summary_memory_fts(summary_memory_fts, rowid, text)
    VALUES ('delete', old.id, old.text);
END;

CREATE TRIGGER IF NOT EXISTS summary_memory_fts_update AFTER UPDATE ON summary_memory BEGIN
    INSERT INTO summary_memory_fts(summary_memory_fts, rowid, text)
    VALUES ('delete', old.id, old.text);
    INSERT INTO summary_memory_fts(rowid, text)
    VALUES (new.id, new.text);
END;

CREATE TABLE IF NOT EXISTS reminders (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    type TEXT NOT NULL,
    schedule_json TEXT NOT NULL,
    timezone TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    last_sent_at TEXT,
    next_due_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS imports (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    source TEXT NOT NULL,
    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TEXT,
    metadata_json TEXT
);

CREATE TABLE IF NOT EXISTS import_items (
    id INTEGER PRIMARY KEY,
    import_id INTEGER NOT NULL REFERENCES imports(id) ON DELETE CASCADE,
    external_id TEXT NOT NULL,
    status TEXT NOT NULL,
    metadata_json TEXT,
    UNIQUE (import_id, external_id)
);

CREATE INDEX IF NOT EXISTS idx_gateway_accounts_user_id ON gateway_accounts(user_id);
CREATE INDEX IF NOT EXISTS idx_health_entries_user_logged_at ON health_entries(user_id, logged_at);
CREATE INDEX IF NOT EXISTS idx_health_entries_user_kind_logged_at ON health_entries(user_id, kind, logged_at);
CREATE INDEX IF NOT EXISTS idx_profile_facts_user_key ON user_profile_facts(user_id, key);
CREATE INDEX IF NOT EXISTS idx_preferences_user_key ON preferences(user_id, key);
CREATE INDEX IF NOT EXISTS idx_conversation_state_user_type ON conversation_state(user_id, state_type);
CREATE INDEX IF NOT EXISTS idx_summary_memory_user_period ON summary_memory(user_id, period_start, period_end);
CREATE INDEX IF NOT EXISTS idx_reminders_enabled_due ON reminders(enabled, next_due_at);
CREATE INDEX IF NOT EXISTS idx_import_items_external_id ON import_items(external_id);
