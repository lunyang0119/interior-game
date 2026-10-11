-- Mine v2: floors. Every KST day each floor (1..data/mine.json floors) gets its own random layout the first time
-- someone asks for it: rocks (partition sprites that block walking, stored as JSON [[x, y, key], ...]) and ore
-- nodes (ore_nodes.floor). One dud node per floor hides the ladder down (ore_nodes.ladder = 1); breaking it, or
-- any other dud with ladder_chance, opens the ladder (mine_floors.ladder_x/y). room_meta 'mine_deepest:<room>'
-- remembers the deepest floor anyone has opened (permanent; the map entrance offers those floors).
ALTER TABLE ore_nodes ADD COLUMN floor INTEGER NOT NULL DEFAULT 1;
ALTER TABLE ore_nodes ADD COLUMN ladder INTEGER NOT NULL DEFAULT 0;
CREATE INDEX idx_ore_nodes_floor ON ore_nodes(room_id, day, floor);
CREATE TABLE mine_floors (
  room_id  TEXT NOT NULL,
  day      INTEGER NOT NULL,
  floor    INTEGER NOT NULL,
  rocks    TEXT NOT NULL DEFAULT '[]',
  ladder_x INTEGER,
  ladder_y INTEGER,
  PRIMARY KEY (room_id, day, floor)
);
-- days already spawned under v1 count as a generated floor 1 (no second set for today)
INSERT INTO mine_floors(room_id, day, floor) SELECT DISTINCT room_id, day, 1 FROM ore_nodes;
DELETE FROM room_meta WHERE k LIKE 'mine_day:%';
