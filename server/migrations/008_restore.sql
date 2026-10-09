-- Restoration stages, deliveries (fish handed in instead of sold) and the activity log.

-- What happened, for the activity panel. amount = signed change of the shared pool (+ = the pool grew):
-- place -price, remove/sell +price, fish +value, deliver -value, earn +delta, stage NULL.
CREATE TABLE events (
  seq       INTEGER PRIMARY KEY AUTOINCREMENT,
  ts        INTEGER NOT NULL,
  kind      TEXT NOT NULL,
  room_id   TEXT,
  player_id TEXT,
  item_id   TEXT,
  amount    INTEGER,
  data      TEXT
);
CREATE INDEX idx_events_ts ON events(ts);

-- A catch counted toward a room's stage. ledger_seq = the 'fish' ledger row it came from (one delivery per catch).
CREATE TABLE deliveries (
  seq        INTEGER PRIMARY KEY AUTOINCREMENT,
  ts         INTEGER NOT NULL,
  player_id  TEXT NOT NULL REFERENCES players(id),
  room_id    TEXT NOT NULL,
  stage_idx  INTEGER NOT NULL,
  kind       TEXT NOT NULL,
  item_id    TEXT NOT NULL,
  ledger_seq INTEGER NOT NULL UNIQUE REFERENCES ledger(seq)
);
CREATE INDEX idx_deliveries_stage ON deliveries(room_id, stage_idx);

-- Backfill the log from the ledger: a refund with no matching purchase was seeded junk (= sold).
INSERT INTO events(ts, kind, room_id, player_id, item_id, amount)
SELECT l.ts,
       CASE l.kind
         WHEN 'refund' THEN CASE WHEN EXISTS (SELECT 1 FROM ledger p WHERE p.kind = 'place' AND p.item_uid = l.item_uid)
                                 THEN 'remove' ELSE 'sell' END
         ELSE l.kind END,
       i.room_id, l.player_id,
       CASE WHEN l.kind = 'fish' THEN substr(l.item_id, 6) ELSE l.item_id END,
       -l.amount
FROM ledger l LEFT JOIN items i ON i.uid = l.item_uid
ORDER BY l.seq;
