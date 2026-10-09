# preprocess

Turns the raw packs in `assets/` (gitignored) into clean sheets under `client/public/gen/`.

`assets/graphic/`은 용도별로 세 폴더: `Interior/`(방·가구·캐릭터 팩), `Map/`(바깥 맵 타일, 부두 배경), `GUI/`(프레임·아이콘).
`config.py`의 `SHEETS`(실내)와 `MAP_SHEETS`(맵)가 각 시트 경로를 잡고 있다.

```
python tools/preprocess/preprocess.py scan --sheet interiors   # find pieces → slices.json + contact_interiors.png
python tools/preprocess/preprocess.py build                    # named slices → interiors.png/.json, chars/, map.png/.json, dock/, manifest.json
python tools/preprocess/preprocess.py scaffold                 # add placeholder items.json rows for new keys
```

## 편집기 (좌표 안 찾아도 됨)

```
python tools/preprocess/preprocess.py editor      # = python tools/preprocess/editor.py, 브라우저가 열림
```
시트를 골라 확대해서 보면서 **빈 곳을 드래그하면 새 슬라이스**(16px 격자 스냅), 박스를 클릭·드래그·모서리로 이동/크기 조절, 방향키로 한 칸씩.
오른쪽 패널에서 key·좌표·`parts`(세로 이어붙이기), 잘린 결과 미리보기, 같은 key의 `items.json` 항목(이름·가격·칸수·레이어·is_surface),
방에 놓인 모습(벽지는 폭 슬라이더)까지 보고 **슬라이스 저장 / 아이템 저장 / 빌드** 버튼으로 마무리. 빌드 후 `client/public/gen/`을 VM에 올리면 됨.

Workflow for adding furniture:
1. `scan`, open `contact_interiors.png`, find the red `#NNN` label of the piece you want.
2. In `slices.json` rename `auto_interiors_NNN` to a real key (e.g. `sofa_blue`). Fix x/y/w/h if the scan merged neighbours.
3. `build`, then `scaffold`, then edit the new row in `data/items.json` (name, price, footprint w/h, layer, is_surface).

A slice can also be `"parts": [{sheet,x,y,w,h}, ...]` — rects stacked top-to-bottom into one frame (used for the wallpaper strips whose blocks are separated by transparent lines; every wallpaper is cut to 48px = 3 wall rows).

Only named slices (not `auto_*`) go into the atlas. Keys starting with `tile_` are room tiles, not shop items.
In the editor, tick slices in the list (☑ 전체 / ☑ auto = everything visible on the current sheet + search) and press
**이름 일괄 변경**: each `auto_`/`new_` key becomes `[<folder>_]<sheet><original>`, e.g. `auto_interiors_017` → `inte_017`,
a Map sheet `.../Grass.png` → `map_gras_003` (folder omitted when it is `Interior`; sheet = first 4 letters of the file
name; collisions get `_2`, `_3`…). Items using the slice follow the rename. Named slices are left alone.
Character strips: 24 frames = 6 per direction in order right, up, left, down. `run` then `idle` are concatenated (48 frames).

## 정식 팩 낱개 가구 (Theme_Sorter_Singles)

`assets/graphic/Interior/moderninteriors-win/1_Interiors/16x16/Theme_Sorter_Singles/<테마>/`에 가구가 한 장씩 PNG로 있다 (탐색기에서 미리보기로 고르면 됨).
`slices.json`에 좌표 대신 파일로 추가:

```json
{"key": "bed_blue", "file": "moderninteriors-win/1_Interiors/16x16/Theme_Sorter_Singles/4_Bedroom_Singles/Bedroom_Singles_12.png"}
```

경로는 `assets/graphic/Interior/` 기준. 그 다음 `build` → `scaffold` → `data/items.json`에서 이름/가격 편집 (footprint w/h는 내가 잡음).

## 동결(freeze): 소스 팩이 사라진 슬라이스

`build`는 슬라이스의 시트/파일이 디스크에 없으면 **직전 아틀라스(`gen/interiors.png`)의 프레임을 그대로 복사**한다.
끝나면 `WARNING: N interior slices copied from the previous atlas ...`로 어떤 시트의 어떤 키가 동결됐는지 찍힌다.
지금은 `Modern tiles_Free` 팩(`interiors`, `room_builder` 시트, 184개)이 그렇다. 동결된 슬라이스는 에디터에서 좌표를 바꿔도 반영되지 않는다.
팩을 다시 `assets/graphic/Interior/Modern tiles_Free/`에 넣으면 다음 빌드부터 원본에서 잘린다.
아틀라스와 직전 아틀라스 둘 다에 없는 키는 예전처럼 빌드가 멈춘다.

