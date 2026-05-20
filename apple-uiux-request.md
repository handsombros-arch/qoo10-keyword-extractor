# UI/UX 리디자인 요청서 — Apple 디자인 스타일

## 목표

현재 프로젝트의 UI/UX를 Apple의 디자인 철학에 맞게 전면 리디자인한다.
핵심 키워드: **미니멀, 여백, 명료함, 정제된 우아함.**

---

## 1. 디자인 원칙

아래 Apple 디자인 원칙을 모든 컴포넌트에 일관 적용할 것.

| 원칙 | 설명 |
|---|---|
| **Clarity** | 콘텐츠가 곧 UI. 장식 요소는 최소화하고, 텍스트와 아이콘만으로 의미가 전달되어야 함 |
| **Deference** | UI는 콘텐츠를 돋보이게 하는 배경 역할. 과도한 색상·그라데이션·장식 제거 |
| **Depth** | 미묘한 레이어, 그림자, blur 효과로 공간감과 계층 구조를 표현 |

---

## 2. 컬러 시스템

```
/* Light Mode */
--bg-primary: #FFFFFF;
--bg-secondary: #F5F5F7;
--bg-tertiary: #FBFBFD;
--text-primary: #1D1D1F;
--text-secondary: #6E6E73;
--text-tertiary: #86868B;
--accent: #0071E3;
--accent-hover: #0077ED;
--border: rgba(0, 0, 0, 0.08);
--card-bg: rgba(255, 255, 255, 0.72);
--card-shadow: 0 2px 12px rgba(0, 0, 0, 0.08);

/* Dark Mode */
--bg-primary: #000000;
--bg-secondary: #1D1D1F;
--bg-tertiary: #2D2D2F;
--text-primary: #F5F5F7;
--text-secondary: #A1A1A6;
--text-tertiary: #6E6E73;
--accent: #2997FF;
--accent-hover: #0A84FF;
--border: rgba(255, 255, 255, 0.1);
--card-bg: rgba(29, 29, 31, 0.72);
--card-shadow: 0 2px 12px rgba(0, 0, 0, 0.32);
```

