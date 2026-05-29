# SCM 주간 KPI 자동화 에이전트 아키텍처

**버전**: v1.0  
**작성일**: 2026-05-26  
**작성자**: Claude (SCM 자동화 에이전트)  
**목적**: 외주생산파트 주간 KPI 리포트 전 과정을 자동화하는 에이전트 시스템의 설계를 기술한다.

---

## 1. 시스템 개요

### 1-1. 왜 에이전트 아키텍처인가

외주생산 SCM 업무는 4개 Airtable 베이스에 데이터가 분산되어 있고, 주마다 반복되는 집계·리포팅 작업이 전체 업무 시간의 상당 부분을 차지한다. 기존 방식은 담당자가 수동으로 각 테이블을 열람하고 엑셀로 집계한 뒤 보고서를 작성해야 했다. 에이전트 아키텍처는 이 반복 사이클을 완전 자동화하여 담당자가 "데이터 확인 → 판단 → 조치"에만 집중할 수 있게 한다.

### 1-2. 핵심 설계 원칙

- **SSOT(Single Source of Truth)**: `SCM_SSOT_field_mapping_v1.0.md`에 정의된 필드만 SSOT로 사용
- **필드 ID 기반 API 호출**: 필드명 변경에 영향 받지 않도록 field_id(fld…) 사용
- **ISO Week 기준 집계**: 모든 주별 집계는 ISO 8601 주차(월~일) 기준
- **버전 관리 자동화**: 산출물 파일명에 주차(YYYY-Www) 또는 버전 번호 자동 부여
- **환경변수 기반 인증**: AIRTABLE_PAT는 절대 코드에 하드코딩하지 않음

---

## 2. 시스템 구성요소

```
┌─────────────────────────────────────────────────────────────────┐
│                   SCM KPI 자동화 에이전트 시스템                    │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  [트리거 레이어]                                                    │
│   ├─ ① 스케줄러 (매주 월요일 09:00 자동실행)                          │
│   ├─ ② CLI 수동실행 (python scm_weekly_kpi_agent.py --week YYYY-Www) │
│   └─ ③ Cowork 대시보드 조회 버튼 (실시간 조회)                         │
│                                                                   │
│  [데이터 수집 레이어]                                                │
│   ├─ Airtable REST API (PAT 인증)                                  │
│   ├─ 페이지네이션 처리 (100건/페이지, cursor 기반)                      │
│   └─ 4개 베이스 × 8개 테이블 동시 조회                                │
│                                                                   │
│  [처리 레이어]                                                      │
│   ├─ 필드 파싱 (lookup nested → flat value)                        │
│   ├─ ISO week 필터링                                               │
│   ├─ KPI 계산 (6개 도메인)                                          │
│   └─ 전주 대비(WoW) 계산 (이전 주 CSV 참조)                           │
│                                                                   │
│  [산출물 레이어]                                                     │
│   ├─ scm_raw_YYYY-Www.csv (원본 데이터 아카이브)                      │
│   ├─ scm_kpi_report_YYYY-Www.md (주간 KPI 보고서)                   │
│   └─ Cowork 대시보드 자동 갱신 (live artifact)                        │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘
```

---

## 3. 데이터 소스 매핑

| 소스 베이스 | base_id | 사용 테이블 | KPI 역할 |
|---|---|---|---|
| SERPA_v3.0 | `appkRWtF2j99XgBTq` | task (`tbllJFVBoFjmbQXLN`) | 발주 KPI, 매입·원가 |
| SERPA_v3.0 | `appkRWtF2j99XgBTq` | order (`tblUYmhOvtHGJ9NO3`) | 매출 KPI |
| SERPA_v3.0 | `appkRWtF2j99XgBTq` | movement (`tblsG3x3gCSZGPVB9`) | 이슈·입하 KPI |
| SERPA_v3.0 | `appkRWtF2j99XgBTq` | project (`tblcw5sagkDlgAtJN`) | 체크파이널 KPI |
| MRP (재고) | `applObFUJy5o025oQ` | sync_parts (`tblYGM8wBxlZQOu1l`) | 품절·재고 KPI |
| Sincerely DB | `appAbBz1Y48qhpHwz` | partner (`tbl5BjEkhn3CUMIlI`) | 협력사 마스터 |
| 이슈 등록 DB | `appkbGFSIds8NMDOH` | issue_register (`tblDMc8PuiJJkVe6H`) | 고객인지이슈 KPI |
| 이슈 등록 DB | `appkbGFSIds8NMDOH` | check_standard_answer (`tblwNrIIsD6dDIDDf`) | 제품 Q&A 집계 |