캐릭터 레이어는 **줄어들면 빌드가 거부**된다 (`refusing to shrink character layers`). 캐릭터 생성기 폴더가 없는 PC에서 빌드하면
머리 508종이 사라지고 DB에 저장된 아바타 인덱스가 밀리기 때문. 정말 줄이려는 거면 `build --allow-shrink`.

## 타일 메타: 발소리 · 통행 (`step`, `walk`)

슬라이스 편집기에서 `tile_*` 슬라이스나 맵 시트 슬라이스를 고르면 **발소리**(wood / tile / grass / water / none)와 **못 지나감**(walk:false) 칸이 뜬다.
`slices.json`/`map_slices.json`의 해당 슬라이스에 `"step": "wood"`, `"walk": false`로 저장되고, `build`가 `manifest.json`의 키 정보에 복사한다. 서버는 이를 `/api/catalog`의 `tiles` (`interior`/`map` 아틀라스별)로 내보낸다.
- 방: 아바타가 서 있는 칸의 바닥 타일(`floor` 격자 → 없으면 `tiles.floor`)의 `step`으로 발소리를 고른다(기본 wood). 맵은 deco → ground 순서로 보고 기본은 grass.
- `walk:false` 타일은 아바타가 못 밟고(길찾기가 돌아감), 가구·러그도 못 놓는다(`placement.py`·`rules.ts` 양쪽 규칙). 물 타일이 대표적. 지금 `mtile_water`는 `step: water`만 있고 통행은 열려 있다 — 맵에 다리가 다 놓이면 체크박스 하나로 막으면 된다.
- 가구 충돌은 **플레이어가 놓은 가구**만 막는다. 시드(`$seed`)와 `ruined` 물건은 겹쳐 놓이는 연출용이라 통과된다.
- 발소리 파일은 `assets/sfx/walking/<종류>_*.mp3` (아래 media 참고).

## 구역 (객실) — 방 탭 "구역 그리기"

방 안에 사각형을 드래그하면 `zones: [{id, name, x, y, w, h}]`로 저장된다(id는 자동 `r1, r2…`, 이름은 `1호실…`; 옆 폼에서 바꿀 수 있음). 구역은 **손님을 따로 받는 객실**이라 안락도·침대·예약이 구역별로 계산되고, 가구는 왼쪽 위 칸이 들어 있는 구역 소속이다. 구역이 없는 방은 방 전체가 한 단위. 구역끼리 겹치거나 방 밖으로 나가면 에디터가 빨갛게 표시하고 저장을 거부하며, 게임 서버도 기동 때 거부한다. 선택/이동 도구로 드래그해 옮기고 Delete로 지운다. 구역을 그린 뒤에는 침대가 구역 안에 있는지 확인(복도의 침대는 손님에 안 잡힘). 바꾸면 **서버 재시작 필요**.

## 칸막이 벽 `partition` · `door` (방 나누기)

`wall` 레이어 스프라이트(중세 벽, 문 벽 등)에 `partition` 태그를 주면 **벽 줄이 아니라 바닥에** 놓인다: 가구와 같은 층에서 충돌하고, 아바타가 못 지나가고, 가구처럼 아래 기준으로 그려져 앞뒤 정렬이 맞는다. 문이 달린 벽에는 `partition, door`를 주면 통과할 수 있다. 측면 그림이라 세로 칸 수가 크게 잡혀 있으니 아이템 탭에서 **h를 1**로 줄여 두는 게 좋다(발자국은 맨 아랫줄, 그림은 위로 솟음). 열린 문짝처럼 그림이 벽 밑으로 몇 px 삐져나오는 조각(parts 슬라이스로 띠를 붙인 것)은 아이템의 **`offset_y`**(px)에 그 높이를 적으면 그림만 그만큼 내려 그려져 옆 벽과 바닥선이 맞는다. 발자국은 안 움직인다. 구역(객실)을 벽으로 나눌 때 쓰고, 시드로도 놓을 수 있다.

## 가구 태그 `bed` · `dog` (손님용)

