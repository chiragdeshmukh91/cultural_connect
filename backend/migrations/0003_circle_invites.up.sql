-- Private Circles are invite-only: the host shares a random invite code; requests still need host approval.
ALTER TABLE circles ADD COLUMN invite_code TEXT;
CREATE UNIQUE INDEX uq_circle_invite ON circles(invite_code) WHERE invite_code IS NOT NULL;
