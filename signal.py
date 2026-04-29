"""
CryptoPilot AI — Cloud Runner (GitHub Actions version)
=======================================================
Runs on GitHub Actions free tier — 00:00 UTC = 08:00 SGT daily
All 8 coins tracked with correct Singapore time display
"""

import os
import json
import time
import requests
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ── Singapore timezone ──────────────────────────────────────────────────
SGT = timezone(timedelta(hours=8))

def now_sgt():
    return datetime.now(SGT)

# ── Config ──────────────────────────────────────────────────────────────
CFG_PATH = Path(__file__).parent / "config.json"

def load_config():
    if CFG_PATH.exists():
        try:
            return json.loads(CFG_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"bot_token": "", "chat_id": ""}

cfg       = load_config()
BOT_TOKEN = os.environ.get("BOT_TOKEN") or cfg.get("bot_token", "")
CHAT_ID   = os.environ.get("CHAT_ID")   or cfg.get("chat_id", "")

# ── Ivan's complete portfolio ───────────────────────────────────────────
PORTFOLIO = {
    "ETH":  {"qty": 4.6063,       "avg_cost_sgd": 4672.35, "stop": 2280.0,    "trim": 3750.0,    "tier": "large"},
    "XRP":  {"qty": 5797.74,      "avg_cost_sgd": 2.80,    "stop": 1.42,      "trim": 2.65,      "tier": "large"},
    "NEAR": {"qty": 3306.68,      "avg_cost_sgd": 8.01,    "stop": 1.45,      "trim": 2.80,      "tier": "mid"},
    "DOGE": {"qty": 44345.5,      "avg_cost_sgd": 0.1645,  "stop": 0.092,     "trim": 0.195,     "tier": "mid"},
    "ADA":  {"qty": 5461.4,       "avg_cost_sgd": 0.6466,  "stop": 0.235,     "trim": 0.48,      "tier": "mid"},
    "USDT": {"qty": 4753.4,       "avg_cost_sgd": 1.27,    "stop": None,      "trim": None,      "tier": "stable"},
    "TRUMP":{"qty": 26.84,        "avg_cost_sgd": 2.80,    "stop": 2.50,      "trim": 5.00,      "tier": "micro"},
    "SHIB": {"qty": 11614382.62,  "avg_cost_sgd": 0.000035,"stop": 0.0000055, "trim": 0.000015,  "tier": "micro"},
}

COINGECKO_IDS = {
    "ETH":   "ethereum",
    "XRP":   "ripple",
    "NEAR":  "near",
    "DOGE":  "dogecoin",
    "ADA":   "cardano",
    "BTC":   "bitcoin",
    "TRUMP": "official-trump",
    "SHIB":  "shiba-inu",
}

REGIME_EMOJI = {
    "expansion": "🟢", "caution": "🟡",
    "contraction": "🔴", "recovery": "🔵",
}

# ── HTTP helper ─────────────────────────────────────────────────────────
def get(url, params=None, delay=1.2):
    time.sleep(delay)
    try:
        r = requests.get(url, params=params or {}, timeout=15,
                         headers={"User-Agent": "CryptoPilotAI/2.0"})
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"  [warn] {url.split('/')[2]}: {e}")
        return None

def tg(text):
    if not BOT_TOKEN or not CHAT_ID:
        print("  [warn] No Telegram config")
        return False
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": text,
                  "parse_mode": "HTML",
                  "disable_web_page_preview": True},
            timeout=15,
        )
        ok = r.json().get("ok", False)
        print(f"  Telegram: {'✅ sent' if ok else '❌ ' + str(r.json().get('description'))}")
        return ok
    except Exception as e:
        print(f"  [error] Telegram: {e}")
        return False

# ── Data fetchers ────────────────────────────────────────────────────────
def fetch_prices():
    ids  = ",".join(COINGECKO_IDS.values())
    data = get("https://api.coingecko.com/api/v3/simple/price", {
        "ids": ids, "vs_currencies": "usd,sgd",
        "include_24hr_change": "true",
        "include_7d_change":   "true",
    })
    if not data:
        return {}
    out = {}
    for ticker, cg_id in COINGECKO_IDS.items():
        if cg_id in data:
            d = data[cg_id]
            out[ticker] = {
                "price_sgd":  d.get("sgd", 0),
                "change_24h": d.get("usd_24h_change", 0),
                "change_7d":  d.get("usd_7d_change", 0),
            }
        else:
            print(f"  [warn] {ticker} not in price response")
    return out