아이템 탭 태그 입력에 `bed`를 넣은 가구가 방에 있어야 손님이 온다(침대 수 = 손님 상한, 시드 침대도 셈). `dog`는 매달 오는 "개를 좋아하는 손님"이 찾는 장식(강아지 인형·개집 등). 둘 다 `items.json`에 저장되고, 카탈로그는 기동 때 읽으니 바꾼 뒤 **서버 재시작 필요**.

## 가구 세트 (`set`, 안락도 세트 보너스용)

`build`가 인테리어 슬라이스마다 **출처**에서 세트 슬러그를 만들어 `manifest.json` 키에 `set`으로 넣고, 서버가 `/api/catalog`의 `items[].set`으로 내보낸다(`items.json`에는 저장하지 않는다 — 수정할 게 없음). 규칙(`preprocess.py set_of`): `SHEETS` 키는 `config.py`의 `SET_ALIASES`로 묶이고(`pi_*_lrk` → `pi_living`, `pi_*_br` → `pi_bedroom`, `topdown_*` → `topdown` …), Modern Interiors `Theme_Sorter/NN_이름_16x16.png`은 `mi_<이름>`(`mi_bedroom`, `mi_halloween`), 그 외 발견된 PNG는 파일 이름, `file` 슬라이스는 맨 위 폴더 이름. 같은 세트 가구로만 방을 채우면 안락도 보너스(설계: `docs/261009_comfort_design.md`). 세트를 합치거나 쪼개고 싶으면 `SET_ALIASES`만 고치고 `build`. 슬러그에 `sheet`가 들어가면 빌드가 거부한다.

## 맵 · 부두 에셋 (`map_slices.json`, `gen/map.*`, `gen/dock/`)

```
python tools/preprocess/preprocess.py scan --map --sheet houses   # MAP_SHEETS 시트를 map_slices.json으로 스캔
python tools/preprocess/preprocess.py build                        # map_slices.json → gen/map.png + map.json, Map/Dock/N.png → gen/dock/N.png
```
- `map_slices.json`은 `slices.json`과 같은 형식. `file` 경로는 `assets/graphic/` 기준 (예: `GUI/Map Legend Icons/Icons/Exclamation.png`).
- 배경이 단색으로 칠해진 시트(`Houses.png`)는 슬라이스에 `"transparent": [202, 226, 234]`를 주면 그 색이 투명으로 빠진다.
- 키에 `sheet`라는 단어는 쓰지 말 것 (서버 테스트가 `/api/catalog` 출력에 그 문자열이 없는지 검사한다).
- manifest에 `map: {atlas, keys}`, `dock: {layers, w, h}`가 추가된다. 부두 레이어는 0(뒤) → 8(앞) 순서, 전부 같은 크기여야 한다.

## VM 업로드 알림 (에디터 하단 바)

에디터(`/`)와 방·맵 에디터(`/world`) 하단에 **VM에 올릴 파일 N개** 상자가 뜬다. 마지막으로 `올렸음 ✔`을 누른 시점의 파일 해시를
`tools/preprocess/.deploy_state.json`(gitignore)에 기억해두고, 그 뒤 내용이 바뀐 배포 대상 파일을 폴더별로 보여준다.

- 폴더마다 VM 경로(`/opt/interior/...`)가 같이 나오니 그 폴더에 그대로 SFTP로 올리면 된다.
- 서버가 시작할 때만 읽는 파일(`server/app`, `data/`, `gen/manifest.json`)이 끼어 있으면 **재시작 필요**가 빨갛게 뜨고 명령이 같이 나온다.
  아틀라스 png/json, `media/`, `server/static/`만 바뀌었으면 재시작 없이 브라우저 새로고침으로 충분하다 (URL에 `asset_version`이 붙어 캐시를 우회).
- `client/src`가 마지막 `npm run build`보다 새로우면 **npm run build 필요**가 뜬다. 빌드하면 `server/static/`이 목록에 들어온다.
- 처음엔 기록이 없어서 "지금 상태를 기준으로 삼기" 버튼만 보인다. VM과 같은 상태일 때 한 번 눌러두면 그 뒤부터 차이만 보인다.
- 파일을 다 올리고(재시작까지 하고) `올렸음 ✔`을 누르면 목록이 비워진다. 4초마다 다시 검사하므로 저장/빌드 직후에 바로 반영된다.

## 에디터 탭 정리

