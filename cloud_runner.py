import os, json, time, requests
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ── SINGAPORE TIME — hardcoded UTC+8 ───────────────────────────────────
SGT = timezone(timedelta(hours=8))
def sgt(): return datetime.now(SGT).strftime("%a %d %b %Y, %H:%M SGT")

# ── Config ──────────────────────────────────────────────────────────────
def load_cfg():
    p = Path(__file__).parent / "config.json"
    if p.exists():
        try: return json.loads(p.read_text(encoding="utf-8"))
        except: pass
    return {}

cfg  = load_cfg()
BOT  = os.environ.get("BOT_TOKEN") or cfg.get("bot_token","")
CHAT = os.environ.get("CHAT_ID")   or cfg.get("chat_id","")

# ── Portfolio ───────────────────────────────────────────────────────────
PORT = {
    "ETH":  {"qty":4.6063,      "cost":4672.35, "stop":2280.0,    "trim":3750.0,   "tier":"large"},
    "XRP":  {"qty":5797.74,     "cost":2.80,    "stop":1.42,      "trim":2.65,     "tier":"large"},
    "NEAR": {"qty":3306.68,     "cost":8.01,    "stop":1.45,      "trim":2.80,     "tier":"mid"},
    "DOGE": {"qty":44345.5,     "cost":0.1645,  "stop":0.092,     "trim":0.195,    "tier":"mid"},
    "ADA":  {"qty":5461.4,      "cost":0.6466,  "stop":0.235,     "trim":0.48,     "tier":"mid"},
    "USDT": {"qty":4753.4,      "cost":1.27,    "stop":None,      "trim":None,     "tier":"stable"},
    "TRUMP":{"qty":26.84,       "cost":2.80,    "stop":2.50,      "trim":5.00,     "tier":"micro"},
    "SHIB": {"qty":11614382.62, "cost":0.000035,"stop":0.0000055, "trim":0.000015, "tier":"micro"},
}

CG = {
    "ETH":"ethereum","XRP":"ripple","NEAR":"near","DOGE":"dogecoin",
    "ADA":"cardano","BTC":"bitcoin","TRUMP":"official-trump","SHIB":"shiba-inu",
}

# ── HTTP ────────────────────────────────────────────────────────────────
def get(url, params=None, delay=1.2):
    time.sleep(delay)
    try:
        r = requests.get(url, params=params or {}, timeout=15,
                         headers={"User-Agent":"CryptoPilotAI/5.0"})
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"  [warn] {e}")
        return None

def tg(text):
    if not BOT or not CHAT:
        print("  [warn] No Telegram config")
        return
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{BOT}/sendMessage",
            data={"chat_id":CHAT,"text":text,
                  "parse_mode":"HTML","disable_web_page_preview":True},
            timeout=15)
        print(f"  Telegram: {'OK' if r.json().get('ok') else 'FAIL'}")
    except Exception as e:
        print(f"  [error] {e}")

# ── Data ────────────────────────────────────────────────────────────────
def fetch_prices():
    d = get("https://api.coingecko.com/api/v3/simple/price", {
        "ids": ",".join(CG.values()),
        "vs_currencies": "sgd",
        "include_24hr_change": "true",
        "include_7d_change": "true",
    })
    if not d: return {}
    out = {}
    for t, cid in CG.items():
        if cid in d:
            out[t] = {
                "sgd": d[cid].get("sgd", 0),
                "h24": d[cid].get("usd_24h_change", 0),
                "d7":  d[cid].get("usd_7d_change", 0),
            }
    return out

def fetch_fg():
    d = get("https://api.alternative.me/fng/?limit=7&format=json")
    if not d or "data" not in d: return None
    v = [int(x["value"]) for x in d["data"]]
    return {
        "val":   v[0],
        "avg":   round(sum(v)/len(v), 1),
        "lbl":   d["data"][0]["value_classification"],
        "trend": "improving" if v[0] > v[1] else "worsening",
        "mom":   v[0] - v[6],
    }

def fetch_glb():
    d = get("https://api.coingecko.com/api/v3/global")
    if not d: return None
    mp = d["data"].get("market_cap_percentage", {})
    return {
        "dom": round(mp.get("btc", 0), 2),
        "chg": round(d["data"].get("market_cap_change_percentage_24h_usd", 0), 2),
    }

