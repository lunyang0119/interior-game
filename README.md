# Shared Room Decorator

친구들끼리 하나의 방을 같이 꾸미는 작은 웹 게임. Google Sheet의 개인별 재화를 합친 공용 풀로 가구를 사서 놓고, 온라인인 사람들의 아바타가 방을 돌아다닌다.

- 클라이언트: Phaser 3 + Vite + TypeScript (`client/`)
- 서버: FastAPI + SQLite (`server/`)
- 에셋: LimeZu Modern Interiors → `tools/preprocess/`로 전처리 (원본은 gitignore)

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

**배포할 때마다 (VM에서)**
```bash
sudo systemctl restart interior
```

수정된 파일 전송 후, 재시작.

## API 요약

| 메서드 | 경로 | 설명 |
|---|---|---|
| POST | `/api/register` | 닉네임으로 로그인/등록. DB에 있는 ID면 새 토큰 발급(이전 토큰 무효), 없으면 시트 R열에 기록(없으면 새 행) 후 생성 |
| GET | `/api/me` | 내 정보 + 공용 잔액 + 기여 목록 |
| POST | `/api/sync` | 시트 강제 동기화 |
| PUT | `/api/avatar` | 아바타 레이어 인덱스 |
| GET | `/api/catalog` | 아이템/방/캐릭터 메타 |
| GET | `/api/room` | 방 아이템 (ETag 지원) |
| POST | `/api/room/place` · `/api/room/move` · DELETE `/api/room/item/{uid}` | 배치/이동/삭제 (서버가 규칙 검증) |
| POST | `/api/token/rotate` · GET `/api/me/logins` | 토큰 재발급 / 접속 기록 |
| WS | `/ws` | 온라인 아바타 위치, 방 변경 알림 |

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