- **시트·슬라이스**: 시트 드롭다운에 `assets/graphic/Interior`·`Map` 아래 모든 PNG가 자동으로 뜬다 (이름 있는 시트 / 팩 전체 / 맵 세 그룹, 위 칸에 이름 일부를 치면 걸러짐).
  맵 그룹 시트에서 만든 슬라이스는 `map_slices.json`으로 간다. 슬라이스에 `scale`(32px 타일은 0.5)과 `배경색 제거`(단색 배경 시트용, "찍기"로 픽셀 클릭)를 줄 수 있다.
  원본이 없는 시트(동결)도 목록에 뜨지만 좌표는 못 바꾼다.
  **32px 시트**는 슬라이스마다 `scale` 0.5를 주는 대신 **32→16 축소본 만들기** 버튼(또는 `python tools/preprocess/preprocess.py shrink <시트 경로|폴더>`)으로
  `assets/graphic/<Interior|Map>/_16px/<경로를 __로 이은 이름>.png` 사본을 만들고 그 시트를 16px 격자로 자른다. 방식 `auto`는 그림이 2배 확대된 픽셀아트면
  `nearest`(픽셀 그대로 되돌림), 아니면 `box`(평균 축소)를 고른다. 원본이 바뀌면 다시 만들어야 하고, 사본도 `assets/`라 gitignore.
- **아이템**: items.json 전체를 썸네일로 검색·태그·레이어로 거른다. 카드 클릭 → 그 슬라이스로 이동.
  오른쪽 아이템 폼의 **태그**(`ruined`, `fixed`, `stairs`, `note`=쪽지로 글을 남길 수 있는 아이템, `board`=탭하면 📋 게시판(의뢰·예약)이 열리는 가구 …)와 **쌍(pair)**: 부서진 가구 ↔ 멀쩡한 가구를 양방향으로 잇는다. `ruined` 체크박스는 태그 단축키.
- **낱개**: 정식 팩 `Theme_Sorter_Singles`의 낱개 PNG를 테마별 썸네일로 보고 클릭하면 `file` 슬라이스가 생긴다.
- **캐릭터**: 전과 같음.
- **방·맵 에디터** (`/world`): 아래 참고.

## 방·맵 에디터 (`python tools/preprocess/preprocess.py editor` → 상단 "방·맵 에디터 →")

**방** 탭: `data/rooms/<id>.json`. 방 추가/복제/삭제, 이름, cols/rows/wall_rows/zoom, 벽·바닥 타일(`tile_*` 슬라이스), 막힌 칸, 스폰.
- **시드**: 팔레트에서 아이템을 고르고 "시드 놓기"로 클릭. 게임 시작 시 `$seed` 소유로 미리 놓이고 화면엔 "???"로 보인다. 시드는 방 밖으로 삐져나가거나 서로 겹쳐도 된다(원근·연출용). 단 가구는 바닥 칸(발 위치), 벽지·벽 장식은 벽 칸에 있어야 하고, 소품은 is_surface 가구 위여야 한다 — 어기면 빨간 칸으로 표시되고 게임에서 건너뛴다. `ruined` 태그면 팔 수 있고, `fixed`면 못 건드린다.
- **바닥 칠하기**: 팔레트가 `tile_floor_*` 타일로 바뀐다. 타일을 고르고 클릭/드래그로 칸마다 다른 바닥을 칠한다(우클릭 = 기본 바닥으로). 방 JSON에는 `floor: [[…]]`(rows×cols, `null` = `tiles.floor`)로 저장되고, 전부 비어 있으면 저장 시 필드가 빠진다. 게임은 이 칸의 타일로 **발소리**와 **통행 가능 여부**를 정한다(아래 "타일 메타" 참고).
- **출구(기믹)**: "출구 그리기"로 사각형을 드래그 → 어느 방(`inn_2f` 등)이나 `map`으로 갈지, 도착 좌표. 아바타가 그 칸에 도착하면 이동. 계단 스프라이트는 같은 자리에 시드로 놓고 `stairs, fixed` 태그.
- **복구 단계(`restore`)**: 방 JSON에 직접 적는다(에디터 UI는 아직 없음). 단계마다 `need`(조건)와 `reward`(보상)이 있고, 서버(`server/app/restore.py`)가 아이템·납품·공동 자금을 보고 판정해서 완료 단계 수만 `room_meta`의 `stage:<id>`에 저장한다. 단계는 되돌아가지 않는다(돈을 나중에 써도 안 잠김).
  ```json
  "restore": [
    {"id": "clean", "name": "청소", "need": [{"type": "ruined_zero"}], "reward": [{"type": "unlock", "room": "map"}]},
    {"id": "fishing", "name": "낚시", "need": [{"type": "deliver", "kind": "fish", "count": 20}, {"type": "pool", "amount": 1000}],
     "reward": [{"type": "unlock", "room": "floor_2"}]}
  ]
  ```
  need 타입: `ruined_zero`(이 방의 ruined 0개) · `placed`(플레이어가 놓은 아이템 수; `layer`/`tag`/`item_id` 중 하나로 거를 수 있음, `count`) · `deliver`(이 단계에 납품된 물고기 수, `id`로 종류 지정 가능, `count`) · `pool`(공동 자금 잔액 ≥ `amount`, 소비 안 함 — 납품하면 그 물고기 값은 풀에서 빠지니 같이 쓸 때 감안). `label`은 체크리스트 문구(없으면 기본 문구).
  reward: `unlock {room}` — 방 id, `"map"`, `"dock"`. 어떤 단계가 unlock으로 가리키는 장소는 그 단계가 끝날 때까지 **잠긴다**(배치·이동 거부, 들어가기 거부, 맵에 `icon_lock`). 아무도 가리키지 않는 장소는 늘 열려 있다. 여관(inn)·자기 방·같은 장소를 두 단계가 여는 것·순환은 서버가 시작할 때 거부한다.
