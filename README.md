# print-web

행사장 노트북에 연결된 프린터로, 외부에서 들어온 사진 인쇄 요청을 받아 관리자가 검토 후 인쇄하는 웹 서비스.

사용자는 휴대전화 브라우저에서 이름과 사진 1장을 올리고, 관리자는 같은 노트북의 별도 화면에서 요청을 승인하거나 거절한다. 승인된 작업은 백그라운드 워커가 Windows 프린터로 자동 출력한다. 노트북은 모바일 데이터 + 개인 터널링 서버 뒤에서 단일 포트(`0.0.0.0:8000`)만 노출하면 끝나도록 설계했다.

## 스택

| 영역 | 기술 |
|---|---|
| 백엔드 | Python 3.10+, FastAPI, SQLModel, SQLite, pywin32 |
| 이미지 | Pillow + pillow-heif (iPhone HEIC 디코드) |
| 프론트엔드 | Vite, React, TypeScript, Tailwind CSS v4, TanStack Query, orval |
| 인쇄 | Windows GDI via pywin32, DEVMODE level-9 per-user 오버라이드 |
| 통신 | HTTP 폴링 (사용자 2.5s, 관리자 4s) |
| 인증 | bcrypt + itsdangerous 서명 세션 쿠키 (관리자 1인) |

## 구조

```
print-web/
├── backend/
│   ├── app/
│   │   ├── main.py              FastAPI 엔트리 + 라이프스팬 + 프린터 캘리브레이션
│   │   ├── api/                 jobs (공개) · admin (관리자)
│   │   ├── core/                설정 · 보안 · 의존성
│   │   ├── db/                  SQLModel models · engine
│   │   ├── printer/
│   │   │   ├── driver.py        GDI 인쇄 + 캐시된 PrintGeometry
│   │   │   ├── calibration.py   오버사이즈 트릭 + DEVMODE 스냅샷
│   │   │   ├── spool.py         EnumJobs로 실제 출력 완료까지 폴링 (60s 타임아웃)
│   │   │   └── worker.py        워커 루프
│   │   ├── services/            image · jobs · retention
│   │   ├── spa.py               정적 SPA 마운트 + catch-all
│   │   └── static/              (배포용) 빌드된 SPA 복사 위치
│   ├── uploads/                 업로드 이미지 (gitignore)
│   ├── data.db                  SQLite (gitignore)
│   └── pyproject.toml
└── frontend/
    ├── src/
    │   ├── pages/
    │   │   ├── UserPage.tsx     업로드 + 폴링 + 저해상도 경고
    │   │   ├── AdminPage.tsx    로그인 게이트
    │   │   └── admin/           Shell · LoginScreen · Dashboard · cards · RejectModal · status
    │   ├── api/
    │   │   ├── client.ts        axios 인스턴스 + orval mutator
    │   │   └── generated/       orval 생성물 (커밋됨)
    │   ├── App.tsx · main.tsx · index.css
    └── orval.config.ts · vite.config.ts
```

## 상태 머신

```
                approve              worker                       ┌─→ DONE
PENDING ─────────────────→ APPROVED ────────→ PRINTING ──────────┤
   │                          ↑                                  └─→ FAILED ─┐
   │     reject               │                                              │
   └────────→ REJECTED        │                                              │
                              │                                              │
                              └──── admin: "다시 인쇄" (retry_count++) ──────┘
```

- `DONE`과 `REJECTED`가 사실상 종료 상태. `FAILED`는 admin이 **"다시 인쇄"** 버튼을 누르면 `APPROVED`로 되돌아가고 `retry_count`가 +1된다 (자동 재시도는 없음 — 종이 낭비/중복 인쇄 방지).
- `PRINTING` 단계는 GDI 렌더링 + **스풀러 잡 추적**까지 포함한다. 60초 안에 `JOB_STATUS_PRINTED`가 안 보이거나 에러 비트가 뜨면 `FAILED`. 자세한 내용은 아래 *설계 메모*의 스풀러 추적 항목.
- 보관 청소 백그라운드 태스크가 24시간마다 종료 상태 작업 중 `RETENTION_DAYS`보다 오래된 것들의 이미지 파일을 지운다 (DB 행은 감사용으로 유지).
- 백엔드는 6단계를 그대로 노출하지만, **공개 응답(`PublicJob`)에서는 `reject_reason`·`status_message`·`retry_count`를 모두 빼고** 클라이언트의 사용자 뷰는 3단계로 축약한다:

| 사용자 뷰 라벨 | 매핑되는 상태 | 폴링 |
|---|---|---|
| 대기중 | PENDING, APPROVED, **FAILED, REJECTED** | 계속 |
| 출력중 | PRINTING | 계속 |
| 출력 완료 | DONE | 중단 (사용자 입장에서 terminal) |

- **DONE만 사용자 입장에서 종료 상태.** `FAILED`는 admin 재시도를 기다리며 사용자 뷰는 계속 `대기중`을 폴링하고, 재시도가 성공하면 `대기중 → 출력중 → 출력 완료`로 자연스럽게 흐른다 — 사용자는 인쇄가 한 번 실패했다는 사실을 모른다.
- `REJECTED`도 같은 이유로 `대기중`으로 노출되며 폴링이 멈추지 않는다. 관리자의 거절을 사용자에게 절대 알리지 않는다는 원칙의 비용으로, 거절된 사용자는 무한 `대기중` 상태가 된다 (실제로는 자리를 떠나거나 직접 물어봄).
- admin 뷰에서는 `retry_count > 0`인 잡에 한해 `재시도 중 (N)` / `재시도 대기 (N)` 라벨이 붙어 첫 시도와 재시도가 구분된다.

관리자의 존재, 승인/거절 사실, 인쇄 실패는 사용자 화면에 절대 드러나지 않는다.

## 이미지 처리 파이프라인

```
[모바일 갤러리] → [프론트: createImageBitmap]
                      ↓ EXIF orientation 픽셀에 굽기
                      ↓ portrait이면 90° CW 회전
                  [프론트: 1500x1000 미만이면 저해상도 경고]
                      ↓ JPEG 0.92로 재인코딩
                  [백엔드: pillow-heif → ImageOps.exif_transpose → RGB]
                      ↓ height > width면 422 거절 (방어 코드)
                  [디스크: uploads/{job_id}.jpg + 썸네일]
                      ↓
                  [워커: GDI draw → 캐시된 PrintGeometry]
```

- **프론트가 정규화** — 모든 업로드를 가로 방향 JPEG로 강제. EXIF가 베이크되어 회전 정보 분실 시에도 문제 없음.
- **백엔드 검증** — 클라이언트를 우회한 portrait 업로드(curl 등)는 422로 거절. 종이 낭비 차단.
- **HEIC** — iPhone 기본 포맷. iOS Safari는 브라우저가 디코드하므로 프론트에서 처리되고, 그 외 브라우저는 원본 그대로 백엔드로 전달되어 `pillow-heif`가 처리.
- **저해상도 경고** — 긴 축이 1500 px 미만(≈ 4×6 인치 출력 시 250 ppi 미만)이면 비차단 경고. 사용자가 무시하고 제출 가능.

## 인쇄 캘리브레이션 (4×6 borderless)

대부분의 잉크젯·레이저 드라이버는 4×6 용지에서 4~6 mm의 unprintable margin을 강제한다 (HP Inkjet 3000: ~5.6 mm). 행사용 사진 인쇄에서는 이게 흰 띠로 보여 거슬리므로, **"오버사이즈 종이 트릭"** 으로 우회한다:

1. 서버 시작 시 [`configure_borderless`](backend/app/printer/calibration.py)가 실제 4×6 (102 × 152 mm)로 DEVMODE를 설정하고 GDI에 마진을 묻는다.
2. 측정된 마진을 더해서 "약간 더 큰 종이" (예: 113 × 164 mm)를 산출하고, 그걸 SetPrinter level 9 (per-user, no admin)로 푸시한다.
3. 그러면 드라이버의 "인쇄 가능 영역"이 **정확히 4×6 mm 영역**으로 잡힌다.
4. 워커는 그 영역을 가득 채워 그리므로, 실제 4×6 용지에는 가장자리까지 잉크가 닿는다.
5. 종료 시 (Ctrl+C로 graceful shutdown) 원본 DEVMODE를 복원한다.

검증된 자동 동작 (모두 SetPrinter level 9 사용, admin 권한 불필요):

