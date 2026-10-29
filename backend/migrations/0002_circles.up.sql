-- Individuals, Qloo-resolved interests, Circles, discussion, moderation, member-led events.
CREATE TABLE users (
  id TEXT PRIMARY KEY,
  token_hash TEXT NOT NULL UNIQUE,          -- sha256 of the bearer token; the raw token is never stored
  created_at REAL NOT NULL
);

CREATE TABLE profiles (
  user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  alias TEXT NOT NULL CHECK (length(alias) BETWEEN 2 AND 40),
  area TEXT NOT NULL DEFAULT '',            -- broad area only (city / neighbourhood), never an address
  show_area INTEGER NOT NULL DEFAULT 0,     -- opt-in: show area to fellow members
  share_interests INTEGER NOT NULL DEFAULT 0, -- opt-in: show interests to fellow members / use in Circle planning
  bio TEXT NOT NULL DEFAULT '',
  language TEXT NOT NULL DEFAULT '',
  budget_max REAL,                          -- optional, private
  availability TEXT NOT NULL DEFAULT '[]',  -- JSON list, private
  activity_prefs TEXT NOT NULL DEFAULT '[]',-- JSON list (in_person / online / indoor / outdoor)
  accessibility TEXT NOT NULL DEFAULT '[]', -- JSON list, private (used as hard constraints)
  exclude_topics TEXT NOT NULL DEFAULT '[]',-- JSON list of topics the person never wants recommended
  adult_confirmed INTEGER NOT NULL CHECK (adult_confirmed = 1),
  discoverable INTEGER NOT NULL DEFAULT 0,  -- explicit consent to be used for Circle discovery
  consent_at REAL,
  updated_at REAL NOT NULL
);

CREATE TABLE profile_interests (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  label TEXT NOT NULL CHECK (length(label) BETWEEN 1 AND 60),
  intent TEXT NOT NULL CHECK (intent IN ('enjoy','teach','learn','discuss','collaborate')),
  UNIQUE (user_id, label)
);
CREATE INDEX idx_pi_user ON profile_interests(user_id);

-- Real Qloo identifiers returned by /search, /v2/tags or /v2/audiences, as confirmed by the user.
CREATE TABLE interest_signals (
  interest_id INTEGER NOT NULL REFERENCES profile_interests(id) ON DELETE CASCADE,
  qloo_id TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('entity','tag','audience')),
  name TEXT NOT NULL,
  type TEXT NOT NULL DEFAULT '',
  source TEXT NOT NULL DEFAULT '',
  retrieved_at REAL NOT NULL,
  PRIMARY KEY (interest_id, qloo_id)
);
CREATE INDEX idx_is_qloo ON interest_signals(qloo_id);

-- Cached Qloo Insights taste profile (urn:tag + recommendations) for a discoverable user.
CREATE TABLE user_taste (
  user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  taste TEXT NOT NULL,
  retrieved_at REAL NOT NULL
);

CREATE TABLE circles (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL CHECK (length(name) BETWEEN 3 AND 80),
  purpose TEXT NOT NULL DEFAULT '',
  topic_label TEXT NOT NULL,
  topic_key TEXT NOT NULL,                  -- primary Qloo id, or 'label:<normalized>' when unresolved
  category TEXT NOT NULL DEFAULT 'general' CHECK (category IN ('general','health','political')),
  visibility TEXT NOT NULL DEFAULT 'public' CHECK (visibility IN ('public','private')),
  meeting_mode TEXT NOT NULL DEFAULT 'either' CHECK (meeting_mode IN ('in_person','online','either')),
  area TEXT NOT NULL DEFAULT '',
  area_key TEXT NOT NULL DEFAULT '',
  language TEXT NOT NULL DEFAULT '',
  intents TEXT NOT NULL DEFAULT '[]',
  accessibility TEXT NOT NULL DEFAULT '[]', -- accessibility commitments the host makes
  capacity INTEGER NOT NULL DEFAULT 12 CHECK (capacity BETWEEN 3 AND 50),
  min_size INTEGER NOT NULL DEFAULT 3 CHECK (min_size BETWEEN 2 AND 10),
  member_events INTEGER NOT NULL DEFAULT 1, -- 1: any member may propose events; 0: hosts only
  host_id TEXT REFERENCES users(id) ON DELETE SET NULL,
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','archived')),
  created_at REAL NOT NULL
);
-- One active public Circle per topic per area: blocks duplicate / racing creation.
CREATE UNIQUE INDEX uq_circle_topic_area ON circles(topic_key, area_key) WHERE status = 'active' AND visibility = 'public';