- 서버는 시작할 때 방마다 **한 번만** 시드를 놓는다 (`room_meta`의 `seeded:<id>`). 시드를 고친 뒤 다시 놓고 싶으면 VM에서 `sqlite3 server/interior.db "DELETE FROM room_meta WHERE k='seeded:inn'"` 후 재시작 (이미 놓인 물건은 그대로 두고 빈 자리에만 추가된다).
- 저장하면 `inn`은 예전 서버가 읽던 `data/room.json`에도 복사된다 (`data/rooms/`가 있으면 서버는 그쪽을 쓴다).

**맵** 탭: `data/map.json`. 서버가 시작할 때 읽어 `/api/catalog`의 `map`으로 내보내고, 게임의 `MapScene`이 그린다(20×14칸 창이 아바타를 따라 스크롤). 장소 footprint는 문 칸만 빼고 막힌 칸이 되고, 데코는 막지 않는다. 부서진 물건이 남은 방의 장소 위엔 `icon_exclamation`이 둥둥 뜨고, 복구 단계가 아직 안 연 장소엔 `icon_lock`이 뜬다(둘 다 `GUI/Map Legend Icons`의 맵 슬라이스). 방에서 `to: "map"` 출구로 나오면 그 방을 가리키는 장소의 스폰에 선다(바깥·2층 같은 장소는 방의 `restore` 단계가 열어 준다 — 위 "방" 절). cols/rows(크기 적용 버튼), ground/deco 두 레이어에 맵 슬라이스를 칠하기(우클릭=지우개), 막힌 칸, 스폰.
- **장소**: 큰 스프라이트(집·표지판)를 고르면 "장소 놓기"로 바뀐다. 클릭해서 놓고 → 방 id(또는 `dock`), 이름, 문 칸("문 칸 찍기"). 아바타가 문 칸에 도착하면 "들어가시겠습니까?".
- 비교용 캐릭터(16×32)가 스폰 위치에 그려진다. 집이 너무 크면 슬라이스 에디터에서 그 집 슬라이스에 `scale` 0.5를 주고 빌드.
- 팔레트는 마지막 빌드의 `gen/map.png` 기준. 슬라이스를 추가했으면 빌드 후 새로고침.
- **배경**: `assets/graphic/Map/Backgrounds/*.png`를 넣고 빌드하면 `gen/mapbg/<파일이름>.png`로 복사되고(이름은 소문자·영숫자·_), 맵 탭 "배경" 섹션에 뜬다. "기본 배경"은 맵 전체, "배경 영역" 도구로 사각형을 그리면 그 안에서 다른 배경. 게임에선 화면에 고정된 채(스크롤 안 됨) 타일 없는 칸에 비쳐 보이고, 아바타가 영역에 들어서면 0.5초 크로스페이드로 바뀐다. 겹치면 나중 영역이 이긴다. `map.json`의 `bg_default`, `bg_zones[] {x,y,w,h,bg}`.
- **데코**(`map.decos[]`): 나무·바위처럼 타일 위에 겹쳐 놓는 오브젝트. 팔레트에서 16px보다 큰 스프라이트를 고르면 "데코 놓기"(집 이름이면 "장소 놓기"). ground/deco 타일 레이어와 무관하게 grass·water 위에 놓을 수 있다.
- **회전·반전**: 장소/데코를 선택하고 `R`(90°씩) / `F`(좌우 반전), 또는 패널 버튼. `rot`(0/90/180/270)·`flip` 필드로 저장. 90/270이면 칸 수 w/h가 바뀐다. 게임 씬은 `setAngle/setFlipX`로 같은 값을 쓰면 된다.
- **문 여러 칸**: 장소의 "문 칸 찍기"를 켜고 클릭/드래그로 칸 추가, 우클릭으로 제거, 버튼을 다시 누르면 끝. `doors: [[x,y], ...]` (예전 `door:{x,y}`는 열 때 자동 변환).
- **집별 스폰**: 장소마다 `spawn:{x,y}` = 그 집에서 나왔을 때 서는 칸(기본은 첫 문 바로 아래, "스폰 찍기"로 변경). 방 출구의 `to:"map"`은 이 값을 쓰므로 출구 쪽 도착 좌표는 비활성.

