-- Premade character preset (0 = none → layered avatar).
ALTER TABLE avatars ADD COLUMN preset INTEGER NOT NULL DEFAULT 0;
