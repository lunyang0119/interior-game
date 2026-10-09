# Shared Room Decorator

친구들끼리 하나의 방을 같이 꾸미는 작은 웹 게임. Google Sheet의 개인별 재화를 합친 공용 풀로 가구를 사서 놓고, 온라인인 사람들의 아바타가 방을 돌아다닌다.

- 클라이언트: Phaser 3 + Vite + TypeScript (`client/`)
- 서버: FastAPI + SQLite (`server/`)
- 에셋: LimeZu Modern Interiors → `tools/preprocess/`로 전처리 (원본은 gitignore)

## 카탈로그 편집

`data/items.json`이 유일한 소스. 새 가구 추가 절차는 `tools/preprocess/README.md` 참고.
방은 `data/rooms/<id>.json` (에디터 "방" 탭; `inn`은 필수, `seed`/`exits`/`tags` 설명은 같은 README). UI 색/폰트/프레임은 `data/ui_theme.json` (같은 README의 "UI 스킨" 절).

## BGM

`assets/BGM/day/`, `assets/BGM/night/`의 mp3가 기본 BGM으로 한국시간 08:00–18:00 / 그 외로 나뉘어 랜덤 재생된다. 장소별 BGM은 `assets/BGM/<장소>/*.mp3`(낮밤 공용) 또는 `assets/BGM/<장소>/day|night/*.mp3`에 넣는다 — 장소 이름은 `dock`(낚시터), `field`(필드 지도), `room`(방들). 해당 장소·시간대에 곡이 없으면 기본 목록을 쓰고, `legacy/`는 무시된다. 장면이 바뀌면 재생 목록이 실제로 달라질 때만 페이드로 전환된다. 필드 배경은 밤(18:00–08:00)에 어둡게 덮어 그려진다(아직 전용 밤 그림은 없음). 첫 터치 후 시작, HUD 🔊 버튼으로 끄면 기억됨. 테스트용 `?bgm=day|night` 쿼리로 강제 가능.

## 배포 (Oracle Free Tier + Caddy + DuckDNS)

VM에는 Node가 필요 없다. 클라이언트 빌드와 gitignore된 산출물(`gen/`, `media/`, `server/static/`)은 PC에서 만들어 올린다.

**최초 1회 (VM에서)**
```bash
curl -fsSL https://raw.githubusercontent.com/lunyang0119/interior-game/main/deploy/setup-vm.sh | bash
nano /opt/interior/server/.env     # SHEET_URL, DUCKDNS_TOKEN 채우기 (IP_SALT는 자동 생성됨)
```
Oracle 콘솔에서 VCN → Security List → Ingress에 TCP 80, 443 추가 (스크립트가 VM 안 iptables는 열어줌).

**배포할 때마다 (VM에서)**
```bash
sudo systemctl restart interior
```
수정된 파일 전송 후, 재시작.

## 손님 · 숙박료

방의 **안락도(0–100)** 는 플레이어가 놓은 가구 가격 합(같은 가구는 두 번째부터 절반씩), 방 크기에 따른 포화, 같은 세트(출처 팩) 가구가 과반이면 보너스(최대 ×1.5), 부서진 물건 1개당 −5로 계산된다(`server/app/comfort.py`, 수치는 `data/guests.json`). 매일 **KST 09:00 체크아웃**에 잠기지 않은 방마다 `min(침대 수, 안락도 구간 1~3명)`의 손님이 `4 + 0.36×안락도`💰씩 공동 자금에 넣는다(`ledger.kind='guest'`, 📜 기록 `guest`). `bed` 태그 가구가 없으면 손님 0. 서버가 꺼져 있던 날은 최대 3일까지 소급. 가끔 **예약**(특정 가구를 2~4일 안에 놓으면 손님 1명이 2배, 못 놓으면 다음날 손님 없음)과 매달 한 번 **개를 좋아하는 손님**(`dog` 태그 장식이 있거나 안락도 70 이상이면 3배, 아니면 그냥 안 옴)이 온다. 설계 전문: `docs/261009_comfort_design.md`.

정산 상태는 `room_meta`의 `guest_day:<방>`(마지막 정산일), `no_guests_day:<방>`, `dog_month`와 `reservations` 테이블에 있다. 처음 켜진 날은 "오늘부터 센다"라 돈이 소급되지 않는다.

**맵 바꿀 때 (VM에서)**
```bash
sudo systemctl stop interior
grep DB_PATH /opt/interior/server/.env
sqlite3 <그 경로> "DELETE FROM room_meta WHERE k IN ('seeded:room2','seed_hash:room2');"
# 복구 단계를 처음부터 다시 하고 싶으면 (납품 기록은 남음)
sqlite3 <그 경로> "DELETE FROM room_meta WHERE k LIKE 'stage:%' OR k LIKE 'stage_ts:%';"
sudo systemctl start interior
```
  로그에 seeded room inn: N items (M old seed rows replaced)가 나오면 된 거

