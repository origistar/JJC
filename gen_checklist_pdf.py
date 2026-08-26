# -*- coding: utf-8 -*-
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                TableStyle)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

pdfmetrics.registerFont(TTFont('YaHei', 'C:/Windows/Fonts/msyh.ttc', subfontIndex=0))
pdfmetrics.registerFont(TTFont('YaHei-Bold', 'C:/Windows/Fonts/msyhbd.ttc', subfontIndex=0))

INK = colors.HexColor('#10151A')
GREY = colors.HexColor('#3C4950')
ACCENT = colors.HexColor('#C2410C')
SOFT = colors.HexColor('#EAF1F5')
LINE = colors.HexColor('#D4CFBF')

title = ParagraphStyle('t', fontName='YaHei-Bold', fontSize=22, textColor=INK, spaceAfter=3, leading=26)
sub = ParagraphStyle('s', fontName='YaHei', fontSize=11, textColor=GREY, spaceAfter=10, leading=15)
h = ParagraphStyle('h', fontName='YaHei-Bold', fontSize=14, textColor=ACCENT, spaceBefore=12, spaceAfter=6, leading=18)
body = ParagraphStyle('b', fontName='YaHei', fontSize=11, textColor=INK, leading=16, spaceAfter=4)
small = ParagraphStyle('sm', fontName='YaHei', fontSize=10, textColor=INK, leading=14)
warn = ParagraphStyle('w', fontName='YaHei-Bold', fontSize=11, textColor=ACCENT, leading=16)
foot = ParagraphStyle('f', fontName='YaHei', fontSize=9, textColor=GREY, leading=13)

doc = SimpleDocTemplate('D:/workbuddy/金建成/建仓五问清单卡.pdf', pagesize=A4,
    leftMargin=16*mm, rightMargin=16*mm, topMargin=16*mm, bottomMargin=16*mm,
    title='建仓五问清单卡')
flow = []

flow.append(Paragraph('建仓五问 · 决策清单', title))
flow.append(Paragraph('玑哥 × 老雷 双专家方法论 · 买每只新股前照填 · 数据截至 2026-08', sub))

flow.append(Paragraph('第〇关 · 资格门槛（答不上 = 不买）', h))
for t in ['懂不懂：在不在能力圈？看懂了没？连这门生意怎么赚钱都没搞明白，一毛都别投',
          '定价权：是不是第一兼唯一？话语权不在手里 → 完全不能碰',
          '财报：只有财报好的公司才是好公司']:
    flow.append(Paragraph('• ' + t, body))

flow.append(Paragraph('五问要点', h))
qa = [
    ('① 为什么买', '行业第一/双寡头？护城河 10–20 年难破？财报稳？一句话说清“凭什么赢”'),
    ('② 买多少', '单票 ≤ 15–20%；首笔 3–4 成金字塔；先有宽基底仓；债股 1:1 对冲'),
    ('③ 什么价买', '等像样回调；好公司出问题时；VX 高时建仓；分 3–5 批金字塔'),
    ('④ 什么价卖', '止盈：达节点/负成本/价涨估值同涨必减；止损：逻辑破就走'),
    ('⑤ 目标', '预期收益？周期 3–5–10 年？认错离场条件？'),
]
data = [[Paragraph('<b>' + q + '</b>', small), Paragraph(a, small)] for q, a in qa]
tbl = Table(data, colWidths=[30*mm, 132*mm])
tbl.setStyle(TableStyle([
    ('FONTNAME', (0, 0), (-1, -1), 'YaHei'),
    ('FONTSIZE', (0, 0), (-1, -1), 10),
    ('TEXTCOLOR', (0, 0), (-1, -1), INK),
    ('VALIGN', (0, 0), (-1, -1), 'TOP'),
    ('ROWBACKGROUNDS', (0, 0), (-1, -1), [colors.white, SOFT]),
    ('GRID', (0, 0), (-1, -1), 0.5, LINE),
    ('LEFTPADDING', (0, 0), (-1, -1), 6), ('RIGHTPADDING', (0, 0), (-1, -1), 6),
    ('TOPPADDING', (0, 0), (-1, -1), 5), ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
]))
flow.append(tbl)

flow.append(Paragraph('⚠️ 止盈触发清单（你的 A杀痛点 · 到了就动）', h))
checklist = (
    '标的：__________  建仓价：____  当前价：____  浮盈：____%\n\n'
    '□ 收益 ≥ 30%        → 减 __%（落袋第一笔）\n'
    '□ 收益 ≥ 60%        → 减 __%\n'
    '□ 收益 ≥ 100%       → 减 __%（留底仓吃长线）\n'
    '□ PE 历史分位超 80% → 减 __%\n'
    '□ 价涨 + 估值同涨（背离消失）→ 减 __%（老雷警报）\n'
    '□ 单票仓位因上涨超上限（如超 25%）→ 减回上限\n'
    '□ 周围人都在聊它（FOMO 顶峰）→ 减 __%\n\n'
    '★ 负成本目标：减出总额超本金 → 成本转负，剩余仓位涨跌随意。\n'
    '★ 铁律：节点提前定，到了就执行，不许临场“再等等”。'
)
flow.append(Paragraph(checklist.replace('\n', '<br/>'), body))

flow.append(Paragraph('五条止盈铁律', h))
for t in ['浮盈是纸，落袋才是钱：到节点就减，不问还会不会涨',
          '阶梯式分批减，永远留底仓：涨 30% 减一批、翻倍再减，A杀回来利润已锁',
          '负成本 = 终极防A杀盾（玑哥）：减出金额超本金，成本转负，后面永不亏',
          '估值背离警报（老雷）：价涨 PE 同涨必跌回，是减的信号不是贪的信号',
          '锚定了结利润不是卖最高：成本不动只了结利润，一年几次、每次 20–30% 就够']:
    flow.append(Paragraph('• ' + t, body))

flow.append(Paragraph('双专家共识', h))
for t in ['永不杠杆', '先活下来', '只买懂的、有定价权的', '不追高、等节点', '不预测只应对']:
    flow.append(Paragraph('• ' + t, body))

flow.append(Spacer(1, 10))
flow.append(Paragraph('利润不是你的，直到你把它卖掉。', warn))
flow.append(Spacer(1, 4))
flow.append(Paragraph('风险提示：以上仅为对玑哥/老雷公开观点的梳理，仅供参考，不构成任何投资建议。股市有风险，投资需谨慎。', foot))

doc.build(flow)
print('PDF_OK')