# ── Regime ──────────────────────────────────────────────────────────────
def regime(px, f, g):
    v = {"expansion":0.0, "caution":0.0, "contraction":0.0, "recovery":0.0}
    if f:
        fv = f["val"]
        if fv >= 75:   v["caution"]     += 2.0
        elif fv >= 55: v["expansion"]   += 2.0
        elif fv >= 40: v["expansion"]   += 1.0
        elif fv >= 25: v["caution"]     += 1.5
        elif fv >= 15: v["contraction"] += 2.0
        else:          v["contraction"] += 3.0
        if f["mom"] > 10:   v["expansion"]   += 0.5
        elif f["mom"] < -10:v["contraction"] += 0.5
    if g:
        d = g["dom"]
        if d >= 62:   v["contraction"] += 1.5
        elif d >= 57: v["caution"]     += 1.5
        elif d >= 46: v["expansion"]   += 1.0
        else:         v["expansion"]   += 1.5
        if g["chg"] >= 3:   v["expansion"]   += 1.0
        elif g["chg"] < -3: v["contraction"] += 1.0
    if px:
        b24 = px.get("BTC", {}).get("h24", 0)
        b7  = px.get("BTC", {}).get("d7",  0)
        if b24 >= 5:    v["expansion"]   += 1.5
        elif b24 >= 2:  v["expansion"]   += 0.8
        elif b24 >= -3: v["caution"]     += 0.8
        else:           v["contraction"] += 1.5
        if b7 >= 10:    v["expansion"]   += 1.5
        elif b7 >= 3:   v["expansion"]   += 0.8
        elif b7 >= -10: v["contraction"] += 1.0
        else:           v["contraction"] += 1.5
    reg  = max(v, key=v.get)
    tot  = sum(v.values())
    conf = round(v[reg]/tot*100) if tot > 0 else 50
    if conf < 45: reg, conf = "caution", 45
    return reg, conf

# ── Score ───────────────────────────────────────────────────────────────
def score(t, pos, px, f, reg):
    if pos["tier"] == "stable": return None
    p   = px.get(t, {}).get("sgd", 0)
    if p <= 0: return None
    h24 = px.get(t, {}).get("h24", 0)
    d7  = px.get(t, {}).get("d7",  0)
    pnl = (p - pos["cost"]) / pos["cost"] * 100

    if d7 >= 15:   m = 82
    elif d7 >= 7:  m = 70
    elif d7 >= 2:  m = 60
    elif d7 >= -2: m = 48
    elif d7 >= -8: m = 35
    else:          m = 18
    m = max(5, min(95, m + h24 * 0.5))

    if pnl >= 50:    cb = 78
    elif pnl >= 20:  cb = 65
    elif pnl >= 0:   cb = 55
    elif pnl >= -20: cb = 42
    elif pnl >= -40: cb = 30
    elif pnl >= -60: cb = 20
    elif pnl >= -80: cb = 12
    else:            cb = 6

    fv = f["val"] if f else 50
    if fv >= 80:   sa = 25
    elif fv >= 65: sa = 40
    elif fv >= 45: sa = 58
    elif fv >= 30: sa = 52
    else:          sa = 42

    st = pos.get("stop")
    if st and p > 0:
        pct = (p - st) / st * 100
        if pct >= 30:  sl = 70
        elif pct >= 15:sl = 60
        elif pct >= 8: sl = 50
        elif pct >= 3: sl = 35
        elif pct >= 0: sl = 20
        else:          sl = 5
    else: sl = 55

    raw = m*0.25 + cb*0.30 + sa*0.20 + sl*0.15 + 55*0.10
    M = {
        "expansion":   {"large":1.10,"mid":1.05,"micro":1.0},
        "caution":     {"large":0.92,"mid":0.78,"micro":0.65},
        "contraction": {"large":0.80,"mid":0.62,"micro":0.50},
        "recovery":    {"large":1.05,"mid":0.90,"micro":0.80},
    }
    sc = round(max(3, min(97, raw * M.get(reg, {}).get(pos["tier"], 1.0))), 1)

    if sc >= 72:   act = "ACCUMULATE"
    elif sc >= 56: act = "HOLD"
    elif sc >= 42: act = "WATCH"
    elif sc >= 27: act = "TRIM"
    else:          act = "DE-RISK"

    EM = {"ACCUMULATE":"🟢","HOLD":"🔵","WATCH":"🟡","TRIM":"🟠","DE-RISK":"🔴"}
    bar = "█" * round(sc/10) + "░" * (10 - round(sc/10))
    return {"t":t,"sc":sc,"act":act,"em":EM[act],"pnl":round(pnl,1),
            "p":p,"h24":round(h24,1),"d7":round(d7,1),
            "stop":st,"trim":pos.get("trim"),"bar":bar}

