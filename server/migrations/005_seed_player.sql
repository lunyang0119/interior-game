-- System player that owns pre-placed (seeded) items. '$' is outside RegisterIn's pattern, so nobody can log in as it.
INSERT INTO players(id, token_hash, created_ts) VALUES ('$seed', 'seed-no-login', 0);
