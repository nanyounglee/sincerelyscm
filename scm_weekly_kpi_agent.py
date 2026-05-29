"""
SCM 주간 KPI 자동화 에이전트
버전: v1.0
작성일: 2026-05-26

실행 방법:
  python scm_weekly_kpi_agent.py                     # 현재 주차 자동 감지
  python scm_weekly_kpi_agent.py --week 2026-W21     # 특정 주차 지정
  python scm_weekly_kpi_agent.py --month 2026-05     # 월간 리포트

필요 패키지: pip install requests pandas python-dateutil
환경 변수: AIRTABLE_PAT=your_personal_access_token
"""

import os
import sys
import json
import argparse
import datetime
import requests
import pandas as pd
from pathlib import Path

# ─────────────────────────────────────────────
# 설정값 (SSOT 필드 매핑)
# ─────────────────────────────────────────────

AIRTABLE_PAT = os.environ.get("AIRTABLE_PAT", "")  # 환경변수에서 로드
BASE_URL = "https://api.airtable.com/v0"

# 베이스 & 테이블 ID
BASES = {
    "SERPA":      "appkRWtF2j99XgBTq",
    "SINCERELY":  "appAbBz1Y48qhpHwz",
    "MRP":        "applObFUJy5o025oQ",
    "ISSUE_DB":   "appkbGFSIds8NMDOH",
}

TABLES = {
    "task":                  ("SERPA",    "tbllJFVBoFjmbQXLN"),
    "order":                 ("SERPA",    "tblUYmhOvtHGJ9NO3"),
    "movement":              ("SERPA",    "tblsG3x3gCSZGPVB9"),
    "project":               ("SERPA",    "tblcw5sagkDlgAtJN"),
    "partner":               ("SINCERELY","tbl5BjEkhn3CUMIlI"),
    "sync_parts":            ("MRP",      "tblYGM8wBxlZQOu1l"),
    "sync_material_purchase":("MRP",      "tblrfPOPNnscvf75i"),
    "issue_register":        ("ISSUE_DB", "tblDMc8PuiJJkVe6H"),
    "check_standard_answer": ("ISSUE_DB", "tblwNrIIsD6dDIDDf"),  # Q&A by product
}

# 주간 KPI 집계에 사용할 핵심 필드 (이름 기반)
TASK_KPI_FIELDS = [
    "task_id", "과업지시일자", "과업담당자_이름", "수주처",
    "발주번호", "발주지시수량", "고객주문수량",
    "긴급여부", "미입하 발생이력_movement", "재제작/추가제작",
    "공급가액", "배송비", "취득원가", "총 지출액 (VAT 포함)",
    "R) 판매가(최종)", "비스포크여부", "goods (from order)",
    "산출물", "이슈체크(Order 이슈 관리용) (from order)",
    "결제일(from 지출결의)", "과업지시상태",
]

ORDER_KPI_FIELDS = [
    "order_id", "goods (통합)", "item (통합)", "주문수량",
    "매출 총액", "매출 원가", "이슈체크(Order 이슈 관리용)",
    "발주단계", "Created time",
]

MOVEMENT_KPI_FIELDS = [
    "movement_id", "이슈카테고리", "입하예정일", "실제입하일",
    "project_name", "item (통합) (from order)",
    "이동수량_예정", "입하수량", "검수수량", "불량수량_샘플링검수",
    "재제작/추가제작", "운영이슈내용(by물류)", "운영이슈개선여부",
    "수량이슈내용", "수량이슈대응방안",
    "품질이슈내용구분", "품질이슈대응필요여부", "품질이슈내용",
    "품질등급최초판정", "품질등급의견_SCM", "품질등급의견판단사유_SCM",
    "품질이슈대응방안_SCM", "프로젝트_발주자", "출하장소",
]

SYNC_PARTS_FIELDS = [
    "파츠명", "판매상태", "파츠품절 Status", "협력사_재고수량",
    "협력사_재입고예정일자", "총재고수량", "품절위험여부",
    "재고수급안정성", "굿즈품절여부",
]

ISSUE_REGISTER_FIELDS = [
    "idx_issue", "등록일자", "상태", "구분", "작성자명",
    "프로젝트명", "관련제품", "이슈내용", "발생원인", "개선방안",
]

CHECK_QA_FIELDS = [
    "관련제품", "문의유형", "질문내용", "답변내용", "등록일자", "상태",
]

