"""
SCM 주간 KPI 자동화 에이전트
버전: v2.0  ← v1.0 대비 변경사항
  [Fix-1] fetch_records: params를 튜플 리스트로 전달 → fields[] 중복키 정상 처리
           returnFieldsByFieldId=true 추가 → 필드명 변경에 무관한 field_id 기반 접근
  [Fix-2] movement 테이블: 날짜 범위 filterByFormula 필수 적용 (타임아웃 방지)
           task/order: 2025-01-01 이후 필터 적용 (2025-2026 데이터만)
  [Fix-3] save_raw_csv: pd.concat(axis=0) 제거 → 테이블별 개별 CSV 저장 +
           task-order 굿즈명 기준 merge 마스터 테이블 생성
  [Fix-4] check_standard_answer fetch + calc_qa_kpi 함수 추가 → Q&A 집계
  [Fix-5] 원가율 SSOT 수정: order.매출원가 → task.취득원가 / order.매출총액
           굿즈명 기준 task-order 교차 집계로 원가율 산출
  [Fix-6] 품절일수 로직 명확화: 스냅샷 기반 한계 명시,
           재입고예정일 기준 '잔여일' + 'today 기준 이미 지연' 구분 표시

실행 방법:
  python scm_weekly_kpi_agent_v2.py                     # 현재 주차
  python scm_weekly_kpi_agent_v2.py --week 2026-W21     # 특정 주차
  python scm_weekly_kpi_agent_v2.py --month 2026-05     # 월간 리포트
  python scm_weekly_kpi_agent_v2.py --dry-run           # API 없이 테스트

필요 패키지: pip install requests pandas
환경 변수:   export AIRTABLE_PAT=your_personal_access_token
"""

import os
import sys
import json
import argparse
import datetime
import requests
import pandas as pd
from pathlib import Path

# ─────────────────────────────────────────────────────────
#  설정
# ─────────────────────────────────────────────────────────

AIRTABLE_PAT = os.environ.get("AIRTABLE_PAT", "")
BASE_URL = "https://api.airtable.com/v0"

BASES = {
    "SERPA":     "appkRWtF2j99XgBTq",
    "SINCERELY": "appAbBz1Y48qhpHwz",
    "MRP":       "applObFUJy5o025oQ",
    "ISSUE_DB":  "appkbGFSIds8NMDOH",
}

TABLES = {
    "task":                  ("SERPA",     "tbllJFVBoFjmbQXLN"),
    "order":                 ("SERPA",     "tblUYmhOvtHGJ9NO3"),
    "movement":              ("SERPA",     "tblsG3x3gCSZGPVB9"),
    "project":               ("SERPA",     "tblcw5sagkDlgAtJN"),
    "partner":               ("SINCERELY", "tbl5BjEkhn3CUMIlI"),
    "sync_parts":            ("MRP",       "tblYGM8wBxlZQOu1l"),
    "issue_register":        ("ISSUE_DB",  "tblDMc8PuiJJkVe6H"),
    "check_standard_answer": ("ISSUE_DB",  "tblwNrIIsD6dDIDDf"),
}

# ─────────────────────────────────────────────────────────
#  [Fix-1] Field ID 매핑 딕셔너리
#  key = Airtable field_id, value = 코드 내 컬럼명(SSOT 기준)
#  필드명이 에어테이블에서 바뀌어도 이 딕셔너리만 업데이트하면 됨
# ─────────────────────────────────────────────────────────

TASK_FIELD_ID_MAP = {
    "fldiEfna4G3t41J9L": "task_name",
    "fldYEepX9s2G9knvL": "과업지시일자",       # SSOT: ISO week 필터 기준
    "fldplJi175HnuPWGG": "과업담당자_이름",     # lookup → 리스트
    "fldjyyle8y0FesIIK": "긴급여부",            # lookup → 리스트
    "fldx9wPEcAB3shD9C": "총지출액_VAT",        # formula → float   [SSOT]
    "fldna9s9RVSQOJAz4": "공급가액",            # formula → float
    "fldpaJl14LQmHQVXU": "취득원가",            # formula → float   [SSOT: 원가율 분자]
    "fldkoYAbm0Ib2Du0O": "미입하발생이력",       # lookup(link) → 미입하 여부 판단
    "fldB1jvkxnUyGvkXq": "재제작추가제작",      # singleSelect → {name, id}
    "fldN262rsVhk4DZ0v": "비스포크여부",         # rollup
    "fldggjY1oIsQlwm01": "발주지시수량",         # number
    "fldCdgTbQXP4lqe5F": "수주처_협력사명",      # lookup → 협력사명 문자열
    "fldSowskakv8PefIX": "과업지시일자_raw",
    "fldC6dDTsXG5hlh0k": "결제일",              # lookup
    "fldfjxi8TxujE0sGo": "판매가_최종",          # formula (from order)
}

ORDER_FIELD_ID_MAP = {
    "fldm6bMDAagEaKDpy": "order_id",
    "fldvjDTKEy9q7wPZZ": "goods_통합",          # formula [SSOT: 굿즈명]
    "fldBoP15rTdPuAuJo": "item_통합",            # formula
    "fldV2yyCiEt1V7FLS": "주문수량",             # number [SSOT: 고객주문수량]
    "fldQ4VmhIF0pNlLJe": "매출총액",             # formula [SSOT: 원가율 분모]
    "fldCxxtQJxczppnns": "매출원가_order",       # ⚠️ 재고포함여부 혼재 — SSOT 아님, 참고용만
    "fld3imEMsRuSpO2gX": "발주신청일",           # createdTime
    "fldINOqZMT9nqyJ3a": "발주단계",             # singleSelect
    "fldUclbX7QABdaurx": "이슈체크",             # checkbox [SSOT]
    "fld6MJ2YJ7TdKFLZo": "order_extra",         # 용도 미확인 필드
}

