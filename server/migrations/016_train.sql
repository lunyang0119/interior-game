-- Train (fugitive hidden-movement) minigame, server/app/train. One game at a time; every transition snapshots the
-- engine state (GameState.to_dict(), null while the lobby is open) plus the server policy (deadline, votes, pause)
-- as one JSON blob so a restart restores the game and re-arms the round timer from the stored deadline.
CREATE TABLE train_games (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  status     TEXT NOT NULL,          -- LOBBY | ROUND_OPEN | PAUSED | CAPTURED | ENDED
  state_json TEXT NOT NULL,          -- {"engine": ..., "policy": ...}
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);
CREATE INDEX idx_train_games_status ON train_games(status);
-- the fugitive/admin binding (POST /api/train/claim) outlives games
CREATE TABLE train_meta (k TEXT PRIMARY KEY, v TEXT NOT NULL);
