#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
每日便宜价检测生成器 · 个人投资组合监测
================================================
固定算法：对每只标的预设三档锚定价（extreme <= sweet <= fair），
拉取实时价后判定落在哪个区间，输出 Apple 风格网页 + 原始数据 JSON。

区间判定（越低越便宜，越低越好）：
  price <= extreme  -> 极度便宜（深度折价，强烈关注）
  price <= sweet    -> 甜区（便宜，可建仓）
  price <= fair     -> 合理（可小仓 / 观察）
  price >  fair     -> 偏贵 / 等待

数据来源（无需 API Key，服务器端可跑）：
  1) CNBC   JSON : quote.cnbc.com quote-html-webservice（优先，最稳）
  2) Nasdaq JSON : api.nasdaq.com/api/quote/<sym>/info（兜底）
抓取失败时沿用 cheap-data.json 中的上次有效价（首次运行用 FALLBACK）。

扩展方法：在 ASSETS 里加一项即可，网页与工作流无需改动。
"""

import json
import os
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta

# ---- 时区：北京（GMT+8） ----
BJ = timezone(timedelta(hours=8))

# ---- 锚定算法配置（便宜价三档锚定参数） ----
# stooq / yahoo 为不同数据源用的代码；extreme/sweet/fair 单位与 currency 一致。
ASSETS = [
    {
        "ticker": "SCHD",
        "name": "施瓦布美国股息 ETF · 防守档定投核心",
        "role": "防守",
        "currency": "$",
        "cnbc": "SCHD",
        "nasdaq_class": "etf",
        "extreme": 27.0,   # 极端便宜
        "sweet": 30.0,     # 甜区（29–30）
        "fair": 32.0,      # 合理（股息率≈3.3% 锚）
        "fair_note": "合理区间 ≤ $32（股息率约 3.3% 锚）",
        "note": "高股息宽基，防守档定投核心；按股息率 3.3% 反推便宜价。",
    },
    {
        "ticker": "BRK.B",
        "name": "伯克希尔·哈撒韦 B · 防守档压舱石",
        "role": "防守",
        "currency": "$",
        "cnbc": "BRK.B",
        "nasdaq_class": "stocks",
        "extreme": 450.0,  # 深度折价
        "sweet": 475.0,    # 甜区（465–475）
        "fair": 500.0,     # 合理（PB≈1.4，可建仓）
        "fair_note": "合理区间 $490–500（PB≈1.4，可建仓）",
        "note": "按账面价值 PB≈1.4 锚定；≤ $450 为深度折价，强烈关注。",
    },
]

# 首次运行（无任何历史数据）时的兜底价，保证页面永远能渲染。
FALLBACK = {"SCHD": 35.11, "BRK.B": 504.32}

DATA_JSON = "cheap-data.json"
OUT_HTML = "cheap-monitor.html"
UA = {"User-Agent": "Mozilla/5.0 (compatible; cheap-monitor/1.0)"}


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
    """按 CNBC -> Nasdaq 顺序抓取；都失败则回落到上次有效价。"""
    sym = asset["ticker"]
    attempts = [
        ("CNBC", fetch_cnbc, (asset["cnbc"],)),
        ("Nasdaq", fetch_nasdaq, (asset["ticker"], asset["nasdaq_class"])),
    ]
    for name, fn, args in attempts:
        try:
            p = fn(*args)
            if p and p > 0:
                log(f"{sym}: {name} 获取成功 = {p:.2f}")
                return p, name, True
        except Exception as e:
            log(f"{sym}: {name} 失败: {e}")
    # 全失败：沿用上次
    fb = last_good if last_good else FALLBACK.get(sym)
    if fb:
        log(f"{sym}: 数据源全部失败，沿用上次有效价 {fb:.2f}")
        return fb, "缓存", False
    return None, "无数据", False


def zone_of(price, a):
    if price <= a["extreme"]:
        return 0, "极度便宜", ("#047857", "#d1fae5", "#064e3b")
    if price <= a["sweet"]:
        return 1, "甜区", ("#0d9488", "#cffafe", "#155e75")
    if price <= a["fair"]:
        return 2, "合理", ("#d97706", "#fef3c7", "#b45309")
    return 3, "偏贵 / 等待", ("#9ca3af", "#f1f5f9", "#475569")


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


def card_html(a, price, src_ok, updated_iso):
    cur = a["currency"]
    level, zname, (zc, zbg, zfg) = zone_of(price, a)
    # 价格轴范围
    lo = a["extreme"] * 0.92
    hi = max(a["fair"] * 1.12, price * 1.04, a["fair"] * 1.05)
    p_ext = pct(a["extreme"], lo, hi)
    p_swe = pct(a["sweet"], lo, hi)
    p_fai = pct(a["fair"], lo, hi)
    p_cur = pct(price, lo, hi)

    seg_green = p_ext
    seg_teal = p_swe - p_ext
    seg_amber = p_fai - p_swe
    seg_gray = 100 - p_fai

    gap_txt = ""
    if level == 3:
        gap = price - a["fair"]
        gap_pct = gap / a["fair"] * 100
        gap_txt = (f"距合理上限 +{gap:.2f}（{gap_pct:+.1f}%），回到 "
                   f"{cur}{a['fair']:.0f} 再考虑")
    else:
        room = a[("extreme", "sweet", "fair")[level]] - price
        gap_txt = (f"距本档上沿还有 {cur}{room:.2f} 空间，"
                   f"{'已到底' if level == 0 else '可分批建仓'}")

    status_src = "实时" if src_ok else "缓存(数据源暂不可达)"

    return f"""
    <div class="monitor-card">
      <div class="mc-head">
        <div>
          <div class="mc-ticker">{a['ticker']}</div>
          <div class="mc-name">{a['name']}</div>
        </div>
        <span class="tag tag-{ 'defensive' if a['role']=='防守' else ('stable' if a['role']=='稳健' else 'aggressive') }">{a['role']}</span>
      </div>

      <div class="mc-price-row">
        <div class="mc-price">{cur}{price:,.2f}</div>
        <span class="zone-badge" style="background:{zbg};color:{zfg};border:1px solid {zc};">{zname}</span>
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
          <span style="left:{p_ext:.2f}%">极端 {cur}{a['extreme']:.0f}</span>
          <span style="left:{p_swe:.2f}%">甜区 {cur}{a['sweet']:.0f}</span>
          <span style="left:{p_fai:.2f}%">合理 {cur}{a['fair']:.0f}</span>
        </div>
      </div>

      <div class="mc-meta">
        <div class="mc-row"><span>合理锚定</span><b>{a['fair_note']}</b></div>
        <div class="mc-row"><span>研判</span><b>{a['note']}</b></div>
        <div class="mc-row"><span>信号解读</span><b>{gap_txt}</b></div>
        <div class="mc-row"><span>数据状态</span><b>{status_src}</b></div>
      </div>
    </div>
    """


def render(records, updated_iso):
    n_cheap = sum(1 for r in records if r["level"] <= 1)
    n_fair = sum(1 for r in records if r["level"] == 2)
    n_wait = sum(1 for r in records if r["level"] == 3)
    upd_bj = datetime.fromisoformat(updated_iso).strftime("%Y-%m-%d %H:%M 北京时间")

    cards = "\n".join(r["html"] for r in records)

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>每日便宜价检测 · 个人投资组合监测</title>
<link rel="stylesheet" href="assets/style.css">
<style>
  /* 监测页专属样式（复用全站设计系统变量） */
  .mc-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(360px,1fr)); gap:18px; }}
  .monitor-card {{ background:var(--paper); border:1px solid var(--line); border-radius:16px; padding:22px 24px; box-shadow:var(--shadow-sm); }}
  .mc-head {{ display:flex; align-items:flex-start; justify-content:space-between; gap:12px; margin-bottom:14px; }}
  .mc-ticker {{ font-size:22px; font-weight:700; font-family:"SF Mono",Menlo,Consolas,monospace; letter-spacing:-0.5px; }}
  .mc-name {{ font-size:13px; color:var(--ink-2); margin-top:2px; }}
  .mc-price-row {{ display:flex; align-items:center; justify-content:space-between; gap:12px; margin-bottom:16px; }}
  .mc-price {{ font-size:34px; font-weight:800; font-family:"SF Mono",Menlo,Consolas,monospace; letter-spacing:-1px; }}
  .zone-badge {{ font-size:13px; font-weight:700; padding:6px 14px; border-radius:999px; white-space:nowrap; }}
  .mc-bar-wrap {{ margin:6px 0 18px; }}
  .mc-bar {{ position:relative; display:flex; height:12px; border-radius:999px; overflow:hidden; background:var(--bg-soft2); }}
  .seg {{ height:100%; }}
  .cur-dot {{ position:absolute; top:50%; width:18px; height:18px; border-radius:50%; background:#fff; border:3px solid var(--ink); transform:translate(-50%,-50%); box-shadow:var(--shadow-sm); }}
  .mc-axis {{ position:relative; height:34px; margin-top:6px; }}
  .mc-axis span {{ position:absolute; transform:translateX(-50%); font-size:11px; color:var(--ink-3); white-space:nowrap; top:0; font-family:"SF Mono",Menlo,Consolas,monospace; }}
  .mc-axis span::before {{ content:""; position:absolute; top:-8px; left:50%; width:1px; height:6px; background:var(--line-2); }}
  .mc-meta {{ border-top:1px dashed var(--line); padding-top:12px; }}
  .mc-row {{ display:flex; justify-content:space-between; gap:14px; padding:6px 0; font-size:13px; border-bottom:1px dashed var(--line); }}
  .mc-row:last-child {{ border-bottom:none; }}
  .mc-row span {{ color:var(--ink-3); flex-shrink:0; }}
  .mc-row b {{ color:var(--ink); text-align:right; font-weight:600; }}
  .legend {{ display:flex; flex-wrap:wrap; gap:14px; margin:14px 0 4px; font-size:12.5px; color:var(--ink-2); }}
  .legend i {{ display:inline-block; width:11px; height:11px; border-radius:3px; margin-right:6px; vertical-align:middle; }}
  .updated {{ font-size:13px; color:var(--ink-3); font-family:"SF Mono",Menlo,Consolas,monospace; }}
  @media (max-width:760px){{ .mc-axis span{{ font-size:10px; }} .mc-price{{ font-size:28px; }} }}
  .standalone-head {{ background:rgba(251,250,246,0.92); backdrop-filter:saturate(180%) blur(12px); -webkit-backdrop-filter:saturate(180%) blur(12px); border-bottom:1px solid var(--line); padding:0 24px; position:sticky; top:0; z-index:100; }}
  .sh-inner {{ max-width:1240px; margin:0 auto; height:64px; display:flex; align-items:center; justify-content:space-between; gap:16px; flex-wrap:wrap; }}
  .sh-brand {{ font-weight:700; font-size:17px; letter-spacing:0.3px; display:flex; align-items:center; gap:9px; }}
  .sh-brand::before {{ content:""; width:10px; height:10px; border-radius:50%; background:linear-gradient(135deg,var(--aggressive) 0%,var(--accent) 100%); box-shadow:0 0 0 3px var(--accent-soft); display:inline-block; }}
  .sh-tag {{ font-size:12.5px; color:var(--ink-3); }}
</style>
</head>
<body>

<header class="standalone-head">
  <div class="sh-inner">
    <div class="sh-brand">每日便宜价检测</div>
    <div class="sh-tag">个人投资组合监测 · 固定算法自动盯盘</div>
  </div>
</header>

<main>
  <section class="hero">
    <div class="meta">每日自动检测 · 个人投资组合监测</div>
    <h1>每日便宜价检测</h1>
    <p class="hero-sub">固定算法自动盯盘：SCHD 与伯克希尔是否进入「便宜区」。低于锚定价才动手，不预测只应对。</p>
    <div class="updated">最后更新：{upd_bj}　|　刷新机制：GitHub Actions 每日北京时间 06:00 / 22:00 自动重算</div>
  </section>

  <section class="kpi-grid">
    <div class="kpi"><div class="kpi-label">便宜信号</div><div class="kpi-value" style="color:#047857">{n_cheap}</div><div class="kpi-sub">极度便宜 + 甜区</div></div>
    <div class="kpi"><div class="kpi-label">合理</div><div class="kpi-value" style="color:#d97706">{n_fair}</div><div class="kpi-sub">可小仓观察</div></div>
    <div class="kpi"><div class="kpi-label">偏贵等待</div><div class="kpi-value" style="color:#9ca3af">{n_wait}</div><div class="kpi-sub">未到击球区</div></div>
    <div class="kpi"><div class="kpi-label">监测标的</div><div class="kpi-value">{len(records)}</div><div class="kpi-sub">SCHD · BRK.B</div></div>
  </section>

  <div class="legend">
    <span><i style="background:#047857"></i>极度便宜（深度折价，强烈关注）</span>
    <span><i style="background:#0d9488"></i>甜区（便宜，可建仓）</span>
    <span><i style="background:#d97706"></i>合理（可小仓 / 观察）</span>
    <span><i style="background:#cbd5e1"></i>偏贵（等待，不追）</span>
  </div>

  <div class="mc-grid">
{cards}
  </div>

  <h2>算法说明（透明可复核）</h2>
  <div class="card">
    <div class="card-title">判定规则</div>
    <p style="margin:0 0 10px">每只标的预设三档锚定价（<b>极端 ≤ 甜区 ≤ 合理</b>），取实时价后：</p>
    <ul class="strategy-list">
      <li><b>价格 ≤ 极端</b> → 极度便宜：深度折价，强烈关注 / 可重仓。</li>
      <li><b>价格 ≤ 甜区</b> → 甜区：便宜，进入建仓区间，分批买入。</li>
      <li><b>价格 ≤ 合理</b> → 合理：估值合理，可小仓或继续观察。</li>
      <li><b>价格 &gt; 合理</b> → 偏贵 / 等待：未到击球区，不追高。</li>
    </ul>
    <p style="margin:12px 0 0;color:var(--ink-3);font-size:13px">数据来源：CNBC（优先）→ Nasdaq（兜底），无需 API Key。抓取失败时沿用上次有效价并标注「缓存」。锚定价为预设的主观便宜价，非投资建议；可随时在 <code>gen_cheap_monitor.py</code> 的 ASSETS 中调整或新增标的。</p>
  </div>
</main>

<footer>
  个人投资组合监测 · 固定算法自动盯盘，所有数据仅供参考，非投资建议。
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
            price = FALLBACK.get(sym, a["fair"])
            ok = False
            src = "兜底"
        level, zname, _ = zone_of(price, a)
        html = card_html(a, price, ok, updated.isoformat())
        records.append({
            "ticker": sym, "price": round(price, 2), "source": src,
            "live": ok, "level": level, "zone": zname, "html": html,
        })
        log(f"{sym}: 价 {price:.2f} 档={zname} 源={src}")

    out_html = render(records, updated.isoformat())
    with open(OUT_HTML, "w", encoding="utf-8") as f:
        f.write(out_html)

    out_data = {
        "updated": updated.isoformat(),
        "prices": {r["ticker"]: r["price"] for r in records},
        "detail": [
            {"ticker": r["ticker"], "price": r["price"], "zone": r["zone"],
             "level": r["level"], "source": r["source"], "live": r["live"]}
            for r in records
        ],
    }
    with open(DATA_JSON, "w", encoding="utf-8") as f:
        json.dump(out_data, f, ensure_ascii=False, indent=2)

    log(f"已生成 {OUT_HTML} 与 {DATA_JSON}")


if __name__ == "__main__":
    main()