# ── Portfolio value ──────────────────────────────────────────────────────
def port_val(px):
    tot = 0.0; uval = 0.0; hold = []; alts = []
    for t, pos in PORT.items():
        qty = pos["qty"]
        p   = px.get(t, {}).get("sgd", 0) if t != "USDT" else 1.27
        val = qty * p
        tot += val
        if t == "USDT":
            uval = val
            continue
        cost = qty * pos["cost"]
        pnl  = (val - cost) / cost * 100 if cost > 0 else 0
        hold.append({"t":t,"p":p,"val":val,"pnl":pnl})
        st = pos.get("stop")
        tr = pos.get("trim")
        if st and p > 0:
            pct = (p - st) / st * 100
            if p <= st:
                alts.append(f"🚨 STOP-LOSS: {t} S${p:.4f} BELOW S${st:.4f} — SELL NOW")
            elif pct < 5:
                alts.append(f"⚠️ NEAR STOP: {t} S${p:.4f} — {pct:.1f}% above S${st:.4f}")
        if tr and p >= tr:
            alts.append(f"✅ TRIM TARGET: {t} S${p:.4f} hit S${tr:.4f}")
    up = round(uval/tot*100, 1) if tot > 0 else 0
    return round(tot, 2), up, hold, alts

# ── Message ─────────────────────────────────────────────────────────────
def build(reg, conf, f, g, sigs, tot, up, alts):
    ts  = sgt()   # <-- Singapore time, always correct
    RE  = {"expansion":"🟢","caution":"🟡","contraction":"🔴","recovery":"🔵"}
    fv  = f["val"]   if f else "?"
    fl  = f["lbl"]   if f else "?"
    ft  = f["trend"] if f else ""
    f7  = f["avg"]   if f else "?"
    dom = g["dom"]   if g else "?"
    mc  = g["chg"]   if g else 0
    cb  = "█" * round(conf/10) + "░" * (10 - round(conf/10))

    L = [
        f"<b>🤖 CryptoPilot AI</b>",
        f"📅 {ts}",
        f"",
        f"{RE.get(reg,'⚪')} <b>REGIME: {reg.upper()}</b>",
        f"  Confidence : {cb} {conf}%",
        f"",
        f"<b>📊 Market</b>",
        f"  Fear &amp; Greed  : {fv} ({fl}) {ft}",
        f"  7d avg F&amp;G   : {f7}",
        f"  BTC dominance : {dom}%  ({mc:+.1f}% 24h)",
        f"",
        f"<b>💼 Portfolio</b>",
        f"  Total  : S${tot:,.2f}",
        f"  USDT   : {up}%  {'✅' if up>=10 else '⚠️ TOP UP'}",
        f"",
        f"<b>📈 Coin signals</b>",
    ]

    for s in sorted(sigs, key=lambda x: -x["sc"]):
        st = f"S${s['stop']:.4f}"  if s.get("stop") else "—"
        tr = f"S${s['trim']:.4f}"  if s.get("trim") else "—"
        L += [
            f"  {s['em']} <b>{s['t']}</b>  {s['act']}  {s['sc']:.0f}/100",
            f"     {s['bar']}",
            f"     P&amp;L {s['pnl']:+.0f}%  7d {s['d7']:+.1f}%  24h {s['h24']:+.1f}%",
            f"     Stop {st}  →  Trim {tr}",
        ]

    if alts:
        L += [f"", "<b>───────────────────────</b>"]
        for a in alts:
            L.append(f"  {a}")
    else:
        L += [f"", "✅ <b>All stop-losses safe</b>"]

    AD = {
        "expansion":   "🚀 Hold positions. Trim into targets.",
        "caution":     "🛡 Stay defensive. Hold USDT. No new buys.",
        "contraction": "🔒 Capital preservation. Respect stops now.",
        "recovery":    "👀 Early signs of turn. Wait for BTC confirmation.",
    }
    L += [f"", f"💡 {AD.get(reg,'')}", f"", f"<i>Analytics only. Not financial advice.</i>"]
    return "\n".join(L)

# ── Main ─────────────────────────────────────────────────────────────────
def main():
    print(f"SGT time check: {sgt()}")
    print("Fetching data...")

    px = fetch_prices()
    f  = fetch_fg()
    g  = fetch_glb()

    reg, conf = regime(px, f, g)
    print(f"Regime: {reg.upper()} ({conf}%)")
    print(f"F&G: {f['val'] if f else 'N/A'}  BTC dom: {g['dom'] if g else 'N/A'}%")

    sigs = []
    for t, pos in PORT.items():
        s = score(t, pos, px, f, reg)
        if s:
            sigs.append(s)
            print(f"  {t:<6} {s['sc']:>5.1f}/100  {s['act']:<12}  P&L {s['pnl']:+.0f}%")

    tot, up, hold, alts = port_val(px)
    print(f"Total: S${tot:,.2f}  USDT {up}%  Alerts: {len(alts)}")

    msg = build(reg, conf, f, g, sigs, tot, up, alts)
    tg(msg)
    print("Done.")

if __name__ == "__main__":
    main()