**부두** 탭: `data/dock.json` → 빌드/저장 시 `client/public/gen/dock.json`. `assets/graphic/Map/Dock/N.png` 이미지 레이어와 슬라이스(맵·실내 아틀라스) 레이어를 겹쳐 놓는다.
- 목록 위가 앞. ↑/↓로 순서, 체크로 표시/숨김, 캔버스 드래그로 픽셀 단위 이동(Shift=16px 스냅), 슬라이스는 scale.
- **낚시**: `data/fishing.json`에 물고기(id·이름·값·확률·아이콘 경로)와 입질 타이밍. 빌드가 아이콘을 `gen/fish/<id>.png`로 복사(결과 팝업용). 부두 탭의 "찌 위치"가 입질 표시(`icon_exclamation`)가 뜨는 자리(`dock.json`의 `fish:{x,y}`), 낚싯대는 `fish_rod` 슬라이스를 레이어로. 게임: 버튼 한 번 누르면 던지고, 미끼 건드림(작은 표시)은 무시, 진짜 입질(큰 표시·진동)에 버튼을 꾹 눌러 게이지를 채우면 잡힘. 값이 클수록 오래 눌러야 하고, 미끼 건드림에 누르면 도망간다.
- 게임에서는 `DockScene`이 `gen/dock.json`을 읽어 같은 순서로 그린다(아바타 없음, 왼쪽 위 나가기·낚시 버튼). 맵에서 `room: "dock"` 장소의 문에 서면 들어가고, 나가기는 그 장소의 스폰으로 돌아온다. 주소 뒤 `#dock`으로도 바로 들어갈 수 있다.
- VM에 올릴 것: `client/public/gen/dock.json`, `client/public/gen/dock/*.png`, 그리고 클라를 다시 빌드했으면 `server/static/`.

## 캐릭터 레이어

`config.py`의 `CHAR_LAYERS`가 Character_Generator 폴더(Bodies/Eyes/Outfits/Hairstyles/Accessories, 16x16)를 자동으로 읽는다.
시트 896×656에서 2번째 줄(idle)·3번째 줄(run)만 잘라 `gen/chars/<layer>/<n>.png`(48프레임)로 만든다.
`Hairstyle_SS_CC` 식 파일명의 SS가 스타일, CC가 색 → manifest의 `groups`로 묶여 에디터에서 "스타일 / 색" 두 줄이 된다.
머리·악세서리는 index 0 = 없음.

## 여관 고양이 (`gen/cat/<변종>.png`)

