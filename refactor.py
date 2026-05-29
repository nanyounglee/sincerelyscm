import re

with open('scm_kpi_dashboard_v2.html', 'r', encoding='utf-8') as f:
    content = f.read()

# Replace cards in renderOrder
content = content.replace('<div class="card blue">\n    <div class="card-lbl">발주 TASK</div>', '<div class="card blue clickable" onclick="showTaskModal(\'주간 발주 TASK\', \'cur\')">\n    <div class="card-lbl">발주 TASK</div>')
content = content.replace('<div class="card green">\n    <div class="card-lbl">총 지출액(VAT포함)</div>', '<div class="card green clickable" onclick="showTaskModal(\'주간 발주(매입액 기준)\', \'cur\')">\n    <div class="card-lbl">총 지출액(VAT포함)</div>')
content = content.replace('<div class="card orange">\n    <div class="card-lbl">총 매출액</div>', '<div class="card orange clickable" onclick="showOrderModal(\'주간 매출액\', \'cur\')">\n    <div class="card-lbl">총 매출액</div>')
content = re.sub(r'<div class="card ([^"]+)">\n    <div class="card-lbl">원가율', r'<div class="card \1 clickable" onclick="showTaskModal(\'주간 발주\', \'cur\')">\n    <div class="card-lbl">원가율', content)

content = content.replace('<div class="card red">\n    <div class="card-lbl">긴급 발주</div>', '<div class="card red clickable" onclick="showTaskModal(\'주간 긴급 발주\', \'cur\', \'urgent\')">\n    <div class="card-lbl">긴급 발주</div>')
content = content.replace('<div class="card orange">\n    <div class="card-lbl">긴급률</div>', '<div class="card orange clickable" onclick="showTaskModal(\'주간 긴급 발주\', \'cur\', \'urgent\')">\n    <div class="card-lbl">긴급률</div>')
content = content.replace('<div class="card purple">\n    <div class="card-lbl">미입하 발생</div>', '<div class="card purple clickable" onclick="showTaskModal(\'주간 미입하 발생\', \'cur\', \'uninput\')">\n    <div class="card-lbl">미입하 발생</div>')
content = content.replace('<div class="card teal">\n    <div class="card-lbl">재제작/추가제작</div>', '<div class="card teal clickable" onclick="showTaskModal(\'주간 재제작/추가제작\', \'cur\', \'rework\')">\n    <div class="card-lbl">재제작/추가제작</div>')

# Table row replacement in renderOrder
content = content.replace('<td>${p.name}</td>', '<td class="td-clickable" onclick="showTaskModal(\'${p.name} 발주 상세\', \'cur\', \'partner\', \'${p.name}\')">${p.name}</td>')
content = content.replace('<td>${g.goods}</td>', '<td class="td-clickable" onclick="showOrderModal(\'${g.goods} 매출 상세\', \'cur\', \'${g.goods}\')">${g.goods}</td>')
content = content.replace('<span style="min-width:70px;font-weight:600;">${nm}</span>', '<span class="td-clickable" style="min-width:70px;font-weight:600;" onclick="showTaskModal(\'${nm} 발주 상세\', \'cur\', \'assignee\', \'${nm}\')">${nm}</span>')
content = content.replace('<td>${p.name}</td><td class="num">${fmtM(p.expCur)}</td><td style="font-size:10px;color:#6b7280;">${pt.goods_category||\'—\'}</td>', '<td class="td-clickable" onclick="showTaskModal(\'${p.name} 발주 상세\', \'cur\', \'partner\', \'${p.name}\')">${p.name}</td><td class="num">${fmtM(p.expCur)}</td><td style="font-size:10px;color:#6b7280;">${pt.goods_category||\'—\'}</td>')

