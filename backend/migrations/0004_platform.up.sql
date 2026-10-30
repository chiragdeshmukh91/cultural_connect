-- Real accounts, sessions, organisations, published events, meeting-place polls, chat, notifications.
CREATE TABLE accounts (
  user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  email TEXT NOT NULL UNIQUE,               -- stored lower-cased
  password_hash TEXT NOT NULL,              -- scrypt$N$r$p$salt$hash, never plaintext
  email_verified INTEGER NOT NULL DEFAULT 0,
  primary_mode TEXT CHECK (primary_mode IN ('individual','organisation')),
  failed_attempts INTEGER NOT NULL DEFAULT 0,
  locked_until REAL,
  created_at REAL NOT NULL,
  last_login_at REAL
);

CREATE TABLE sessions (
  token_hash TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at REAL NOT NULL,
  expires_at REAL NOT NULL,
  last_seen REAL NOT NULL
);
CREATE INDEX idx_sessions_user ON sessions(user_id);

CREATE TABLE auth_tokens (
  token_hash TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  purpose TEXT NOT NULL CHECK (purpose IN ('reset','verify')),
  created_at REAL NOT NULL,
  expires_at REAL NOT NULL,
  used_at REAL
);

CREATE TABLE organisations (
  id TEXT PRIMARY KEY,
  slug TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL CHECK (length(name) BETWEEN 2 AND 100),
  description TEXT NOT NULL DEFAULT '',
  logo_url TEXT NOT NULL DEFAULT '',
  category TEXT NOT NULL DEFAULT '',
  service_area TEXT NOT NULL DEFAULT '',
  contact_kind TEXT NOT NULL DEFAULT '' CHECK (contact_kind IN ('','email','phone','url')),
  contact_value TEXT NOT NULL DEFAULT '',
  verification_status TEXT NOT NULL DEFAULT 'not_verified'
      CHECK (verification_status IN ('not_verified','pending','verified','rejected')),
  verification_evidence TEXT NOT NULL DEFAULT '',
  verification_note TEXT NOT NULL DEFAULT '',
  verified_at REAL,
  verified_by TEXT REFERENCES users(id) ON DELETE SET NULL,
  created_by TEXT REFERENCES users(id) ON DELETE SET NULL,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);

CREATE TABLE org_members (
  org_id TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  role TEXT NOT NULL CHECK (role IN ('owner','staff')),
  created_at REAL NOT NULL,
  PRIMARY KEY (org_id, user_id)
);
CREATE INDEX idx_orgm_user ON org_members(user_id);

CREATE TABLE org_invites (
  code_hash TEXT PRIMARY KEY,
  org_id TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
  created_by TEXT REFERENCES users(id) ON DELETE SET NULL,
  created_at REAL NOT NULL,
  expires_at REAL NOT NULL,
  used_by TEXT REFERENCES users(id) ON DELETE SET NULL,
  used_at REAL
);

-- Circles: organisation ownership, image, join policy, update time.
ALTER TABLE circles ADD COLUMN org_id TEXT REFERENCES organisations(id) ON DELETE SET NULL;
ALTER TABLE circles ADD COLUMN image_url TEXT NOT NULL DEFAULT '';
ALTER TABLE circles ADD COLUMN join_policy TEXT NOT NULL DEFAULT 'auto';  -- auto | invite_only
ALTER TABLE circles ADD COLUMN updated_at REAL;
CREATE INDEX idx_circles_org ON circles(org_id);

-- Memberships: rebuild to add 'rejected' and 'invited' states (data preserved).
CREATE TABLE memberships_v2 (
  circle_id TEXT NOT NULL REFERENCES circles(id) ON DELETE CASCADE,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  role TEXT NOT NULL DEFAULT 'member' CHECK (role IN ('host','moderator','member')),
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','pending','left','removed','rejected')),
  joined_at REAL NOT NULL,
  PRIMARY KEY (circle_id, user_id)
);
INSERT INTO memberships_v2 SELECT circle_id, user_id, role, status, joined_at FROM memberships;
DROP TABLE memberships;
ALTER TABLE memberships_v2 RENAME TO memberships;
CREATE INDEX idx_mem_user ON memberships(user_id);

-- Reports: rebuild to allow reporting chat messages (data preserved).
CREATE TABLE reports_v2 (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  reporter_id TEXT REFERENCES users(id) ON DELETE SET NULL,
  circle_id TEXT NOT NULL REFERENCES circles(id) ON DELETE CASCADE,
  target_type TEXT NOT NULL CHECK (target_type IN ('post','user','message')),
  target_id TEXT NOT NULL,
  reason TEXT NOT NULL CHECK (length(reason) BETWEEN 3 AND 500),
  status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','resolved')),
  created_at REAL NOT NULL,
  UNIQUE (reporter_id, target_type, target_id)
);
INSERT INTO reports_v2 SELECT * FROM reports;
DROP TABLE reports;
ALTER TABLE reports_v2 RENAME TO reports;