def fetch_fear_greed():
    data = get("https://api.alternative.me/fng/?limit=7&format=json")
    if not data or "data" not in data:
        return None
    items = data["data"]
    vals  = [int(x["value"]) for x in items]
    return {
        "today":   vals[0],
        "7d_avg":  round(sum(vals)/len(vals), 1),
        "label":   items[0]["value_classification"],
        "trend":   "improving" if vals[0] > vals[1] else "worsening",
        "momentum":vals[0] - vals[6],
    }

def fetch_global():
    data = get("https://api.coingecko.com/api/v3/global")
    if not data:
        return None
    d  = data.get("data", {})
    mp = d.get("market_cap_percentage", {})
    return {
        "btc_dominance":    round(mp.get("btc", 0), 2),
        "market_cap_change":round(d.get("market_cap_change_percentage_24h_usd", 0), 2),
    }

def fetch_funding():
    rates = {}
    for coin, sym in [("BTC","BTCUSDT"),("ETH","ETHUSDT")]:
        d = get("https://fapi.binance.com/fapi/v1/premiumIndex",
                {"symbol": sym}, delay=0.4)
        if d:
            rates[coin] = float(d.get("lastFundingRate", 0))
    return rates

# ── Regime classifier ────────────────────────────────────────────────────
def compute_regime(prices, fg, glb, funding):
    votes = {"expansion":0.0,"caution":0.0,"contraction":0.0,"recovery":0.0}

    if fg:
        fgv = fg["today"]
        if fgv >= 75:    votes["caution"]     += 2.0
        elif fgv >= 55:  votes["expansion"]   += 2.0
        elif fgv >= 40:  votes["expansion"]   += 1.0
        elif fgv >= 25:  votes["caution"]     += 1.5
        elif fgv >= 15:  votes["contraction"] += 2.0
        else:            votes["contraction"] += 3.0
        mom = fg.get("momentum", 0)
        if mom > 10:     votes["expansion"]   += 0.5
        elif mom < -10:  votes["contraction"] += 0.5

    if glb:
        dom = glb["btc_dominance"]
        if dom >= 62:    votes["contraction"] += 1.5
        elif dom >= 57:  votes["caution"]     += 1.5
        elif dom >= 46:  votes["expansion"]   += 1.0
        else:            votes["expansion"]   += 1.5

    if prices:
        btc_24h = prices.get("BTC",{}).get("change_24h",0)
        btc_7d  = prices.get("BTC",{}).get("change_7d",0)
        if btc_24h >= 5:    votes["expansion"]   += 1.5
        elif btc_24h >= 2:  votes["expansion"]   += 0.8
        elif btc_24h >= -3: votes["caution"]     += 0.8
        else:               votes["contraction"] += 1.5
        if btc_7d >= 10:    votes["expansion"]   += 1.5
        elif btc_7d >= 3:   votes["expansion"]   += 0.8
        elif btc_7d >= -10: votes["contraction"] += 1.0
        else:               votes["contraction"] += 1.5

    if funding:
        avg_fr = sum(funding.values()) / max(len(funding),1)
        if avg_fr > 0.0015:  votes["caution"]   += 1.0
        elif avg_fr < -0.0005: votes["recovery"] += 1.0

    if glb:
        mc = glb["market_cap_change"]
        if mc >= 3:    votes["expansion"]   += 1.0
        elif mc >= -3: votes["caution"]     += 0.3
        else:          votes["contraction"] += 1.0

    regime = max(votes, key=votes.get)
    total  = sum(votes.values())
    conf   = round(votes[regime]/total*100) if total > 0 else 50
    if conf < 45:
        regime = "caution"
        conf   = 45
    return regime, conf

# ── Coin scorer ──────────────────────────────────────────────────────────
def score_bar(score):
    filled = round(score / 10)
    return "█" * filled + "░" * (10 - filled)