### check_standard_answer 핵심 필드

| 필드명 | field_id | 타입 | 비고 |
|---|---|---|---|
| 문의유형 | `fldoyTSSbG8JpALrL` | singleSelect | 제품문의/제작기간문의/임가공·출고문의 등 |
| 질문내용 | `fldsIVosP043Z3CiZ` | text | 원문 질문 |
| 답변내용 | `fldvTyY5LqECg5WhI` | text | 담당자 답변 |
| 굿즈명(lookup) | `fldl2dz6NO8FummAE` | lookup | linked record → 제품명 문자열 |
| 굿즈명(link) | `fldnh7Onpc6utQVqA` | link | linked record 원본 |
| 등록날짜 | `fldflEhnYx1gOLNUn` | date | 문의 발생일 |
| 담당팀 | `fldA9VYyj7YPqd8rv` | text | MD / POM / FFM |
| 수량 | `fld5lynz7vWSLpG1G` | number | 문의 관련 수량 |
| 납기일 | `fldEiY2Wsu3ZRVah8` | date | |
| 리드타임(일) | `fldSjibAvP5fu3mK6` | number | 확인된 제작기간 |
| 답변완료 | `fld3V3LhvfMcEzMGy` | checkbox | |

---

## 4. 주간 자동화 플로우 (단계별)

### Step 1. 트리거 — 매주 월요일 09:00

```bash
# cron 설정 (서버/Cowork 스케줄러)
# 0 9 * * 1 — 매주 월요일 오전 9시
export AIRTABLE_PAT=<token>
cd /path/to/scm_project
python scm_weekly_kpi_agent.py
```

CLI 옵션:
```bash
python scm_weekly_kpi_agent.py               # 직전 주 자동 집계
python scm_weekly_kpi_agent.py --week 2026-W21  # 특정 주 지정
python scm_weekly_kpi_agent.py --month 2026-05  # 월간 집계
python scm_weekly_kpi_agent.py --dry-run         # API 없이 더미 데이터로 테스트
```

---

### Step 2. 데이터 수집

```
[SERPA task] ──→ 발주 KPI raw (최근 2000건, 과업지시일자 필터)
[SERPA order] ─→ 매출 KPI raw (최근 2000건, Created time 필터)
[SERPA movement] → 이슈 KPI raw (날짜 범위 필터, ⚠️ 대용량 — 반드시 기간 필터 적용)
[MRP sync_parts] → 품절 현황 (전체 스냅샷 ~1000건)
[이슈DB check_standard_answer] → 제품 Q&A (문의날짜 필터)
```

**페이지네이션 처리 원칙:**
- 한 페이지당 최대 100건 (Airtable 기본값)
- `nextCursor` 있을 시 재귀 호출
- movement 테이블은 반드시 날짜 범위 필터 적용 후 조회 (타임아웃 방지)

---

### Step 3. KPI 계산 (6개 도메인)

#### 3-1. 발주 KPI
```python
발주_TASK건수 = task WHERE 과업지시일자 IN [week_start, week_end] COUNT
주간_총지출액 = SUM(task.총지출액_VAT포함)
긴급발주율(%) = 긴급발주건수 / 발주_TASK건수 × 100
미입하율(%) = 미입하발생건수 / 발주_TASK건수 × 100
담당자별_발주건수 = GROUP_BY(task.과업담당자_이름) COUNT
```

#### 3-2. 매출·매입·원가율 KPI
```python
# 굿즈별 집계
굿즈별_주간매출 = SUM(order.매출총액) GROUP BY order.goods(통합) [fldvjDTKEy9q7wPZZ]
굿즈별_주간매입 = SUM(task.공급가액) GROUP BY order.goods(통합)  # task-order JOIN 필요
굿즈별_원가율 = 굿즈별_주간매입 / 굿즈별_주간매출 × 100

# 매입 TOP 랭킹
주간_매입랭킹 = ORDER BY SUM(task.총지출액) DESC LIMIT 10
```

