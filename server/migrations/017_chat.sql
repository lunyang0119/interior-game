-- Chat: one row per message sent over the room game's socket (ws {"type":"chat"}). Only the newest
-- chat.HISTORY rows are ever served (GET /api/chat); `room` is the presence room the sender stood in, so
-- clients draw a speech bubble over the avatar only where it was said. The train page has no chat.
CREATE TABLE chat (
  id        INTEGER PRIMARY KEY AUTOINCREMENT,
  ts        INTEGER NOT NULL,
  player_id TEXT NOT NULL,
  room      TEXT NOT NULL,
  text      TEXT NOT NULL
);