def score_coin(ticker, pos, prices, fg, regime):
    if pos["tier"] == "stable":
        return None
    price_sgd  = prices.get(ticker, {}).get("price_sgd", 0)
    change_24h = prices.get(ticker, {}).get("change_24h", 0)
    change_7d  = prices.get(ticker, {}).get("change_7d", 0)
    if price_sgd <= 0:
        return None

    avg_cost = pos["avg_cost_sgd"]
    pnl_pct  = (price_sgd - avg_cost) / avg_cost * 100

    # Momentum (25%)
    mom = 50.0
    if change_7d >= 15:    mom = 82
    elif change_7d >= 7:   mom = 70
    elif change_7d >= 2:   mom = 60
    elif change_7d >= -2:  mom = 48
    elif change_7d >= -8:  mom = 35
    else:                  mom = 18
    mom = max(5, min(95, mom + change_24h * 0.5))

    # Cost basis (30%)
    if pnl_pct >= 50:    cb = 78
    elif pnl_pct >= 20:  cb = 65
    elif pnl_pct >= 0:   cb = 55
    elif pnl_pct >= -20: cb = 42
    elif pnl_pct >= -40: cb = 30
    elif pnl_pct >= -60: cb = 20
    elif pnl_pct >= -80: cb = 12
    else:                cb = 6

    # Sentiment (20%)
    fg_val = fg["today"] if fg else 50
    if fg_val >= 80:    sa = 25
    elif fg_val >= 65:  sa = 40
    elif fg_val >= 45:  sa = 58
    elif fg_val >= 30:  sa = 52
    else:               sa = 42

    # Stop distance (15%)
    stop = pos.get("stop")
    if stop and price_sgd > 0:
        pct = (price_sgd - stop) / stop * 100
        if pct >= 30:  sl = 70
        elif pct >= 15:sl = 60
        elif pct >= 8: sl = 50
        elif pct >= 3: sl = 35
        elif pct >= 0: sl = 20
        else:          sl = 5
    else:
        sl = 55

    # Liquidity (10%)
    liq = 55

    raw  = mom*0.25 + cb*0.30 + sa*0.20 + sl*0.15 + liq*0.10
    MULT = {
        "expansion":  {"large":1.10,"mid":1.05,"micro":1.0},
        "caution":    {"large":0.92,"mid":0.78,"micro":0.65},
        "contraction":{"large":0.80,"mid":0.62,"micro":0.50},
        "recovery":   {"large":1.05,"mid":0.90,"micro":0.80},
    }
    mult  = MULT.get(regime,{}).get(pos["tier"],1.0)
    score = round(max(3, min(97, raw*mult)), 1)

    if score >= 72:    action = "ACCUMULATE"
    elif score >= 56:  action = "HOLD"
    elif score >= 42:  action = "WATCH"
    elif score >= 27:  action = "TRIM"
    else:              action = "DE-RISK"

    ACTION_E = {"ACCUMULATE":"🟢","HOLD":"🔵","WATCH":"🟡","TRIM":"🟠","DE-RISK":"🔴"}

    return {
        "ticker":   ticker,
        "score":    score,
        "action":   action,
        "emoji":    ACTION_E[action],
        "pnl_pct":  round(pnl_pct, 1),
        "price":    price_sgd,
        "chg_24h":  round(change_24h, 1),
        "chg_7d":   round(change_7d, 1),
        "stop":     pos.get("stop"),
        "trim":     pos.get("trim"),
        "bar":      score_bar(score),
    }

# ── Portfolio valuation ──────────────────────────────────────────────────
def value_portfolio(prices):
    total, usdt_val = 0.0, 0.0
    holdings, alerts = [], []

    for ticker, pos in PORTFOLIO.items():
        qty   = pos["qty"]
        price = prices.get(ticker,{}).get("price_sgd",0) if ticker!="USDT" else 1.27
        chg   = prices.get(ticker,{}).get("change_24h",0) if ticker!="USDT" else 0
        val   = qty * price
        total += val
        if ticker == "USDT":
            usdt_val = val
            continue

        cost = qty * pos["avg_cost_sgd"]
        pnl  = (val-cost)/cost*100 if cost > 0 else 0
        holdings.append({"ticker":ticker,"price":price,"val":val,"chg":chg,"pnl":pnl})

        stop = pos.get("stop")
        trim = pos.get("trim")
        if stop and price > 0:
            pct = (price-stop)/stop*100
            if price <= stop:
                alerts.append(f"🚨 STOP-LOSS: {ticker} S${price:.4f} BELOW S${stop:.4f} — SELL NOW")
            elif pct < 5:
                alerts.append(f"⚠️ NEAR STOP: {ticker} S${price:.4f} only {pct:.1f}% above stop S${stop:.4f}")
        if trim and price >= trim:
            alerts.append(f"✅ TRIM TARGET: {ticker} S${price:.4f} reached S${trim:.4f}")

    usdt_pct = round(usdt_val/total*100,1) if total > 0 else 0
    return round(total,2), usdt_pct, holdings, alerts

