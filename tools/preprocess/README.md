# preprocess

Turns the raw LimeZu pack in `assets/` (gitignored) into clean sheets under `client/public/gen/`.

```
python tools/preprocess/preprocess.py scan --sheet interiors   # find pieces → slices.json + contact_interiors.png
python tools/preprocess/preprocess.py build                    # named slices → interiors.png/.json, chars/, manifest.json
python tools/preprocess/preprocess.py scaffold                 # add placeholder items.json rows for new keys
```

Workflow for adding furniture:
1. `scan`, open `contact_interiors.png`, find the red `#NNN` label of the piece you want.
2. In `slices.json` rename `auto_interiors_NNN` to a real key (e.g. `sofa_blue`). Fix x/y/w/h if the scan merged neighbours.
3. `build`, then `scaffold`, then edit the new row in `data/items.json` (name, price, footprint w/h, layer, is_surface).

Only named slices (not `auto_*`) go into the atlas. Keys starting with `tile_` are room tiles, not shop items.
Character strips: 24 frames = 6 per direction in order right, up, left, down. `run` then `idle` are concatenated (48 frames).

## 정식 팩 낱개 가구 (Theme_Sorter_Singles)

`assets/graphic/moderninteriors-win/1_Interiors/16x16/Theme_Sorter_Singles/<테마>/`에 가구가 한 장씩 PNG로 있다 (탐색기에서 미리보기로 고르면 됨).
`slices.json`에 좌표 대신 파일로 추가:

```json
{"key": "bed_blue", "file": "moderninteriors-win/1_Interiors/16x16/Theme_Sorter_Singles/4_Bedroom_Singles/Bedroom_Singles_12.png"}
```

경로는 `assets/graphic/` 기준. 그 다음 `build` → `scaffold` → `data/items.json`에서 이름/가격 편집 (footprint w/h는 내가 잡음).

## 캐릭터 레이어

`config.py`의 `CHAR_LAYERS`가 Character_Generator 폴더(Bodies/Eyes/Outfits/Hairstyles/Accessories, 16x16)를 자동으로 읽는다.
시트 896×656에서 2번째 줄(idle)·3번째 줄(run)만 잘라 `gen/chars/<layer>/<n>.png`(48프레임)로 만든다.
`Hairstyle_SS_CC` 식 파일명의 SS가 스타일, CC가 색 → manifest의 `groups`로 묶여 에디터에서 "스타일 / 색" 두 줄이 된다.
머리·악세서리는 index 0 = 없음.

## media (BGM · 폰트)

```
python tools/preprocess/preprocess.py media
```
`assets/BGM/day|night/*.mp3` → `client/public/media/bgm/day|night/NN-이름.mp3` + `bgm.json`, `assets/fonts/*.ttf` → `media/fonts/stardust*.ttf`.
곡을 바꾸면 다시 실행. mp3/ttf는 gitignore라 VM에는 rsync.

## UI 스킨 바꾸기 (`data/ui_theme.json`)

```
python tools/preprocess/preprocess.py ui      # → client/public/media/theme.css + media/ui/*.png
```

1. 프레임 PNG를 구한다. 예: `assets/graphic/Pocket GUI/DIY_16x16.png`를 Aseprite/그림판으로 열어 원하는 박스의 **x, y, w, h**와 테두리 두께(**slice**, 모서리가 늘어나지 않는 픽셀 수)를 적는다.
   직접 잘라 저장했으면 `assets/ui/<이름>.png`로 두고 `file`로 지정해도 된다.
2. `data/ui_theme.json`의 `frames`에 넣는다. 쓸 수 있는 이름: `panel`, `button`, `button_primary`, `chip`, `input`, `ctx`(길게 누르면 뜨는 메뉴), `toast`.
   ```json
   "frames": {
     "panel":  {"sheet": "graphic/Pocket GUI/DIY_16x16.png", "x": 0, "y": 0, "w": 48, "h": 48, "slice": 8},
     "button": {"file": "ui/button.png", "slice": 6, "pad": 8}
   }
   ```
   `pad` = 안쪽 여백(px, 기본 slice와 같음). `scale` = 화면 배율(2면 원본 1px이 2px). `colors`로 배경/글자/강조색, `font.size`로 글자 크기.
   폰트는 `font.body` / `font.bold`에 `media/fonts/`의 파일 이름(확장자 없이): `stardust`, `stardust-bold`, `stardust-s` 등.
3. `ui` 실행 → 브라우저 새로고침. 프레임을 지우면 원래 둥근 스타일로 돌아간다.
   프레임이 정의된 요소는 배경색·둥근 모서리가 꺼지고 PNG가 9-slice로 늘어난다 (`border-image`).

## 머리 색 추가 (`data/hair_palette.png`)

팩의 `Hairstyles_palette.png`를 복사한 파일. 가로 5px짜리 세로 열 하나가 색 하나이고, 위 3줄 = 밝은색, 가운데 3줄 = 중간, 아래 3줄 = 어두운색.
앞의 8열(7색 + 윤곽선)은 팩 원본이라 건드리지 말고, **오른쪽에 5px 열을 더 그리면** 그 색이 모든 헤어스타일에 추가된다 (예시로 분홍·민트 두 열이 들어있음).
`build` 실행 → 에디터의 "머리 색"이 늘어남. 열을 지우면 색도 사라지니 이미 저장된 아바타 인덱스가 밀릴 수 있음 (뒤에만 붙이는 게 안전).
