-- Notes: items tagged `note` (memo pads, chalkboards, ...) carry a short text anyone can rewrite.
ALTER TABLE items ADD COLUMN note TEXT;
ALTER TABLE items ADD COLUMN note_by TEXT;
ALTER TABLE items ADD COLUMN note_ts INTEGER;
