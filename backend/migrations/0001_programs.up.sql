-- Baseline: the organizer-workflow document store that already existed (store.py).
CREATE TABLE IF NOT EXISTS programs (id TEXT PRIMARY KEY, doc TEXT NOT NULL, updated REAL);