#### 3-3. 이슈 KPI
```python
이슈건수_운영 = movement WHERE 이슈카테고리='운영' COUNT
이슈건수_수량 = movement WHERE 이슈카테고리='수량' COUNT
이슈건수_품질 = movement WHERE 이슈카테고리='품질' COUNT
품질등급_일치율 = (SCM의견 == 최초판정 건수) / 전체검수건수 × 100
```

#### 3-4. 협력사 재고 품절 KPI
```python
품절_파츠수 = sync_parts WHERE 판매상태='품절' COUNT
품절_파츠목록 = [(파츠명, 굿즈명, 협력사, 재입고예정일, 잔여일수)]
잔여일수 = 재입고예정일 - TODAY()
품절위험_파츠수 = sync_parts WHERE 품절위험여부=TRUE COUNT
```

#### 3-5. 체크파이널 KPI
```python
체크파이널_신청건수 = project.체크파이널_신청개수 [주차 필터]
체크파이널_검토시작건수 = project.체크파이널_검토시작_개수
체크파이널_오류유형_분포 = GROUP_BY(project.체크파이널_오류유형)
```

#### 3-6. 제품 Q&A 집계 (check_standard_answer)
```python
# 주차 필터 기준: fldflEhnYx1gOLNUn (등록날짜)
qa_records = check_standard_answer WHERE 등록날짜 IN [week_start, week_end]

문의유형_분포 = GROUP_BY(fldoyTSSbG8JpALrL) COUNT
  # 예: 제품문의 12건, 제작기간문의 5건, 임가공/출고문의 8건

굿즈별_문의건수 = GROUP_BY(fldl2dz6NO8FummAE) COUNT
  # 예: 올 블랙 펜 3건, 디자이너 노트 2건 ...

팀별_문의건수 = GROUP_BY(fldA9VYyj7YPqd8rv) COUNT
  # MD, POM, FFM

상위문의제품_TOP5 = ORDER BY 문의건수 DESC LIMIT 5
```

---

### Step 4. 전주 대비(WoW) 계산

```python
# 이전 주 CSV 로드
prev_week_csv = f"scm_raw_{prev_iso_week}.csv"
if os.path.exists(prev_week_csv):
    df_prev = pd.read_csv(prev_week_csv)
    wow_발주건수 = (this_발주건수 - prev_발주건수) / prev_발주건수 × 100
    wow_지출액 = (this_지출액 - prev_지출액) / prev_지출액 × 100
    # ... 각 KPI별 동일 패턴
else:
    wow_* = None  # 첫 주는 WoW 없음
```

---

### Step 5. 산출물 생성

#### 5-1. Raw CSV 저장
```
파일명: scm_raw_YYYY-Www.csv
경로: SCM SUPER BASE DB/raw_data/
구조: 멀티시트 → CSV는 단일 시트 (task raw + order raw + parts raw 순서대로 행 구분자 포함)
```

#### 5-2. KPI 리포트 MD 생성
```
파일명: scm_kpi_report_YYYY-Www.md
경로: SCM SUPER BASE DB/reports/
구조:
  # SCM 주간 KPI 리포트 — YYYY년 W주차
  ## 요약 대시보드 (텍스트 테이블)
  ## 1. 발주 KPI
  ## 2. 매출·매입·원가율
  ## 3. 이슈 현황
  ## 4. 협력사 재고·품절
  ## 5. 체크파이널
  ## 6. 제품 Q&A 동향
  ## 7. 다음 주 주요 액션 아이템
```

#### 5-3. Cowork 대시보드 갱신
```
대시보드는 독립적으로 Airtable API 직접 호출 (window.cowork.callMcpTool)
→ 별도 Push 불필요. 조회 시점 기준 실시간 데이터 표시
```

---

## 5. 파일 구조 및 버전 관리

```
SCM SUPER BASE DB/
├── scm_weekly_kpi_agent.py          # 메인 자동화 스크립트
├── SCM_SSOT_field_mapping_v1.0.md   # SSOT 필드 설계서 (수정 시 버전 올림)
├── SCM_agent_architecture_v1.0.md   # 본 문서 (수정 시 버전 올림)
│
├── raw_data/                         # 주별 원본 데이터
│   ├── scm_raw_2026-W21.csv
│   ├── scm_raw_2026-W22.csv
│   └── ...
│
├── reports/                          # 주별 KPI 리포트
│   ├── scm_kpi_report_2026-W21.md
│   ├── scm_kpi_report_2026-W22.md
│   └── ...
│
└── monthly/                          # 월간 집계 (주별 CSV 집계)
    ├── scm_monthly_2026-05.md
    └── ...
```

