CREATE TABLE players (
  id           TEXT PRIMARY KEY,
  token_hash   TEXT NOT NULL UNIQUE,
  created_ts   INTEGER NOT NULL,
  last_seen_ts INTEGER
);

CREATE TABLE avatars (
  id         TEXT PRIMARY KEY REFERENCES players(id),
  skin       INTEGER NOT NULL DEFAULT 0,
  hair       INTEGER NOT NULL DEFAULT 0,
  hair_color INTEGER NOT NULL DEFAULT 0,
  outfit     INTEGER NOT NULL DEFAULT 0,
  acc        INTEGER NOT NULL DEFAULT 0
);

-- Money leaving (+) or returning to (-) the shared pool. Balance is never stored.
CREATE TABLE ledger (
  seq       INTEGER PRIMARY KEY AUTOINCREMENT,
  ts        INTEGER NOT NULL,
  player_id TEXT NOT NULL REFERENCES players(id),
  amount    INTEGER NOT NULL,
  kind      TEXT NOT NULL,
  item_uid  INTEGER,
  item_id   TEXT NOT NULL
);

CREATE TABLE items (
  uid        INTEGER PRIMARY KEY AUTOINCREMENT,
  item_id    TEXT NOT NULL,
  x          INTEGER NOT NULL,
  y          INTEGER NOT NULL,
  z          INTEGER NOT NULL,
  parent_uid INTEGER REFERENCES items(uid),
  placed_by  TEXT NOT NULL REFERENCES players(id),
  ts         INTEGER NOT NULL
);
CREATE INDEX idx_items_cell ON items(x, y);

-- Last successful sheet fetch, per member.
CREATE TABLE sheet_snapshot (
  player_id  TEXT PRIMARY KEY,
  earned     INTEGER NOT NULL,
  fetched_ts INTEGER NOT NULL
);

CREATE TABLE access_log (
  seq       INTEGER PRIMARY KEY AUTOINCREMENT,
  ts        INTEGER NOT NULL,
  player_id TEXT,
  action    TEXT NOT NULL,
  ip_hash   TEXT NOT NULL,
  ua        TEXT,
  ok        INTEGER NOT NULL
);
CREATE INDEX idx_access_player_ts ON access_log(player_id, ts);

CREATE TABLE room_meta (k TEXT PRIMARY KEY, v INTEGER NOT NULL);
INSERT INTO room_meta VALUES ('version', 0);