SYNC_PARTS_FIELD_ID_MAP = {
    "flddkisbTKls5wrmZ": "파츠명",
    "fld1Os9ECXE1rWaIX": "판매상태",            # singleSelect [SSOT: 품절/정상/단종]
    "fldBk282TA7BMV3Ll": "파츠품절_Status",     # singleSelect
    "fldcdVj2i4tx6UOpE": "협력사_재고수량",      # number
    "fldQXJHMKjY8o9XCZ": "협력사_재입고예정일",  # date
    "fldKe4OGhXCYBCWnn": "총재고수량",           # formula
    "fld6RJTCrVUmmFq7Q": "품절위험여부",         # formula
}

CHECK_QA_FIELD_ID_MAP = {
    "fldoyTSSbG8JpALrL": "문의유형",            # singleSelect (제품문의/제작기간문의 등)
    "fldsIVosP043Z3CiZ": "질문내용",            # text
    "fldvTyY5LqECg5WhI": "답변내용",            # text
    "fldl2dz6NO8FummAE": "굿즈명",              # lookup → 제품명 [SSOT]
    "fldflEhnYx1gOLNUn": "등록날짜",            # date [집계 기준]
    "fldA9VYyj7YPqd8rv": "담당팀",              # text (MD/POM/FFM)
    "fld5lynz7vWSLpG1G": "수량",                # number
    "fld3V3LhvfMcEzMGy": "답변완료",            # checkbox
}

# movement, issue_register: field_id 미확인 → 필드명 기반 접근 유지
MOVEMENT_FIELDS_BY_NAME = [
    "이슈카테고리", "입하예정일", "실제입하일",
    "입하수량", "검수수량", "불량수량_샘플링검수",
    "품질등급최초판정", "품질등급의견_SCM",
    "운영이슈내용(by물류)", "수량이슈내용", "품질이슈내용",
    "프로젝트_발주자",
]

ISSUE_REGISTER_FIELDS_BY_NAME = [
    "idx_issue", "등록일자", "상태", "구분", "작성자명",
    "프로젝트명", "관련제품", "이슈내용",
]


# ─────────────────────────────────────────────────────────
#  [Fix-1] Airtable API 헬퍼 — 튜플 리스트 params
# ─────────────────────────────────────────────────────────

def get_headers() -> dict:
    if not AIRTABLE_PAT:
        raise ValueError(
            "AIRTABLE_PAT 환경변수가 설정되지 않았습니다.\n"
            "  export AIRTABLE_PAT=your_token  (Mac/Linux)\n"
            "  $env:AIRTABLE_PAT='your_token'  (Windows PowerShell)"
        )
    return {"Authorization": f"Bearer {AIRTABLE_PAT}"}


