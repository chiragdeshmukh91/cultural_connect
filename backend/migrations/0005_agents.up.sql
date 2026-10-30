-- Autonomous agent workflows: persistent job queue + step log, discovery snapshots, Circle formation proposals,
-- automation settings, notification de-duplication, agent-drafted activity proposals and validated venues.
CREATE TABLE agent_runs (
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,                       -- discovery | circle_formation | event_planning | coordinate_proposal | event_followup
  subject_type TEXT NOT NULL DEFAULT '',    -- user | circle | circle_proposal | proposal | event
  subject_id TEXT NOT NULL DEFAULT '',
  user_id TEXT REFERENCES users(id) ON DELETE CASCADE,   -- person the run acts for (NULL = Circle/system run)
  circle_id TEXT REFERENCES circles(id) ON DELETE CASCADE, -- members of this Circle may see the run
  trigger TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'queued'
      CHECK (status IN ('queued','running','succeeded','failed','paused','cancelled','skipped')),
  dedupe_key TEXT,                          -- at most one queued/running/paused run per key
  once_key TEXT UNIQUE,                     -- runs that must happen at most once ever (reminders, follow-ups)
  attempts INTEGER NOT NULL DEFAULT 0,
  max_attempts INTEGER NOT NULL DEFAULT 3,
  next_run_at REAL NOT NULL,
  locked_at REAL,
  input TEXT NOT NULL DEFAULT '{}',
  state TEXT NOT NULL DEFAULT '{}',         -- completed step outputs: makes a run resumable after restart
  output TEXT NOT NULL DEFAULT '{}',
  error TEXT NOT NULL DEFAULT '',
  created_at REAL NOT NULL,
  started_at REAL,
  finished_at REAL,
  updated_at REAL NOT NULL
);
CREATE UNIQUE INDEX uq_agent_runs_active ON agent_runs(dedupe_key) WHERE dedupe_key IS NOT NULL AND status IN ('queued','running','paused');
CREATE INDEX idx_agent_runs_queue ON agent_runs(status, next_run_at);
CREATE INDEX idx_agent_runs_user ON agent_runs(user_id, created_at);
CREATE INDEX idx_agent_runs_circle ON agent_runs(circle_id, created_at);

CREATE TABLE agent_steps (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
  attempt INTEGER NOT NULL,
  name TEXT NOT NULL,
  tool TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('running','ok','warn','error','skipped')),
  message TEXT NOT NULL DEFAULT '',
  sources TEXT NOT NULL DEFAULT '[]',       -- real data sources checked: [{type, detail, ...}]
  data TEXT NOT NULL DEFAULT '{}',
  started_at REAL NOT NULL,
  finished_at REAL
);
CREATE INDEX idx_agent_steps_run ON agent_steps(run_id, id);

CREATE TABLE agent_settings (
  user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  automation INTEGER NOT NULL DEFAULT 1,     -- 0 = paused: no automatic discovery / formation for this person
  circle_invites INTEGER NOT NULL DEFAULT 1, -- 0 = never invite me to agent-proposed Circles
  email_notify INTEGER NOT NULL DEFAULT 0,   -- 1 = also email agent notifications (only if SMTP is configured)
  updated_at REAL NOT NULL
);

CREATE TABLE user_discovery (
  user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  run_id TEXT NOT NULL,
  payload TEXT NOT NULL,
  created_at REAL NOT NULL
);

CREATE TABLE circle_proposals (
  id TEXT PRIMARY KEY,
  topic_key TEXT NOT NULL,
  area_key TEXT NOT NULL,
  topic_label TEXT NOT NULL,
  name TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  category TEXT NOT NULL DEFAULT 'general',
  meeting_mode TEXT NOT NULL DEFAULT 'either',
  area TEXT NOT NULL DEFAULT '',
  language TEXT NOT NULL DEFAULT '',
  signals TEXT NOT NULL DEFAULT '[]',       -- Qloo signals of the topic (as resolved for the initiator)
  min_size INTEGER NOT NULL DEFAULT 3,
  status TEXT NOT NULL DEFAULT 'gathering' CHECK (status IN ('gathering','open','formed','cancelled')),
  circle_id TEXT REFERENCES circles(id) ON DELETE SET NULL,
  created_by_run TEXT,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);
CREATE UNIQUE INDEX uq_cprop_open ON circle_proposals(topic_key, area_key) WHERE status IN ('gathering','open');

CREATE TABLE circle_proposal_members (
  proposal_id TEXT NOT NULL REFERENCES circle_proposals(id) ON DELETE CASCADE,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  role TEXT NOT NULL DEFAULT 'invitee' CHECK (role IN ('initiator','invitee')),
  status TEXT NOT NULL DEFAULT 'candidate' CHECK (status IN ('candidate','invited','accepted','declined','withdrawn')),
  score REAL NOT NULL DEFAULT 0,
  reasons TEXT NOT NULL DEFAULT '[]',       -- shown only to this person
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL,
  PRIMARY KEY (proposal_id, user_id)
);
CREATE INDEX idx_cpm_user ON circle_proposal_members(user_id);

ALTER TABLE notifications ADD COLUMN dedupe_key TEXT;
CREATE UNIQUE INDEX uq_notif_dedupe ON notifications(dedupe_key) WHERE dedupe_key IS NOT NULL;

ALTER TABLE profiles ADD COLUMN timezone TEXT NOT NULL DEFAULT '';
ALTER TABLE circles ADD COLUMN auto_plan INTEGER NOT NULL DEFAULT 1;
ALTER TABLE circles ADD COLUMN approval_policy TEXT NOT NULL DEFAULT 'host';  -- host | auto

ALTER TABLE circle_events ADD COLUMN source TEXT NOT NULL DEFAULT 'member';     -- member | agent
ALTER TABLE circle_events ADD COLUMN run_id TEXT;
ALTER TABLE circle_events ADD COLUMN vote_deadline REAL;
ALTER TABLE circle_events ADD COLUMN selection TEXT;                            -- JSON: tallied choice + rule used
CREATE UNIQUE INDEX uq_agent_draft ON circle_events(circle_id) WHERE source = 'agent' AND status = 'proposed';

ALTER TABLE place_candidates ADD COLUMN source_ref TEXT NOT NULL DEFAULT '';    -- Qloo entity id when found by the agent
ALTER TABLE place_candidates ADD COLUMN validation TEXT NOT NULL DEFAULT '';    -- JSON: per-field verification status
