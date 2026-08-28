# econtech-cardnews

인스타그램 카드뉴스 자동 생성·게시 파이프라인. GitHub Actions에서 하루 두 번 실행된다.

```
content/news_YYYYMMDD_{am|pm}.json   ← 그날의 콘텐츠 (Claude가 작성)
        ↓  검증 (규칙 위반이면 여기서 중단)
        ↓  카드 8장 렌더링 (1080×1350 PNG)
        ↓  Cloudinary 업로드 (인스타는 공개 URL만 받는다)
        ↓  인스타그램 캐러셀 게시
```

## 왜 GitHub Actions인가

Claude가 실행되는 클라우드 환경과 데스크톱 연동 셸 **둘 다** 네트워크 허용목록에 막혀
`graph.instagram.com`과 `api.cloudinary.com`에 접속할 수 없다. GitHub Actions 러너는
제약이 없어서, 무인 실행이 가능한 유일한 경로다.

---

## 최초 설정 (한 번만)

### 1. 이 파일들을 레포에 올린다

GitHub에서 **private** 레포를 만들고 이 폴더 전체를 업로드한다.
웹 UI로 할 경우: 레포 페이지 → `Add file` → `Upload files` → 폴더째 드래그.

> `.github/workflows/daily.yml` 이 반드시 그 경로 그대로 올라가야 워크플로가 인식된다.

### 2. 시크릿 4개를 등록한다

레포 → **Settings → Secrets and variables → Actions → New repository secret**

| 이름 | 값 | 어디서 얻나 |
|---|---|---|
| `IG_USER_ID` | 인스타 비즈니스 계정 ID | Meta 앱 대시보드 |
| `IG_LONG_LIVED_TOKEN` | 장기 액세스 토큰 (60일) | Meta 앱 대시보드 → Generate Token |
| `CLOUDINARY_CLOUD_NAME` | Cloudinary 클라우드 이름 | Cloudinary 대시보드 |
| `CLOUDINARY_UPLOAD_PRESET` | unsigned 업로드 프리셋 이름 | Cloudinary → Settings → Upload |

**토큰은 반드시 본인이 직접 입력한다.** 채팅이나 코드에 붙여넣지 말 것.
시크릿은 로그에 자동 마스킹되고 레포 코드에는 남지 않는다.

계정 핸들을 바꾸려면 같은 화면의 **Variables** 탭에서 `ACCOUNT_HANDLE` 을 등록한다
(없으면 `itsue_issue` 로 렌더링된다).

### 3. Cloudinary unsigned 프리셋 만들기

Cloudinary → Settings → Upload → Upload presets → **Add upload preset**
→ Signing Mode 를 **Unsigned** 로 설정하고 이름을 복사해 위 시크릿에 넣는다.

### 4. 수동으로 한 번 돌려본다

레포 → **Actions → 카드뉴스 자동 게시 → Run workflow**
→ slot 을 `pm` 으로 두고 실행.

`content/` 에 오늘 날짜 파일이 없으면 `[skip]` 로그만 남기고 정상 종료한다.
지금 들어 있는 `news_20260828_pm.json` 으로 테스트하려면 `news_file` 칸에
`content/news_20260828_pm.json` 을 넣고 실행한다.

---

## 매일 운영

1. Claude 세션에서 그날 뉴스를 리서치하고 콘텐츠 JSON을 만든다
2. 그 파일을 `content/news_YYYYMMDD_am.json` 또는 `_pm.json` 이름으로 레포에 커밋한다
3. 정해진 시각에 워크플로가 자동으로 게시한다

| 슬롯 | cron (UTC) | 실제 시각 (KST) | 내용 |
|---|---|---|---|
| AM | `0 23 * * *` | 08:00 | 미국장 브리핑 (라이트 테마) |
| PM | `0 9 * * *` | 18:00 | 국내 경제 브리핑 (다크 테마) |

> GitHub Actions의 cron은 러너 혼잡도에 따라 **수 분에서 길게는 30분 이상 늦게** 시작될 수 있다.
> 정확한 시각이 중요하면 스케줄을 조금 앞당겨 두는 편이 낫다.

### 콘텐츠 파일 규칙

`pipeline/validate_news.py` 가 게시 전에 검사한다. 하나라도 걸리면 게시되지 않는다.

- 해시태그 5개 이하 (2025.12 인스타 공식 제한)
- 모든 아이템에 `sowhat` (해석 한 줄) — 애그리게이터 정책 방어
- `hook` 존재하고 `headline` 과 달라야 함 — 캐러셀 2번 카드 재노출 메커니즘
- `question` 존재 — 댓글 유도
- "좋아요 눌러주세요" 금지 — 참여율 역효과
- 카드 7~10장, 모든 아이템에 출처

---

## 토큰 관리

인스타 장기 토큰은 **60일**짜리다. 워크플로가 매 실행마다 갱신을 시도하지만,
**갱신된 토큰을 레포 시크릿에 자동 저장하지는 않는다**(시크릿 쓰기 권한이 필요해 의도적으로 뺐다).

→ **50일에 한 번쯤 Meta 대시보드에서 새 토큰을 발급받아 `IG_LONG_LIVED_TOKEN` 을 갱신할 것.**
   만료되면 워크플로가 실패하고 Actions 탭에 빨간 표시가 뜬다.

---

## 로컬에서 테스트

```bash
pip install -r requirements.txt
playwright install chromium

# 카드만 렌더링 (게시 없음)
python pipeline/generate_cards.py content/news_20260828_pm.json

# 규칙 검증만
python pipeline/validate_news.py content/news_20260828_pm.json
```

---

## 아직 자동이 아닌 것

**콘텐츠 작성.** 매일 뉴스를 조사하고 JSON을 만드는 일은 사람(Claude 세션)이 한다.
이걸까지 무인화하려면 러너에서 Anthropic API를 호출해 리서치·작성까지 시키는
스크립트가 필요하고, 별도의 API 키와 비용이 든다. 지금 구조는 거기까지 확장할 수 있게
`ci_publish.py` 가 콘텐츠 파일을 읽는 부분만 바꾸면 되도록 분리해 두었다.

**사진 배경 카드.** 이미지 파일을 사람이 넣어줘야 한다. 텍스트·차트 기반 카드만 무인으로 돈다.