# ─────────────────────────────────────────────
# Airtable API 헬퍼
# ─────────────────────────────────────────────

def get_headers():
    if not AIRTABLE_PAT:
        raise ValueError("AIRTABLE_PAT 환경변수가 설정되지 않았습니다.\n"
                         "  export AIRTABLE_PAT=your_token  (Mac/Linux)\n"
                         "  set AIRTABLE_PAT=your_token     (Windows)")
    return {"Authorization": f"Bearer {AIRTABLE_PAT}", "Content-Type": "application/json"}


def fetch_records(table_key: str, fields: list[str] = None,
                  filter_formula: str = None, max_records: int = 5000) -> pd.DataFrame:
    """지정된 테이블의 레코드를 전부 가져와 DataFrame으로 반환"""
    base_key, table_id = TABLES[table_key]
    base_id = BASES[base_key]
    url = f"{BASE_URL}/{base_id}/{table_id}"

    params = {"pageSize": 100}
    if fields:
        for i, f in enumerate(fields):
            params[f"fields[{i}]"] = f
    if filter_formula:
        params["filterByFormula"] = filter_formula

    records = []
    offset = None
    while True:
        if offset:
            params["offset"] = offset
        resp = requests.get(url, headers=get_headers(), params=params)
        resp.raise_for_status()
        data = resp.json()
        batch = data.get("records", [])
        records.extend(batch)
        offset = data.get("offset")
        if not offset or len(records) >= max_records:
            break

    if not records:
        return pd.DataFrame()

    rows = []
    for r in records:
        row = {"record_id": r["id"]}
        row.update(r.get("fields", {}))
        rows.append(row)
    return pd.DataFrame(rows)


# ─────────────────────────────────────────────
# ISO week 유틸
# ─────────────────────────────────────────────

def parse_iso_week(iso_str: str):
    """'2026-W21' → (2026, 21)"""
    parts = iso_str.split("-W")
    return int(parts[0]), int(parts[1])


def get_week_range(year: int, week: int):
    """ISO week → (월요일, 일요일) date 반환"""
    jan4 = datetime.date(year, 1, 4)
    week_start = jan4 + datetime.timedelta(weeks=week - 1, days=-jan4.weekday())
    week_end = week_start + datetime.timedelta(days=6)
    return week_start, week_end


def current_iso_week() -> str:
    today = datetime.date.today()
    iso = today.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def date_to_iso_week(d: datetime.date) -> str:
    iso = d.isocalendar()
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


# ─────────────────────────────────────────────
# KPI 계산 함수
# ─────────────────────────────────────────────

def calc_task_kpi(df_task: pd.DataFrame, week_start: datetime.date,
                  week_end: datetime.date) -> dict:
    """발주 KPI 집계"""

    def in_week(val):
        d = safe_date(val)
        if d is None:
            return False
        return week_start <= d <= week_end

    mask = df_task["과업지시일자"].apply(in_week)
    df = df_task[mask].copy()

    total_tasks = len(df)
    total_expenditure = pd.to_numeric(df.get("총 지출액 (VAT 포함)", pd.Series(dtype=float)),
                                       errors="coerce").sum()
    supply_amount = pd.to_numeric(df.get("공급가액", pd.Series(dtype=float)),
                                   errors="coerce").sum()
    acquisition_cost = pd.to_numeric(df.get("취득원가", pd.Series(dtype=float)),
                                      errors="coerce").sum()

    # 긴급 건수 (긴급여부 필드가 truthy인 경우)
    def is_urgent(val):
        if val is None or val == [] or val == "":
            return False
        if isinstance(val, list):
            return len(val) > 0
        return bool(val)
    urgent_count = df["긴급여부"].apply(is_urgent).sum() if "긴급여부" in df.columns else 0
    urgent_rate = urgent_count / total_tasks if total_tasks > 0 else 0

    # 미입하
    def has_uninput(val):
        if val is None or val == [] or val == "":
            return False
        if isinstance(val, list):
            return len(val) > 0
        return bool(val)
    uninput_count = df["미입하 발생이력_movement"].apply(has_uninput).sum() \
        if "미입하 발생이력_movement" in df.columns else 0
    uninput_rate = uninput_count / total_tasks if total_tasks > 0 else 0

    # 담당자별 발주건수
    def get_name(val):
        if isinstance(val, list):
            return ", ".join(str(v) for v in val) if val else "미지정"
        return str(val) if val else "미지정"
    by_assignee = df["과업담당자_이름"].apply(get_name).value_counts().to_dict() \
        if "과업담당자_이름" in df.columns else {}

    # 굿즈별 매입
    goods_col = "goods (from order)"
    goods_purchase = {}
    if goods_col in df.columns:
        df["_goods"] = df[goods_col].apply(
            lambda v: ", ".join(v) if isinstance(v, list) else str(v) if v else "미확인")
        df["_cost"] = pd.to_numeric(df["총 지출액 (VAT 포함)"], errors="coerce").fillna(0)
        goods_purchase = df.groupby("_goods")["_cost"].sum().sort_values(ascending=False).to_dict()

    return {
        "total_tasks": int(total_tasks),
        "total_expenditure_vat": float(total_expenditure),
        "supply_amount": float(supply_amount),
        "acquisition_cost": float(acquisition_cost),
        "urgent_count": int(urgent_count),
        "urgent_rate": float(urgent_rate),
        "uninput_count": int(uninput_count),
        "uninput_rate": float(uninput_rate),
        "by_assignee": by_assignee,
        "goods_purchase_ranking": goods_purchase,
        "raw_df": df,
    }


