# TIGER 미국우주테크 데일리

매일 미국장 마감 후, 구성종목 전일 등락 + 환율로 **오늘자 한국 ETF 예상 변동폭**과
**주가 영향 뉴스(한국어)** 를 만들어, GitHub Pages 웹페이지로 자동 갱신합니다.

> ⚠️ 예상 변동폭은 직전 미국 종가·환율 기반 추정치이며 투자 자문이 아닌 참고용입니다.

## 구조
```
├─ tiger_space_alert.py   # 수집·계산·뉴스번역 핵심 로직
├─ build_web.py           # 모바일 웹뷰(site/index.html) 생성
├─ holdings.json          # 종목 매핑(보통 손댈 필요 없음)
├─ requirements.txt
└─ .github/workflows/
   ├─ pages.yml           # 매 평일 07시(KST) 웹페이지 자동 배포
   └─ daily.yml           # (선택) 이메일 자동 발송
```

## GitHub Pages 설정 (웹뷰)
1. 이 폴더 전체를 GitHub 저장소에 업로드
2. **Settings → Pages → Source** 를 **"GitHub Actions"** 로 선택
3. **Actions** 탭 → `tiger-space-pages` → **Run workflow** 로 첫 배포
4. 생성된 `https://<사용자>.github.io/<저장소>/` 를 폰에서 열고 홈 화면에 추가
5. 이후 매 평일 07:00(KST) 자동 갱신

## (선택) 이메일 발송
`daily.yml` 사용 시 저장소 Secrets 에 `GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD`(앱 비밀번호), 선택 `MAIL_TO` 등록.
원치 않으면 `.github/workflows/daily.yml` 파일은 삭제해도 됩니다.

## 로컬 테스트
```bash
pip install -r requirements.txt
python tiger_space_alert.py --no-send        # 콘솔 리포트
OUT=site/index.html python build_web.py      # 웹뷰 생성 → site/index.html
```
