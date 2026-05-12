# print-web

행사장 노트북에 연결된 프린터로, 외부에서 들어온 사진 인쇄 요청을 받아 관리자가 검토 후 인쇄하는 웹 서비스.

사용자는 휴대전화 브라우저에서 이름과 사진 1장을 올리고, 관리자는 같은 노트북의 별도 화면에서 요청을 승인하거나 거절한다. 승인된 작업은 백그라운드 워커가 Windows 프린터로 자동 출력한다. 노트북은 모바일 데이터 + 개인 터널링 서버 뒤에서 단일 포트(`0.0.0.0:8000`)만 노출하면 끝나도록 설계했다.

## 스택

| 영역 | 기술 |
|---|---|
| 백엔드 | Python 3.10+, FastAPI, SQLModel, SQLite, pywin32, Pillow |
| 프론트엔드 | Vite, React, TypeScript, Tailwind CSS v4, TanStack Query, orval |
| 인쇄 | Windows GDI via pywin32 (모든 설치된 Windows 프린터) |
| 통신 | HTTP 폴링 (사용자 2.5s, 관리자 4s) |
| 인증 | bcrypt + itsdangerous 서명 세션 쿠키 (관리자 1인) |

## 구조

```
print-web/
├── backend/
│   ├── app/
│   │   ├── main.py          FastAPI 엔트리 + 라이프스팬
│   │   ├── api/             jobs (공개) · admin (관리자)
│   │   ├── core/            설정 · 보안 · 의존성
│   │   ├── db/              SQLModel models · engine
│   │   ├── printer/         GDI driver · 워커 루프
│   │   ├── services/        image · jobs · retention
│   │   ├── spa.py           정적 SPA 마운트 + catch-all
│   │   └── static/          (배포용) 빌드된 SPA 복사 위치
│   ├── uploads/             업로드 이미지 (gitignore)
│   ├── data.db              SQLite (gitignore)
│   └── pyproject.toml
└── frontend/
    ├── src/
    │   ├── pages/           UserPage · AdminPage
    │   ├── api/
    │   │   ├── client.ts    axios 인스턴스 + orval mutator
    │   │   └── generated/   orval 생성물 (커밋됨)
    │   ├── App.tsx · main.tsx · index.css
    └── orval.config.ts · vite.config.ts
```

## 상태 머신

```
        ┌─ approve ─→ APPROVED ─ worker ─→ PRINTING ─→ DONE
PENDING ┤                                              └─→ FAILED
        └─ reject  ─→ REJECTED
```

- `DONE`, `FAILED`, `REJECTED`가 종료 상태.
- 사용자 뷰에서는 `PENDING / APPROVED` → **대기중**, `PRINTING` → **진행중**, 나머지 → **완료** 로 묶여 보이고, 관리자의 존재나 거절 사실은 노출하지 않는다.
- 보관 청소 백그라운드 태스크가 24시간마다 종료 상태 작업 중 `RETENTION_DAYS`보다 오래된 것들의 이미지 파일을 지운다 (DB 행은 감사용으로 유지).

## 개발 환경 셋업

### 1. 백엔드

```powershell
# 가상환경 + 의존성 (pywin32는 Windows에서만 필요)
python -m venv backend\.venv
backend\.venv\Scripts\python.exe -m pip install --upgrade pip
backend\.venv\Scripts\python.exe -m pip install -e backend

# .env 생성
Copy-Item backend\.env.example backend\.env

# 관리자 비밀번호 해시 (출력값을 .env의 ADMIN_PASSWORD_HASH에 넣는다)
backend\.venv\Scripts\python.exe -c "import bcrypt; print(bcrypt.hashpw(b'본인비밀번호', bcrypt.gensalt()).decode())"

# 세션 서명 키
backend\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(32))"
```

`backend\.env` 편집:

```
PORT=8000
ADMIN_PASSWORD_HASH=<bcrypt 해시>
SECRET_KEY=<위에서 생성한 키>
PRINTER_NAME=Samsung CLX-6240 Series PS
RETENTION_DAYS=7
UPLOAD_MAX_MB=15
SESSION_SECURE=false
```

`PRINTER_NAME`을 비워두면 Windows 기본 프린터를 사용한다.
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

# 운영용 .env 확인 (강한 SECRET_KEY, SESSION_SECURE=true 등)

# 실행
backend\.venv\Scripts\python.exe -m app.main
```

FastAPI가 자동으로 `backend/app/static`을 찾으면 SPA를 함께 서빙한다 (없으면 `frontend/dist`를 폴백으로 시도). 이후 터널링은 `0.0.0.0:8000` 하나만 외부에 노출하면 끝.

### 자동 기동 (선택)

Windows 작업 스케줄러로 부팅 시 트리거하거나 NSSM으로 서비스화하면 노트북이 깨어 있을 때 항상 응답한다.

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
| GET | `/api/admin/jobs/{id}/thumb` | 썸네일 |
| GET | `/api/admin/jobs/{id}/image` | 원본 |

## 설계 메모

- **단일 워커, 직렬 인쇄.** 프린터는 한 번에 한 장씩이 자연스럽고, 동시 인쇄로 얻을 게 없다. `app/printer/worker.py`는 가장 오래된 `APPROVED` 작업을 atomic하게 `PRINTING`으로 마킹하고 GDI 호출을 스레드 풀에 넘긴 뒤 `DONE` 또는 `FAILED`로 정산한다.
- **부팅 복구.** 이전 실행에서 `PRINTING` 상태로 남은 작업은 시작 직후 `FAILED("interrupted")`로 마킹한다. 재시도는 관리자가 다시 새 요청을 받는 방식 (자동 재인쇄 X).
- **멱등성.** 클라이언트가 `idempotency_key`를 매번 새로 만들어 보내면 모바일 데이터 끊김으로 인한 재시도가 같은 작업으로 합쳐진다. 같은 키를 두 번 받으면 첫 번째 결과를 그대로 돌려준다.
- **거절 사유의 비대칭.** 백엔드에서 `PublicJob`은 `reject_reason`을 아예 갖지 않고, `AdminJob`만 갖는다. 클라이언트 카피 역시 사용자 뷰에서는 거절 사실을 "완료"로 표기해 관리자의 존재를 드러내지 않는다.
- **시각 처리.** SQLite는 timezone 정보를 round-trip 시 잃기 때문에 `utcnow()`는 naive UTC를 반환하고 모든 비교를 naive 기준으로 한다.
- **세션 키 부재 시.** `SECRET_KEY`가 비어 있어도 프로세스는 죽지 않고 ephemeral 키로 부팅하지만, 재시작 시 모든 관리자 세션이 무효화된다. 운영용 `.env`에는 반드시 채울 것.

## 트러블슈팅

- **프린트가 큐는 통과하는데 종이가 안 나옴.** 프린터 포트가 `127.x.x.x` 대역이면 RDP/세션 리다이렉트 가능성이 높다. 물리 프린터인지 `Get-CimInstance Win32_Printer | Select Name, PortName`으로 확인.
- **세션 쿠키가 안 붙음.** HTTPS 터널 뒤라면 `.env`에 `SESSION_SECURE=true` 필수. 로컬에서는 `false`.
- **`npm run gen`이 실패.** 백엔드가 먼저 떠 있어야 한다. `http://127.0.0.1:8000/openapi.json`이 응답하는지 확인.
- **이미지가 옆으로 누워서 인쇄됨.** 모바일 사진의 EXIF orientation 영향. 백엔드 `services/image.py`에서 `ImageOps.exif_transpose`로 보정한 뒤 저장하므로, 갱신 후에도 같은 증상이면 원본 EXIF 자체가 빠진 경우. 다시 촬영하거나 갤러리에서 회전 후 업로드.
