#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
保守仓定投参考 · 动态锚定生成器
================================
把「便宜价检测」升级为「定投参考」：价低多投、价高少投，锚定完全动态，
不写死任何美元价格。每日 GitHub Actions 自动重算。

两套内在逻辑（与 BTC 用 AHR999、纳指用 PE/DD 同一范式——一个实时便宜度指标 + 定投系数）：

1) SCHD（施瓦布美国股息 ETF）—— 股息率锚定
   - 历史（2012–2025）年化股息率中位数 = 3.16% 作为「合理收益率」。
   - 合理价   = TTM分红 / 3.16%
   - 甜区价   = TTM分红 / (3.16% + 0.30%)
   - 极度便宜 = TTM分红 / (3.16% + 0.70%)
   - 偏贵线   = TTM分红 / (3.16% - 0.30%)
   - 随分红每年增长，各档价自动抬高 → 长期可用、不会被价格写死。
   - 定投系数 = 当前股息率 / 合理收益率（价格越低→股息率越高→系数越大）。

2) BRK.B（伯克希尔 B）—— 市净率(P/B)锚定（巴菲特亲手定的估值框架）
   - 巴菲特历史上在 P/B ≤ 1.2 倍认定为「显著低估、大规模回购区」；
     1.4–1.5 倍为常态/乐观溢价。账面价值/股(BVPS)取最新季报。
   - 合理价   = 1.40 × BVPS
   - 甜区价   = 1.20 × BVPS
   - 极度便宜 = 1.00 × BVPS
   - 偏贵线   = 1.50 × BVPS
   - 随账面价值每季度增长，各档价自动抬高。
   - 定投系数 = 1.40 / 当前P/B（P/B越低→系数越大）。

