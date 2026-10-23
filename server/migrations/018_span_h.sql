-- Floor patterns (untagged floor items) stretch both ways like wallpaper stretches sideways:
-- `span` (004) is the width, `span_h` the height in cells chosen at placement. NULL = the item's own h.
ALTER TABLE items ADD COLUMN span_h INTEGER;