-- Persistent Circle chat (optionally threaded to an activity proposal or event).
CREATE TABLE circle_messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  circle_id TEXT NOT NULL REFERENCES circles(id) ON DELETE CASCADE,
  user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
  thread TEXT NOT NULL DEFAULT '',          -- '' = main chat, 'proposal:<id>' or 'event:<id>'
  body TEXT NOT NULL CHECK (length(body) BETWEEN 1 AND 2000),
  client_id TEXT NOT NULL,                  -- idempotency key from the sender
  created_at REAL NOT NULL,
  deleted INTEGER NOT NULL DEFAULT 0,
  hidden INTEGER NOT NULL DEFAULT 0,
  UNIQUE (circle_id, user_id, client_id)
);
CREATE INDEX idx_msg_circle ON circle_messages(circle_id, thread, id);

-- Real, published events (organisation events and confirmed Circle events share this table).
CREATE TABLE events (
  id TEXT PRIMARY KEY,
  owner_kind TEXT NOT NULL CHECK (owner_kind IN ('org','circle')),
  org_id TEXT REFERENCES organisations(id) ON DELETE CASCADE,
  circle_id TEXT REFERENCES circles(id) ON DELETE CASCADE,
  proposal_id TEXT UNIQUE REFERENCES circle_events(id) ON DELETE SET NULL,
  title TEXT NOT NULL CHECK (length(title) BETWEEN 3 AND 120),
  description TEXT NOT NULL DEFAULT '',
  purpose TEXT NOT NULL DEFAULT '',
  category TEXT NOT NULL DEFAULT '',
  starts_at TEXT NOT NULL,                  -- local wall-clock ISO, interpreted in `timezone`
  ends_at TEXT NOT NULL,
  timezone TEXT NOT NULL,
  location_status TEXT NOT NULL DEFAULT 'tbc' CHECK (location_status IN ('tbc','confirmed','online')),
  venue_name TEXT NOT NULL DEFAULT '',
  address TEXT NOT NULL DEFAULT '',
  lat REAL, lon REAL,
  geo_source TEXT NOT NULL DEFAULT '',      -- '' | 'organiser' | 'nominatim'
  online_url TEXT NOT NULL DEFAULT '',
  capacity INTEGER NOT NULL CHECK (capacity BETWEEN 1 AND 5000),
  rsvp_deadline TEXT,
  cost_note TEXT NOT NULL DEFAULT '',
  materials TEXT NOT NULL DEFAULT '',
  accessibility TEXT NOT NULL DEFAULT '',
  requirements TEXT NOT NULL DEFAULT '',
  min_age INTEGER,
  safety TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','published','cancelled','completed')),
  cancel_reason TEXT NOT NULL DEFAULT '',
  visibility TEXT NOT NULL DEFAULT 'public' CHECK (visibility IN ('public','members')),
  created_by TEXT REFERENCES users(id) ON DELETE SET NULL,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL,
  published_at REAL,
  CHECK ((owner_kind = 'org' AND org_id IS NOT NULL) OR (owner_kind = 'circle' AND circle_id IS NOT NULL))
);
CREATE INDEX idx_events_org ON events(org_id, status, starts_at);
CREATE INDEX idx_events_circle2 ON events(circle_id, status, starts_at);
ALTER TABLE circle_events ADD COLUMN event_id TEXT;

CREATE TABLE event_rsvps (
  event_id TEXT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  status TEXT NOT NULL CHECK (status IN ('going','maybe','not_going')),
  attended INTEGER,                         -- NULL unknown, 1 attended, 0 no-show (set by organiser)
  updated_at REAL NOT NULL,
  PRIMARY KEY (event_id, user_id)
);

CREATE TABLE event_feedback (
  event_id TEXT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  rating INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
  comment TEXT NOT NULL DEFAULT '',
  created_at REAL NOT NULL,
  PRIMARY KEY (event_id, user_id)
);

CREATE TABLE event_updates (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id TEXT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
  author_id TEXT REFERENCES users(id) ON DELETE SET NULL,
  kind TEXT NOT NULL,
  message TEXT NOT NULL,
  reason TEXT NOT NULL DEFAULT '',
  created_at REAL NOT NULL
);
CREATE INDEX idx_evupd ON event_updates(event_id, id);

-- Meeting-place candidates for an activity proposal, and one vote per member per proposal.
CREATE TABLE place_candidates (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  proposal_id TEXT NOT NULL REFERENCES circle_events(id) ON DELETE CASCADE,
  proposer_id TEXT REFERENCES users(id) ON DELETE SET NULL,
  name TEXT NOT NULL CHECK (length(name) BETWEEN 2 AND 120),
  address TEXT NOT NULL CHECK (length(address) BETWEEN 3 AND 300),
  lat REAL, lon REAL,
  geo_source TEXT NOT NULL DEFAULT '',
  url TEXT NOT NULL DEFAULT '',
  cost_note TEXT NOT NULL DEFAULT '',
  accessibility_note TEXT NOT NULL DEFAULT '',
  created_at REAL NOT NULL,
  UNIQUE (proposal_id, name, address)
);
CREATE TABLE place_votes (
  proposal_id TEXT NOT NULL REFERENCES circle_events(id) ON DELETE CASCADE,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  place_id INTEGER NOT NULL REFERENCES place_candidates(id) ON DELETE CASCADE,
  PRIMARY KEY (proposal_id, user_id)
);

CREATE TABLE notifications (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  kind TEXT NOT NULL,
  title TEXT NOT NULL,
  body TEXT NOT NULL DEFAULT '',
  link TEXT NOT NULL DEFAULT '',
  created_at REAL NOT NULL,
  read_at REAL
);
CREATE INDEX idx_notif_user ON notifications(user_id, read_at, id);
