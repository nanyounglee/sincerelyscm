# SCM SUPER BASE DB — SSOT 필드 매핑 설계서

**버전**: v1.0  
**작성일**: 2026-05-26  
**작성자**: Claude (SCM 자동화 에이전트)  
**목적**: 에어테이블 4개 베이스에 분산된 데이터 중 신뢰할 단일 소스(SSOT)를 확정하고, 주간 KPI 집계 기준을 표준화한다.

---

## 1. 베이스 & 테이블 구조 전체 지도

| 베이스명 | base_id | 핵심 테이블 | KPI 역할 |
|---|---|---|---|
| SERPA_v3.0 | `appkRWtF2j99XgBTq` | task, order, movement, project | 발주·이슈·체크파이널 |
| Sincerely DB_v1.0 | `appAbBz1Y48qhpHwz` | 2. partner | 협력사 마스터 |
| MRP (재고) | `applObFUJy5o025oQ` | sync_material_purchase, sync_parts | 재고·품절 현황 |
| 이슈 등록 DB | `appkbGFSIds8NMDOH` | 등록 & TBD | 고객인지이슈 |

---

## 2. KPI별 SSOT 필드 매핑

### 2-1. 발주 KPI (소스: SERPA task)

| KPI 항목 | SSOT 테이블 | SSOT 필드명 | field_id | 타입 | 비고 |
|---|---|---|---|---|---|
| 발주 TASK 건수 | task | *(레코드 수)* | — | count | 과업지시일자 기준 주차 필터 |
| 과업지시일자 | task | 과업지시일자 | `fldYEepX9s2G9knvL` | formula | ISO week 필터 기준 |
| 과업담당자 | task | 과업담당자_이름 | `fldplJi175HnuPWGG` | lookup | 담당자별 발주건수 집계용 |
| 발주지시수량 | task | 발주지시수량 | `fldggjY1oIsQlwm01` | number | **SSOT** (order.발주지시수량_최종과 중복 — task 우선) |
| 고객주문수량 | order | 주문수량 | `fldV2yyCiEt1V7FLS` | number | **SSOT** (task.고객주문수량은 rollup 집계값) |
| 총 지출액(VAT포함) | task | 총 지출액 (VAT 포함) | `fldx9wPEcAB3shD9C` | formula | 매입 KPI 핵심 지표 |
| 공급가액(매입원가) | task | 공급가액 | `fldna9s9RVSQOJAz4` | formula | VAT 제외 매입액 |
| 취득원가 | task | 취득원가 | `fldpaJl14LQmHQVXU` | formula | 재고 포함 실원가 |
| 배송비 | task | 배송비 | `fldb7XNy20leNRHs2` | formula | |
| 판매가(최종) | task | R) 판매가(최종) | `fldfjxi8TxujE0sGo` | formula | 매출대비 원가율 계산용 |
| 긴급여부 | task | 긴급여부 | `fldjyyle8y0FesIIK` | lookup | 긴급건수 집계 |
| 미입하 발생이력 | task | 미입하 발생이력_movement | `fldkoYAbm0Ib2Du0O` | lookup | 미입하 TASK 집계 |
| 재제작/추가제작 | task | 재제작/추가제작 | `fldB1jvkxnUyGvkXq` | singleSelect | |
| 비스포크여부 | task | 비스포크여부 | `fldN262rsVhk4DZ0v` | rollup | |
| 수주처(협력사) | task | 수주처 | `fldVhPSugTYwKVNwa` | link | 협력사별 집계용 |
| 결제일 | task | 결제일(from 지출결의) | `fldC6dDTsXG5hlh0k` | lookup | 정산 현황 |
| 굿즈명 | task | goods (from order) | `fldnU6QRLLujfEuL7` | lookup | 제품별 매입 집계용 |
| 산출물 | task | 산출물 | `fldXLxtuoo9Y29kTC` | rollup | |