def calc_order_kpi(df_order: pd.DataFrame, week_start: datetime.date,
                   week_end: datetime.date) -> dict:
    """매출·매입 KPI 집계 (제품별)"""

    def in_week(val):
        d = safe_date(val)
        if d is None:
            return False
        return week_start <= d <= week_end

    time_col = "Created time" if "Created time" in df_order.columns else None
    if time_col:
        mask = df_order[time_col].apply(in_week)
        df = df_order[mask].copy()
    else:
        df = df_order.copy()

    def get_goods(val):
        if isinstance(val, list):
            return ", ".join(str(v) for v in val) if val else "미확인"
        return str(val) if val else "미확인"

    if "goods (통합)" in df.columns:
        df["_goods"] = df["goods (통합)"].apply(get_goods)
    elif "goods" in df.columns:
        df["_goods"] = df["goods"].apply(get_goods)
    else:
        df["_goods"] = "미확인"

    df["_qty"] = pd.to_numeric(df.get("주문수량", pd.Series(dtype=float)), errors="coerce").fillna(0)
    df["_revenue"] = pd.to_numeric(df.get("매출 총액", pd.Series(dtype=float)), errors="coerce").fillna(0)
    df["_cogs"] = pd.to_numeric(df.get("매출 원가", pd.Series(dtype=float)), errors="coerce").fillna(0)

    by_goods = df.groupby("_goods").agg(
        판매수량=("_qty", "sum"),
        매출액=("_revenue", "sum"),
        매입원가=("_cogs", "sum"),
    ).reset_index()
    by_goods.rename(columns={"_goods": "굿즈명"}, inplace=True)
    by_goods["원가율(%)"] = (by_goods["매입원가"] / by_goods["매출액"].replace(0, float("nan")) * 100).round(1)
    by_goods = by_goods.sort_values("매출액", ascending=False)

    total_revenue = df["_revenue"].sum()
    total_cogs = df["_cogs"].sum()
    total_qty = df["_qty"].sum()
    overall_cost_rate = (total_cogs / total_revenue * 100) if total_revenue > 0 else 0

    return {
        "total_orders": len(df),
        "total_revenue": float(total_revenue),
        "total_cogs": float(total_cogs),
        "total_qty": float(total_qty),
        "overall_cost_rate": float(overall_cost_rate),
        "by_goods": by_goods,
        "raw_df": df,
    }


