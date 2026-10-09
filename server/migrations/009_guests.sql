-- Guests: reservations (a guest who asks for a specific item, or the monthly dog lover).
-- Settlement itself stores only room_meta 'guest_day:<room>' (last settled day) and 'no_guests_day:<room>'
-- (the day a missed reservation keeps everyone away); money goes to ledger kind 'guest' (item_id 'room:<id>').
CREATE TABLE reservations (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  room_id    TEXT NOT NULL,
  kind       TEXT NOT NULL,            -- 'item' | 'dog'
  item_id    TEXT,                     -- the item asked for (kind 'item')
  due_day    INTEGER NOT NULL,         -- guest day ordinal (see guests.day_key)
  created_ts INTEGER NOT NULL,
  status     TEXT NOT NULL DEFAULT 'pending',   -- pending | paid | missed | skipped
  pay        INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_reservations_room ON reservations(room_id, status);
