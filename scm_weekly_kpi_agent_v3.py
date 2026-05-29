"""
SCM 주간 KPI 자동화 에이전트
버전: v4.0  ← v3.0 대비 변경사항
  [v4-Fix-1] sales_status_history 테이블 연동:
             TABLES에 추가, SALES_STATUS_HISTORY_FIELD_ID_MAP 신규 정의
  [v4-Fix-2] calc_stockout_kpi 완전 재구현 (이력 기반):
             - 품절경과일수 = end_time - 변경일 (해소) / today - 변경일 (진행 중)
             - 이번 주 신규 품절 / 이번 주 품절 해소 집계
             - 평균 품절기간 계산 (해소된 건 기준)
             - 품절사유(10종) · 품절성격(의도적/비의도적) 분포 집계
  [v4-Fix-3] MD 리포트 품절 섹션 확장:
             이력 기반 경과일수 컬럼 + 주간 신규·해소 테이블 추가

버전 이력:
  v1.0 — 최초 작성
  v2.0 — filterByFormula 추가·field_id 매핑·Q&A 집계·원가 SSOT 수정·품절 caveat
  v3.0 — 굿즈명 join key 확보 → 굿즈별 원가율 계산 완성
  v4.0 — sales_status_history 연동 → 품절경과일수 실계산·주간 품절 동향 KPI

실행 방법:
  python scm_weekly_kpi_agent_v4.py                     # 현재 주차
  python scm_weekly_kpi_agent_v4.py --week 2026-W21     # 특정 주차
  python scm_weekly_kpi_agent_v4.py --month 2026-05     # 월간 리포트
  python scm_weekly_kpi_agent_v4.py --dry-run           # API 없이 테스트

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
    # [v4] 품절 이력 — MRP 베이스
    "sales_status_history":  ("MRP",       "tblLaQ4d0B675Mxw2"),
}

# ─────────────────────────────────────────────────────────
#  Field ID 매핑 딕셔너리
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
    # [v3-Fix-1] 굿즈명 JOIN KEY 추가 (SSOT: task.goods(from order) lookup)
    "fldnU6QRLLujfEuL7": "굿즈명_task",         # lookup → order.goods(통합) [SSOT join key]
}

ORDER_FIELD_ID_MAP = {
    "fldm6bMDAagEaKDpy": "order_id",
    "fldvjDTKEy9q7wPZZ": "goods_통합",          # formula [SSOT: 굿즈명]
    "fldBoP15rTdPuAuJo": "item_통합",            # formula
    "fldV2yyCiEt1V7FLS": "주문수량",             # number [SSOT: 고객주문수량]
    "fldQ4VmhIF0pNlLJe": "매출총액",             # formula [SSOT: 원가율 분모]
    "fldCxxtQJxczppnns": "매출원가_order",       # ⚠️ 재고포함여부 혼재 — SSOT 아님, 참고용만
    "fld3imEMsRuSpO2gX": "발주신청일",           # createdTime  ← Airtable field명: "Created time"
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
    "fldoyTSSbG8JpALrL": "문의유형",            # singleSelect
    "fldsIVosP043Z3CiZ": "질문내용",            # text
    "fldvTyY5LqECg5WhI": "답변내용",            # text
    "fldl2dz6NO8FummAE": "굿즈명",              # lookup → 제품명 [SSOT]
    "fldflEhnYx1gOLNUn": "등록날짜",            # date [집계 기준]
    "fldA9VYyj7YPqd8rv": "담당팀",              # text (MD/POM/FFM)
    "fld5lynz7vWSLpG1G": "수량",                # number
    "fld3V3LhvfMcEzMGy": "답변완료",            # checkbox
}

# [v4] sales_status_history field_id 매핑
#  판매상태 선택지: 판매가능/품절예정/일시품절/제품 철수(졸업)/의도적 품절
SALES_STATUS_HISTORY_FIELD_ID_MAP = {
    "fld71aeYoGELhKLaX": "변경일",     # createdTime = 품절 시작일 (이 레코드가 생성된 시각)
    "fldiN3i81l8AdcXAn": "end_time",   # dateTime    = 품절 종료일 (null → 현재 품절 진행 중)
    "fldETvwFt5WwQ5ZJI": "판매상태",    # singleSelect: 일시품절 / 의도적 품절
    "fldO9nzsirNxfOoxb": "파츠_이름",   # lookup → 파츠명 문자열 [SSOT]
    "fldoKqCgmezRheT3u": "품절_성격",   # singleSelect: 의도적품절 / 비의도적품절
    "fldtoSMpp8MRic2b2": "품절_사유",   # singleSelect: 10종 세부사유
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
#  Airtable API 헬퍼 — 튜플 리스트 params
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
    field_ids: list[str] = None,
    field_names: list[str] = None,
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
    while True:
        params = base_params.copy()
        if offset:
            params.append(("offset", offset))
        resp = requests.get(url, headers=get_headers(), params=params, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        batch = data.get("records", [])
        records.extend(batch)
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
            return obj["linkedRecordIds"]
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
    cost_amt    = num("취득원가").sum()    # SSOT: 원가율 분자
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
        "acquisition_cost":   float(cost_amt),   # SSOT 원가율 분자
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
    # ⚠️ order.매출원가_order는 참고용만 — 원가율 공식에는 task.취득원가 사용 (SSOT)

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
) -> tuple[pd.DataFrame, float]:
    """
    [v3-Fix-2] 원가율 SSOT — task.취득원가 / order.매출총액 × 100
      굿즈명_task (fldnU6QRLLujfEuL7) 기준 task 집계 후 order.goods_통합 기준 join
      — v2의 '⚠️ 굿즈별 join key 미확인' 한계 해소

    SSOT 설계서 5-2:
      [order JOIN task on order_id] → goods(통합) 기준 매출·매입 합산 후 원가율 계산
      원가율 = SUM(task.취득원가) / SUM(order.매출총액) × 100  GROUP BY 굿즈명
    """
    # ── task: 굿즈명_task 기준 취득원가 집계 ────────────────
    task_goods_agg: dict[str, float] = {}   # {굿즈명: 취득원가합계}
    total_cost = 0.0

    if "굿즈명_task" in df_task_week.columns and not df_task_week.empty:
        for _, row in df_task_week.iterrows():
            raw_g = row.get("굿즈명_task")
            # lookup 필드는 리스트나 dict로 올 수 있음 → first_str 파싱
            g = first_str(raw_g) if not isinstance(raw_g, str) else raw_g
            g = (g or "").strip() or "미확인"
            cost = float(pd.to_numeric(row.get("취득원가", 0), errors="coerce") or 0)
            task_goods_agg[g] = task_goods_agg.get(g, 0) + cost
            total_cost += cost
    else:
        # fallback: 굿즈명_task 필드 없을 때 전체 합계만 (field_id 미매핑 상태)
        total_cost = float(
            pd.to_numeric(
                df_task_week.get("취득원가", pd.Series(dtype=float)), errors="coerce"
            ).fillna(0).sum()
        )

    # ── order: 전체 매출액 합계 ───────────────────────────
    total_revenue = float(by_goods_order["매출액"].sum()) if not by_goods_order.empty else 0.0
    overall_rate  = (total_cost / total_revenue * 100) if total_revenue > 0 else 0.0

    # ── 굿즈별 원가율 계산 ──────────────────────────────────
    result = by_goods_order.copy()

    if task_goods_agg:
        result["취득원가"] = result["굿즈명"].map(task_goods_agg).fillna(0)
        result["원가율(%)"] = result.apply(
            lambda r: round(r["취득원가"] / r["매출액"] * 100, 1)
                      if r["매출액"] > 0 else float("nan"),
            axis=1,
        )
        # 취득원가가 0인 굿즈는 task 미매핑 — 참고용으로 표시
        result["원가율_신뢰도"] = result["취득원가"].apply(
            lambda c: "정상" if c > 0 else "task미매핑"
        )
    else:
        # 굿즈명_task 필드 미확인 시 전체 원가율만 제공
        result["취득원가"]     = float("nan")
        result["원가율(%)"]   = float("nan")
        result["원가율_신뢰도"] = "굿즈명_task 필드 미매핑"

    result["전체_원가율(%)"] = round(overall_rate, 1)
    return result, overall_rate


# ─────────────────────────────────────────────────────────
#  KPI 계산 — 이슈 KPI (movement + issue_register 기준)
# ─────────────────────────────────────────────────────────

def calc_issue_kpi(df_movement: pd.DataFrame, df_issue_reg: pd.DataFrame,
                    week_start: datetime.date, week_end: datetime.date) -> dict:
    """이슈 KPI 집계 — movement 날짜 필터는 fetch 단계에서 적용됨"""
    df_m = df_movement.copy()

    cats = {"운영이슈": 0, "수량이슈": 0, "품질이슈": 0}
    if "이슈카테고리" in df_m.columns:
        for val in df_m["이슈카테고리"]:
            for cat in cats:
                if cat in str(val or ""):
                    cats[cat] += 1

    q_total, q_match = 0, 0
    if "품질등급최초판정" in df_m.columns and "품질등급의견_SCM" in df_m.columns:
        qdf = df_m.dropna(subset=["품질등급최초판정"])
        q_total = len(qdf)
        if q_total:
            q_match = int((qdf["품질등급최초판정"] == qdf["품질등급의견_SCM"]).sum())
    quality_match_rate = (q_match / q_total * 100) if q_total else 100.0

    quality_by_partner: dict = {}
    if "이슈카테고리" in df_m.columns and "프로젝트_발주자" in df_m.columns:
        q_df = df_m[df_m["이슈카테고리"].apply(lambda v: "품질" in str(v or ""))]
        quality_by_partner = (q_df["프로젝트_발주자"]
                              .apply(lambda v: first_str(v) or "미확인")
                              .value_counts().head(5).to_dict())

    cx_count = 0
    if not df_issue_reg.empty and "등록일자" in df_issue_reg.columns:
        cx_count = int(df_issue_reg["등록일자"].apply(
            lambda v: in_week(v, week_start, week_end)).sum())

    return {
        "operation_issues":        int(cats["운영이슈"]),
        "quantity_issues":         int(cats["수량이슈"]),
        "quality_issues":          int(cats["품질이슈"]),
        "quality_match_rate":      float(quality_match_rate),
        "quality_by_partner_top5": quality_by_partner,
        "cx_issues":               cx_count,
        "raw_df":                  df_m,
    }


# ─────────────────────────────────────────────────────────
#  KPI 계산 — 품절 KPI (sync_parts 기준)
# ─────────────────────────────────────────────────────────

def calc_stockout_kpi(
    df_parts: pd.DataFrame,
    df_ssh: pd.DataFrame,
    week_start: datetime.date,
    week_end: datetime.date,
) -> dict:
    """
    [v4] 품절 KPI — sales_status_history 이력 기반 실계산

    품절경과일수 계산 로직:
      - 진행 중: end_time IS NULL  → 경과일수 = today - 변경일
      - 해소 후: end_time IS NOT NULL → 경과일수 = end_time - 변경일
    대상: 판매상태 = '일시품절' OR '의도적 품절'

    주간 KPI:
      stockout_parts     — 현재 품절 파츠 목록 (이력 기반, 경과일수 내림차순)
      new_this_week      — 이번 주 신규 품절 (변경일 ∈ [week_start, week_end])
      resolved_this_week — 이번 주 품절 해소 (end_time ∈ [week_start, week_end])
      avg_resolved_days  — 해소된 품절의 평균 기간 (전체 이력 기준)
      reason_dist        — 품절사유 분포 (이번 주 신규 + 진행 중 기준)
    """
    today = datetime.date.today()

    # ── 스냅샷: 품절위험 파츠 수 (sync_parts 보조) ─────────
    risk_count = 0
    if not df_parts.empty and "품절위험여부" in df_parts.columns:
        risk_count = int(df_parts["품절위험여부"].apply(
            lambda v: bool(v) if v not in (None, "", False) else False
        ).sum())

    # ── 이력 기반 집계 ──────────────────────────────────────
    currently_out:   dict[str, dict] = {}   # 파츠명 → 최신 진행 중 품절 정보
    new_this_week:   list[dict] = []
    resolved_this_week: list[dict] = []
    resolved_durations: list[int] = []
    reason_counter:  dict[str, int] = {}    # 품절사유 분포

    if not df_ssh.empty:
        for _, row in df_ssh.iterrows():
            raw_name  = row.get("파츠_이름")
            parts_name = first_str(raw_name) if raw_name is not None else ""
            if not parts_name:
                continue

            start_dt = safe_date(row.get("변경일"))
            end_dt   = safe_date(row.get("end_time"))
            if start_dt is None:
                continue

            # singleSelect 파싱 (returnFieldsByFieldId=true 시 dict 반환)
            def _sel(col):
                v = row.get(col)
                return first_str(v) if not isinstance(v, str) else (v or "—")

            status = _sel("판매상태")
            nature = _sel("품절_성격") or "—"
            reason = _sel("품절_사유") or "—"

            if end_dt is None:
                # ── 현재 품절 진행 중 ──────────────────────
                elapsed = (today - start_dt).days
                entry = {
                    "파츠명":       parts_name,
                    "품절시작일":   str(start_dt),
                    "품절경과일수": elapsed,
                    "재입고예정일": _get_restock_date(df_parts, parts_name),
                    "판매상태":     status,
                    "품절성격":     nature,
                    "품절사유":     reason,
                }
                # 같은 파츠 중 가장 최근 시작일 유지
                prev = currently_out.get(parts_name)
                if prev is None or start_dt > safe_date(prev["품절시작일"]):
                    currently_out[parts_name] = entry

                # 이번 주 신규 품절 여부
                if in_week(start_dt, week_start, week_end):
                    new_this_week.append(entry)

                # 사유 집계
                if reason != "—":
                    reason_counter[reason] = reason_counter.get(reason, 0) + 1

            else:
                # ── 품절 해소됨 ────────────────────────────
                elapsed = (end_dt - start_dt).days
                resolved_durations.append(elapsed)

                if in_week(end_dt, week_start, week_end):
                    resolved_this_week.append({
                        "파츠명":      parts_name,
                        "품절시작일":  str(start_dt),
                        "품절종료일":  str(end_dt),
                        "품절일수":    elapsed,
                        "판매상태":    status,
                        "품절성격":    nature,
                        "품절사유":    reason,
                    })

    # 경과일수 내림차순 정렬
    stockout_list = sorted(currently_out.values(),
                           key=lambda x: x["품절경과일수"], reverse=True)
    avg_resolved = (round(sum(resolved_durations) / len(resolved_durations), 1)
                    if resolved_durations else 0.0)
    reason_dist  = dict(sorted(reason_counter.items(), key=lambda x: -x[1]))

    return {
        "stockout_parts":        stockout_list,
        "stockout_count":        len(stockout_list),
        "risk_count":            risk_count,
        "new_this_week":         new_this_week,
        "resolved_this_week":    resolved_this_week,
        "avg_resolved_days":     avg_resolved,
        "total_history_count":   len(df_ssh),
        "reason_dist":           reason_dist,
    }


def _get_restock_date(df_parts: pd.DataFrame, parts_name: str) -> str:
    """sync_parts에서 파츠명으로 재입고예정일 조회 (보조 함수)"""
    if df_parts.empty or "파츠명" not in df_parts.columns:
        return "미정"
    mask = df_parts["파츠명"].astype(str).str.contains(
        parts_name[:10], na=False, regex=False
    )
    rows = df_parts[mask]
    if rows.empty:
        return "미정"
    val = rows.iloc[0].get("협력사_재입고예정일")
    return str(val) if val else "미정"


# ─────────────────────────────────────────────────────────
#  KPI 계산 — 제품 Q&A (check_standard_answer)
# ─────────────────────────────────────────────────────────

def calc_qa_kpi(df_qa: pd.DataFrame,
                week_start: datetime.date, week_end: datetime.date) -> dict:
    """제품 Q&A 집계 — 문의유형별, 굿즈별, 팀별"""
    if df_qa.empty:
        return {"total_qa": 0, "by_type": {}, "by_goods_top10": {}, "by_team": {}}

    # 주차 필터 (API에서 이미 필터됐지만 안전망으로 유지)
    mask = df_qa["등록날짜"].apply(lambda v: in_week(v, week_start, week_end)) \
        if "등록날짜" in df_qa.columns else pd.Series([True] * len(df_qa))
    df = df_qa[mask].copy()

    total = len(df)

    by_type: dict[str, int] = {}
    if "문의유형" in df.columns:
        for val in df["문의유형"]:
            t = first_str(val) if isinstance(val, dict) else str(val or "미분류")
            by_type[t] = by_type.get(t, 0) + 1

    by_goods: dict[str, int] = {}
    if "굿즈명" in df.columns:
        for val in df["굿즈명"]:
            g = first_str(val) if not isinstance(val, str) else val
            g = g or "미확인"
            by_goods[g] = by_goods.get(g, 0) + 1
    top10_goods = dict(sorted(by_goods.items(), key=lambda x: -x[1])[:10])

    by_team: dict[str, int] = {}
    if "담당팀" in df.columns:
        for val in df["담당팀"]:
            t = str(val or "미확인")
            by_team[t] = by_team.get(t, 0) + 1

    answered = int(df["답변완료"].apply(lambda v: bool(v)).sum()) \
        if "답변완료" in df.columns else 0
    answer_rate = (answered / total * 100) if total else 0.0

    return {
        "total_qa":       total,
        "answered":       answered,
        "answer_rate":    round(answer_rate, 1),
        "by_type":        by_type,
        "by_goods_top10": top10_goods,
        "by_team":        by_team,
        "raw_df":         df,
    }


# ─────────────────────────────────────────────────────────
#  [v3-Fix-3] CSV 저장 — 테이블별 개별 저장 + 굿즈명 기준 마스터 merge
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
    저장 구조:
      scm_raw_{week}/
        task_{week}.csv          — 발주 raw (주차 필터 적용)
        order_{week}.csv         — 주문 raw (주차 필터 적용)
        movement_{week}.csv      — 이슈/입하 raw
        parts_snapshot.csv       — 재고 스냅샷
        qa_{week}.csv            — Q&A
        master_goods_{week}.csv  — [v3] 굿즈명 기준 task×order 통합 (원가율 계산용)
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

    # [v3-Fix-3] 마스터 merge: 굿즈명 기준 task(취득원가) × order(매출총액) 통합
    if not df_task.empty and not df_order.empty:
        try:
            # task: 굿즈명_task 기준 집계 (fldnU6QRLLujfEuL7 lookup)
            goods_col_available = "굿즈명_task" in df_task.columns
            if goods_col_available:
                t_agg = (df_task
                         .assign(_goods=df_task["굿즈명_task"].apply(
                             lambda v: (first_str(v) if not isinstance(v, str) else (v or "미확인")).strip()))
                         .assign(_cost=pd.to_numeric(df_task.get("취득원가", pd.Series()),
                                                      errors="coerce").fillna(0))
                         .assign(_supply=pd.to_numeric(df_task.get("공급가액", pd.Series()),
                                                        errors="coerce").fillna(0))
                         .groupby("_goods")
                         .agg(task_발주건수=("_cost", "count"),
                              task_취득원가합계=("_cost", "sum"),
                              task_공급가액합계=("_supply", "sum"))
                         .reset_index()
                         .rename(columns={"_goods": "굿즈명"}))
            else:
                # fallback: 굿즈명_task 없으면 협력사명 기준 집계 (v2 방식)
                t_agg = (df_task
                         .assign(_partner=df_task.get("수주처_협력사명",
                                                        pd.Series()).apply(
                             lambda v: first_str(v) or "미지정"))
                         .assign(_cost=pd.to_numeric(df_task.get("취득원가", pd.Series()),
                                                      errors="coerce").fillna(0))
                         .groupby("_partner")
                         .agg(task_발주건수=("_cost", "count"),
                              task_취득원가합계=("_cost", "sum"))
                         .reset_index()
                         .rename(columns={"_partner": "협력사명"}))

            # order: 굿즈명 기준 집계
            o_agg = (df_order
                     .assign(_goods=df_order.get("goods_통합", pd.Series()).fillna("미확인"))
                     .assign(_rev=pd.to_numeric(df_order.get("매출총액", pd.Series()),
                                                 errors="coerce").fillna(0))
                     .assign(_qty=pd.to_numeric(df_order.get("주문수량", pd.Series()),
                                                 errors="coerce").fillna(0))
                     .groupby("_goods")
                     .agg(order_주문건수=("_rev", "count"),
                          order_매출총액합계=("_rev", "sum"),
                          order_주문수량합계=("_qty", "sum"))
                     .reset_index()
                     .rename(columns={"_goods": "굿즈명"}))

            if goods_col_available:
                # 굿즈명 기준 outer join → 원가율 계산 포함 마스터 CSV
                master = pd.merge(t_agg, o_agg, on="굿즈명", how="outer")
                master["원가율(%)"] = master.apply(
                    lambda r: round(r["task_취득원가합계"] / r["order_매출총액합계"] * 100, 1)
                              if r.get("order_매출총액합계", 0) > 0 else float("nan"),
                    axis=1,
                )
                saved["master_goods"] = save(master, f"master_goods_{iso_week}.csv")
            else:
                saved["master_task_partner"] = save(t_agg,  f"master_task_partner_{iso_week}.csv")
                saved["master_order_goods"]  = save(o_agg,  f"master_order_goods_{iso_week}.csv")

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
    """주간 SCM KPI 리포트 MD 생성 — v3.0"""
    output_dir.mkdir(parents=True, exist_ok=True)
    fname = output_dir / f"scm_kpi_report_{iso_week}.md"

    year, week_num = parse_iso_week(iso_week)
    month_week = f"{week_start.month}월 {((week_start.day - 1) // 7) + 1}주차"
    period = f"{week_start.strftime('%Y.%m.%d')}~{week_end.strftime('%m.%d')}"

    # 협력사별 발주 현황 TOP10
    partner_rows = ""
    for nm, info in list(task_kpi["by_partner"].items())[:10]:
        partner_rows += f"| {nm} | {info.get('건수', 0)}건 | {info.get('매입액', 0):,.0f}원 |\n"
    if not partner_rows:
        partner_rows = "| (데이터 없음) | — | — |\n"

    # 담당자별 발주건수
    assignee_rows = ""
    total_tasks_denom = task_kpi["total_tasks"] or 1
    for nm, cnt in sorted(task_kpi["by_assignee"].items(), key=lambda x: -x[1])[:8]:
        assignee_rows += f"| {nm} | {cnt}건 | {cnt/total_tasks_denom*100:.1f}% |\n"
    if not assignee_rows:
        assignee_rows = "| (데이터 없음) | — | — |\n"

    # [v4] 품절 목록 — 이력 기반 경과일수 포함
    stockout_rows = ""
    for row in stockout_kpi["stockout_parts"][:10]:
        stockout_rows += (
            f"| {row['파츠명']} | {row['품절시작일']} | {row['품절경과일수']}일 "
            f"| {row['재입고예정일']} | {row['판매상태']} | {row['품절사유']} |\n"
        )
    if not stockout_rows:
        stockout_rows = ""

    # 이번 주 신규 품절
    new_stockout_rows = ""
    for row in stockout_kpi.get("new_this_week", [])[:10]:
        new_stockout_rows += (
            f"| {row['파츠명']} | {row['품절시작일']} | {row['판매상태']} | {row['품절사유']} |\n"
        )

    # 이번 주 품절 해소
    resolved_rows = ""
    for row in stockout_kpi.get("resolved_this_week", [])[:10]:
        resolved_rows += (
            f"| {row['파츠명']} | {row['품절시작일']} | {row['품절종료일']} "
            f"| {row['품절일수']}일 | {row['품절사유']} |\n"
        )

    # 품절사유 분포
    reason_rows = ""
    for reason, cnt in list(stockout_kpi.get("reason_dist", {}).items())[:8]:
        reason_rows += f"| {reason} | {cnt}건 |\n"

    # 굿즈별 매출 + [v3-Fix-4] 원가율 컬럼 추가
    goods_rows = ""
    if not cost_rate_df.empty and "원가율(%)" in cost_rate_df.columns:
        for _, r in cost_rate_df.head(10).iterrows():
            cost_val  = r.get("취득원가", float("nan"))
            rate_val  = r.get("원가율(%)", float("nan"))
            trust     = r.get("원가율_신뢰도", "")
            cost_str  = f"{cost_val:,.0f}원" if not pd.isna(cost_val) else "—"
            rate_str  = f"{rate_val:.1f}%" if not pd.isna(rate_val) else "—"
            trust_str = f" _{trust}_" if trust and trust != "정상" else ""
            goods_rows += (
                f"| {r.get('굿즈명', '—')} | {int(r.get('판매수량', 0)):,}개 "
                f"| {r.get('매출액', 0):,.0f}원 | {cost_str} | {rate_str}{trust_str} |\n"
            )
    else:
        for _, r in order_kpi["by_goods"].head(10).iterrows():
            goods_rows += (f"| {r['굿즈명']} | {int(r['판매수량']):,}개 "
                           f"| {r['매출액']:,.0f}원 | — | — |\n")
    if not goods_rows:
        goods_rows = "| (데이터 없음) | — | — | — | — |\n"

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
version: v3.0
team: 외주생산파트
generated_by: scm_weekly_kpi_agent_v3.0
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

> SSOT: 원가율 = task.취득원가 / order.매출총액. order.매출원가는 재고포함여부 혼재로 미사용.

### 굿즈별 매출 · 원가율 (TOP 10)

| 굿즈명 | 판매수량 | 매출액 | 취득원가 | 원가율(%) |
|---|---|---|---|---|
{goods_rows}

> 원가율 출처: task.굿즈명_task (fldnU6QRLLujfEuL7) × order.goods_통합 기준 집계.
> _task미매핑_ 표시 = 해당 굿즈에 연결된 task 레코드 없음 (이번 주차 발주 없음).

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

## ■ 협력사 재고 품절 현황 (sales_status_history 이력 기반)

| 구분 | 건수 |
|---|---|
| 현재 품절 파츠 | {stockout_kpi['stockout_count']}종 |
| 품절위험 파츠 | {stockout_kpi['risk_count']}종 |
| 이번 주 신규 품절 | {len(stockout_kpi.get('new_this_week', []))}건 |
| 이번 주 품절 해소 | {len(stockout_kpi.get('resolved_this_week', []))}건 |
| 평균 품절기간 (해소 기준) | {stockout_kpi.get('avg_resolved_days', 0):.1f}일 |
| 누적 품절 이력 | {stockout_kpi.get('total_history_count', 0)}건 |

### 현재 품절 파츠 (경과일수 내림차순 TOP 10)

| 파츠명 | 품절시작일 | 경과일수 | 재입고예정일 | 상태 | 품절사유 |
|---|---|---|---|---|---|
{stockout_rows or '> 현재 품절 파츠 없음'}

### 이번 주 신규 품절

| 파츠명 | 품절시작일 | 상태 | 품절사유 |
|---|---|---|---|
{new_stockout_rows or '> 이번 주 신규 품절 없음'}

### 이번 주 품절 해소

| 파츠명 | 품절시작일 | 해소일 | 품절기간 | 품절사유 |
|---|---|---|---|---|
{resolved_rows or '> 이번 주 품절 해소 없음'}

### 품절사유 분포 (현재 진행 중 기준)

| 품절사유 | 건수 |
|---|---|
{reason_rows or '| 데이터 없음 | — |'}

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

*Generated by scm_weekly_kpi_agent v3.0 — {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}*
"""
    fname.write_text(md, encoding="utf-8")
    print(f"✅ KPI 리포트 저장: {fname}")
    return fname