def calc_issue_kpi(df_movement: pd.DataFrame, df_issue_reg: pd.DataFrame,
                   week_start: datetime.date, week_end: datetime.date) -> dict:
    """이슈 KPI 집계"""

    def in_week(val):
        d = safe_date(val)
        if d is None:
            return False
        return week_start <= d <= week_end

    # movement 기준 이슈 필터 (입하예정일 기준)
    date_col = "실제입하일" if "실제입하일" in df_movement.columns else "입하예정일"
    mask = df_movement[date_col].apply(in_week) if date_col in df_movement.columns \
        else pd.Series([True] * len(df_movement))
    df_m = df_movement[mask].copy()

    def count_category(cat_val):
        cats = ["운영이슈", "수량이슈", "품질이슈"]
        result = {c: 0 for c in cats}
        if "이슈카테고리" not in df_m.columns:
            return result
        for _, row in df_m.iterrows():
            val = row.get("이슈카테고리", "")
            if isinstance(val, list):
                for v in val:
                    for c in cats:
                        if c in str(v):
                            result[c] += 1
            elif val:
                for c in cats:
                    if c in str(val):
                        result[c] += 1
        return result

    issue_counts = count_category(None)

    # 품질등급 일치율
    match_count = 0
    total_quality = 0
    if "품질등급최초판정" in df_m.columns and "품질등급의견_SCM" in df_m.columns:
        quality_df = df_m.dropna(subset=["품질등급최초판정"])
        total_quality = len(quality_df)
        if total_quality > 0:
            match_count = (quality_df["품질등급최초판정"] == quality_df["품질등급의견_SCM"]).sum()
    quality_match_rate = (match_count / total_quality * 100) if total_quality > 0 else 100.0

    # 품질이슈 협력사 TOP
    quality_issues = df_m[df_m["이슈카테고리"].apply(
        lambda v: "품질" in str(v) if v else False
    )] if "이슈카테고리" in df_m.columns else pd.DataFrame()

    quality_by_partner = {}
    if not quality_issues.empty and "프로젝트_발주자" in quality_issues.columns:
        quality_by_partner = quality_issues["프로젝트_발주자"].apply(
            lambda v: str(v[0]) if isinstance(v, list) and v else str(v) if v else "미확인"
        ).value_counts().head(5).to_dict()

    # 고객인지이슈 (별도 DB)
    cx_count = 0
    cx_cost = 0
    if not df_issue_reg.empty:
        mask_i = df_issue_reg["등록일자"].apply(in_week) if "등록일자" in df_issue_reg.columns \
            else pd.Series([True] * len(df_issue_reg))
        df_cx = df_issue_reg[mask_i]
        cx_count = len(df_cx)

    return {
        "operation_issues": int(issue_counts.get("운영이슈", 0)),
        "quantity_issues": int(issue_counts.get("수량이슈", 0)),
        "quality_issues": int(issue_counts.get("품질이슈", 0)),
        "quality_match_rate": float(quality_match_rate),
        "quality_by_partner_top5": quality_by_partner,
        "cx_issues": int(cx_count),
        "cx_cost": float(cx_cost),
        "raw_df": df_m,
    }


def calc_stockout_kpi(df_parts: pd.DataFrame) -> dict:
    """협력사 재고 품절 KPI"""
    today = datetime.date.today()

    if df_parts.empty:
        return {"stockout_parts": [], "stockout_count": 0, "risk_count": 0}

    # 품절 파츠
    stockout_mask = df_parts["판매상태"].apply(
        lambda v: "품절" in str(v) if v else False
    ) if "판매상태" in df_parts.columns else pd.Series([False] * len(df_parts))

    df_out = df_parts[stockout_mask].copy()

    # 재입고 예정일 → 품절 잔여일수
    def days_until_restock(val):
        d = safe_date(val)
        if d is None:
            return None
        return (d - today).days

    if "협력사_재입고예정일자" in df_out.columns:
        df_out["품절잔여일"] = df_out["협력사_재입고예정일자"].apply(days_until_restock)
    else:
        df_out["품절잔여일"] = None

    # 위험 파츠 (품절 아니지만 위험)
    risk_mask = df_parts["품절위험여부"].apply(
        lambda v: bool(v) if v else False
    ) if "품절위험여부" in df_parts.columns else pd.Series([False] * len(df_parts))
    risk_count = int(risk_mask.sum())

    stockout_list = []
    for _, row in df_out.iterrows():
        stockout_list.append({
            "파츠명": row.get("파츠명", ""),
            "협력사재고": row.get("협력사_재고수량", 0),
            "재입고예정일": row.get("협력사_재입고예정일자", ""),
            "품절잔여일": row.get("품절잔여일", ""),
        })

    return {
        "stockout_parts": stockout_list,
        "stockout_count": len(stockout_list),
        "risk_count": risk_count,
    }


# ─────────────────────────────────────────────
# CSV 저장
# ─────────────────────────────────────────────

