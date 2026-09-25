# Shared Room Decorator

친구들끼리 하나의 방을 같이 꾸미는 작은 웹 게임. Google Sheet의 개인별 재화를 합친 공용 풀로 가구를 사서 놓고, 온라인인 사람들의 아바타가 방을 돌아다닌다.

- 클라이언트: Phaser 3 + Vite + TypeScript (`client/`)
- 서버: FastAPI + SQLite (`server/`)
- 에셋: LimeZu Modern Interiors → `tools/preprocess/`로 전처리 (원본은 gitignore)

## 로컬 개발

```bash
# 0. 에셋 (한 번만) — assets/ 에 LimeZu 팩, BGM, 폰트를 둔 뒤
python tools/preprocess/preprocess.py build    # 가구 아틀라스 + 캐릭터 레이어 → client/public/gen/
python tools/preprocess/preprocess.py media    # BGM/폰트 → client/public/media/
python tools/preprocess/preprocess.py ui       # data/ui_theme.json → media/theme.css (+ 9-slice 프레임)

# 1. 서버 (가짜 시트 data/fake_sheet.json 사용)
cd server
python -m venv .venv && .venv/Scripts/pip install -e ".[dev]"   # mac/linux: .venv/bin/pip  (pillow 포함 → preprocess 도구도 이 venv로)
.venv/Scripts/python -m pytest -q
.venv/Scripts/python -m uvicorn app.main:app --port 8000 --reload

# 2. 클라이언트 (핫 리로드, /api·/ws 는 8000으로 프록시)
cd client
npm install
npm run dev        # http://localhost:5173  (폰: 같은 와이파이에서 --host 주소)
```

프로덕션 빌드는 `npm run build` → `server/static/`에 생성되고 FastAPI가 같은 오리진에서 서빙한다.

## 카탈로그 편집

`data/items.json`이 유일한 소스. 새 가구 추가 절차는 `tools/preprocess/README.md` 참고.
방 크기/타일은 `data/room.json`. UI 색/폰트/프레임은 `data/ui_theme.json` (같은 README의 "UI 스킨" 절).

## BGM

`assets/BGM/day/`, `assets/BGM/night/`의 mp3가 한국시간 08:00–18:00 / 그 외로 나뉘어 랜덤 재생된다. 첫 터치 후 시작, HUD 🔊 버튼으로 끄면 기억됨. 테스트용 `?bgm=day|night` 쿼리로 강제 가능.

## 배포 (Oracle Free Tier + Caddy + DuckDNS)

VM에는 Node가 필요 없다. 클라이언트 빌드와 gitignore된 산출물(`gen/`, `media/`, `server/static/`)은 PC에서 만들어 올린다.

**최초 1회 (VM에서)**
```bash
curl -fsSL https://raw.githubusercontent.com/lunyang0119/interior-game/main/deploy/setup-vm.sh | bash
nano /opt/interior/server/.env     # SHEET_URL, DUCKDNS_TOKEN 채우기 (IP_SALT는 자동 생성됨)
```
Oracle 콘솔에서 VCN → Security List → Ingress에 TCP 80, 443 추가 (스크립트가 VM 안 iptables는 열어줌).

**배포할 때마다 (PC의 Git Bash에서)**
```bash
./deploy/push.sh ubuntu@<VM_IP>
```
빌드 → git push → gen/media/static 전송 → VM에서 git pull + 서비스 재시작까지 한 번에.

Apps Script 코드는 `tools/appsscript/Code.gs` (GET = 재화 목록, POST = 등록 기록). 코드 바꾸면 반드시 새 버전으로 재배포.

## API 요약

| 메서드 | 경로 | 설명 |
|---|---|---|
| POST | `/api/register` | 닉네임(시트 B열)으로 등록 → 시트 R열에 기록(없으면 새 행) → 토큰 1회 발급 |
| GET | `/api/me` | 내 정보 + 공용 잔액 + 기여 목록 |
| POST | `/api/sync` | 시트 강제 동기화 |
| PUT | `/api/avatar` | 아바타 레이어 인덱스 |
| GET | `/api/catalog` | 아이템/방/캐릭터 메타 |
| GET | `/api/room` | 방 아이템 (ETag 지원) |
| POST | `/api/room/place` · `/api/room/move` · DELETE `/api/room/item/{uid}` | 배치/이동/삭제 (서버가 규칙 검증) |
| POST | `/api/token/rotate` · GET `/api/me/logins` | 토큰 재발급 / 접속 기록 |
| WS | `/ws` | 온라인 아바타 위치, 방 변경 알림 |

복구 링크: `https://도메인/?t=TOKEN` — 열면 토큰이 localStorage로 옮겨지고 URL에서 지워진다.