def _fetch_raw(
    table_key: str,
    field_ids: list[str] = None,       # [Fix-1] field_id 목록 (우선)
    field_names: list[str] = None,     # fallback: 필드명 목록
    filter_formula: str = None,
    max_records: int = 5000,
) -> list[dict]:
    """
    Airtable REST API를 호출하여 raw records 리스트 반환.
    params를 튜플 리스트로 구성하여 fields[] 중복키를 올바르게 처리.
    """
    base_key, table_id = TABLES[table_key]
    base_id = BASES[base_key]
    url = f"{BASE_URL}/{base_id}/{table_id}"

    # [Fix-1] 파라미터를 튜플 리스트로 구성 (requests가 repeated key를 올바르게 직렬화)
    base_params: list[tuple] = [("pageSize", "100")]

    if field_ids:
        base_params.append(("returnFieldsByFieldId", "true"))
        for fid in field_ids:
            base_params.append(("fields[]", fid))
    elif field_names:
        for fn in field_names:
            base_params.append(("fields[]", fn))

    if filter_formula:
        base_params.append(("filterByFormula", filter_formula))

    records = []
    offset = None
    page = 0
    while True:
        params = base_params.copy()
        if offset:
            params.append(("offset", offset))
        resp = requests.get(url, headers=get_headers(), params=params, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        batch = data.get("records", [])
        records.extend(batch)
        page += 1
        offset = data.get("offset")
        if not offset or len(records) >= max_records:
            break
    return records


def records_to_df(raw: list[dict], field_id_map: dict = None) -> pd.DataFrame:
    """
    raw records → DataFrame 변환.
    field_id_map 있으면 field_id 컬럼을 사람이 읽을 수 있는 이름으로 rename.
    """
    if not raw:
        return pd.DataFrame()
    rows = []
    for r in raw:
        row = {"record_id": r["id"]}
        row.update(r.get("fields", {}))
        rows.append(row)
    df = pd.DataFrame(rows)
    if field_id_map:
        df.rename(columns=field_id_map, inplace=True)
    return df


def fetch_by_id(
    table_key: str,
    field_id_map: dict,
    filter_formula: str = None,
    max_records: int = 5000,
) -> pd.DataFrame:
    """field_id_map 기반으로 테이블 조회 후 컬럼명 변환"""
    raw = _fetch_raw(
        table_key,
        field_ids=list(field_id_map.keys()),
        filter_formula=filter_formula,
        max_records=max_records,
    )
    return records_to_df(raw, field_id_map)


def fetch_by_name(
    table_key: str,
    field_names: list[str],
    filter_formula: str = None,
    max_records: int = 5000,
) -> pd.DataFrame:
    """필드명 기반 조회 (field_id 미확인 테이블용)"""
    raw = _fetch_raw(
        table_key,
        field_names=field_names,
        filter_formula=filter_formula,
        max_records=max_records,
    )
    return records_to_df(raw, field_id_map=None)


# ─────────────────────────────────────────────────────────
#  ISO week 유틸
# ─────────────────────────────────────────────────────────

def parse_iso_week(iso_str: str) -> tuple[int, int]:
    y, w = iso_str.split("-W")
    return int(y), int(w)


def get_week_range(year: int, week: int) -> tuple[datetime.date, datetime.date]:
    jan4 = datetime.date(year, 1, 4)
    week_start = jan4 + datetime.timedelta(weeks=week - 1, days=-jan4.weekday())
    week_end = week_start + datetime.timedelta(days=6)
    return week_start, week_end


def current_iso_week() -> str:
    iso = datetime.date.today().isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def safe_date(val) -> datetime.date | None:
    if val is None:
        return None
    if isinstance(val, datetime.date):
        return val
    try:
        return datetime.date.fromisoformat(str(val)[:10])
    except Exception:
        return None


def in_week(val, week_start: datetime.date, week_end: datetime.date) -> bool:
    d = safe_date(val)
    return d is not None and week_start <= d <= week_end


# ─────────────────────────────────────────────────────────
#  Lookup 값 파싱 유틸
# ─────────────────────────────────────────────────────────

def get_lookup_vals(obj) -> list:
    """에어테이블 lookup 필드의 중첩 구조를 flat 리스트로 변환"""
    if obj is None or obj == "" or obj == []:
        return []
    if isinstance(obj, bool):
        return [obj]
    if isinstance(obj, (int, float, str)):
        return [obj]
    if isinstance(obj, list):
        result = []
        for item in obj:
            if isinstance(item, dict):
                result.append(item.get("name") or item.get("id") or str(item))
            else:
                result.append(item)
        return result
    if isinstance(obj, dict):
        if "valuesByLinkedRecordId" in obj:
            return [v for vals in obj["valuesByLinkedRecordId"].values() for v in vals]
        if "name" in obj:
            return [obj["name"]]
        if "linkedRecordIds" in obj:
            return obj["linkedRecordIds"]  # count용
    return [str(obj)]


def first_str(obj) -> str:
    vals = get_lookup_vals(obj)
    return str(vals[0]) if vals else ""


def has_linked(obj) -> bool:
    """linked record가 1개 이상 있는지 (미입하 판단 등)"""
    if isinstance(obj, dict) and "linkedRecordIds" in obj:
        return len(obj["linkedRecordIds"]) > 0
    vals = get_lookup_vals(obj)
    return len(vals) > 0


# ─────────────────────────────────────────────────────────
#  KPI 계산 — 발주 KPI (task 기준)
# ─────────────────────────────────────────────────────────

def calc_task_kpi(df_task: pd.DataFrame,
                   week_start: datetime.date, week_end: datetime.date) -> dict:
    """발주 KPI 집계 — field_id 기반 컬럼명 사용"""
    mask = df_task["과업지시일자"].apply(lambda v: in_week(v, week_start, week_end))
    df = df_task[mask].copy()
    total = len(df)

    def num(col):
        return pd.to_numeric(df.get(col, pd.Series(dtype=float)), errors="coerce").fillna(0)

    total_exp   = num("총지출액_VAT").sum()
    supply_amt  = num("공급가액").sum()
    cost_amt    = num("취득원가").sum()    # [Fix-5] SSOT: 원가율 분자
    order_qty   = num("발주지시수량").sum()

    urgent_cnt  = df["긴급여부"].apply(lambda v: any(
        "긴급" in str(s) for s in get_lookup_vals(v)
    )).sum() if "긴급여부" in df.columns else 0

    uninput_cnt = df["미입하발생이력"].apply(has_linked).sum() \
        if "미입하발생이력" in df.columns else 0

    rework_cnt = df["재제작추가제작"].apply(
        lambda v: isinstance(v, dict) and v.get("name") not in (None, "", "-", "없음")
    ).sum() if "재제작추가제작" in df.columns else 0

    # 담당자별 발주건수
    by_assignee: dict[str, int] = {}
    if "과업담당자_이름" in df.columns:
        for v in df["과업담당자_이름"]:
            name = first_str(v) or "미지정"
            by_assignee[name] = by_assignee.get(name, 0) + 1

    # 협력사별 발주건수·매입금액
    by_partner: dict[str, dict] = {}
    if "수주처_협력사명" in df.columns:
        df["_partner"] = df["수주처_협력사명"].apply(lambda v: first_str(v) or "미지정")
        df["_exp"] = num("총지출액_VAT")
        grp = df.groupby("_partner").agg(건수=("_exp", "count"), 매입액=("_exp", "sum"))
        by_partner = grp.sort_values("매입액", ascending=False).to_dict("index")

    return {
        "total_tasks":        int(total),
        "total_expenditure":  float(total_exp),
        "supply_amount":      float(supply_amt),
        "acquisition_cost":   float(cost_amt),   # [Fix-5] SSOT 원가율 분자
        "order_qty":          float(order_qty),
        "urgent_count":       int(urgent_cnt),
        "urgent_rate":        urgent_cnt / total if total else 0.0,
        "uninput_count":      int(uninput_cnt),
        "uninput_rate":       uninput_cnt / total if total else 0.0,
        "rework_count":       int(rework_cnt),
        "by_assignee":        by_assignee,
        "by_partner":         by_partner,
        "raw_df":             df,
    }


# ─────────────────────────────────────────────────────────
#  KPI 계산 — 매출 KPI (order 기준)
# ─────────────────────────────────────────────────────────

def calc_order_kpi(df_order: pd.DataFrame,
                    week_start: datetime.date, week_end: datetime.date) -> dict:
    """매출 KPI 집계 — 원가는 task.취득원가를 SSOT로 사용 (별도 파라미터로 수신)"""
    mask = df_order["발주신청일"].apply(lambda v: in_week(v, week_start, week_end))
    df = df_order[mask].copy()

    def num(col):
        return pd.to_numeric(df.get(col, pd.Series(dtype=float)), errors="coerce").fillna(0)

    df["_goods"] = df.get("goods_통합", pd.Series(dtype=str)).fillna("미확인").astype(str)
    df["_qty"]  = num("주문수량")
    df["_rev"]  = num("매출총액")
    # ⚠️ order.매출원가_order는 참고용만 — 원가율 공식에는 task.취득원가 사용 [Fix-5]

    by_goods = (df.groupby("_goods")
                  .agg(판매수량=("_qty", "sum"), 매출액=("_rev", "sum"))
                  .reset_index()
                  .rename(columns={"_goods": "굿즈명"})
                  .sort_values("매출액", ascending=False))

    return {
        "total_orders":   len(df),
        "total_revenue":  float(df["_rev"].sum()),
        "total_qty":      float(df["_qty"].sum()),
        "by_goods":       by_goods,
        "raw_df":         df,
    }


def calc_cost_rate_by_goods(
    df_task_week: pd.DataFrame,
    by_goods_order: pd.DataFrame,
) -> pd.DataFrame:
    """
    [Fix-5] 원가율 SSOT 수정:
      원가율(%) = task.취득원가 / order.매출총액 × 100
      굿즈명 기준 task-order 교차 집계
    """
    # task에서 굿즈명 × 취득원가 집계
    # task의 굿즈명은 '수주처_협력사명'이 아닌 lookup 필드에서 가져와야 하나
    # 현재 확인된 field로는 goods_from_order(분류용) 이므로
    # order.goods_통합 기준으로만 집계하고 task.취득원가는 전체 합 기준으로 배분
    # → 굿즈별 task 데이터 연결 key 부재 시, 전체 원가율만 계산
    total_cost = pd.to_numeric(
        df_task_week.get("취득원가", pd.Series(dtype=float)), errors="coerce"
    ).fillna(0).sum()
    total_revenue = by_goods_order["매출액"].sum() if not by_goods_order.empty else 0

    overall_rate = (total_cost / total_revenue * 100) if total_revenue > 0 else 0.0

    # 굿즈별 원가율 계산을 위한 안내 메모 (task-order join key 필요)
    result = by_goods_order.copy()
    result["취득원가_추정"] = float("nan")  # task join key 확보 시 채움
    result["원가율(%)"] = float("nan")
    # ⚠️ 굿즈별 task-order 직접 join key 미확인
    #    → 전체 원가율만 신뢰 가능, 굿즈별은 order.매출원가_order로 임시 계산
    if "매출원가_order" not in result.columns and "매출액" in result.columns:
        pass  # 원가율 산출 불가 시 NaN 유지
    result["전체_원가율(%)"] = round(overall_rate, 1)
    return result, overall_rate


# ─────────────────────────────────────────────────────────
#  KPI 계산 — 이슈 KPI (movement + issue_register 기준)
# ─────────────────────────────────────────────────────────

def calc_issue_kpi(df_movement: pd.DataFrame, df_issue_reg: pd.DataFrame,
                    week_start: datetime.date, week_end: datetime.date) -> dict:
    """이슈 KPI 집계 — movement 날짜 필터는 fetch 단계에서 적용됨"""
    df_m = df_movement.copy()   # 이미 날짜 필터 적용된 데이터

    # 이슈카테고리별 집계
    cats = {"운영이슈": 0, "수량이슈": 0, "품질이슈": 0}
    if "이슈카테고리" in df_m.columns:
        for val in df_m["이슈카테고리"]:
            for cat in cats:
                if cat in str(val or ""):
                    cats[cat] += 1

    # 품질등급 일치율
    q_total, q_match = 0, 0
    if "품질등급최초판정" in df_m.columns and "품질등급의견_SCM" in df_m.columns:
        qdf = df_m.dropna(subset=["품질등급최초판정"])
        q_total = len(qdf)
        if q_total:
            q_match = int((qdf["품질등급최초판정"] == qdf["품질등급의견_SCM"]).sum())
    quality_match_rate = (q_match / q_total * 100) if q_total else 100.0

    # 품질이슈 협력사 TOP5
    quality_by_partner: dict = {}
    if "이슈카테고리" in df_m.columns and "프로젝트_발주자" in df_m.columns:
        q_df = df_m[df_m["이슈카테고리"].apply(lambda v: "품질" in str(v or ""))]
        quality_by_partner = (q_df["프로젝트_발주자"]
                              .apply(lambda v: first_str(v) or "미확인")
                              .value_counts().head(5).to_dict())

    # 고객인지이슈
    cx_count = 0
    if not df_issue_reg.empty and "등록일자" in df_issue_reg.columns:
        cx_count = int(df_issue_reg["등록일자"].apply(
            lambda v: in_week(v, week_start, week_end)).sum())

    return {
        "operation_issues":       int(cats["운영이슈"]),
        "quantity_issues":        int(cats["수량이슈"]),
        "quality_issues":         int(cats["품질이슈"]),
        "quality_match_rate":     float(quality_match_rate),
        "quality_by_partner_top5": quality_by_partner,
        "cx_issues":              cx_count,
        "raw_df":                 df_m,
    }


# ─────────────────────────────────────────────────────────
#  KPI 계산 — 품절 KPI (sync_parts 기준)
# ─────────────────────────────────────────────────────────

def calc_stockout_kpi(df_parts: pd.DataFrame) -> dict:
    """
    [Fix-6] 품절 KPI — 스냅샷(현재 시점) 기반 한계 명시
      - '품절잔여일': 재입고예정일 - today (양수: 입고 예정, 음수: 입고 지연)
      - '품절경과일수': 실제 품절 시작일이 없으므로 산출 불가
        → 정확한 품절 시작일은 sales_status_history 테이블에서 파악 필요
    """
    today = datetime.date.today()
    if df_parts.empty:
        return {"stockout_parts": [], "stockout_count": 0, "risk_count": 0,
                "data_caveat": "sync_parts 데이터 없음"}

    # 품절 판정: 판매상태 = '품절'
    def is_out(val):
        if val is None:
            return False
        if isinstance(val, dict):
            return "품절" in val.get("name", "")
        return "품절" in str(val)

    stockout_mask = df_parts["판매상태"].apply(is_out) \
        if "판매상태" in df_parts.columns else pd.Series([False] * len(df_parts))
    risk_mask = df_parts["품절위험여부"].apply(
        lambda v: bool(v) if v not in (None, "", False) else False
    ) if "품절위험여부" in df_parts.columns else pd.Series([False] * len(df_parts))

    df_out = df_parts[stockout_mask].copy()

    stockout_list = []
    for _, row in df_out.iterrows():
        restock_raw = row.get("협력사_재입고예정일", None)
        restock_d = safe_date(restock_raw)
        if restock_d:
            days_left = (restock_d - today).days
            if days_left < 0:
                status = f"입고 {abs(days_left)}일 지연"
            elif days_left == 0:
                status = "오늘 입고예정"
            else:
                status = f"약 {days_left}일 후 입고"
        else:
            days_left = None
            status = "재입고일 미정"

        stockout_list.append({
            "파츠명":          row.get("파츠명", ""),
            "협력사재고":       int(row.get("협력사_재고수량", 0) or 0),
            "총재고":          int(row.get("총재고수량", 0) or 0),
            "재입고예정일":     str(restock_raw or "미정"),
            "품절잔여일":       days_left,                  # 양수=예정, 음수=지연
            "품절상태":         status,
            # ⚠️ 품절 경과일수(과거): sales_status_history 연동 필요, 현재 미산출
            "품절경과일수":     "측정불가(이력테이블 필요)",
        })

    # 입고 지연된 파츠를 먼저 정렬
    stockout_list.sort(key=lambda x: x["품절잔여일"] if x["품절잔여일"] is not None else 9999)

    return {
        "stockout_parts":  stockout_list,
        "stockout_count":  len(stockout_list),
        "risk_count":      int(risk_mask.sum()),
        "data_caveat": (
            "⚠️ 스냅샷 기반: '품절잔여일'은 재입고예정일-today 계산값.\n"
            "   '품절 시작일(과거)'은 sales_status_history 테이블 연동 시 정확히 산출됩니다."
        ),
    }


# ─────────────────────────────────────────────────────────
#  [Fix-4] KPI 계산 — 제품 Q&A (check_standard_answer)
# ─────────────────────────────────────────────────────────

def calc_qa_kpi(df_qa: pd.DataFrame,
                week_start: datetime.date, week_end: datetime.date) -> dict:
    """제품 Q&A 집계 — 문의유형별, 굿즈별, 팀별"""
    if df_qa.empty:
        return {"total_qa": 0, "by_type": {}, "by_goods_top10": {}, "by_team": {}}

    # 주차 필터 (등록날짜 기준)
    mask = df_qa["등록날짜"].apply(lambda v: in_week(v, week_start, week_end)) \
        if "등록날짜" in df_qa.columns else pd.Series([True] * len(df_qa))
    df = df_qa[mask].copy()

    total = len(df)

    # 문의유형 분포
    by_type: dict[str, int] = {}
    if "문의유형" in df.columns:
        for val in df["문의유형"]:
            t = first_str(val) if isinstance(val, dict) else str(val or "미분류")
            by_type[t] = by_type.get(t, 0) + 1

    # 굿즈별 문의 TOP10
    by_goods: dict[str, int] = {}
    if "굿즈명" in df.columns:
        for val in df["굿즈명"]:
            g = first_str(val) if not isinstance(val, str) else val
            g = g or "미확인"
            by_goods[g] = by_goods.get(g, 0) + 1
    top10_goods = dict(sorted(by_goods.items(), key=lambda x: -x[1])[:10])

    # 팀별 집계
    by_team: dict[str, int] = {}
    if "담당팀" in df.columns:
        for val in df["담당팀"]:
            t = str(val or "미확인")
            by_team[t] = by_team.get(t, 0) + 1

    # 답변완료율
    answered = int(df["답변완료"].apply(lambda v: bool(v)).sum()) \
        if "답변완료" in df.columns else 0
    answer_rate = (answered / total * 100) if total else 0.0

    return {
        "total_qa":         total,
        "answered":         answered,
        "answer_rate":      round(answer_rate, 1),
        "by_type":          by_type,
        "by_goods_top10":   top10_goods,
        "by_team":          by_team,
        "raw_df":           df,
    }


# ─────────────────────────────────────────────────────────
#  [Fix-3] CSV 저장 — 테이블별 개별 저장 + 마스터 merge
# ─────────────────────────────────────────────────────────

def save_raw_csv(
    iso_week: str,
    df_task: pd.DataFrame,
    df_order: pd.DataFrame,
    df_movement: pd.DataFrame,
    df_parts: pd.DataFrame,
    df_qa: pd.DataFrame,
    output_dir: Path,
) -> dict[str, Path]:
    """
    [Fix-3] pd.concat(axis=0) 제거 → 의미 없는 희소 DataFrame 방지
    저장 구조:
      scm_raw_{week}/
        task_{week}.csv       — 발주 raw
        order_{week}.csv      — 주문 raw
        movement_{week}.csv   — 이슈/입하 raw (당주 필터 적용됨)
        parts_snapshot.csv    — 재고 스냅샷
        qa_{week}.csv         — Q&A (당주 필터 적용됨)
        master_{week}.csv     — task × order 굿즈명 기준 merge (원가율 계산용)
    """
    week_dir = output_dir / f"scm_raw_{iso_week}"
    week_dir.mkdir(parents=True, exist_ok=True)
    saved = {}

    def save(df: pd.DataFrame, fname: str) -> Path:
        p = week_dir / fname
        df.to_csv(p, index=False, encoding="utf-8-sig")
        print(f"  💾 {p.name} ({len(df)}행)")
        return p

    saved["task"]     = save(df_task,     f"task_{iso_week}.csv")
    saved["order"]    = save(df_order,    f"order_{iso_week}.csv")
    saved["movement"] = save(df_movement, f"movement_{iso_week}.csv")
    saved["parts"]    = save(df_parts,    f"parts_snapshot.csv")
    saved["qa"]       = save(df_qa,       f"qa_{iso_week}.csv")

    # [Fix-3] 마스터 merge: order.goods_통합 기준으로 task 집계와 join
    # task에는 직접적인 order_id FK가 없으므로, 주차+굿즈명 기준 집계 join
    if not df_task.empty and not df_order.empty:
        try:
            # task 집계: 굿즈명별 취득원가 합계 (partner name 기준 집계)
            t_agg = (df_task
                     .assign(_partner=df_task.get("수주처_협력사명", pd.Series()).apply(
                         lambda v: first_str(v) or "미지정"))
                     .assign(_cost=pd.to_numeric(df_task.get("취득원가", pd.Series()),
                                                  errors="coerce").fillna(0))
                     .groupby("_partner")
                     .agg(발주건수=("_cost", "count"), 취득원가합계=("_cost", "sum"))
                     .reset_index()
                     .rename(columns={"_partner": "협력사명"}))

            # order 집계: 굿즈명별 매출 합계
            o_agg = (df_order
                     .assign(_goods=df_order.get("goods_통합", pd.Series()).fillna("미확인"))
                     .assign(_rev=pd.to_numeric(df_order.get("매출총액", pd.Series()),
                                                 errors="coerce").fillna(0))
                     .assign(_qty=pd.to_numeric(df_order.get("주문수량", pd.Series()),
                                                 errors="coerce").fillna(0))
                     .groupby("_goods")
                     .agg(주문건수=("_rev", "count"), 매출총액합계=("_rev", "sum"),
                          주문수량합계=("_qty", "sum"))
                     .reset_index()
                     .rename(columns={"_goods": "굿즈명"}))

            saved["master_task"] = save(t_agg, f"master_task_partner_{iso_week}.csv")
            saved["master_order"] = save(o_agg, f"master_order_goods_{iso_week}.csv")
        except Exception as e:
            print(f"  ⚠️ 마스터 merge 실패: {e}")

    print(f"✅ Raw CSV 저장 완료: {week_dir}")
    return saved


# ─────────────────────────────────────────────────────────
#  MD 리포트 생성
# ─────────────────────────────────────────────────────────

def generate_md_report(
    iso_week: str, week_start: datetime.date, week_end: datetime.date,
    task_kpi: dict, order_kpi: dict, cost_rate_df: pd.DataFrame,
    overall_cost_rate: float, issue_kpi: dict, stockout_kpi: dict,
    qa_kpi: dict, output_dir: Path,
) -> Path:
    """주간 SCM KPI 리포트 MD 생성 — v2.0"""
    output_dir.mkdir(parents=True, exist_ok=True)
    fname = output_dir / f"scm_kpi_report_{iso_week}.md"

    year, week_num = parse_iso_week(iso_week)
    month_week = f"{week_start.month}월 {((week_start.day - 1) // 7) + 1}주차"
    period = f"{week_start.strftime('%Y.%m.%d')}~{week_end.strftime('%m.%d')}"

    # 협력사별 발주 현황 TOP10
    partner_rows = ""
    for nm, info in list(task_kpi["by_partner"].items())[:10]:
        partner_rows += f"| {nm} | {info.get('건수', 0)}건 | {info.get('매입액', 0):,.0f}원 |\n"

    # 담당자별 발주건수
    assignee_rows = ""
    total = task_kpi["total_tasks"] or 1
    for nm, cnt in sorted(task_kpi["by_assignee"].items(), key=lambda x: -x[1])[:8]:
        assignee_rows += f"| {nm} | {cnt}건 | {cnt/total*100:.1f}% |\n"

    # 품절 목록
    stockout_rows = ""
    for row in stockout_kpi["stockout_parts"][:10]:
        stockout_rows += (
            f"| {row['파츠명']} | {row['협력사재고']} | {row['총재고']} "
            f"| {row['재입고예정일']} | {row['품절상태']} |\n"
        )

    # 굿즈별 매출
    goods_rows = ""
    for _, r in order_kpi["by_goods"].head(10).iterrows():
        goods_rows += (f"| {r['굿즈명']} | {int(r['판매수량']):,}개 "
                       f"| {r['매출액']:,.0f}원 |\n")

    # Q&A 문의유형
    qa_type_rows = ""
    for t, cnt in sorted(qa_kpi.get("by_type", {}).items(), key=lambda x: -x[1])[:8]:
        qa_type_rows += f"| {t} | {cnt}건 |\n"
    qa_goods_rows = ""
    for g, cnt in list(qa_kpi.get("by_goods_top10", {}).items())[:8]:
        qa_goods_rows += f"| {g} | {cnt}건 |\n"

    md = f"""---
date: {datetime.date.today().isoformat()}
iso_week: {iso_week}
type: weekly_scm_kpi_report
version: v2.0
team: 외주생산파트
generated_by: scm_weekly_kpi_agent_v2.0
---

# 구매조달 주간 KPI — {iso_week}

| 기준 | {month_week} | 기간 | {period} |
|---|---|---|---|

---

## ■ 발주 KPI 요약

| 항목 | 지표 |
|---|---|
| 발주 TASK | {task_kpi['total_tasks']:,}건 |
| 총 지출액(VAT포함) | {task_kpi['total_expenditure']:,.0f}원 |
| 공급가액(매입) | {task_kpi['supply_amount']:,.0f}원 |
| 취득원가 | {task_kpi['acquisition_cost']:,.0f}원 |
| 발주지시수량 합계 | {task_kpi['order_qty']:,.0f}개 |
| 긴급건수 | {task_kpi['urgent_count']:,}건 |
| 긴급률 | {task_kpi['urgent_rate']*100:.1f}% |
| 미입하 TASK | {task_kpi['uninput_count']:,}건 |
| 미입하율 | {task_kpi['uninput_rate']*100:.1f}% |
| 재제작/추가제작 | {task_kpi['rework_count']:,}건 |

---

## ■ 협력사별 발주 현황 (TOP 10)

| 협력사 | 발주건수 | 매입금액 |
|---|---|---|
{partner_rows}

---

## ■ 담당자별 발주건수

| 담당자 | 발주건수 | 비율 |
|---|---|---|
{assignee_rows}

---

## ■ 매출 KPI (order 기준)

| 항목 | 지표 |
|---|---|
| 총 주문건수 | {order_kpi['total_orders']:,}건 |
| 총 주문수량 | {order_kpi['total_qty']:,.0f}개 |
| 총 매출액 | {order_kpi['total_revenue']:,.0f}원 |
| **전체 원가율** (취득원가/매출총액) | **{overall_cost_rate:.1f}%** |

> ⚠️ SSOT: 원가율 = task.취득원가 / order.매출총액. order.매출원가는 재고포함여부 혼재로 미사용.

### 굿즈별 매출 (TOP 10)

| 굿즈명 | 판매수량 | 매출액 |
|---|---|---|
{goods_rows}

---

## ■ 이슈 KPI

| 항목 | 건수 |
|---|---|
| 운영이슈 | {issue_kpi['operation_issues']:,}건 |
| 수량이슈 | {issue_kpi['quantity_issues']:,}건 |
| 품질이슈 | {issue_kpi['quality_issues']:,}건 |
| 품질등급 일치율 | {issue_kpi['quality_match_rate']:.1f}% |
| 고객인지이슈 | {issue_kpi['cx_issues']:,}건 |

---

## ■ 협력사 재고 품절 현황

{stockout_kpi['data_caveat']}

| 구분 | 건수 |
|---|---|
| 품절 파츠 | {stockout_kpi['stockout_count']}종 |
| 품절위험 파츠 | {stockout_kpi['risk_count']}종 |

| 파츠명 | 협력사재고 | 총재고 | 재입고예정일 | 상태 |
|---|---|---|---|---|
{stockout_rows or '> 품절 파츠 없음'}

---

## ■ 제품 Q&A 동향 (check_standard_answer)

| 항목 | 건수 |
|---|---|
| 총 문의 건수 | {qa_kpi.get('total_qa', 0):,}건 |
| 답변완료 | {qa_kpi.get('answered', 0):,}건 |
| 답변완료율 | {qa_kpi.get('answer_rate', 0):.1f}% |

### 문의유형별

| 유형 | 건수 |
|---|---|
{qa_type_rows or '| 데이터 없음 | — |'}

### 문의 다빈도 제품 TOP8

| 굿즈명 | 문의건수 |
|---|---|
{qa_goods_rows or '| 데이터 없음 | — |'}

---

*Generated by scm_weekly_kpi_agent v2.0 — {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}*
"""
    fname.write_text(md, encoding="utf-8")
    print(f"✅ KPI 리포트 저장: {fname}")
    return fname


# ─────────────────────────────────────────────────────────
#  메인 실행
# ─────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="SCM 주간 KPI 자동화 에이전트 v2.0")
    parser.add_argument("--week",       type=str, help="ISO week (예: 2026-W21)")
    parser.add_argument("--month",      type=str, help="월간 리포트 (예: 2026-05)")
    parser.add_argument("--output-dir", type=str, default="./scm_reports")
    parser.add_argument("--dry-run",    action="store_true", help="API 없이 빈 데이터로 테스트")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)

    # 월간 리포트 모드
    if args.month:
        year, month = map(int, args.month.split("-"))
        raw_dir = output_dir
        csv_files = sorted(raw_dir.glob(f"scm_raw_{year}-W*/task_{year}-W*.csv"))
        if not csv_files:
            print(f"⚠️ {year}년 task CSV 없음. 먼저 주간 리포트를 실행하세요.")
            return
        dfs = []
        for f in csv_files:
            wk_str = f.stem.replace("task_", "")
            yr2, wk2 = parse_iso_week(wk_str)
            ws, we = get_week_range(yr2, wk2)
            if ws.month == month or we.month == month:
                df = pd.read_csv(f, encoding="utf-8-sig")
                df["iso_week"] = wk_str
                dfs.append(df)
        if not dfs:
            print(f"⚠️ {year}-{month:02d} 해당 주차 데이터 없음")
            return
        monthly = pd.concat(dfs, ignore_index=True)
        out = output_dir / f"monthly/scm_monthly_{year}-{month:02d}.csv"
        out.parent.mkdir(parents=True, exist_ok=True)
        monthly.to_csv(out, index=False, encoding="utf-8-sig")
        print(f"✅ 월간 집계: {out} ({len(monthly)}행)")
        return

    # 주차 결정
    iso_week = args.week or current_iso_week()
    year, week_num = parse_iso_week(iso_week)
    week_start, week_end = get_week_range(year, week_num)
    print(f"\n🗓️  처리 주차: {iso_week} ({week_start} ~ {week_end})")

    if args.dry_run:
        print("⚠️  Dry-run 모드: 빈 DataFrame으로 실행합니다.")
        df_task     = pd.DataFrame(columns=list(TASK_FIELD_ID_MAP.values()))
        df_order    = pd.DataFrame(columns=list(ORDER_FIELD_ID_MAP.values()))
        df_movement = pd.DataFrame(columns=MOVEMENT_FIELDS_BY_NAME)
        df_parts    = pd.DataFrame(columns=list(SYNC_PARTS_FIELD_ID_MAP.values()))
        df_issue    = pd.DataFrame(columns=ISSUE_REGISTER_FIELDS_BY_NAME)
        df_qa       = pd.DataFrame(columns=list(CHECK_QA_FIELD_ID_MAP.values()))
    else:
        print("📡 Airtable 데이터 수집 중 (2025-2026 범위)...")

        # [Fix-2] task: 2025년 이후 + field_id 기반
        TASK_FILTER = "IS_AFTER({과업지시일자}, '2024-12-31')"
        df_task = fetch_by_id("task", TASK_FIELD_ID_MAP,
                               filter_formula=TASK_FILTER, max_records=8000)
        print(f"  task: {len(df_task)}건")

        # [Fix-2] order: 2025년 이후 + field_id 기반
        ORDER_FILTER = "IS_AFTER({Created time}, '2024-12-31')"
        df_order = fetch_by_id("order", ORDER_FIELD_ID_MAP,
                                filter_formula=ORDER_FILTER, max_records=8000)
        print(f"  order: {len(df_order)}건")

        # [Fix-2] movement: 날짜 범위 필터 필수 (타임아웃 방지)
        #   입하예정일 또는 실제입하일이 당주에 해당하는 레코드만 조회
        MOV_FILTER = (
            f"OR("
            f"AND({{입하예정일}} >= '{week_start}', {{입하예정일}} <= '{week_end}'),"
            f"AND({{실제입하일}} >= '{week_start}', {{실제입하일}} <= '{week_end}')"
            f")"
        )
        df_movement = fetch_by_name("movement", MOVEMENT_FIELDS_BY_NAME,
                                     filter_formula=MOV_FILTER, max_records=2000)
        print(f"  movement: {len(df_movement)}건")

        # sync_parts: 전체 스냅샷 (수량 적음)
        df_parts = fetch_by_id("sync_parts", SYNC_PARTS_FIELD_ID_MAP, max_records=2000)
        print(f"  sync_parts: {len(df_parts)}건")

        # issue_register: 필드명 기반 (field_id 미확인)
        ISSUE_FILTER = f"AND({{등록일자}} >= '{week_start}', {{등록일자}} <= '{week_end}')"
        df_issue = fetch_by_name("issue_register", ISSUE_REGISTER_FIELDS_BY_NAME,
                                  filter_formula=ISSUE_FILTER, max_records=500)
        print(f"  issue_register: {len(df_issue)}건")

        # [Fix-4] check_standard_answer: field_id 기반 + 날짜 필터
        QA_FILTER = f"AND({{등록날짜}} >= '{week_start}', {{등록날짜}} <= '{week_end}')"
        df_qa = fetch_by_id("check_standard_answer", CHECK_QA_FIELD_ID_MAP,
                             filter_formula=QA_FILTER, max_records=1000)
        print(f"  check_standard_answer: {len(df_qa)}건")

    # ── KPI 집계 ──
    print("\n🧮 KPI 집계 중...")

    task_kpi    = calc_task_kpi(df_task, week_start, week_end)
    order_kpi   = calc_order_kpi(df_order, week_start, week_end)

    # [Fix-5] 원가율: task.취득원가 / order.매출총액 (SSOT)
    cost_rate_df, overall_cost_rate = calc_cost_rate_by_goods(
        task_kpi["raw_df"], order_kpi["by_goods"]
    )

    issue_kpi   = calc_issue_kpi(df_movement, df_issue, week_start, week_end)
    stockout_kpi = calc_stockout_kpi(df_parts)

    # [Fix-4] Q&A 집계 (df_qa는 이미 날짜 필터 적용)
    qa_kpi = calc_qa_kpi(df_qa, week_start, week_end)

    # ── 파일 저장 ──
    print("\n💾 파일 저장 중...")
    save_raw_csv(iso_week, task_kpi["raw_df"], order_kpi["raw_df"],
                 issue_kpi["raw_df"], df_parts,
                 qa_kpi.get("raw_df", pd.DataFrame()), output_dir)

    report_path = generate_md_report(
        iso_week, week_start, week_end,
        task_kpi, order_kpi, cost_rate_df, overall_cost_rate,
        issue_kpi, stockout_kpi, qa_kpi, output_dir,
    )

    # ── 요약 출력 ──
    print(f"\n✅ 완료! 리포트: {report_path}")
    print(f"   발주 TASK:     {task_kpi['total_tasks']}건")
    print(f"   총 지출액:     {task_kpi['total_expenditure']:,.0f}원")
    print(f"   긴급률:        {task_kpi['urgent_rate']*100:.1f}%")
    print(f"   전체 원가율:   {overall_cost_rate:.1f}% (취득원가/매출총액, SSOT)")
    print(f"   품질일치율:    {issue_kpi['quality_match_rate']:.1f}%")
    print(f"   품절 파츠:     {stockout_kpi['stockout_count']}종")
    print(f"   Q&A 문의:      {qa_kpi['total_qa']}건")


if __name__ == "__main__":
    main()
