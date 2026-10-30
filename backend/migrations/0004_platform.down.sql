DROP TABLE IF EXISTS notifications;
DROP TABLE IF EXISTS place_votes;
DROP TABLE IF EXISTS place_candidates;
DROP TABLE IF EXISTS event_updates;
DROP TABLE IF EXISTS event_feedback;
DROP TABLE IF EXISTS event_rsvps;
ALTER TABLE circle_events DROP COLUMN event_id;
DROP INDEX IF EXISTS idx_events_org;
DROP INDEX IF EXISTS idx_events_circle2;
DROP TABLE IF EXISTS events;
DROP TABLE IF EXISTS circle_messages;
CREATE TABLE reports_v1 (
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
INSERT INTO reports_v1 SELECT * FROM reports WHERE target_type <> 'message';
DROP TABLE reports;
ALTER TABLE reports_v1 RENAME TO reports;
CREATE TABLE memberships_v1 (
  circle_id TEXT NOT NULL REFERENCES circles(id) ON DELETE CASCADE,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  role TEXT NOT NULL DEFAULT 'member' CHECK (role IN ('host','moderator','member')),
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','pending','left','removed')),
  joined_at REAL NOT NULL,
  PRIMARY KEY (circle_id, user_id)
);
INSERT INTO memberships_v1 SELECT circle_id, user_id, role, CASE status WHEN 'rejected' THEN 'left' ELSE status END, joined_at FROM memberships;
DROP TABLE memberships;
ALTER TABLE memberships_v1 RENAME TO memberships;
CREATE INDEX idx_mem_user ON memberships(user_id);
DROP INDEX IF EXISTS idx_circles_org;
ALTER TABLE circles DROP COLUMN updated_at;
ALTER TABLE circles DROP COLUMN join_policy;
ALTER TABLE circles DROP COLUMN image_url;
ALTER TABLE circles DROP COLUMN org_id;
DROP TABLE IF EXISTS org_invites;
DROP TABLE IF EXISTS org_members;
DROP TABLE IF EXISTS organisations;
DROP TABLE IF EXISTS auth_tokens;
DROP TABLE IF EXISTS sessions;
DROP TABLE IF EXISTS accounts;
