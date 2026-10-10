-- The inn cat, take two: every pet counts. Rows are batches of taps (the client groups quick taps);
-- affection = min(3, SUM(n) / 100), never decays. The old once-a-day rows become one tap each.
CREATE TABLE cat_taps (
  seq       INTEGER PRIMARY KEY AUTOINCREMENT,
  ts        INTEGER NOT NULL,
  player_id TEXT NOT NULL REFERENCES players(id),
  n         INTEGER NOT NULL
);
INSERT INTO cat_taps(ts, player_id, n) SELECT ts, player_id, 1 FROM cat_pets ORDER BY ts;
DROP TABLE cat_pets;
