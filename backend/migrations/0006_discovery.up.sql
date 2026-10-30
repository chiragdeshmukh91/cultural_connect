-- Personalised discovery: what a person saved or dismissed from their recommendations (used only for their own ranking).
CREATE TABLE recommendation_feedback (
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  item_type TEXT NOT NULL CHECK (item_type IN ('circle','event','interest')),
  item_id TEXT NOT NULL,
  action TEXT NOT NULL CHECK (action IN ('saved','dismissed')),
  label TEXT NOT NULL DEFAULT '',            -- for saved Qloo interests: the name Qloo returned
  kind TEXT NOT NULL DEFAULT '',             -- for saved Qloo interests: tag | entity
  created_at REAL NOT NULL,
  PRIMARY KEY (user_id, item_type, item_id)
);