CREATE TABLE circle_signals (
  circle_id TEXT NOT NULL REFERENCES circles(id) ON DELETE CASCADE,
  qloo_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  name TEXT NOT NULL,
  type TEXT NOT NULL DEFAULT '',
  PRIMARY KEY (circle_id, qloo_id)
);
CREATE INDEX idx_cs_qloo ON circle_signals(qloo_id);

CREATE TABLE memberships (
  circle_id TEXT NOT NULL REFERENCES circles(id) ON DELETE CASCADE,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  role TEXT NOT NULL DEFAULT 'member' CHECK (role IN ('host','moderator','member')),
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','pending','left','removed')),
  joined_at REAL NOT NULL,
  PRIMARY KEY (circle_id, user_id)
);
CREATE INDEX idx_mem_user ON memberships(user_id);

CREATE TABLE posts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  circle_id TEXT NOT NULL REFERENCES circles(id) ON DELETE CASCADE,
  user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
  parent_id INTEGER REFERENCES posts(id) ON DELETE CASCADE,
  body TEXT NOT NULL CHECK (length(body) <= 2000),
  created_at REAL NOT NULL,
  edited_at REAL,
  deleted INTEGER NOT NULL DEFAULT 0,
  hidden INTEGER NOT NULL DEFAULT 0          -- hidden by a moderator
);
CREATE INDEX idx_posts_circle ON posts(circle_id, parent_id, id);

CREATE TABLE reports (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  reporter_id TEXT REFERENCES users(id) ON DELETE SET NULL,
  circle_id TEXT NOT NULL REFERENCES circles(id) ON DELETE CASCADE,
  target_type TEXT NOT NULL CHECK (target_type IN ('post','user')),
  target_id TEXT NOT NULL,
  reason TEXT NOT NULL CHECK (length(reason) BETWEEN 3 AND 500),
  status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','resolved')),
  created_at REAL NOT NULL,
  UNIQUE (reporter_id, target_type, target_id)
);

CREATE TABLE blocks (
  blocker_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  blocked_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at REAL NOT NULL,
  PRIMARY KEY (blocker_id, blocked_id),
  CHECK (blocker_id <> blocked_id)
);

CREATE TABLE circle_events (
  id TEXT PRIMARY KEY,
  circle_id TEXT NOT NULL REFERENCES circles(id) ON DELETE CASCADE,
  proposer_id TEXT REFERENCES users(id) ON DELETE SET NULL,
  title TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'proposed' CHECK (status IN ('proposed','confirmed','cancelled')),
  constraints TEXT NOT NULL,                -- JSON: validated constraints given to the planner
  plan TEXT NOT NULL,                       -- JSON: agent output (2 options, evidence, checks)
  time_options TEXT NOT NULL DEFAULT '[]',  -- JSON list of ISO datetimes
  chosen_option INTEGER,
  chosen_time TEXT,
  capacity INTEGER NOT NULL,
  location_note TEXT NOT NULL DEFAULT '',
  created_at REAL NOT NULL,
  confirmed_by TEXT REFERENCES users(id) ON DELETE SET NULL,
  confirmed_at REAL
);
CREATE INDEX idx_events_circle ON circle_events(circle_id, status);

CREATE TABLE event_votes (
  event_id TEXT NOT NULL REFERENCES circle_events(id) ON DELETE CASCADE,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  kind TEXT NOT NULL CHECK (kind IN ('activity','time')),
  choice INTEGER NOT NULL,
  PRIMARY KEY (event_id, user_id, kind)
);

CREATE TABLE rsvps (
  event_id TEXT NOT NULL REFERENCES circle_events(id) ON DELETE CASCADE,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  status TEXT NOT NULL CHECK (status IN ('going','maybe','not_going')),
  updated_at REAL NOT NULL,
  PRIMARY KEY (event_id, user_id)
);
