-- Multiple shared rooms: every item belongs to one room; each room has its own version counter.
ALTER TABLE items ADD COLUMN room_id TEXT NOT NULL DEFAULT 'inn';
CREATE INDEX idx_items_room ON items(room_id);
INSERT INTO room_meta(k, v) SELECT 'version:inn', v FROM room_meta WHERE k = 'version';
DELETE FROM room_meta WHERE k = 'version';