数据来源（无需 API Key）：CNBC（优先）→ Nasdaq（兜底）。抓取失败沿用上次有效价。
"""

import json
import os
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta

BJ = timezone(timedelta(hours=8))

# ---------- SCHD 季度分红历史（除息日, 每股美元），用于 TTM 与历史收益率中位数 ----------
SCHD_DIV = [
    ("2012-03", 0.087), ("2012-06", 0.106), ("2012-09", 0.120), ("2012-12", 0.082),
    ("2013-03", 0.090), ("2013-06", 0.092), ("2013-09", 0.085), ("2013-12", 0.092),
    ("2014-03", 0.090), ("2014-06", 0.081), ("2014-09", 0.085), ("2014-12", 0.092),
    ("2015-03", 0.090), ("2015-06", 0.092), ("2015-09", 0.090), ("2015-12", 0.082),
    ("2016-03", 0.099), ("2016-06", 0.106), ("2016-09", 0.103), ("2016-12", 0.120),
    ("2017-03", 0.109), ("2017-06", 0.110), ("2017-09", 0.103), ("2017-12", 0.115),
    ("2018-03", 0.117), ("2018-06", 0.135), ("2018-09", 0.122), ("2018-12", 0.135),
    ("2019-03", 0.147), ("2019-06", 0.149), ("2019-09", 0.162), ("2019-12", 0.155),
    ("2020-03", 0.147), ("2020-06", 0.147), ("2020-09", 0.181), ("2020-12", 0.201),
    ("2021-03", 0.168), ("2021-06", 0.180), ("2021-09", 0.196), ("2021-12", 0.207),
    ("2022-03", 0.173), ("2022-06", 0.235), ("2022-09", 0.212), ("2022-12", 0.234),
    ("2023-03", 0.199), ("2023-06", 0.222), ("2023-09", 0.218), ("2023-12", 0.247),
    ("2024-03", 0.204), ("2024-06", 0.275), ("2024-09", 0.252), ("2024-12", 0.265),
    ("2025-03", 0.249), ("2025-06", 0.260), ("2025-09", 0.260), ("2025-12", 0.278),
    ("2026-03", 0.257), ("2026-06", 0.253),
]
SCHD_TTM = sum(a for _, a in SCHD_DIV[-4:])          # 近 4 季 = TTM 分红
SCHD_FAIR_YIELD = 0.0316                             # 2012–2025 年化收益率中位数（本地测算）

# ---------- BRK.B 账面价值/股（最新季报） ----------
BRKB_BVPS = 337.04                                   # 2026-06-30 季报，单位美元/股 B
BRKB_BVPS_ASOF = "2026-06-30"

ASSETS = [
    {
        "ticker": "SCHD",
        "name": "施瓦布美国股息 ETF · 防守档定投核心",
        "role": "防守",
        "currency": "$",
        "cnbc": "SCHD",
        "nasdaq_class": "etf",
        "metric": "yield",
        "metric_label": "股息率",
        "anchor_note": "合理收益率 = 2012–2025 历史中位数 3.16%；各档价 = TTM分红÷目标收益率，随分红自动抬高",
        "zone_fn": "schd",
    },
    {
        "ticker": "BRK.B",
        "name": "伯克希尔·哈撒韦 B · 防守档压舱石",
        "role": "防守",
        "currency": "$",
        "cnbc": "BRK.B",
        "nasdaq_class": "stocks",
        "metric": "pbr",
        "metric_label": "市净率 P/B",
        "anchor_note": f"锚定巴菲特框架：合理=1.40×BVPS、甜区=1.20×BVPS（显著低估回购区）、偏贵线=1.50×BVPS；BVPS={BRKB_BVPS}（{BRKB_BVPS_ASOF}）",
        "zone_fn": "brkb",
    },
]

FALLBACK = {"SCHD": 35.11, "BRK.B": 504.32}
DATA_JSON = "dca-data.json"
OUT_HTML = "dca.html"
UA = {"User-Agent": "Mozilla/5.0 (compatible; dca-monitor/1.0)"}


def log(msg):
    print(f"[{datetime.now(BJ).strftime('%H:%M:%S')}] {msg}", flush=True)


def fetch_cnbc(sym):
    url = ("https://quote.cnbc.com/quote-html-webservice/restQuote/symbolType/symbol"
           f"?symbols={sym}&requestMethod=itv&fund=1&exthrs=0&output=json")
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.loads(r.read().decode("utf-8", "ignore"))
    q = data["FormattedQuoteResult"]["FormattedQuote"][0]
    last = q.get("last")
    if not last:
        return None
    return float(str(last).replace("$", "").replace(",", "").strip())


def fetch_nasdaq(sym, assetclass):
    url = f"https://api.nasdaq.com/api/quote/{sym}/info?assetclass={assetclass}"
    hdrs = {**UA, "Accept": "application/json"}
    req = urllib.request.Request(url, headers=hdrs)
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.loads(r.read().decode("utf-8", "ignore"))
    price = data["data"]["primaryData"]["lastSalePrice"]
    return float(str(price).replace("$", "").replace(",", "").strip())


def fetch_price(asset, last_good):
    sym = asset["ticker"]
    for name, fn, args in [("CNBC", fetch_cnbc, (asset["cnbc"],)),
                            ("Nasdaq", fetch_nasdaq, (asset["ticker"], asset["nasdaq_class"]))]:
        try:
            p = fn(*args)
            if p and p > 0:
                log(f"{sym}: {name} 获取成功 = {p:.2f}")
                return p, name, True
        except Exception as e:
            log(f"{sym}: {name} 失败: {e}")
    fb = last_good if last_good else FALLBACK.get(sym)
    if fb:
        log(f"{sym}: 数据源全部失败，沿用上次有效价 {fb:.2f}")
        return fb, "缓存", False
    return None, "无数据", False


def compute_schd(price):
    fy = SCHD_FAIR_YIELD
    ttm = SCHD_TTM
    fair_p = ttm / fy
    sweet_p = ttm / (fy + 0.003)
    ext_p = ttm / (fy + 0.007)
    exp_p = ttm / (fy - 0.003)
    cur_yield = ttm / price
    cheap = cur_yield / fy
    if price <= ext_p:
        lvl, zone, mult = 0, "极度便宜", 2.0
    elif price <= sweet_p:
        lvl, zone, mult = 1, "甜区", 1.5
    elif price <= fair_p:
        lvl, zone, mult = 2, "合理", 1.0
    elif price <= exp_p:
        lvl, zone, mult = 3, "偏贵 / 等待", 0.6
    else:
        lvl, zone, mult = 4, "极贵 / 观望", 0.3
    return dict(lvl=lvl, zone=zone, mult=mult, ext_p=ext_p, sweet_p=sweet_p,
                fair_p=fair_p, exp_p=exp_p, metric_val=cur_yield, metric_pct=True,
                cheap=cheap, fair_ref=fy, anchor_extra=f"TTM分红 ${ttm:.3f}")


def compute_brkb(price):
    bvps = BRKB_BVPS
    ext_p = bvps * 1.0
    sweet_p = bvps * 1.2
    fair_p = bvps * 1.4
    exp_p = bvps * 1.5
    pbr = price / bvps
    cheap = 1.4 / pbr
    if pbr <= 1.0:
        lvl, zone, mult = 0, "极度便宜", 2.0
    elif pbr <= 1.2:
        lvl, zone, mult = 1, "甜区", 1.5
    elif pbr <= 1.4:
        lvl, zone, mult = 2, "合理", 1.0
    elif pbr <= 1.5:
        lvl, zone, mult = 3, "偏贵 / 等待", 0.6
    else:
        lvl, zone, mult = 4, "极贵 / 观望", 0.3
    return dict(lvl=lvl, zone=zone, mult=mult, ext_p=ext_p, sweet_p=sweet_p,
                fair_p=fair_p, exp_p=exp_p, metric_val=pbr, metric_pct=False,
                cheap=cheap, fair_ref=1.4, anchor_extra=f"BVPS ${bvps:.2f}（{BRKB_BVPS_ASOF}）")


def load_last():
    try:
        with open(DATA_JSON, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def pct(v, lo, hi):
    if hi <= lo:
        return 0.0
    return max(0.0, min(100.0, (v - lo) / (hi - lo) * 100.0))


ZONE_COLORS = [
    ("#047857", "#d1fae5", "#064e3b"),  # 极度便宜 绿
    ("#0d9488", "#cffafe", "#155e75"),  # 甜区 青
    ("#d97706", "#fef3c7", "#b45309"),  # 合理 琥珀
    ("#9ca3af", "#f1f5f9", "#475569"),  # 偏贵 灰
    ("#dc2626", "#fee2e2", "#7f1d1d"),  # 极贵 红
]


def card_html(a, price, src_ok, updated_iso):
    cur = a["currency"]
    c = compute_schd(price) if a["zone_fn"] == "schd" else compute_brkb(price)
    lvl, zone, mult = c["lvl"], c["zone"], c["mult"]
    zc, zbg, zfg = ZONE_COLORS[lvl]

    lo = c["ext_p"] * 0.92
    hi = max(c["fair_p"] * 1.12, c["exp_p"] * 1.05, price * 1.04)
    p_ext = pct(c["ext_p"], lo, hi)
    p_swe = pct(c["sweet_p"], lo, hi)
    p_fai = pct(c["fair_p"], lo, hi)
    p_exp = pct(c["exp_p"], lo, hi)
    p_cur = pct(price, lo, hi)

    seg_green = p_ext
    seg_teal = p_swe - p_ext
    seg_amber = p_fai - p_swe
    seg_gray = 100 - p_fai

    metric_txt = (f"{c['metric_val']*100:.2f}%" if c["metric_pct"]
                  else f"{c['metric_val']:.2f}×")
    fair_txt = (f"{c['fair_ref']*100:.2f}%" if c["metric_pct"] else f"{c['fair_ref']:.2f}×")
    cheap_txt = f"{c['cheap']:.2f}"

    # 信号文字
    if lvl <= 1:
        sig = f"价处{c['zone']}，本周按 <b>×{mult:.1f}</b> 加投"
    elif lvl == 2:
        sig = f"价处合理区，本周按基准 <b>×{mult:.1f}</b> 定投"
    elif lvl == 3:
        gap = (price - c["fair_p"]) / c["fair_p"] * 100
        sig = f"价高于合理线 {gap:+.1f}%，本周按 <b>×{mult:.1f}</b> 减量等待"
    else:
        sig = f"价显著偏贵，本周按 <b>×{mult:.1f}</b> 观望/极少投"

    status_src = "实时" if src_ok else "缓存(数据源暂不可达)"
    mult_color = "#047857" if mult >= 1.0 else ("#d97706" if mult >= 0.6 else "#dc2626")

    return f"""
    <div class="monitor-card">
      <div class="mc-head">
        <div>
          <div class="mc-ticker">{a['ticker']}</div>
          <div class="mc-name">{a['name']}</div>
        </div>
        <span class="tag tag-defensive">{a['role']}</span>
      </div>

      <div class="mc-price-row">
        <div class="mc-price">{cur}{price:,.2f}</div>
        <span class="zone-badge" style="background:{zbg};color:{zfg};border:1px solid {zc};">{zone}</span>
      </div>

      <div class="mc-mult-row">
        <div class="mc-mult-label">本周定投系数</div>
        <div class="mc-mult" style="color:{mult_color}">×{mult:.1f}</div>
        <div class="mc-mult-sub">便宜度 {cheap_txt} · {a['metric_label']} {metric_txt}（合理 {fair_txt}）</div>
      </div>

      <div class="mc-bar-wrap">
        <div class="mc-bar">
          <div class="seg" style="width:{seg_green:.2f}%;background:#047857;"></div>
          <div class="seg" style="width:{seg_teal:.2f}%;background:#0d9488;"></div>
          <div class="seg" style="width:{seg_amber:.2f}%;background:#d97706;"></div>
          <div class="seg" style="width:{seg_gray:.2f}%;background:#cbd5e1;"></div>
          <div class="cur-dot" style="left:{p_cur:.2f}%;"></div>
        </div>
        <div class="mc-axis">
          <span style="left:{p_ext:.2f}%">极度 {cur}{c['ext_p']:.0f}</span>
          <span style="left:{p_swe:.2f}%">甜区 {cur}{c['sweet_p']:.0f}</span>
          <span style="left:{p_fai:.2f}%">合理 {cur}{c['fair_p']:.0f}</span>
          <span style="left:{min(p_exp,99):.2f}%">偏贵 {cur}{c['exp_p']:.0f}</span>
        </div>
      </div>

      <div class="mc-meta">
        <div class="mc-row"><span>锚定逻辑</span><b>{a['anchor_note']}</b></div>
        <div class="mc-row"><span>信号解读</span><b>{sig}</b></div>
        <div class="mc-row"><span>数据状态</span><b>{status_src}</b></div>
      </div>
    </div>
    """


def render(records, updated_iso):
    schd = next(r for r in records if r["ticker"] == "SCHD")
    brkb = next(r for r in records if r["ticker"] == "BRK.B")
    cards = "\n".join(r["html"] for r in records)
    upd_bj = datetime.fromisoformat(updated_iso).strftime("%Y-%m-%d %H:%M 北京时间")

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>保守仓定投参考 · SCHD & BRK.B</title>
<link rel="stylesheet" href="assets/style.css">
<style>
  .mc-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(380px,1fr)); gap:18px; }}
  .monitor-card {{ background:var(--paper); border:1px solid var(--line); border-radius:16px; padding:22px 24px; box-shadow:var(--shadow-sm); }}
  .mc-head {{ display:flex; align-items:flex-start; justify-content:space-between; gap:12px; margin-bottom:14px; }}
  .mc-ticker {{ font-size:22px; font-weight:700; font-family:"SF Mono",Menlo,Consolas,monospace; letter-spacing:-0.5px; }}
  .mc-name {{ font-size:13px; color:var(--ink-2); margin-top:2px; }}
  .mc-price-row {{ display:flex; align-items:center; justify-content:space-between; gap:12px; margin-bottom:10px; }}
  .mc-price {{ font-size:34px; font-weight:800; font-family:"SF Mono",Menlo,Consolas,monospace; letter-spacing:-1px; }}
  .zone-badge {{ font-size:13px; font-weight:700; padding:6px 14px; border-radius:999px; white-space:nowrap; }}
  .mc-mult-row {{ display:flex; align-items:baseline; gap:12px; flex-wrap:wrap; background:var(--bg-soft2); border-radius:12px; padding:12px 14px; margin-bottom:14px; }}
  .mc-mult-label {{ font-size:13px; color:var(--ink-3); }}
  .mc-mult {{ font-size:30px; font-weight:800; font-family:"SF Mono",Menlo,Consolas,monospace; }}
  .mc-mult-sub {{ font-size:12px; color:var(--ink-3); }}
  .mc-bar-wrap {{ margin:6px 0 14px; }}
  .mc-bar {{ position:relative; display:flex; height:12px; border-radius:999px; overflow:hidden; background:var(--bg-soft2); }}
  .seg {{ height:100%; }}
  .cur-dot {{ position:absolute; top:50%; width:18px; height:18px; border-radius:50%; background:#fff; border:3px solid var(--ink); transform:translate(-50%,-50%); box-shadow:var(--shadow-sm); }}
  .mc-axis {{ position:relative; height:34px; margin-top:6px; }}
  .mc-axis span {{ position:absolute; transform:translateX(-50%); font-size:11px; color:var(--ink-3); white-space:nowrap; top:0; font-family:"SF Mono",Menlo,Consolas,monospace; }}
  .mc-axis span::before {{ content:""; position:absolute; top:-8px; left:50%; width:1px; height:6px; background:var(--line-2); }}
  .mc-meta {{ border-top:1px dashed var(--line); padding-top:10px; }}
  .mc-row {{ display:flex; justify-content:space-between; gap:14px; padding:6px 0; font-size:13px; border-bottom:1px dashed var(--line); }}
  .mc-row:last-child {{ border-bottom:none; }}
  .mc-row span {{ color:var(--ink-3); flex-shrink:0; }}
  .mc-row b {{ color:var(--ink); text-align:right; font-weight:600; }}
  .legend {{ display:flex; flex-wrap:wrap; gap:14px; margin:14px 0 4px; font-size:12.5px; color:var(--ink-2); }}
  .legend i {{ display:inline-block; width:11px; height:11px; border-radius:3px; margin-right:6px; vertical-align:middle; }}
  .standalone-head {{ background:rgba(251,250,246,0.92); backdrop-filter:saturate(180%) blur(12px); -webkit-backdrop-filter:saturate(180%) blur(12px); border-bottom:1px solid var(--line); padding:0 24px; position:sticky; top:0; z-index:100; }}
  .sh-inner {{ max-width:1240px; margin:0 auto; height:64px; display:flex; align-items:center; justify-content:space-between; gap:16px; flex-wrap:wrap; }}
  .sh-brand {{ font-weight:700; font-size:17px; letter-spacing:0.3px; display:flex; align-items:center; gap:9px; }}
  .sh-brand::before {{ content:""; width:10px; height:10px; border-radius:50%; background:linear-gradient(135deg,var(--aggressive) 0%,var(--accent) 100%); box-shadow:0 0 0 3px var(--accent-soft); display:inline-block; }}
  .sh-tag {{ font-size:12.5px; color:var(--ink-3); }}
  @media (max-width:760px){{ .mc-axis span{{ font-size:10px; }} .mc-price{{ font-size:28px; }} .mc-mult{{ font-size:24px; }} }}
</style>
</head>
<body>

<header class="standalone-head">
  <div class="sh-inner">
    <div class="sh-brand">保守仓定投参考</div>
    <div class="sh-tag">SCHD · BRK.B · 价低多投 / 价高少投 · 动态锚定</div>
  </div>
</header>

<main>
  <section class="hero">
    <div class="meta">防守档定投 · 不傻定投 · 锚定随基本面自动调整</div>
    <h1>保守仓定投参考</h1>
    <p class="hero-sub">用「实时便宜度指标 + 定投系数」替代瞎定投：SCHD 看股息率（历史中位数锚），
    BRK.B 看市净率（巴菲特 P/B 框架锚）。价格越低→指标越便宜→本周定投系数越大。所有锚定价由
    分红 / 账面价值动态推导，不写死任何美元价，可长期用。</p>
    <div class="updated">最后更新：{upd_bj}　|　刷新机制：GitHub Actions 每日北京时间 06:00 / 22:00 自动重算</div>
  </section>

  <section class="kpi-grid">
    <div class="kpi"><div class="kpi-label">SCHD 本周系数</div><div class="kpi-value" style="color:{'#047857' if schd['mult']>=1 else '#d97706'}">×{schd['mult']:.1f}</div><div class="kpi-sub">{schd['zone']}</div></div>
    <div class="kpi"><div class="kpi-label">BRK.B 本周系数</div><div class="kpi-value" style="color:{'#047857' if brkb['mult']>=1 else '#d97706'}">×{brkb['mult']:.1f}</div><div class="kpi-sub">{brkb['zone']}</div></div>
    <div class="kpi"><div class="kpi-label">SCHD 股息率</div><div class="kpi-value">{schd['metric']*100:.2f}%</div><div class="kpi-sub">合理 3.16%</div></div>
    <div class="kpi"><div class="kpi-label">BRK.B 市净率</div><div class="kpi-value">{brkb['metric']:.2f}×</div><div class="kpi-sub">合理 1.40×</div></div>
  </section>

  <div class="legend">
    <span><i style="background:#047857"></i>极度便宜（×2.0 重投）</span>
    <span><i style="background:#0d9488"></i>甜区（×1.5 加投）</span>
    <span><i style="background:#d97706"></i>合理（×1.0 基准）</span>
    <span><i style="background:#9ca3af"></i>偏贵（×0.6 减量）</span>
    <span><i style="background:#dc2626"></i>极贵（×0.3 观望）</span>
  </div>

  <div class="mc-grid">
{cards}
  </div>

  <h2>锚定逻辑（透明可复核）</h2>
  <div class="card">
    <div class="card-title">两套内在逻辑</div>
    <p style="margin:0 0 10px"><b>SCHD — 股息率锚定</b>：合理收益率取 2012–2025 年化股息率中位数 <b>3.16%</b>。
    各档价 = TTM分红 ÷ 目标收益率（合理 3.16% / 甜区 3.46% / 极度便宜 3.86% / 偏贵线 2.86%）。
    因 SCHD 分红逐年增长，各档价会<b>自动抬高</b>，不会像固定价那样越往后越「假贵」。</p>
    <p style="margin:0 0 10px"><b>BRK.B — 市净率(P/B)锚定</b>：采用巴菲特亲手定的估值框架——P/B ≤ 1.2 倍为其认定的
    「显著低估、大规模回购区」，1.4–1.5 倍为常态/乐观溢价。各档价 = 倍数 × 账面价值/股（当前 ${BRKB_BVPS}/股，{BRKB_BVPS_ASOF}）。
    账面价值每季度增长，各档价同样自动抬高。</p>
    <p style="margin:12px 0 0;color:var(--ink-3);font-size:13px">定投系数规则：极度便宜 ×2.0｜甜区 ×1.5｜合理 ×1.0｜偏贵 ×0.6｜极贵 ×0.3。
    便宜度 = 当前指标 ÷ 合理指标（SCHD=股息率比；BRK.B=1.40÷P/B）。数据来源 CNBC（优先）→ Nasdaq（兜底）。
    锚定为客观便宜度参考，非投资建议；分红/BVPS 每季度复核一次即可。</p>
  </div>
</main>

<footer>
  保守仓定投参考 · 动态锚定自动重算，所有数据仅供参考，非投资建议。
</footer>

</body>
</html>
"""