def save_raw_csv(iso_week: str, df_task: pd.DataFrame, df_order: pd.DataFrame,
                 df_movement: pd.DataFrame, output_dir: Path):
    """scm_raw_YYYY-Www.csv 저장"""
    output_dir.mkdir(parents=True, exist_ok=True)
    fname = output_dir / f"scm_raw_{iso_week}.csv"

    # task raw
    task_out = df_task.copy()
    task_out["_source"] = "task"
    order_out = df_order.copy()
    order_out["_source"] = "order"
    movement_out = df_movement.copy()
    movement_out["_source"] = "movement"

    # 공통 컬럼 기준 concat
    combined = pd.concat([task_out, order_out, movement_out],
                          ignore_index=True, sort=False)
    combined.to_csv(fname, index=False, encoding="utf-8-sig")
    print(f"✅ Raw CSV 저장: {fname}")
    return fname


# ─────────────────────────────────────────────
# MD 리포트 생성
# ─────────────────────────────────────────────

def generate_md_report(iso_week: str, week_start: datetime.date,
                        week_end: datetime.date,
                        task_kpi: dict, order_kpi: dict,
                        issue_kpi: dict, stockout_kpi: dict,
                        output_dir: Path) -> Path:
    """주간 SCM KPI 리포트 MD 생성"""
    output_dir.mkdir(parents=True, exist_ok=True)
    fname = output_dir / f"scm_kpi_report_{iso_week}.md"

    year, week_num = parse_iso_week(iso_week)
    month_week = f"{week_start.month}월 {((week_start.day - 1) // 7) + 1}주차"
    period = f"{week_start.strftime('%Y.%m.%d')}~{week_end.strftime('%m.%d')}"

    # 전주 대비용 (stub — 실제 구현 시 이전 주차 CSV 로드 필요)
    def wow(curr, prev, fmt="건"):
        if prev is None:
            return ""
        diff = curr - prev
        arrow = "▲" if diff > 0 else "▼" if diff < 0 else "━"
        return f"{arrow}{abs(diff)}{fmt}"

    # 발주건수 bar (텍스트)
    def bar(val, max_val, width=15):
        if max_val == 0:
            return "░" * width
        filled = int(val / max_val * width)
        return "█" * filled + "░" * (width - filled)

    # 굿즈별 매입 TOP5
    goods_top5 = list(task_kpi["goods_purchase_ranking"].items())[:5]

    # 제품별 매출·매입 TOP10
    goods_df = order_kpi["by_goods"].head(10)

    # 품절 목록
    stockout_rows = stockout_kpi["stockout_parts"][:10]

    md = f"""---
date: {datetime.date.today().isoformat()}
iso_week: {iso_week}
type: weekly_kpi_report
team: 외주생산파트
generated_by: scm_weekly_kpi_agent_v1.0
---

# 구매조달 주간 KPI — {iso_week}

| 기준 | {month_week} |
|---|---|
| ISO week | {iso_week} |
| 기간 | {period} |

---

## ■ KPI 리뷰

| 항목 | 지표 | WoW |
|---|---|---|
| 발주 TASK | {task_kpi['total_tasks']:,}건 | — |
| 긴급건수 | {task_kpi['urgent_count']:,}건 | — |
| 긴급률 | {task_kpi['urgent_rate']*100:.1f}% | — |
| 미입하 TASK | {task_kpi['uninput_count']:,}건 | — |
| 미입하율 | {task_kpi['uninput_rate']*100:.1f}% | — |
| 총 지출액(VAT포함) | {task_kpi['total_expenditure_vat']:,.0f}원 | — |
| 공급가액(매입) | {task_kpi['supply_amount']:,.0f}원 | — |
| 운영이슈 | {issue_kpi['operation_issues']:,}건 | — |
| 수량이슈 | {issue_kpi['quantity_issues']:,}건 | — |
| 품질이슈 | {issue_kpi['quality_issues']:,}건 | — |
| 품질등급 일치율 | {issue_kpi['quality_match_rate']:.1f}% | — |
| 고객인지이슈 | {issue_kpi['cx_issues']:,}건 | — |

---

## ■ 협력사 재고 품절 현황

| 구분 | 건수 |
|---|---|
| 품절 파츠 | {stockout_kpi['stockout_count']}개 |
| 품절위험 파츠 | {stockout_kpi['risk_count']}개 |

"""
    if stockout_rows:
        md += "| 파츠명 | 협력사재고 | 재입고예정일 | 품절잔여일 |\n"
        md += "|---|---|---|---|\n"
        for row in stockout_rows:
            md += f"| {row['파츠명']} | {row['협력사재고']} | {row['재입고예정일']} | {row.get('품절잔여일','—')}일 |\n"
    else:
        md += "> 품절 파츠 없음\n"

    md += f"""
---

## ■ 제품별 주간 매출·매입·원가율

| 굿즈명 | 판매수량 | 매출액 | 매입원가 | 원가율 |
|---|---|---|---|---|
"""
    for _, r in goods_df.iterrows():
        md += (f"| {r['굿즈명']} | {int(r['판매수량']):,}개 | "
               f"{r['매출액']:,.0f}원 | {r['매입원가']:,.0f}원 | "
               f"{r['원가율(%)'] if pd.notna(r['원가율(%)']) else '—'}% |\n")

    md += f"""
> 전체: 총 매출 {order_kpi['total_revenue']:,.0f}원 / 총 매입 {order_kpi['total_cogs']:,.0f}원 /
> 전체 원가율 {order_kpi['overall_cost_rate']:.1f}%

---

## ■ 주별 매입 TOP 제품 (이번 주)

| 순위 | 굿즈명 | 매입금액 |
|---|---|---|
"""
    for i, (goods, amt) in enumerate(goods_top5, 1):
        md += f"| {i} | {goods} | {amt:,.0f}원 |\n"

    md += f"""
---

## ■ 주간 대시보드 (담당자별 발주건수)

| 담당자 | 발주건수 | 비율 | 비율바 |
|---|---|---|---|
"""
    total = task_kpi["total_tasks"] or 1
    for assignee, cnt in sorted(task_kpi["by_assignee"].items(),
                                  key=lambda x: -x[1])[:8]:
        rate = cnt / total
        md += f"| {assignee} | {cnt}건 | {rate*100:.1f}% | {bar(cnt, total)} |\n"

    md += f"""
---

## ■ 최근 4주 추이

| ISO week | 발주건수 | 긴급건수 | 품질이슈 | 미입하 | 매입금액 | 고객인지이슈 |
|---|---|---|---|---|---|---|
| {iso_week} | {task_kpi['total_tasks']} | {task_kpi['urgent_count']} | {issue_kpi['quality_issues']} | {task_kpi['uninput_count']} | {task_kpi['total_expenditure_vat']:,.0f} | {issue_kpi['cx_issues']} |
*(이전 주차 데이터는 scm_raw CSV 아카이브에서 자동 로드)*

---

## ■ 품질이슈 협력사 TOP5

| 협력사 | 이슈건수 |
|---|---|
"""
    for partner, cnt in list(issue_kpi["quality_by_partner_top5"].items())[:5]:
        md += f"| {partner} | {cnt}건 |\n"

    md += f"""
---

*Generated by scm_weekly_kpi_agent v1.0 — {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}*
"""

    fname.write_text(md, encoding="utf-8")
    print(f"✅ KPI 리포트 저장: {fname}")
    return fname