### 2-2. 매출·매입 KPI (소스: SERPA order)

| KPI 항목 | SSOT 테이블 | SSOT 필드명 | field_id | 타입 | 비고 |
|---|---|---|---|---|---|
| 주문수량(매출) | order | 주문수량 | `fldV2yyCiEt1V7FLS` | number | **SSOT** |
| 매출 총액 | order | 매출 총액 | `fldQ4VmhIF0pNlLJe` | formula | 판매가×주문수량 |
| 매출 원가 | order | 매출 원가 | `fldCxxtQJxczppnns` | currency | |
| 굿즈명(통합) | order | goods (통합) | `fldvjDTKEy9q7wPZZ` | formula | 제품별 집계 key |
| 아이템명(통합) | order | item (통합) | `fldBoP15rTdPuAuJo` | formula | |
| 발주단계 | order | 발주단계 | `fldINOqZMT9nqyJ3a` | singleSelect | |
| 생성일(발주신청일) | order | Created time | `fld3imEMsRuSpO2gX` | createdTime | 주차 필터 기준 |
| 이슈체크 | order | 이슈체크(Order 이슈 관리용) | `fldUclbX7QABdaurx` | checkbox | |

**원가율 계산 공식:**
```
원가율(%) = 취득원가(task) / 매출 총액(order) × 100
```
> ⚠️ 혼재 주의: `order.매출 원가`는 재고 포함/미포함이 혼재될 수 있음. `task.취득원가`를 SSOT로 사용.

### 2-3. 이슈 KPI (소스: SERPA movement + 이슈 등록 DB)

| KPI 항목 | SSOT 테이블 | SSOT 필드명 | 타입 | 비고 |
|---|---|---|---|---|
| 이슈카테고리 | movement | 이슈카테고리 | singleSelect | 운영/수량/품질 구분 |
| 입하예정일 | movement | 입하예정일 | date | 미입하 판단 기준 |
| 실제입하일 | movement | 실제입하일 | date | |
| 입하수량 | movement | 입하수량 | number | |
| 검수수량 | movement | 검수수량 | number | |
| 불량수량(샘플링) | movement | 불량수량_샘플링검수 | number | 품질등급 계산용 |
| 품질등급최초판정 | movement | 품질등급최초판정 | singleSelect | |
| 품질등급의견_SCM | movement | 품질등급의견_SCM | singleSelect | **SSOT** (최초판정과 다를 수 있음) |
| 운영이슈내용 | movement | 운영이슈내용(by물류) | text | |
| 수량이슈내용 | movement | 수량이슈내용 | text | |
| 품질이슈내용 | movement | 품질이슈내용 | text | |
| 고객인지이슈(등록일) | 이슈등록DB | 등록일자 | date | 별도 베이스 |
| 고객인지이슈(비용) | 이슈등록DB | 이슈내용→비용추정 | text | 현재 수동 입력 |

**품질등급 일치율 계산:**
```
일치율(%) = (품질등급의견_SCM == 품질등급최초판정 건수) / 전체 검수건수 × 100
```

### 2-4. 협력사 재고 품절일수 KPI (소스: MRP sync_parts)

| KPI 항목 | SSOT 테이블 | SSOT 필드명 | field_id | 타입 | 비고 |
|---|---|---|---|---|---|
| 판매상태 | sync_parts | 판매상태 | `fld1Os9ECXE1rWaIX` | singleSelect | 품절/정상/단종 등 |
| 파츠품절 Status | sync_parts | 파츠품절 Status | `fldBk282TA7BMV3Ll` | singleSelect | |
| 협력사 재고수량 | sync_parts | 협력사_재고수량 | `fldcdVj2i4tx6UOpE` | number | |
| 협력사 재입고예정일 | sync_parts | 협력사_재입고예정일자 | `fldQXJHMKjY8o9XCZ` | date | |
| 총재고수량 | sync_parts | 총재고수량 | `fldKe4OGhXCYBCWnn` | formula | 신시어리+협력사 |
| 품절위험여부 | sync_parts | 품절위험여부 | `fld6RJTCrVUmmFq7Q` | formula | |
| 굿즈명 | sync_parts | (via sync_goods 링크) | — | link | |

