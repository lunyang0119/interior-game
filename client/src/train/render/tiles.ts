/** Atlas frames the train renderer uses. One table so the art can be swapped (or replaced by dedicated
 *  `train_*` slices after `preprocess.py build`) without touching the renderer. Keys are interiors-atlas frames. */

export const ATLAS = "interiors";

export const TILES = {
  floor: "tile_floor_gray",
  door: "tile_floor_wood",           // the gap in a partition reads as a threshold
  wallTop: "tile_wall_top",
  wallBottom: "tile_wall_bottom",
  window: "mordgen_024_window_grey", // 32×32: two wall cells
  bench: "mordjail_006_bench_seat",  // 48×16: three floor cells
};

/** Device sprite per engine device; `w`/`h` in cells (for the bottom-left anchor on the device cell). */
export const DEVICES: Record<string, { key: string; w: number; h: number; dy?: number }> = {
  curtain: { key: "mordgen_032_curtain_tan", w: 3, h: 3, dy: -1 },              // hangs over the wall band
  coffeepot: { key: "mordkitchen_090_kettle_with_extras", w: 3, h: 1 },
  light: { key: "ppfurn_090_standing_lamp_cross_a", w: 1, h: 2 },
  speaker: { key: "ppfurn_093_cabinet_speaker_narrow_grey_a", w: 1, h: 2 },
};

export const PARTITION_FILL = 0x23232e;
export const PARTITION_EDGE = 0x3b3b4c;
export const DOOR_FRAME = 0x8a6b3f;
