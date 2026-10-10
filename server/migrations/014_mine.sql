-- The mine: ore nodes the server spawns once per KST calendar day (data/mine.json per_day) on free floor cells
-- of the mine room. Everyone shares them; every hit takes one off hits_left and the last hit pays the pool
-- (ledger.kind='mine', events.kind='mine'). mined_by/mined_ts stay NULL while the node still stands.
-- room_meta 'mine_day:<room>' = the day ordinal last spawned (idempotent like guest days).
CREATE TABLE ore_nodes (
  seq       INTEGER PRIMARY KEY AUTOINCREMENT,
  day       INTEGER NOT NULL,
  room_id   TEXT NOT NULL,
  x         INTEGER NOT NULL,
  y         INTEGER NOT NULL,
  kind      TEXT NOT NULL,
  hits_left INTEGER NOT NULL,
  mined_by  TEXT,
  mined_ts  INTEGER
);
CREATE INDEX idx_ore_nodes_day ON ore_nodes(room_id, day);