**품절일수 계산:**
```
품절일수 = 판매상태='품절' 상태 지속일 (재입고예정일 - 품절판정일)
```
> ⚠️ 이슈: 판매상태 변경 이력은 `sales_status_history` 테이블에 있음. 품절 시작일은 `sales_status_history.변경일`에서 판매상태='품절'로 변경된 시점을 참조해야 함.

### 2-5. 체크파이널 KPI (소스: SERPA project)

| KPI 항목 | SSOT 필드명 | 타입 | 비고 |
|---|---|---|---|
| 체크파이널 신청건수 | 체크파이널_신청개수 | number | |
| 체크파이널 검토시작건수 | 체크파이널_검토시작_개수 | number | |
| 오류유형 | 체크파이널_오류유형 | multipleSelect | 이슈 분류 |
| 발주신청일시 | 발주 신청 일시 (발주 신청서 제출 기준) _tableau | dateTime | |
| 체크파이널일자 | 체크 파이널 일자_tableau | dateTime | |

### 2-6. 공급망 KPI (소스: Sincerely DB partner)

| KPI 항목 | SSOT 필드명 | field_id | 타입 | 비고 |
|---|---|---|---|---|
| 협력사명 | 협력사 이름 | `fldE6OqdiFuv4Vs6b` | text | |
| 협력사 Status | 협력사 Status | `fld3J2NSVMtt42taA` | singleSelect | 활성/비활성/검토중 |
| 결제조건 | 협력사 결제조건 | `fldPUbYM0dupv4GSO` | singleSelect | |
| 취급품목 | 3. item | `fldMsoZfcMnAUlnsF` | link | |
| 발주담당자 | 발주담당자 | `fldlVRz4oIIGOn0og` | link | |

---

## 3. 데이터 혼재·중복 현황 및 SSOT 결정표

| 중복 필드 | 위치 A | 위치 B | SSOT 결정 | 이유 |
|---|---|---|---|---|
| 고객주문수량 | task.고객주문수량 (rollup) | order.주문수량 (number) | **order** | order가 원본, task는 집계값 |
| 발주지시수량 | task.발주지시수량 (number) | order.발주지시수량_최종 (formula) | **task** | task에서 직접 입력, order는 역참조 |
| 매입수량 | order.매입 수량 | sync_material_purchase.매입 수량 | **task.발주지시수량** | 실제 발주 지시 기준 |
| 판매상태 | MRP.sync_parts | Sincerely DB.sync_parts (별도) | **MRP.sync_parts** | MRP가 실운영 재고 베이스 |
| 굿즈명 | task(from order lookup) | order.goods(통합) | **order.goods(통합)** | 포맷 통일된 formula 필드 |
| 이슈체크 | task.이슈체크(from order) | order.이슈체크 | **order.이슈체크** | checkbox 원본 |
| 협력사정보 | SERPA.sync_partner | Sincerely DB.partner | **Sincerely DB.partner** | 계약·결제정보 마스터 |

---

## 4. 주간 KPI 집계 기준

### 시간 필터 기준
```python
# ISO week 기준 필터
import datetime

def get_iso_week_range(year: int, week: int):
    """ISO week의 월요일~일요일 날짜 반환"""
    jan4 = datetime.date(year, 1, 4)
    week_start = jan4 + datetime.timedelta(weeks=week-1, days=-jan4.weekday())
    week_end = week_start + datetime.timedelta(days=6)
    return week_start, week_end
```