def main():
    last = load_last()
    last_prices = last.get("prices", {}) if isinstance(last, dict) else {}
    updated = datetime.now(BJ)
    records = []

    for a in ASSETS:
        sym = a["ticker"]
        last_good = last_prices.get(sym)
        price, src, ok = fetch_price(a, last_good)
        if price is None:
            price = FALLBACK.get(sym, 0)
            ok = False
            src = "兜底"
        c = compute_schd(price) if a["zone_fn"] == "schd" else compute_brkb(price)
        html = card_html(a, price, ok, updated.isoformat())
        records.append({
            "ticker": sym, "price": round(price, 2), "source": src, "live": ok,
            "level": c["lvl"], "zone": c["zone"], "mult": c["mult"],
            "metric": round(c["metric_val"], 4), "html": html,
        })
        log(f"{sym}: 价 {price:.2f} 档={c['zone']} 系数×{c['mult']:.1f} 源={src}")

    out_html = render(records, updated.isoformat())
    with open(OUT_HTML, "w", encoding="utf-8") as f:
        f.write(out_html)
    out_data = {
        "updated": updated.isoformat(),
        "prices": {r["ticker"]: r["price"] for r in records},
        "detail": [
            {"ticker": r["ticker"], "price": r["price"], "zone": r["zone"],
             "level": r["level"], "mult": r["mult"], "metric": r["metric"],
             "source": r["source"], "live": r["live"]}
            for r in records
        ],
    }
    with open(DATA_JSON, "w", encoding="utf-8") as f:
        json.dump(out_data, f, ensure_ascii=False, indent=2)
    log(f"已生成 {OUT_HTML} 与 {DATA_JSON}")


if __name__ == "__main__":
    main()