| 프린터 | 결과 | 비고 |
|---|---|---|
| Canon SELPHY CP1200 | 트릭 건너뜀 | 이미 borderless (offset 0), base 설정 사용 |
| Samsung CLX-6260 PS | printable = 150.3 × 99.5 mm | 목표 ±1 mm (드라이버 픽셀 반올림) |
| Samsung SF-760 | printable = 152.4 × 101.6 mm | 정확 |
| HP Business Inkjet 3000 PS | printable = 152.4 × 101.6 mm | 정확 |

### 한계 (실제 종이에서)

오버사이즈 PostScript가 실제 4×6 용지에 어떻게 떨어지는지는 firmware 행동에 달려있다:

| 시나리오 | 결과 |
|---|---|
| A. 좌표 그대로 매핑 | 좌상단 5.6 mm 흰 띠 + 우하단 5.6 mm 잘림 |
| B. 작은 종이를 가운데 정렬 | **edge-to-edge** ✓ (대부분의 포토 잉크젯) |
| C. 페이지를 종이에 맞춰 축소 | 모든 게 91.6%로 축소, 마진 5.21 mm로 줄어듦 |

행사 직전 한 장 시험 인쇄로 자기 프린터의 시나리오를 확인하는 게 안전.

### PRINTER_NAME 미설정 시

서버 시작 시 설치된 프린터를 번호 목록으로 띄우고 stdin으로 선택을 받는다:

```
PRINTER_NAME이 설정되지 않았습니다. 사용할 프린터를 선택하세요:
  [1] Samsung SF-760 Series
  [2] HP Business Inkjet 3000 PS
  [3] Canon SELPHY CP1200
선택 번호:
```

TTY가 없으면 (Windows 서비스 모드) Windows 기본 프린터로 폴백.

## 인쇄 품질·용지 종류 설정 (수동)

현재 캘리브레이션 코드는 **paper size, orientation, color** 만 강제하고, **인쇄 품질(`dmPrintQuality`)과 용지 종류(`dmMediaType`)는 드라이버 기본값을 그대로 사용**한다. 사진 화질 최대화를 위해서는 행사 전에 한 번 드라이버 UI에서 설정해두면 캘리브레이션이 그 값을 보존한다:

```powershell
# 인쇄 기본 설정 창 열기
rundll32 printui.dll,PrintUIEntry /e /n "HP Business Inkjet 3000 PS"
```

추천 설정:
- **품질**: "최고 품질" 또는 "사진 / Best Photo"
- **용지 종류**: "광택 인화지" / "HP Premium Plus Photo Paper" 등 (보유 인화지에 맞춰)
- **컬러**: 자동 / 사진 모드

### 강제하고 싶다면 (코드 수정)

`calibration.py`의 `_push_custom_paper`에 다음 필드를 추가하면 된다:

| DEVMODE 필드 | 값 |
|---|---|
| `dmPrintQuality` | `-4` (DMRES_HIGH) — 드라이버의 최고 품질, 이식성 ↑ |
| `dmMediaType` | `3` (DMMEDIA_GLOSSY) 또는 드라이버 고유 코드 (256+) |
| `dmDitherType` | `6` (DMDITHER_GRAYSCALE / photo) |

```python
dm.PrintQuality = -4
dm.MediaType = 3
dm.Fields |= 0x0400 | 0x1000  # DM_PRINTQUALITY | DM_MEDIATYPE
```

드라이버별 고유 미디어 코드를 확인하려면:

```python
import win32print
print(win32print.DeviceCapabilities("HP Business Inkjet 3000 PS", "", 38))
# returns ["Plain Paper", "HP Premium Plus Photo Paper", ...]
# index N → dmMediaType = 256 + N
```

## 개발 환경 셋업

### 1. 백엔드

```powershell
# 가상환경 + 의존성 (pywin32는 Windows에서만 필요)
python -m venv backend\.venv
backend\.venv\Scripts\python.exe -m pip install --upgrade pip
backend\.venv\Scripts\python.exe -m pip install -e backend

# .env 생성
Copy-Item backend\.env.example backend\.env

# 관리자 비밀번호 해시
backend\.venv\Scripts\python.exe -c "import bcrypt; print(bcrypt.hashpw(b'본인비밀번호', bcrypt.gensalt()).decode())"

# 세션 서명 키
backend\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(32))"
```

`backend\.env` 편집:

```env
PORT=8000
ADMIN_PASSWORD_HASH=<bcrypt 해시>
SECRET_KEY=<생성된 키>

# 비우면 시작 시 대화형 선택; TTY 없으면 Windows 기본으로 폴백
PRINTER_NAME=

# 실제 인화지 크기 (mm) — 시작 시 마진 측정해서 오버사이즈 자동 계산
PRINT_PAPER_LONG_MM=152.4
PRINT_PAPER_SHORT_MM=101.6

RETENTION_DAYS=7
UPLOAD_MAX_MB=15
SESSION_SECURE=false
```

설치된 프린터 이름 확인:

```powershell
Get-Printer | Select-Object Name
```

백엔드 실행:

```powershell
backend\.venv\Scripts\python.exe -m app.main
```

기본적으로 `0.0.0.0:8000`에서 뜬다.

### 2. 프론트엔드

```powershell
cd frontend
npm install
npm run dev    # Vite dev 서버 (5173) — /api 요청은 8000으로 프록시
```

브라우저에서 `http://localhost:5173/` (사용자), `http://localhost:5173/admin` (관리자).

### 3. OpenAPI 타입 재생성

백엔드를 띄운 채로:

```powershell
npm --prefix frontend run gen
```

orval이 백엔드의 `/openapi.json`을 읽어 `frontend/src/api/generated/`에 TS 타입과 TanStack Query 훅을 다시 만든다. 백엔드 스키마를 바꿨으면 이 명령을 돌려야 프론트가 컴파일된다.

## 운영 배포 (행사장 노트북)

목표: 한 프로세스, 한 포트.

```powershell
# 프론트 빌드
npm --prefix frontend run build

# 결과를 백엔드의 static 디렉토리로 복사
Remove-Item -Recurse -Force backend\app\static -ErrorAction SilentlyContinue
Copy-Item -Recurse frontend\dist backend\app\static

# 운영용 .env 확인 (강한 SECRET_KEY, SESSION_SECURE=true, PRINTER_NAME 명시 권장)

# 실행
backend\.venv\Scripts\python.exe -m app.main
```

FastAPI가 자동으로 `backend/app/static`을 찾으면 SPA를 함께 서빙한다 (없으면 `frontend/dist`를 폴백으로 시도). 이후 터널링은 `0.0.0.0:8000` 하나만 외부에 노출하면 끝.

### 종료 시 주의

DEVMODE 복원은 lifespan의 `finally`에서 일어나므로 **`Ctrl+C` 같은 정상 종료에서만 실행**된다. `taskkill /F` 같은 강제 종료 시에는 오버사이즈 DEVMODE가 그대로 남는데, 다음 서버 시작 시 캘리브레이션이 다시 동일 값을 푸시하므로 실질적 문제는 없다.

### 자동 기동 (선택)

Windows 작업 스케줄러로 부팅 시 트리거하거나 NSSM으로 서비스화하면 노트북이 깨어 있을 때 항상 응답한다. TTY가 없으므로 `PRINTER_NAME`을 .env에 명시해야 대화형 프롬프트를 건너뛴다.

## API 요약

### 공개

| Method | Path | 설명 |
|---|---|---|
| GET | `/api/health` | 헬스 체크 |
| POST | `/api/jobs` | multipart 업로드 (`requester_name`, `idempotency_key`, `image`) |
| GET | `/api/jobs/{id}` | 사용자용 상태 조회 — `PublicJob` (거절 사유 미포함) |

### 관리자 (세션 쿠키 필요)

| Method | Path | 설명 |
|---|---|---|
| POST | `/api/admin/login` | 비밀번호 → 세션 쿠키 발급 |
| POST | `/api/admin/logout` | 쿠키 무효화 |
| GET | `/api/admin/me` | 로그인 여부 |
| GET | `/api/admin/jobs?since=<iso>` | 작업 목록 (cursor 폴링) |
| POST | `/api/admin/jobs/{id}/approve` | PENDING → APPROVED |
| POST | `/api/admin/jobs/{id}/reject` | PENDING → REJECTED + 사유 |
| POST | `/api/admin/jobs/{id}/retry` | FAILED → APPROVED + `retry_count++` (워커가 다시 픽업) |
| GET | `/api/admin/jobs/{id}/thumb` | 썸네일 |
| GET | `/api/admin/jobs/{id}/image` | 원본 |