- 다크/라이트 모드 모두 지원 (`prefers-color-scheme` 반영)
- 주 배경은 순수 화이트(#FFFFFF) / 순수 블랙(#000000)
- 강조 컬러는 Apple Blue(#0071E3) 하나로 통일
- 불필요한 색상 제거. 상태 표시(성공/경고/에러)만 예외 허용

---

## 3. 타이포그래피

```
/* Font Stack */
font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Display',
             'SF Pro Text', 'Helvetica Neue', sans-serif;

/* Scale */
--text-hero:    48px / 1.08 / -0.003em / 600;  /* 히어로 타이틀 */
--text-title1:  32px / 1.12 / -0.002em / 600;  /* 페이지 타이틀 */
--text-title2:  24px / 1.16 / -0.001em / 600;  /* 섹션 타이틀 */
--text-title3:  20px / 1.20 / 0em / 600;       /* 서브 타이틀 */
--text-body:    17px / 1.47 / -0.022em / 400;   /* 본문 */
--text-callout: 16px / 1.38 / -0.02em / 400;   /* 보조 본문 */
--text-caption: 12px / 1.33 / 0em / 400;       /* 캡션 */
```

- Apple은 **tight letter-spacing**(음수 자간)이 핵심
- 제목은 semibold(600), 본문은 regular(400)
- 한글 폰트 fallback: `'Apple SD Gothic Neo', 'Pretendard', sans-serif`

---

## 4. 레이아웃 & 여백

- 최대 콘텐츠 너비: `980px` (일반), `1200px` (대시보드)
- 섹션 간 간격: `80px ~ 120px`
- 카드/컴포넌트 내부 패딩: `24px ~ 32px`
- 요소 간 기본 간격: `16px`
- 좌우 페이지 마진: `max(24px, 5vw)`
- 빈 공간을 두려워하지 말 것 — **여백이 곧 고급스러움**

---

## 5. 컴포넌트 스타일 가이드

### 버튼
```css
.btn-primary {
  background: var(--accent);
  color: #FFFFFF;
  border: none;
  border-radius: 980px;       /* 완전한 pill shape */
  padding: 12px 24px;
  font-size: 17px;
  font-weight: 400;
  cursor: pointer;
  transition: background 0.2s ease;
}
.btn-primary:hover {
  background: var(--accent-hover);
}
.btn-secondary {
  background: transparent;
  color: var(--accent);
  border: none;
  padding: 12px 24px;
  font-size: 17px;
  font-weight: 400;
  cursor: pointer;
}
```

### 카드
```css
.card {
  background: var(--card-bg);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border: 1px solid var(--border);
  border-radius: 18px;
  padding: 28px;
  box-shadow: var(--card-shadow);
  transition: transform 0.3s ease, box-shadow 0.3s ease;
}
.card:hover {
  transform: translateY(-2px);
  box-shadow: 0 8px 30px rgba(0, 0, 0, 0.12);
}
```

### 인풋
```css
.input {
  width: 100%;
  padding: 14px 16px;
  font-size: 17px;
  border: 1px solid var(--border);
  border-radius: 12px;
  background: var(--bg-secondary);
  color: var(--text-primary);
  outline: none;
  transition: border-color 0.2s ease, box-shadow 0.2s ease;
}
.input:focus {
  border-color: var(--accent);
  box-shadow: 0 0 0 4px rgba(0, 113, 227, 0.15);
}
```

### 네비게이션 바
```css
.navbar {
  position: sticky;
  top: 0;
  z-index: 100;
  background: rgba(255, 255, 255, 0.72);
  backdrop-filter: saturate(180%) blur(20px);
  -webkit-backdrop-filter: saturate(180%) blur(20px);
  border-bottom: 1px solid var(--border);
  height: 48px;
  display: flex;
  align-items: center;
  padding: 0 max(24px, 5vw);
}
```

---

## 6. 모션 & 트랜지션

```css
/* 기본 트랜지션 */
--ease-default: cubic-bezier(0.25, 0.1, 0.25, 1);
--duration-fast: 0.2s;
--duration-normal: 0.3s;
--duration-slow: 0.5s;

/* 페이지/섹션 진입 */
@keyframes fadeInUp {
  from { opacity: 0; transform: translateY(20px); }
  to   { opacity: 1; transform: translateY(0); }
}

/* 적용 규칙 */
/* - 호버: 0.2s ease */
/* - 모달/드로어: 0.3s ease-out */
/* - 페이지 전환: 0.5s ease */
/* - 스크롤 트리거 등장: fadeInUp 0.6s ease */
```

- **절제된 애니메이션**만 사용. 바운스, 과한 스프링 효과 금지
- 의미 있는 곳에만 모션 적용 (등장, 상태 변화, 피드백)
- `prefers-reduced-motion` 미디어 쿼리 반드시 존중

---

## 7. 아이콘 & 이미지

- 아이콘: **SF Symbols 스타일** — 가는 선(1.5px~2px stroke), 둥근 끝, 24x24 기본
- 라이브러리: **Lucide React** (`lucide-react`, 5/3 도입)
- 제품/히어로 이미지: 그림자 없이 깔끔한 컷아웃, 배경과 자연스럽게 블렌딩
- 아이콘 컬러: `var(--text-secondary)` 기본, 활성 시 `var(--accent)`

### ★ 이모지 정책 — **금지** (5/3 추가)
사장님 피드백: "이모지 짜치고 색상 이상함."

- 모든 UI 에서 **이모지 절대 사용 X** (📊 ⭐ 📋 ⛔ 🎯 💹 🎨 ✅ 🔥 ✨ 🔗 등 전부 제거)
- **반드시 Lucide 아이콘 사용** — `lucide-react` 의 monochrome line 아이콘
- 기본 stroke: 1.75px, 활성/강조 시 2px
- 크기: 일반 14-16px, 큰 영역 18-20px
- 색상: 기본 `text-apple-text-3` (gray), 활성 시 `text-apple-accent` (blue)
- **이모지 → Lucide 매핑 예시**:
  - `📊` → `LayoutDashboard`
  - `⭐` → `Sparkles` 또는 `Star`
  - `📋` → `FileSpreadsheet` / `ClipboardList`
  - `⛔` → `Ban` / `ShieldOff`
  - `🎯` → `Target`
  - `💹` → `Calculator` / `TrendingUp`
  - `🎨` → `ImageMinus` / `Brush`
  - `✅` → `CheckCircle` / `ClipboardCheck`
  - `✨` → `Wand2` / `Sparkles`
  - `🔄` → `RefreshCw`
  - `🔥` → `Flame`
  - `🔗` → `Link2`
  - `⛔ 블랙리스트` 같은 텍스트도 이모지 X → 아이콘 + 텍스트
- 메시지 prefix `✓ / ✗ / ⚠ / ⛔` 같은 단순 부호도 가급적 색깔과 아이콘으로 대체:
  - `✓` → emerald `CheckCircle` 또는 status dot
  - `✗` → red `XCircle`
  - `⚠` → amber `AlertTriangle`

---

## 8. 반응형 브레이크포인트

```
Mobile:  < 734px   — 1컬럼, 풀 너비 카드, 터치 최적화(44px 탭 영역)
Tablet:  734~1068px — 2컬럼 그리드, 사이드 패딩 확대
Desktop: > 1068px  — 최대 너비 적용, 3~4컬럼 가능
```

---

## 9. 체크리스트

작업 완료 후 아래 항목을 모두 확인할 것:

- [ ] 다크/라이트 모드 정상 전환
- [ ] 모든 텍스트 Apple 타이포그래피 스케일 적용
- [ ] 불필요한 보더·그라데이션·그림자 제거
- [ ] 모든 인터랙션에 0.2~0.3s 트랜지션 적용
- [ ] 카드/모달에 backdrop-filter blur 적용
- [ ] 버튼은 pill shape (border-radius: 980px)
- [ ] 여백 충분한지 확인 (섹션 간 80px 이상)
- [ ] 734px / 1068px 브레이크포인트 반응형 확인
- [ ] `prefers-reduced-motion` 대응
- [ ] 접근성: 색상 대비 4.5:1 이상, 포커스 링 표시

---

## 10. 참고할 Apple 레퍼런스

- apple.com 메인 페이지 레이아웃
- Apple Music / Apple TV+ 앱 UI
- macOS System Preferences (Ventura 이후)
- Apple Human Interface Guidelines (HIG)

---

> **한 줄 요약**: "넣을까 말까 고민되면 빼라." — Apple 디자인의 본질은 **제거**에 있다.
