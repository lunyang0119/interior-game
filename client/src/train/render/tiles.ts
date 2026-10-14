/** Atlas frames the train renderer uses, under stable `train_*` names. layout.ts never sees art; CarMap only
 *  uses these logical keys, so swapping the art (or pointing at dedicated slices after `preprocess.py build`)
 *  is a change in this file alone. Keys ending in `_door` are door placeholders. */

export const ATLAS = "interiors";

/** logical key → interiors-atlas frame */
export const TRAIN_FRAMES = {
  train_floor: "tile_floor_gray",
  train_floor_door: "tile_floor_wood",                   // threshold tile under every door gap
  train_wall_top: "tile_wall_top",
  train_wall_bottom: "tile_wall_bottom",
  train_window: "mordgen_024_window_grey",               // 32×32: two wall cells
  train_bench: "mordjail_006_bench_seat",                // 48×16: three floor cells
  train_side_door: "mordgen_011_door_tan",               // 16×32: the gap in a vertical partition (1 wide × 2 tall)
  train_back_door: "mordernhospital_06_door",            // 32×32: the corridor cut through a back wall (2 wide × 2 tall)
  train_dev_curtain: "mordgen_032_curtain_tan",          // 48×48, hangs over the wall band
  train_dev_coffeepot: "mordkitchen_090_kettle_with_extras",
  train_dev_light: "ppfurn_090_standing_lamp_cross_a",
  train_dev_speaker: "ppfurn_093_cabinet_speaker_narrow_grey_a",
} as const;

export type TrainKey = keyof typeof TRAIN_FRAMES;

/** Device sprite per engine device: logical key + footprint in cells (bottom-left anchored on the device cell). */
export const DEVICES: Record<string, { key: TrainKey; w: number; h: number; dy?: number }> = {
  curtain: { key: "train_dev_curtain", w: 3, h: 3, dy: -1 },
  coffeepot: { key: "train_dev_coffeepot", w: 3, h: 1 },
  light: { key: "train_dev_light", w: 1, h: 2 },
  speaker: { key: "train_dev_speaker", w: 1, h: 2 },
};

export const PARTITION_FILL = 0x23232e;
export const PARTITION_EDGE = 0x3b3b4c;
export const DOOR_FRAME = 0x8a6b3f;