# Issue KPI replacing
content = content.replace('<div class="card red">\n    <div class="card-lbl">총 이슈 건수 (주간)</div>', '<div class="card red clickable" onclick="showTaskModal(\'주간 전체 이슈\', \'cur\')">\n    <div class="card-lbl">총 이슈 건수 (주간)</div>')
content = content.replace('<div class="card red">\n    <div class="card-lbl">품절 파츠 수</div>', '<div class="card red clickable" onclick="showPartsModal(\'품절 파츠 목록\', \'outOfStock\')">\n    <div class="card-lbl">품절 파츠 수</div>')
content = content.replace('<div class="card orange">\n    <div class="card-lbl">품절위험 파츠</div>', '<div class="card orange clickable" onclick="showPartsModal(\'품절위험 파츠\', \'risky\')">\n    <div class="card-lbl">품절위험 파츠</div>')
content = content.replace('<div class="card blue">\n    <div class="card-lbl">미입하율</div>', '<div class="card blue clickable" onclick="showTaskModal(\'미입하 상세\', \'cur\', \'uninput\')">\n    <div class="card-lbl">미입하율</div>')

content = content.replace('<span style="min-width:80px;font-size:11px;">${nm}</span>', '<span class="td-clickable" style="min-width:80px;font-size:11px;" onclick="showTaskModal(\'${nm} 미입하 상세\', \'cur\', \'partner\', \'${nm}\')">${nm}</span>')

# CheckFinal replacing
content = content.replace('<div class="card blue">\n    <div class="card-lbl">주간 발주 TASK 총계</div>', '<div class="card blue clickable" onclick="showTaskModal(\'주간 발주 TASK\', \'cur\')">\n    <div class="card-lbl">주간 발주 TASK 총계</div>')
content = content.replace('<div class="card purple">\n    <div class="card-lbl">비스포크 건수</div>', '<div class="card purple clickable" onclick="showTaskModal(\'비스포크 상세\', \'cur\', \'bespoke\')">\n    <div class="card-lbl">비스포크 건수</div>')
content = content.replace('<div class="card orange">\n    <div class="card-lbl">비스포크 비율</div>', '<div class="card orange clickable" onclick="showTaskModal(\'비스포크 상세\', \'cur\', \'bespoke\')">\n    <div class="card-lbl">비스포크 비율</div>')

# Supply Chain replacing
content = content.replace('<td><strong>${s.name}</strong></td>', '<td class="td-clickable" onclick="showTaskModal(\'${s.name} 전체 발주\', \'all\', \'partner\', \'${s.name}\')"><strong>${s.name}</strong></td>')
content = content.replace('<td style="white-space:nowrap;max-width:130px;overflow:hidden;text-overflow:ellipsis;">${s.name}</td>', '<td class="td-clickable" style="white-space:nowrap;max-width:130px;overflow:hidden;text-overflow:ellipsis;" onclick="showTaskModal(\'${s.name} 전체 발주\', \'all\', \'partner\', \'${s.name}\')">${s.name}</td>')

# Update helper
helper = """window.showTaskModal = (label, wkMode, filterFnName, filterArg) => {
  let list = state.tasks;
  if(wkMode==='cur'){ list = weekSlice(state.tasks, state.week, F.taskDate); }
  else if(wkMode==='prev'){ list = weekSlice(state.tasks, prevWeek(state.week), F.taskDate); }
  else if(wkMode==='yoy'){ list = weekSlice(state.tasks, yoyWeek(state.week), F.taskDate); }
  // else if(wkMode==='all') list stays as state.tasks
"""
content = content.replace("window.showTaskModal = (label, wkMode, filterFnName, filterArg) => {\\n  let list = state.tasks;\\n  if(wkMode==='cur'){ list = weekSlice(state.tasks, state.week, F.taskDate); }\\n  else if(wkMode==='prev'){ list = weekSlice(state.tasks, prevWeek(state.week), F.taskDate); }\\n  else if(wkMode==='yoy'){ list = weekSlice(state.tasks, yoyWeek(state.week), F.taskDate); }", helper)

with open('scm_kpi_dashboard_v2.html', 'w', encoding='utf-8') as f:
    f.write(content)
