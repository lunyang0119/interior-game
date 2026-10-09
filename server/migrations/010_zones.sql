-- Guest units: a reservation belongs to a zone of the room when the room has zones (NULL = the whole room).
ALTER TABLE reservations ADD COLUMN zone_id TEXT;