### 집계 기준 필드
| KPI 도메인 | 시간 필터 적용 필드 | 비고 |
|---|---|---|
| 발주 KPI | task.과업지시일자 | ISO week 기준 |
| 매출/매입 KPI | order.Created time (발주신청일) | 또는 task.과업지시일자 |
| 이슈 KPI | movement.입하예정일 or 실제입하일 | 발생 기준 |
| 재고 품절 | sync_parts.판매상태 변경일 | 스냅샷 기준 |
| 고객인지이슈 | 이슈등록DB.등록일자 | |

---

## 5. 신규 추가 KPI 설계

### 5-1. 협력사 재고 품절일수
```
품절중인 파츠 수 = sync_parts WHERE 판매상태='품절' COUNT
품절 파츠 목록 = 파츠명, 굿즈명, 협력사, 품절시작일(추정), 재입고예정일
품절일수(예상) = 재입고예정일 - TODAY()
```

### 5-2. 제품별 주간 매출·매입·원가율
```
[order JOIN task on order_id]
- 굿즈명: order.goods(통합)
- 주간 판매수량: SUM(order.주문수량) GROUP BY 굿즈명
- 주간 매출: SUM(order.매출 총액) GROUP BY 굿즈명
- 주간 매입: SUM(task.공급가액) GROUP BY 굿즈명
- 원가율: 주간매입 / 주간매출 × 100
```

### 5-3. 주별/월별 매입 TOP 제품 랭킹
```
[task + order JOIN]
- 집계: SUM(task.총 지출액) GROUP BY order.goods(통합), ISO_WEEK
- 정렬: DESC
- 출력: 제품명, 주차, 매입금액, 누적매입, 전주대비
```

---

## 5-4. 제품 Q&A KPI (소스: 이슈 등록 DB — check_standard_answer)

테이블: `tblwNrIIsD6dDIDDf` (총 ~2,972건, 2023년~현재)

| KPI 항목 | SSOT 필드명 | field_id | 타입 | 비고 |
|---|---|---|---|---|
| 문의유형 | 문의유형 | `fldoyTSSbG8JpALrL` | singleSelect | 제품문의/제작기간문의/임가공·출고문의 등 |
| 질문내용 | 질문내용 | `fldsIVosP043Z3CiZ` | text | 원문 질문 |
| 답변내용 | 답변내용 | `fldvTyY5LqECg5WhI` | text | 담당자 답변 |
| 굿즈명(lookup) | 굿즈명 | `fldl2dz6NO8FummAE` | lookup | linked record → 제품명 문자열 **SSOT** |
| 굿즈명(link) | 굿즈명 | `fldnh7Onpc6utQVqA` | link | linked record 원본 |
| 등록날짜 | 등록날짜 | `fldflEhnYx1gOLNUn` | date | 주차 필터 기준 |
| 담당팀 | 담당팀 | `fldA9VYyj7YPqd8rv` | text | MD / POM / FFM |
| 수량 | 수량 | `fld5lynz7vWSLpG1G` | number | 문의 관련 수량 |
| 납기일 | 납기일 | `fldEiY2Wsu3ZRVah8` | date | |
| 리드타임(일) | 리드타임 | `fldSjibAvP5fu3mK6` | number | 확인된 제작기간 |
| 답변완료 | 답변완료 | `fld3V3LhvfMcEzMGy` | checkbox | |

**집계 공식:**
```
문의유형별_건수 = GROUP_BY(fldoyTSSbG8JpALrL) WHERE 등록날짜 IN [week_start, week_end]
굿즈별_문의건수 = GROUP_BY(fldl2dz6NO8FummAE) WHERE 등록날짜 IN [week_start, week_end]
문의_다빈도_제품_TOP5 = ORDER BY 굿즈별_문의건수 DESC LIMIT 5
```

---

## 6. 파일 버전 관리 규칙

```
scm_raw_YYYY-Www.csv          # 주별 raw data
scm_kpi_report_YYYY-Www.md    # 주별 KPI 리포트
SCM_SSOT_field_mapping_vX.Y.md # 본 문서 (수정 시 버전 올림)
```