`build`가 `assets/graphic/Map/Cats/<변종>.png`(1024×544, 32px 칸, 변종은 `config.py`의 `CAT_VARIANT`, 기본 `orange_0`; `Markings/`는 안 씀) 하나를 잘라 `gen/cat/<변종>.png` 가로 띠 하나로 만들고 manifest에 `cat: {frameW, frameH, variant, file, anims}`를 넣는다. 원본 배치: 왼쪽부터 4칸짜리 구역 6개(앉기 `sit`, 두리번 `look`, 눕기 `lay`, 걷기 `walk`, 달리기 `run`, 달리기 2.0은 안 씀), 맨 윗줄은 구역 제목 글자라 프레임이 아니고, 그 아래로 방향마다 2줄씩 8방향(아래·우하·오른쪽·우상·위·좌상·왼쪽·좌하 순) — 첫 줄에 프레임 4개, 넘치면 둘째 줄. 빈 칸은 건너뛰므로 방향마다 프레임 수가 달라도 된다(`orange_0`: sit 7/6/7/6, look 5, lay 8, walk 4, run 5). 4방향(`down`/`right`/`up`/`left`)만 잘라서 `anims`는 `sit_down: [시작, 끝]` 식이다. PNG가 없으면 고양이 없이 빌드된다(서버 `catalog.cat` = null, 클라이언트는 고양이를 안 띄움). 변종을 바꾸면 `gen/cat/`의 이전 PNG는 지워진다. 테스트: `tools/preprocess/tests/test_build.py`.

## media (BGM · 폰트 · 효과음)

```
python tools/preprocess/preprocess.py media
```
`assets/BGM/` 최상위가 `default`(방들, 다른 장소의 폴백), `assets/BGM/<장소>/`가 장소별(`dock`, `field`, `room`; `legacy/`는 건너뜀). 각 폴더 안에서 **`night_`로 시작하는 mp3는 밤 전용, 접두사 없는 mp3는 낮** 목록이고, `day/`·`night/` 하위 폴더가 있으면 그 목록에 더해진다 → `media/bgm/<장소>/day|night/NN-이름.mp3` + `bgm.json`(`{장소: {day: [...], night: [...]}}`). 밤 곡이 하나도 없는 장소는 밤에도 낮 곡을 튼다(클라이언트 폴백), `assets/fonts/*.ttf` → `media/fonts/stardust*.ttf`.
곡을 바꾸면 다시 실행. mp3/ttf는 gitignore라 VM에는 rsync.

**효과음**: `assets/sfx/**/<종류>_아무이름.mp3` → `media/sfx/<종류>.mp3` + `media/sfx.json`. 파일 이름의 첫 `_` 앞이 종류다. 같은 종류 파일이 여러 개면 `<종류>.mp3`, `<종류>_2.mp3`, `<종류>_3.mp3`…로 전부 들어가고(`sfx.json`의 `variants`에 개수) 게임이 재생할 때마다 하나를 랜덤으로 고른다 — 고양이 울음(`cat_*.mp3`)처럼 여러 목소리를 두고 싶을 때.
- `walking/` 폴더 안의 파일은 `step_<종류>`가 된다 (`walking/wood_x.mp3` → `step_wood`). 발소리는 `wood`, `tile`, `grass`, `water` 네 종류.
- 나머지 폴더(예 `UI/`): `rod_`(던지기), `water_`(찌 착수·입질·낚아올림), `reel_`(버티는 동안 반복), `sell_`(팔기/환불), `cat_`(여관 고양이 울음, 여러 개면 랜덤), `ocean_`(부두 환경음: 부두에 있는 동안 BGM 밑에서 파일들을 번갈아 이어서 틂). 이름은 `client/src/audio/sfx.ts`의 `SFX` 표 한 곳에서 잇는다.
- `legacy/` 폴더와 접두어 없는 파일, `.aup3`는 무시. 같은 종류가 두 개면 빌드가 멈춘다.
- 음소거는 BGM 버튼(🔊) 하나로 음악·효과음이 같이 꺼진다. VM에 올릴 것: `client/public/media/sfx/*.mp3`, `media/sfx.json`.

## UI 스킨 바꾸기 (`data/ui_theme.json`)

```
python tools/preprocess/preprocess.py ui      # → client/public/media/theme.css + media/ui/*.png
```

1. 프레임 PNG를 구한다. 예: `assets/graphic/GUI/Pocket GUI/DIY_16x16.png`를 Aseprite/그림판으로 열어 원하는 박스의 **x, y, w, h**와 테두리 두께(**slice**, 모서리가 늘어나지 않는 픽셀 수)를 적는다.
   직접 잘라 저장했으면 `assets/ui/<이름>.png`로 두고 `file`로 지정해도 된다.
2. `data/ui_theme.json`의 `frames`에 넣는다. 쓸 수 있는 이름: `panel`, `button`, `button_primary`, `chip`, `input`, `ctx`(길게 누르면 뜨는 메뉴), `toast`.
   ```json
   "frames": {
     "panel":  {"sheet": "graphic/GUI/Pocket GUI/DIY_16x16.png", "x": 0, "y": 0, "w": 48, "h": 48, "slice": 8},
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

## 글자 크기 · 이름표 폰트 · 미리보기 크기 (`data/ui_theme.json`)

```json
"font": {"body": "stardust", "bold": "stardust-bold", "size": 16,
         "sizes": {"small": 13, "button": 16, "big": 18, "title": 18, "preview": 160}},