# ─────────────────────────────────────────────────────────
#  메인 실행
# ─────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="SCM 주간 KPI 자동화 에이전트 v3.0")
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
        df_ssh      = pd.DataFrame(columns=list(SALES_STATUS_HISTORY_FIELD_ID_MAP.values()))
    else:
        print("📡 Airtable 데이터 수집 중 (2025-2026 범위)...")

        # task: 2025년 이후 + field_id 기반 (굿즈명_task 포함)
        TASK_FILTER = "IS_AFTER({과업지시일자}, '2024-12-31')"
        df_task = fetch_by_id("task", TASK_FIELD_ID_MAP,
                               filter_formula=TASK_FILTER, max_records=8000)
        print(f"  task: {len(df_task)}건  (굿즈명_task 컬럼: {'있음' if '굿즈명_task' in df_task.columns else '없음'})")

        # order: 2025년 이후 + field_id 기반
        # ※ 'Created time'은 Airtable 시스템 필드명 (SSOT 확인)
        ORDER_FILTER = "IS_AFTER({Created time}, '2024-12-31')"
        df_order = fetch_by_id("order", ORDER_FIELD_ID_MAP,
                                filter_formula=ORDER_FILTER, max_records=8000)
        print(f"  order: {len(df_order)}건")

        # movement: 날짜 범위 필터 필수 (대용량 테이블, 타임아웃 방지)
        MOV_FILTER = (
            f"OR("
            f"AND({{입하예정일}} >= '{week_start}', {{입하예정일}} <= '{week_end}'),"
            f"AND({{실제입하일}} >= '{week_start}', {{실제입하일}} <= '{week_end}')"
            f")"
        )
        df_movement = fetch_by_name("movement", MOVEMENT_FIELDS_BY_NAME,
                                     filter_formula=MOV_FILTER, max_records=2000)
        print(f"  movement: {len(df_movement)}건")

        # sync_parts: 전체 스냅샷
        df_parts = fetch_by_id("sync_parts", SYNC_PARTS_FIELD_ID_MAP, max_records=2000)
        print(f"  sync_parts: {len(df_parts)}건")

        # issue_register: 필드명 기반
        ISSUE_FILTER = f"AND({{등록일자}} >= '{week_start}', {{등록일자}} <= '{week_end}')"
        df_issue = fetch_by_name("issue_register", ISSUE_REGISTER_FIELDS_BY_NAME,
                                  filter_formula=ISSUE_FILTER, max_records=500)
        print(f"  issue_register: {len(df_issue)}건")

        # check_standard_answer: field_id 기반 + 날짜 필터
        QA_FILTER = f"AND({{등록날짜}} >= '{week_start}', {{등록날짜}} <= '{week_end}')"
        df_qa = fetch_by_id("check_standard_answer", CHECK_QA_FIELD_ID_MAP,
                             filter_formula=QA_FILTER, max_records=1000)
        print(f"  check_standard_answer: {len(df_qa)}건")

        # [v4] sales_status_history: 품절 이력 전체 (일시품절 + 의도적 품절)
        #      → Python에서 주차별 신규/해소/진행 중 분류 (총 ~430건, 필터 없이 전량 수집)
        SSH_FILTER = "OR({판매상태} = '일시품절', {판매상태} = '의도적 품절')"
        df_ssh = fetch_by_id("sales_status_history", SALES_STATUS_HISTORY_FIELD_ID_MAP,
                              filter_formula=SSH_FILTER, max_records=3000)
        print(f"  sales_status_history: {len(df_ssh)}건 (품절 이력)")

    # ── KPI 집계 ──
    print("\n🧮 KPI 집계 중...")

    task_kpi  = calc_task_kpi(df_task, week_start, week_end)
    order_kpi = calc_order_kpi(df_order, week_start, week_end)

    # 원가율: task.취득원가 / order.매출총액 (SSOT) — v3: 굿즈별 join 포함
    cost_rate_df, overall_cost_rate = calc_cost_rate_by_goods(
        task_kpi["raw_df"], order_kpi["by_goods"]
    )

    issue_kpi    = calc_issue_kpi(df_movement, df_issue, week_start, week_end)
    # [v4] sales_status_history 이력 기반 품절경과일수 실계산
    stockout_kpi = calc_stockout_kpi(df_parts, df_ssh, week_start, week_end)
    qa_kpi       = calc_qa_kpi(df_qa, week_start, week_end)

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
    goods_with_rate = (cost_rate_df["원가율(%)"].notna().sum()
                       if not cost_rate_df.empty and "원가율(%)" in cost_rate_df.columns else 0)
    print(f"\n✅ 완료! 리포트: {report_path}")
    print(f"   발주 TASK:         {task_kpi['total_tasks']}건")
    print(f"   총 지출액:         {task_kpi['total_expenditure']:,.0f}원")
    print(f"   긴급률:            {task_kpi['urgent_rate']*100:.1f}%")
    print(f"   전체 원가율:       {overall_cost_rate:.1f}% (취득원가/매출총액, SSOT)")
    print(f"   굿즈별 원가율 산출: {goods_with_rate}개 굿즈 (task 매핑 기준)")
    print(f"   품질일치율:        {issue_kpi['quality_match_rate']:.1f}%")
    print(f"   현재 품절 파츠:    {stockout_kpi['stockout_count']}종")
    print(f"   이번 주 신규 품절: {len(stockout_kpi.get('new_this_week', []))}건")
    print(f"   이번 주 품절 해소: {len(stockout_kpi.get('resolved_this_week', []))}건")
    print(f"   평균 품절기간:     {stockout_kpi.get('avg_resolved_days', 0):.1f}일 (해소 기준)")
    print(f"   Q&A 문의:          {qa_kpi['total_qa']}건")


if __name__ == "__main__":
    main()