## API 요약

| 메서드 | 경로 | 설명 |
|---|---|---|
| POST | `/api/register` | 닉네임으로 로그인/등록. DB에 있는 ID면 새 토큰 발급(이전 토큰 무효), 없으면 시트 R열에 기록(없으면 새 행) 후 생성 |
| GET | `/api/me` | 내 정보 + 공용 잔액 + 기여 목록 |
| POST | `/api/sync` | 시트 강제 동기화 |
| PUT | `/api/avatar` | 아바타 레이어 인덱스 |
| GET | `/api/catalog` | 아이템/방/캐릭터 메타 |
| GET | `/api/rooms` | 방 목록: 버전, 남은 `ruined` 개수, 접속자 수, 복구 `progress`(단계 수·현재 단계의 need별 진행), `comfort`(안락도·침대 수·오늘 밤 예상 손님/숙박료·예약; 잠긴 방은 null), 최상위 `locked`(아직 못 들어가는 장소) |
| GET | `/api/activity` | 📜 기록: 최근 이벤트 **5개만**(서버가 더는 안 줌), 오늘 요약(벌이·지출·낚시 수), 모든 방의 복구 진행, `comfort`(방별 안락도·손님 뷰) |
| POST | `/api/fish/deliver` (`seq`, `room?`) | 방금 낚은 물고기(`/finish`의 `seq`)를 팔지 않고 어떤 방의 복구 단계에 **납품**. 120초 안에 1번만, 그 돈은 풀에서 다시 빠짐(`ledger.kind='deliver'`) |
| GET | `/api/room/{id}` (`/api/room` = inn) | 방 아이템 + `ruined` (ETag = 방 버전) |
| PUT | `/api/room/item/{uid}/note` `{text}` | `note` 태그 아이템(메모지·칠판·게시판)에 글 남기기(200자, 빈 문자열이면 지움). 누구나 고쳐 쓸 수 있고 방 버전이 올라가 모두에게 갱신 |
| POST | `/api/room/place` (`room_id`) · `/api/room/move` · DELETE `/api/room/item/{uid}` | 배치/이동/삭제 (서버가 규칙 검증). `ruined`/`fixed` 태그는 구매 불가(`not_for_sale`), `fixed`는 이동·삭제도 불가(`fixed_item`) |
| GET `/api/fish` · POST `/api/fish/start` · `/api/fish/finish` | 부두 낚시: 서버가 입질 일정을 만들고(진짜 1번 + 미끼 건드림), 클라가 버튼을 누른 구간을 보내면 판정. 잡으면 공용 풀에 바로 입금(`ledger.kind='fish'`) + 전원 알림. 설정은 `data/fishing.json` |
| POST | `/api/token/rotate` · GET `/api/me/logins` | 토큰 재발급 / 접속 기록 |
| WS | `/ws` | 온라인 아바타 위치(같은 방끼리), `enter`로 방 이동, 방 변경 알림(전체) |

복구 링크: `https://도메인/?t=TOKEN` — 열면 토큰이 localStorage로 옮겨지고 URL에서 지워진다.

# 에러 로그 보는 법

## 실시간으로 보기 (tail -f 같은 느낌)
  journalctl -u interior -f

## 자주 쓰는 것들
  journalctl -u interior -n 200            # 최근 200줄
  journalctl -u interior --since "1 hour ago"
  journalctl -u interior --since today
  journalctl -u interior -p warning        # WARNING 이상만 (에러 찾을 때)
  journalctl -u interior -g "removed item" # grep처럼 검색
  journalctl -u interior --no-pager | less # 페이저 없이 전체

  -f로 켜둔 채 폰에서 조작해 보면 place/move 에러가 바로 찍힘. 파이썬 예외 트레이스백도 여기 다 들어감.

### 영구 보관 확인
  Ubuntu 기본은 journald가 /var/log/journal/에 영구 저장인데, 혹시 재부팅하면 사라지는 상태면 한 번만:
  sudo mkdir -p /var/log/journal && sudo systemctl restart systemd-journald

### 앱 로그가 너무 적다면
  지금 main.py에 logging.basicConfig(level=logging.INFO)라 INFO까지는 나와. 요청별 에러(ApiError)는 access_log 테이블에도 성공/실패로 남으니, journald에서 안 보이면 sqlite3 interior.db
  "select * from access_log order by ts desc limit 50"로 봐도 돼.