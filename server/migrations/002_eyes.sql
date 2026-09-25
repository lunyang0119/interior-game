-- Character Generator layers: eyes is a new layer. hair_color stays in the table but is unused (always 0).
ALTER TABLE avatars ADD COLUMN eyes INTEGER NOT NULL DEFAULT 0;