**버전 관리 규칙:**
- 코드 수정 시: 주석에 수정일·수정자·변경 요약 기재
- 설계서 수정 시: 파일명 버전 번호 업데이트 (v1.0 → v1.1 → v2.0)
- KPI 산출물: 파일명에 ISO week 자동 기재, 덮어쓰기 없음

---

## 6. 스케줄링 설정

### Cowork 스케줄러 (권장)
Cowork의 `mcp__scheduled-tasks__create_scheduled_task`로 설정:
```
cronExpression: "0 9 * * 1"    # 매주 월요일 09:00
prompt: "scm_weekly_kpi_agent.py --week 직전주 실행 후 결과 요약 보고"
```

### 수동 실행 시
```bash
# Windows PowerShell
$env:AIRTABLE_PAT="your_token_here"
python "C:\Users\user\Documents\Claude\Projects\SCM SUPER BASE DB\scm_weekly_kpi_agent.py"

# 특정 주 재생성 (과거 주차 소급 집계)
python scm_weekly_kpi_agent.py --week 2026-W20

# 월간 리포트 (5월 전체)
python scm_weekly_kpi_agent.py --month 2026-05
```

---

## 7. 에러 처리 및 알림

| 에러 유형 | 원인 | 대응 |
|---|---|---|
| API 인증 실패 | PAT 만료/미설정 | AIRTABLE_PAT 환경변수 확인 |
| 테이블 타임아웃 | movement 등 대용량 테이블 전체 조회 | 날짜 필터 필수 적용 |
| 필드 ID 오류 | Airtable 필드 삭제/재생성 | SSOT 설계서 필드 ID 재확인 후 코드 업데이트 |
| 중복 필드 ID | 동일 필드를 이름과 ID 혼용 | 항상 field_id(fld…) 형식만 사용 |
| 빈 주차 데이터 | 공휴일·휴가로 발주 없음 | KPI값 0으로 표시, WoW N/A 처리 |
| CSV 없음 (첫 실행) | 이전 주 아카이브 없음 | WoW 항목 '-' 또는 '기준 없음'으로 표시 |

---

## 8. 확장 로드맵

### Phase 1 (현재 구현 완료)
- [x] 6개 KPI 도메인 집계
- [x] 주별 CSV 아카이브
- [x] 주별 MD 리포트 자동 생성
- [x] Cowork 라이브 대시보드 (4탭)
- [x] check_standard_answer 테이블 스키마 파악

### Phase 2 (다음 구현 대상)
- [ ] check_standard_answer → 대시보드 탭 추가 (제품 Q&A 동향)
- [ ] 월간 집계 리포트 자동 생성 (`--month` 옵션 구현 완성)
- [ ] 협력사별 등급 산정 자동화 (ISO 기준 KPI 합산)
- [ ] 이상치 감지: 원가율 급등·품절 장기화 자동 알림

### Phase 3 (장기)
- [ ] Slack 알림 연동 (`mcp__f956fbe9__slack_send_message`)
- [ ] 협력사 평가 리포트 분기별 자동 생성
- [ ] 신규 공급망 발굴 필요성 지표 자동 산출 (편중도·단일 소싱 위험도)
- [ ] Airtable 자동 업데이트 (품질등급 일치율 결과를 partner 테이블에 write-back)

---

## 9. SSOT 설계서와의 관계

본 아키텍처 문서는 `SCM_SSOT_field_mapping_v1.0.md`의 필드 정의를 기반으로 동작한다.

- **필드 추가·변경 시**: SSOT 설계서 먼저 업데이트 → 본 문서 → 코드 순서로 반영
- **KPI 정의 변경 시**: 두 문서 동시 버전 업데이트
- **코드 단독 변경 시**: 코드 주석 업데이트 + 본 문서 버전 마이너 업 (v1.0 → v1.1)

```
SSOT 설계서 (what to collect)
        ↓
에이전트 아키텍처 (how to process)
        ↓
scm_weekly_kpi_agent.py (implementation)
        ↓
대시보드 + 리포트 + CSV (outputs)
```

---

*문서 히스토리*  
| 버전 | 날짜 | 변경 내용 |
|---|---|---|
| v1.0 | 2026-05-26 | 최초 작성 — 6개 KPI 도메인, check_standard_answer 포함 |
