# 확인 체크리스트

전체 로드맵은 5단계야. Phase 0(전처리 복구)은 코드로 끝나고, 나머지는 아래 에셋 확인이 선행돼야 해.

| Phase | 내용 | 막히는 지점 |
|---|---|---|
| 0 | GUI/Map/Interior 레이아웃으로 빌드 복구, 무료팩 동결, 맵/부두 에셋 파이프라인 | 없음 |
| 1 | `tags` 필드, `ruined` 아이템 시드 + 판매 | 부서진 가구 스프라이트 |
| 2 | 방 여러 개, 계단 이동 | 없음 (기존 계단 스프라이트 사용) |
| 3 | 맵 씬, 느낌표 마커, 입장 확인 | 집 외관·부두 아이콘·길 타일 |
| 4 | 부두 낚시 | 낚시 연출·물고기 아이콘·게이지 UI |

---

## 이미 있는 걸로 커버되는 것

| 용도 | 에셋 |
|---|---|
| 방 타일·가구 | 기존 Interior 팩 + 동결된 아틀라스 프레임 1004개 |
| 계단 | `Interior/pixelinterior/doorswindowsstairs_LRK.png`, 풀팩 `17_Visibile_Upstairs_System_16x16.png` (이미 `stair_*` 아이템 있음) |
| 맵 잔디·물·흙 | `Map/Sprout Lands - Sprites - Basic pack/Tilesets/Grass.png`, `Water.png`, `Hills.png`, `Tilled_Dirt*.png` |
| 맵 길 | `Map/Sprout Lands - Sprites - Basic pack/Objects/Paths.png` (있음, 작음) |
| 맵 다리 | `Map/Sprout Lands - Sprites - Basic pack/Objects/Wood_Bridge.png` |
| 맵 집 외관 | `assets/graphic/Houses.png` (2070×416, 집 20채, 눈 덮인 버전 포함) |
| 느낌표 마커(임시) | `GUI/Map Legend Icons/Icons/Exclamation.png` 16×24 |
| 부두 배경 | `Map/Dock/0..8.png` 384×216 패럴랙스 9장 |
| UI 프레임 | `GUI/UIBundleFree/UiCozyFree.png` (현재 테마) |
| 아바타 | 기존 캐릭터 생성기. 맵·부두에서도 그대로 씀 |

---

## 네가 확인하거나 골라줘야 하는 것

### Phase 1 전
- [ ] **부서진 가구 스프라이트.** 에디터 "시트·슬라이스" 탭에서 팩 전체 시트를 열어 찾고, "아이템" 탭에서 `ruined` 체크 + `쌍(pair)`으로 멀쩡한 가구와 연결. 지금 아틀라스엔 "부서진" 티가 나는 게 하나도 없어.
  후보: 풀팩 `Interior/moderninteriors-win/1_Interiors/16x16/Theme_Sorter/14_Basement_16x16.png`, `11_Halloween_16x16.png`(거미줄·낡은 가구), `Old stuff/`.
  에디터에서 슬라이스한 뒤 `ruined` 태그를 달면 돼. 방 하나당 6~10종은 있어야 "청소" 느낌이 나.
  이상적: 침대/테이블/의자/선반의 **멀쩡한 버전 + 부서진 버전 쌍**.
- [ ] 여관에 처음부터 놓여 있을 부서진 가구 배치(어느 아이템을 어디에). 내가 임시로 잡아도 되지만 네 취향이 우선.

### Phase 3 전
- [ ] **최종 느낌표 마커.** GUI 번들에서 골라서 알려주기로 했던 것. 그때까지 `Exclamation.png` 임시 사용.
- [ ] **부두 미니맵 아이콘.** 맵 위 "부두" 자리에 놓을 16~32px 스프라이트. `Map Legend Icons`엔 부두가 없어서 임시로 `Bridge.png`.
- [ ] (선택) **집 외관 2상태.** 부서진 집 / 복구된 집. `Houses.png`엔 눈 덮인 버전만 있고 부서진 버전은 없음. 없으면 마커만으로 표현.
- [x] `Houses.png`에서 집 고르기 → 여관 `house_09`, 빈 집 `house_07`, `house_04` (2026-09-26 결정)
- [ ] 집 크기: 원본은 10×11칸이라 캐릭터(1×2칸)에 비해 큼. 슬라이스 에디터에서 `house_*`에 `scale` 0.5(→5×6칸)를 줄지 결정. 맵 에디터의 비교용 캐릭터로 확인.
- [ ] `mtile_path`(Sprout Lands Paths.png 0,0)는 가는 조각이라 길 타일로 부적합. 맵 시트에서 제대로 된 길 타일 슬라이스 다시 잡기.

### Phase 4 전
- [ ] **낚시 연출.** 낚싯대 든 아바타 프레임 또는 낚싯대 스프라이트 1장, 찌 1~2프레임.
  풀팩 `Theme_Sorter/9_Fishing_16x16.png`에 낚싯대·물고기가 있을 가능성 높음. 열어서 확인.
- [ ] **물고기 아이콘 4종** (멸치/고등어/참돔/보물상자, 토스트용 16px). 위 시트 후보.
- [ ] **홀드 게이지 UI.** 가로 바 프레임 + 채움. `GUI/Sprout Lands - UI Pack - Basic pack`에 프로그레스 바 있음.
- [ ] (선택) 효과음: 입질, 낚기 성공/실패, 문 여닫기. 지금은 BGM만 있음.

### 언제든
- [ ] `Modern tiles_Free` 팩을 다시 구하면 `assets/graphic/Interior/Modern tiles_Free/`에 넣기. 넣으면 동결 없이 원본에서 다시 잘림.