# ── Message builder ──────────────────────────────────────────────────────
def build_message(regime, conf, fg, glb, funding, signals,
                  total, usdt_pct, alerts):

    r_e  = REGIME_EMOJI.get(regime,"⚪")
    # ── CORRECT SINGAPORE TIME ──────────────────────────────────────────
    now  = now_sgt().strftime("%a %d %b %Y, %H:%M SGT")
    # ───────────────────────────────────────────────────────────────────

    fg_v = fg["today"] if fg else "?"
    fg_l = fg["label"] if fg else "?"
    fg_t = fg["trend"] if fg else ""
    fg_7 = fg["7d_avg"] if fg else "?"
    dom  = glb["btc_dominance"] if glb else "?"
    mc   = glb["market_cap_change"] if glb else 0
    fr_b = funding.get("BTC",0)*100 if funding else 0
    fr_e = funding.get("ETH",0)*100 if funding else 0

    conf_bar = "█"*round(conf/10) + "░"*(10-round(conf/10))

    lines = [
        f"<b>🤖 CryptoPilot AI</b>",
        f"📅 {now}",
        f"",
        f"{r_e} <b>REGIME: {regime.upper()}</b>",
        f"  Confidence : {conf_bar} {conf}%",
        f"",
        f"<b>📊 Market</b>",
        f"  Fear &amp; Greed  : {fg_v} ({fg_l}) {fg_t}",
        f"  7d avg F&amp;G   : {fg_7}",
        f"  BTC dominance : {dom}%  ({mc:+.1f}% mkt 24h)",
        f"  Funding rates : BTC {fr_b:+.3f}%  ETH {fr_e:+.3f}%",
        f"",
        f"<b>💼 Portfolio</b>",
        f"  Total  : S${total:,.2f}",
        f"  USDT   : {usdt_pct}%  {'✅' if usdt_pct>=10 else '⚠️ TOP UP'}",
        f"",
        f"<b>📈 Coin signals</b>",
    ]

    for s in sorted(signals, key=lambda x: -x["score"]):
        stop = f"S${s['stop']:.4f}" if s.get("stop") else "—"
        trim = f"S${s['trim']:.4f}" if s.get("trim") else "—"
        lines += [
            f"  {s['emoji']} <b>{s['ticker']}</b>  {s['action']}  {s['score']:.0f}/100",
            f"     {s['bar']}",
            f"     P&amp;L {s['pnl_pct']:+.0f}%  7d {s['chg_7d']:+.1f}%  24h {s['chg_24h']:+.1f}%",
            f"     Stop {stop}  →  Trim {trim}",
        ]

    if alerts:
        lines += [f"","<b>─────────────────────────</b>"]
        for a in alerts:
            lines.append(f"  {a}")
    else:
        lines += [f"","✅ <b>All stop-losses safe</b>"]

    advice = {
        "expansion":   "🚀 Hold positions. Trim into targets.",
        "caution":     "🛡 Stay defensive. Hold USDT. No new buys.",
        "contraction": "🔒 Capital preservation. Respect stops now.",
        "recovery":    "👀 Early signs of turn. Wait for BTC confirmation.",
    }
    lines += [f"",f"💡 {advice.get(regime,'')}",f"",
              f"<i>Analytics only. Not financial advice.</i>"]
    return "\n".join(lines)

# ── Main ─────────────────────────────────────────────────────────────────
def main():
    start = now_sgt()
    print(f"\n{'='*52}")
    print(f"  CryptoPilot AI v2")
    print(f"  {start.strftime('%Y-%m-%d %H:%M:%S SGT')}")
    print(f"{'='*52}")

    prices  = fetch_prices()
    fg      = fetch_fear_greed()
    glb     = fetch_global()
    funding = fetch_funding()

    regime, conf = compute_regime(prices, fg, glb, funding)
    print(f"  Regime : {regime.upper()} ({conf}%)")
    print(f"  F&G    : {fg['today'] if fg else 'N/A'}")
    print(f"  BTC dom: {glb['btc_dominance'] if glb else 'N/A'}%")

    signals = []
    for ticker, pos in PORTFOLIO.items():
        s = score_coin(ticker, pos, prices, fg, regime)
        if s:
            signals.append(s)
            print(f"  {ticker:<6} {s['score']:>5.1f}/100  {s['action']:<12}  P&L {s['pnl_pct']:+.0f}%")

    total, usdt_pct, holdings, alerts = value_portfolio(prices)
    print(f"  Total  : S${total:,.2f}  USDT {usdt_pct}%")
    print(f"  Alerts : {len(alerts)}")
    for a in alerts:
        print(f"    {a}")

    msg = build_message(regime, conf, fg, glb, funding,
                        signals, total, usdt_pct, alerts)
    tg(msg)

    end = now_sgt()
    print(f"\nDone — {end.strftime('%H:%M:%S SGT')}")

if __name__ == "__main__":
    main()
