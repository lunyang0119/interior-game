-- The inn cat: one row per KST day somebody petted it (the first pet of the day; later pets are no-ops).
-- Affection = number of these rows among the last 3 KST days (0..3), added to the inn's comfort score.
CREATE TABLE cat_pets (
  day       TEXT PRIMARY KEY,                      -- 'YYYY-MM-DD' in KST
  player_id TEXT NOT NULL REFERENCES players(id),
  ts        INTEGER NOT NULL
);