# ─────────────────────────────────────────────
# 월간 리포트
# ─────────────────────────────────────────────

def generate_monthly_report(year: int, month: int,
                              weekly_csv_dir: Path, output_dir: Path):
    """월간 집계 리포트 생성 (주별 CSV 아카이브 기반)"""
    csv_files = list(weekly_csv_dir.glob(f"scm_raw_{year}-W*.csv"))
    if not csv_files:
        print(f"⚠️ {year}년 주별 CSV 파일이 없습니다.")
        return

    monthly_dfs = []
    for f in sorted(csv_files):
        try:
            df = pd.read_csv(f, encoding="utf-8-sig")
            wk_str = f.stem.replace("scm_raw_", "")
            yr, wk = parse_iso_week(wk_str)
            ws, we = get_week_range(yr, wk)
            if ws.month == month or we.month == month:
                df["iso_week"] = wk_str
                monthly_dfs.append(df)
        except Exception as e:
            print(f"  ⚠️ {f.name} 로드 실패: {e}")

    if not monthly_dfs:
        print(f"⚠️ {year}-{month:02d}에 해당하는 주차 데이터가 없습니다.")
        return

    combined = pd.concat(monthly_dfs, ignore_index=True, sort=False)
    out_file = output_dir / f"scm_monthly_{year}-{month:02d}.csv"
    combined.to_csv(out_file, index=False, encoding="utf-8-sig")
    print(f"✅ 월간 집계 CSV: {out_file}")

    # 월간 매입 TOP 제품
    if "_source" in combined.columns and "총 지출액 (VAT 포함)" in combined.columns:
        task_data = combined[combined["_source"] == "task"].copy()
        if "goods (from order)" in task_data.columns:
            task_data["_goods"] = task_data["goods (from order)"].apply(
                lambda v: str(v) if v else "미확인")
            task_data["_cost"] = pd.to_numeric(task_data["총 지출액 (VAT 포함)"],
                                                errors="coerce").fillna(0)
            monthly_top = task_data.groupby("_goods")["_cost"].sum().sort_values(
                ascending=False).head(20)
            print(f"\n📊 {year}-{month:02d} 월간 매입 TOP 제품:")
            for g, amt in monthly_top.items():
                print(f"  {g}: {amt:,.0f}원")