"label": {"font": "", "size": 16, "color": "#ffffff", "stroke": "#000000", "scale": 0.5}
```
- `size` = 기본 글자(px). `sizes.small` = 상점 아이템 이름/가격·안내문, `button` = 일반 버튼, `big` = 하단 상점/아바타 버튼, `title` = 패널 제목, `preview` = 아바타 미리보기 폭(px, 높이는 4:3 자동).
- `sizes_mobile` = 폰(터치 화면 또는 폭 900px 미만)에서 쓰는 같은 키들. 생략하면 `sizes`를 상한(big 20 / title 18 / button 15 / small 13 / preview 120)으로 깎아 씀. 데스크톱 크기를 폰에 그대로 쓰면 하단 버튼이 화면을 삼킴.
- `/gen/*`·`/media/*`는 Caddy가 하루 캐시하므로 클라이언트가 `/api/catalog`의 `asset_version`(아틀라스 JSON + theme.css 해시)을 URL 뒤에 붙임. `build`/`ui`를 다시 돌리고 VM에 올리면 서버 재시작만으로 모든 브라우저가 새 파일을 받음.
- `label` = 아바타 머리 위 이름표. `font`는 `media/fonts/`의 파일 이름(확장자 없이, 예 `stardust-s-bold`), 비우면 본문 폰트. 새 폰트를 쓰려면 ttf를 `assets/fonts/`에 넣고 `media` 실행 → 파일명이 `media/fonts/`에 아스키로 복사되니 그 이름을 적기. `size`×`scale`이 실제 게임 픽셀 높이 (16×0.5 = 8px, 화면 zoom 2배라 16px로 보임). 픽셀 폰트는 제작 크기(보통 16)로 두고 scale로 조절하는 게 깨끗함.
- 바꾼 뒤 `python tools/preprocess/preprocess.py ui` → 새로고침. 서버 재시작 불필요.

## 머리/옷/악세서리 직접 그려서 추가하기

게임은 **16x16 폴더**(캔버스 896×656, 프레임 16×32)만 쓴다. 32x32/48x48은 무시.
참고 파일은 `assets/custom/_reference/`에 모아뒀다 (팩에서 복사):
- `Hairstyle_01_01.png`, `Outfit_01_01.png`, `Accessory_04_Snapback_01.png`, `Body_01.png`, `Eyes_01.png` — 레이어별 예시
- `Spritesheet_animations_GUIDE.png` — 어느 줄이 무슨 애니인지
- `Character_template_16x16.png` — 몸 템플릿
- `blank_sheet_rows_marked.png` — 빈 시트. 빨간 격자 = 게임이 실제로 쓰는 부분 (2번째 줄 idle, 3번째 줄 run, 각 24프레임 = 오른쪽/위/왼쪽/아래 × 6프레임). **이 두 줄만 그리면 됨.** 나머지 줄은 비워둬도 됨.

절차:
1. 예시 파일을 Aseprite 등으로 열어 위에 덧그리거나, 빈 시트에 그린다 (캔버스 크기 896×656 유지, 투명 배경).
2. 저장 위치와 이름: `assets/custom/<폴더>/<이름>.png`
   - 머리: `assets/custom/Hairstyles/Hairstyle_30_01.png` (30 = 팩에 없는 새 스타일 번호, 01 = 색 번호. 같은 스타일의 다른 색은 `_02`, `_03`…)
   - 옷: `assets/custom/Outfits/Outfit_34_01.png`
   - 악세: `assets/custom/Accessories/Accessory_20_Name_01.png`
   - 몸/눈: `assets/custom/Bodies/Body_10.png`, `assets/custom/Eyes/Eyes_08.png`
3. `python tools/preprocess/preprocess.py build` → 에디터에 자동으로 나타남.

머리는 색 01을 팔레트의 세 가지 색(밝음 204,150,89 / 중간 179,123,63 / 어둠 171,103,54)으로만 칠하면 `data/hair_palette.png`의 추가 색들이 자동으로 적용된다. 다른 색을 쓰면 그 색 그대로 한 가지만 나옴.
