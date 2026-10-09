-- System player that owns the notes guests leave behind ('$' keeps it outside RegisterIn's pattern).
INSERT INTO players(id, token_hash, created_ts) VALUES ('$guest', 'guest-no-login', 0);