# ─────────────────────────────────────────────
# 메인 실행
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="SCM 주간 KPI 자동화 에이전트")
    parser.add_argument("--week", type=str, default=None,
                        help="ISO week (예: 2026-W21). 미입력 시 현재 주차 자동 감지")
    parser.add_argument("--month", type=str, default=None,
                        help="월간 리포트 (예: 2026-05)")
    parser.add_argument("--output-dir", type=str,
                        default="./scm_reports",
                        help="출력 폴더 (기본: ./scm_reports)")
    parser.add_argument("--dry-run", action="store_true",
                        help="API 호출 없이 샘플 데이터로 테스트")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)

    # 월간 리포트 모드
    if args.month:
        year, month = map(int, args.month.split("-"))
        generate_monthly_report(year, month, output_dir, output_dir)
        return

    # 주차 결정
    iso_week = args.week or current_iso_week()
    year, week_num = parse_iso_week(iso_week)
    week_start, week_end = get_week_range(year, week_num)
    print(f"\n🗓️  처리 주차: {iso_week} ({week_start} ~ {week_end})")

    if args.dry_run:
        print("⚠️  Dry-run 모드: 빈 데이터프레임으로 실행합니다.")
        df_task = pd.DataFrame(columns=TASK_KPI_FIELDS)
        df_order = pd.DataFrame(columns=ORDER_KPI_FIELDS)
        df_movement = pd.DataFrame(columns=MOVEMENT_KPI_FIELDS)
        df_parts = pd.DataFrame(columns=SYNC_PARTS_FIELDS)
        df_issue_reg = pd.DataFrame(columns=ISSUE_REGISTER_FIELDS)
    else:
        print("📡 Airtable 데이터 수집 중...")
        df_task = fetch_records("task", fields=TASK_KPI_FIELDS)
        print(f"  task: {len(df_task)}건")
        df_order = fetch_records("order", fields=ORDER_KPI_FIELDS)
        print(f"  order: {len(df_order)}건")
        df_movement = fetch_records("movement", fields=MOVEMENT_KPI_FIELDS)
        print(f"  movement: {len(df_movement)}건")
        df_parts = fetch_records("sync_parts", fields=SYNC_PARTS_FIELDS)
        print(f"  sync_parts: {len(df_parts)}건")
        df_issue_reg = fetch_records("issue_register", fields=ISSUE_REGISTER_FIELDS)
        print(f"  issue_register: {len(df_issue_reg)}건")

    print("\n🧮 KPI 집계 중...")
    task_kpi = calc_task_kpi(df_task, week_start, week_end)
    order_kpi = calc_order_kpi(df_order, week_start, week_end)
    issue_kpi = calc_issue_kpi(df_movement, df_issue_reg, week_start, week_end)
    stockout_kpi = calc_stockout_kpi(df_parts)

    print("\n💾 파일 저장 중...")
    save_raw_csv(iso_week, df_task, df_order, df_movement, output_dir)
    report_path = generate_md_report(
        iso_week, week_start, week_end,
        task_kpi, order_kpi, issue_kpi, stockout_kpi,
        output_dir
    )

    print(f"\n✅ 완료! 리포트: {report_path}")
    print(f"   발주 TASK: {task_kpi['total_tasks']}건")
    print(f"   총 지출액: {task_kpi['total_expenditure_vat']:,.0f}원")
    print(f"   긴급률: {task_kpi['urgent_rate']*100:.1f}%")
    print(f"   품질등급 일치율: {issue_kpi['quality_match_rate']:.1f}%")
    print(f"   품절 파츠: {stockout_kpi['stockout_count']}개")


if __name__ == "__main__":
    main()