> 외부 키오스크용 CORS: `https://phosom-kiosk.pages.dev` 한 오리진에 한해 `allow_credentials=True`로 허용 (admin 세션 쿠키를 cross-origin에서 쓰기 위해 명시 오리진 필수). 추가/변경하려면 `app/main.py`의 `CORSMiddleware` 호출을 편집.

## 설계 메모

- **단일 워커, 직렬 인쇄.** 프린터는 한 번에 한 장씩이 자연스럽고, 동시 인쇄로 얻을 게 없다. `app/printer/worker.py`는 가장 오래된 `APPROVED` 작업을 atomic하게 `PRINTING`으로 마킹하고 GDI 호출을 스레드 풀에 넘긴 뒤 `_mark_done` / `_mark_failed`로 정산한다. 같은 시각에 5건을 승인해도 워커는 1건씩 직렬로 처리한다 — Windows 스풀러 큐에도 우리 잡은 항상 0~1개만 존재.
- **스풀러 잡 추적 = "진짜 인쇄 완료" 보장.** `EndDoc()` 반환은 "잡이 스풀러에 들어갔다"일 뿐이라 종이 잼·오프라인·종이없음을 알 길이 없다. `app/printer/spool.py`가 잡당 고유 `pDocument` 이름(`print-web:{job_id}:{retry_count}`)으로 `EnumJobs`를 1초 간격으로 폴링해서:
  - `JOB_STATUS_PRINTED` 비트 → `DONE`
  - 잡이 큐에서 사라짐 (한 번이라도 본 후) → `DONE` (드라이버가 출력 후 즉시 purge하는 경우)
  - `ERROR` / `DELETED` / `BLOCKED_DEVQ` 비트 → 즉시 `FAILED`
  - `OFFLINE` / `PAPEROUT` / `PAUSED` → 계속 대기하며 마지막 상태 기억
  - 60초 타임아웃 → `FAILED` (마지막 본 상태를 `status_message`에 담음)

  덕분에 `DONE`은 "큐에 들어갔다"가 아니라 "실제로 종이가 나갔다"의 의미가 된다.
- **부팅 복구.** 이전 실행에서 `PRINTING` 상태로 남은 작업은 시작 직후 `FAILED("interrupted")`로 마킹한다. 직렬 처리라 항상 0 또는 1건.
- **재시도는 수동.** `FAILED` 잡은 admin UI의 "다시 인쇄" 버튼(`POST /api/admin/jobs/{id}/retry`)으로만 재처리 — `status=APPROVED`로 되돌리고 `retry_count`를 +1, `status_message`를 클리어한다. 자동 재시도는 종이 낭비·중복 인쇄 방지를 위해 의도적으로 없다. 프린터 문제(잼/종이없음/오프라인)는 사람이 해결한 뒤 누르도록.
- **멱등성.** 클라이언트가 `idempotency_key`를 매번 새로 만들어 보내면 모바일 데이터 끊김으로 인한 재시도가 같은 작업으로 합쳐진다. 같은 키를 두 번 받으면 첫 번째 결과를 그대로 돌려준다.
- **거절 사유의 비대칭.** 백엔드에서 `PublicJob`은 `reject_reason`을 아예 갖지 않고, `AdminJob`만 갖는다. 클라이언트 카피 역시 사용자 뷰에서는 거절 사실을 "완료"로 표기해 관리자의 존재를 드러내지 않는다.
- **클라이언트 정규화 + 서버 검증.** 회전과 EXIF 처리는 모두 클라이언트가 하고, 서버는 결과가 가로(또는 정방형)인지만 확인한다. 휴대전화 발열로 인한 처리 부담은 어차피 한 장이라 미미.
- **이미지는 파일, DB는 메타.** SQLite에 BLOB을 안 쓴다. `image_path`만 TEXT로 저장하고 실제 JPEG는 `uploads/`에 둔다. `FileResponse`로 OS sendfile 활용, 보관 청소는 파일만 지우고 행은 NULL 처리.
- **DEVMODE level 9.** 캘리브레이션은 SetPrinter `PRINTER_INFO_9` (per-user)를 쓴다. admin 권한 불필요. 첫 호출 시 per-user 오버라이드가 없으면 level 2 (글로벌 기본)에서 시드해서 시작한다.
- **시각 처리.** SQLite는 timezone 정보를 round-trip 시 잃기 때문에 `utcnow()`는 naive UTC를 반환하고 모든 비교를 naive 기준으로 한다.
- **세션 키 부재 시.** `SECRET_KEY`가 비어 있어도 프로세스는 죽지 않고 ephemeral 키로 부팅하지만, 재시작 시 모든 관리자 세션이 무효화된다. 운영용 `.env`에는 반드시 채울 것.

## 트러블슈팅

- **인쇄가 60초 만에 FAILED로 떨어짐.** 스풀러는 잡을 받았는데 실제 출력이 60초 안에 안 끝남. `status_message`에 마지막 본 비트가 담겨 있어서 원인을 좁힐 수 있다:
  - `OFFLINE` — 프린터 꺼졌거나 USB/네트워크 단절
  - `PAPEROUT` — 종이 없음
  - `PAUSED` / `USER_INTERVENTION` — 윈도우 큐에서 일시정지 또는 사용자 개입 대기 (예: 잼)
  - `ERROR` — 드라이버/전송 오류
  - 프린터 포트가 `127.x.x.x` 대역이면 RDP/세션 리다이렉트 가능성. 물리 프린터인지 `Get-CimInstance Win32_Printer | Select Name, PortName`으로 확인.
  - 매우 큰 사진 + 느린 USB로 60초가 정말로 부족하면 `print_image()`의 `spool_timeout_seconds` 기본값을 늘려야 한다.

  원인 해결 후 admin UI의 "다시 인쇄" 버튼으로 재시도.
- **오버사이즈 트릭이 좌상단에 흰 띠 + 우하단 잘림.** 프린터 firmware가 위 시나리오 A (좌표 그대로 매핑). 드라이버 속성에서 "용지에 맞게 자동 확대/축소" 같은 옵션이 있으면 켜보고, 없으면 `PRINT_PAPER_LONG_MM`/`PRINT_PAPER_SHORT_MM`을 실측치와 맞춰 마진을 줄이는 게 차선.
- **인쇄가 빛바램·일반 모드로 나옴.** `dmPrintQuality`와 `dmMediaType`을 캘리브레이션 코드가 건드리지 않는다. 드라이버 UI에서 "최고 품질 + 광택 인화지"를 한 번 설정해두면 캘리브레이션이 그 값을 보존한다. 위의 "인쇄 품질·용지 종류 설정" 섹션 참고.
- **HEIC가 Chrome에서 거절됨.** Chrome은 HEIC 디코드 불가, 브라우저 정규화 단계를 건너뛰고 원본 그대로 백엔드로 간다. `pillow-heif`가 설치돼 있어야 백엔드가 받아낼 수 있음. `pip show pillow-heif`로 확인.
- **세션 쿠키가 안 붙음.** HTTPS 터널 뒤라면 `.env`에 `SESSION_SECURE=true` 필수. 로컬에서는 `false`.
- **`npm run gen`이 실패.** 백엔드가 먼저 떠 있어야 한다. `http://127.0.0.1:8000/openapi.json`이 응답하는지 확인.
- **이미지가 옆으로 누워서 인쇄됨.** 모바일 사진의 EXIF orientation 영향. 프론트의 `normalizeForPrint`가 EXIF를 베이크하고 회전까지 처리하지만, 브라우저가 createImageBitmap을 못 하는 케이스(예: 매우 오래된 모바일 브라우저)에서는 백엔드의 `ImageOps.exif_transpose`로 폴백. 그래도 옆으로 나오면 원본 EXIF가 빠진 경우 — 다시 촬영 권장.
- **PRINTER_NAME 비웠는데 프롬프트 안 뜸.** Windows 서비스나 detached 프로세스로 띄운 경우 TTY가 없어 자동 폴백된다. `.env`에 명시하는 게 안전.
- **브라우저가 `Failed to load module script: Expected a JavaScript-or-Wasm module script but the server responded with a MIME type of "text/plain"` 오류.** Windows `mimetypes` 모듈이 레지스트리를 읽는데 다른 앱이 `.js`를 `text/plain`으로 오염시킨 경우. `app/spa.py`가 임포트 시점에 `mimetypes.add_type()`으로 `.js`/`.css`/`.svg`/`.wasm` 등을 강제 매핑해서 자동 해결. 그래도 안 되면 `curl -I http://localhost:PORT/assets/*.js`로 `content-type` 헤더 확인.
