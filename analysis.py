"""Stock analysis for Nation Pulse - technical + fundamental scores for Nifty 50 stocks,
a rules-based signal watchlist whose picks are saved and tracked, and big-move alerts.

This is a transparent screener built from public data (Yahoo Finance). It is NOT investment
advice: every score is explained by the numbers behind it.
"""
import http.cookiejar
import json
import os
import statistics
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
FUND_FILE = os.path.join(DATA, "fundamentals.json")
PICKS_FILE = os.path.join(DATA, "picks.json")
ALERTS_FILE = os.path.join(DATA, "alerts.json")
FUND_EVERY_HOURS = 20          # fundamentals change slowly - refresh about once a day
PICKS_PER_DAY = 5
PICK_MIN_SCORE = 60            # both technical and fundamental scores must reach this
REPICK_AFTER_DAYS = 7          # don't re-add the same stock within a week
BIG_DAY, BIG_WEEK = 4.0, 10.0  # % moves that count as "big"
PICK_BIG_UP, PICK_BIG_DOWN = 15.0, -10.0

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130 Safari/537.36"
FINANCIALS = {"Financial Services", "Banks", "Insurance"}


class Yahoo:
    """Tiny Yahoo Finance client (cookie + crumb, needed for fundamentals)."""

    def __init__(self):
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.op.addheaders = [("User-Agent", UA)]
        self.crumb = None

    def get(self, url, timeout=20):
        with self.op.open(url, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))

    def login(self):
        try:
            self.op.open("https://fc.yahoo.com", timeout=15)
        except Exception:
            pass  # returns 404 but still sets the cookie
        with self.op.open("https://query2.finance.yahoo.com/v1/test/getcrumb", timeout=15) as r:
            self.crumb = r.read().decode().strip()

    def history(self, sym):
        d = self.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(sym)}"
                     "?range=1y&interval=1d")["chart"]["result"][0]
        q = d["indicators"]["quote"][0]
        rows = [(t, c, h, l, v) for t, c, h, l, v in
                zip(d.get("timestamp") or [], q.get("close") or [], q.get("high") or [], q.get("low") or [],
                    q.get("volume") or []) if c]
        while len(rows) > 2 and abs(rows[-1][1] - rows[-2][1]) < 1e-9 and not rows[-1][4]:
            rows.pop()  # holiday bar
        return rows, d["meta"]

    def fundamentals(self, sym):
        mods = "financialData,defaultKeyStatistics,summaryDetail,assetProfile,price"
        r = self.get(f"https://query2.finance.yahoo.com/v10/finance/quoteSummary/{urllib.parse.quote(sym)}"
                     f"?modules={mods}&crumb={urllib.parse.quote(self.crumb)}")["quoteSummary"]["result"][0]
        raw = lambda mod, k: (r.get(mod) or {}).get(k, {}).get("raw") if isinstance((r.get(mod) or {}).get(k), dict) else None
        return {
            "name": (r.get("price") or {}).get("shortName") or sym,
            "sector": (r.get("assetProfile") or {}).get("sector") or "",
            "industry": (r.get("assetProfile") or {}).get("industry") or "",
            "pe": raw("summaryDetail", "trailingPE"), "fpe": raw("summaryDetail", "forwardPE"),
            "pb": raw("defaultKeyStatistics", "priceToBook"),
            "roe": raw("financialData", "returnOnEquity"), "margin": raw("financialData", "profitMargins"),
            "rev_growth": raw("financialData", "revenueGrowth"), "eps_growth": raw("financialData", "earningsGrowth"),
            "de": raw("financialData", "debtToEquity"), "div_yield": raw("summaryDetail", "dividendYield"),
            "mcap": raw("price", "marketCap"),
            "analyst": (r.get("financialData") or {}).get("recommendationKey") or "",
            "target": raw("financialData", "targetMeanPrice"),
            "t": int(time.time()),
        }


# ---------------------------------------------------------------- technical indicators
def sma(x, n):
    return sum(x[-n:]) / n if len(x) >= n else None


def ema_series(x, n):
    k, out = 2 / (n + 1), []
    for i, v in enumerate(x):
        out.append(v if i == 0 else v * k + out[-1] * (1 - k))
    return out


def rsi(x, n=14):
    if len(x) <= n:
        return None
    gains = [max(0, x[i] - x[i - 1]) for i in range(1, len(x))]
    losses = [max(0, x[i - 1] - x[i]) for i in range(1, len(x))]
    ag, al = sum(gains[:n]) / n, sum(losses[:n]) / n
    for g, l in zip(gains[n:], losses[n:]):
        ag, al = (ag * (n - 1) + g) / n, (al * (n - 1) + l) / n
    return 100.0 if al == 0 else 100 - 100 / (1 + ag / al)


def ret(x, days):
    return round(100 * (x[-1] / x[-1 - days] - 1), 2) if len(x) > days else None


def technical(rows):
    c = [r[1] for r in rows]
    vol = [r[4] or 0 for r in rows]
    price = c[-1]
    s50, s200 = sma(c, 50), sma(c, 200)
    macd_line = [a - b for a, b in zip(ema_series(c, 12), ema_series(c, 26))]
    signal = ema_series(macd_line, 9)
    r14 = rsi(c)
    hi52, lo52 = max(r[2] or r[1] for r in rows), min(r[3] or r[1] for r in rows)
    daily = [c[i] / c[i - 1] - 1 for i in range(max(1, len(c) - 20), len(c))]
    vola = statistics.pstdev(daily) * (252 ** 0.5) * 100 if len(daily) > 5 else None
    vsurge = (vol[-1] / (sum(vol[-21:-1]) / 20)) if len(vol) > 21 and sum(vol[-21:-1]) else None

    score, notes = 0, []
    if s50 and price > s50:
        score += 15; notes.append("above 50-day average")
    elif s50:
        notes.append("below 50-day average")
    if s200 and price > s200:
        score += 15; notes.append("above 200-day average")
    elif s200:
        notes.append("below 200-day average")
    if s50 and s200 and s50 > s200:
        score += 10; notes.append("50-day above 200-day (golden cross zone)")
    elif s50 and s200:
        notes.append("50-day below 200-day (death cross zone)")
    if macd_line[-1] > signal[-1]:
        score += 15; notes.append("MACD bullish")
    else:
        notes.append("MACD bearish")
    r3m, r1m = ret(c, 63), ret(c, 21)
    if r3m is not None and r3m > 0:
        score += 10
    if r1m is not None and r1m > 0:
        score += 5
    if r14 is not None:
        if 45 <= r14 <= 65:
            score += 15
        elif 65 < r14 <= 75:
            score += 8; notes.append(f"RSI {r14:.0f} strong but getting stretched")
        elif r14 > 75:
            notes.append(f"RSI {r14:.0f} overbought")
        elif r14 < 30:
            score += 5; notes.append(f"RSI {r14:.0f} oversold")
        else:
            score += 5
    off_high = 100 * (price / hi52 - 1)
    if off_high > -10:
        score += 15; notes.append("near 52-week high")
    elif off_high < -30:
        notes.append(f"{abs(off_high):.0f}% below 52-week high")
    label = ("Strong uptrend" if score >= 70 else "Positive" if score >= 50 else "Mixed" if score >= 35
             else "Weak / downtrend")
    return {"price": round(price, 2), "score": score, "label": label, "notes": notes,
            "rsi": round(r14, 1) if r14 is not None else None,
            "sma50": round(s50, 2) if s50 else None, "sma200": round(s200, 2) if s200 else None,
            "macd": "bullish" if macd_line[-1] > signal[-1] else "bearish",
            "r1d": ret(c, 1), "r5d": ret(c, 5), "r1m": r1m, "r3m": r3m, "r6m": ret(c, 126),
            "off_high": round(off_high, 1), "hi52": round(hi52, 2), "lo52": round(lo52, 2),
            "volatility": round(vola, 1) if vola else None,
            "vol_surge": round(vsurge, 1) if vsurge else None,
            "spark": [round(v, 2) for v in c[-90:]]}


# ---------------------------------------------------------------- fundamental score
def fundamental(f, median_pe):
    if not f:
        return None
    score, notes = 0, []
    pct = lambda v: v * 100 if v is not None else None
    roe, margin, rg, eg = pct(f.get("roe")), pct(f.get("margin")), pct(f.get("rev_growth")), pct(f.get("eps_growth"))
    if roe is not None:
        score += 20 if roe >= 20 else 15 if roe >= 15 else 8 if roe >= 10 else 0
        notes.append(f"ROE {roe:.0f}%")
    if margin is not None:
        score += 15 if margin >= 20 else 10 if margin >= 10 else 5 if margin >= 5 else 0
        notes.append(f"profit margin {margin:.0f}%")
    if rg is not None:
        score += 15 if rg >= 15 else 10 if rg >= 8 else 5 if rg >= 0 else 0
        notes.append(f"revenue growth {rg:+.0f}%")
    if eg is not None:
        score += 15 if eg >= 15 else 10 if eg >= 5 else 5 if eg >= 0 else 0
        notes.append(f"earnings growth {eg:+.0f}%")
    if f.get("sector") in FINANCIALS:
        score += 10  # debt is normal for lenders, so judge them on the rest
    elif f.get("de") is not None:
        de = f["de"] / 100
        score += 15 if de < 0.5 else 10 if de < 1 else 5 if de < 2 else 0
        notes.append(f"debt/equity {de:.2f}")
    pe = f.get("pe")
    if pe and pe > 0 and median_pe:
        score += 20 if pe < 0.8 * median_pe else 12 if pe < 1.2 * median_pe else 5 if pe < 1.8 * median_pe else 0
        notes.append(f"P/E {pe:.0f} vs Nifty median {median_pe:.0f}")
    elif pe is not None and pe <= 0:
        notes.append("loss-making (negative P/E)")
    label = ("Strong" if score >= 70 else "Good" if score >= 50 else "Average" if score >= 35 else "Weak")
    return {"score": score, "label": label, "notes": notes}


# ---------------------------------------------------------------- main
def load(path, default):
    try:
        return json.load(open(path, encoding="utf-8"))
    except Exception:
        return default


def save(path, obj):
    os.makedirs(DATA, exist_ok=True)
    json.dump(obj, open(path, "w", encoding="utf-8"), ensure_ascii=False)


def run(symbols, status, nifty_price=None):
    y = Yahoo()
    # 1) price history -> technicals
    def one(s):
        try:
            rows, _ = y.history(s + ".NS")
            return s, technical(rows) if len(rows) > 60 else None
        except Exception:
            return s, None
    with ThreadPoolExecutor(8) as ex:
        tech = {s: t for s, t in ex.map(one, symbols) if t}
    status["Stock analysis (prices)"] = f"{len(tech)} of {len(symbols)} stocks"

    # 2) fundamentals, refreshed about once a day
    funds = load(FUND_FILE, {})
    stale = [s for s in symbols if time.time() - funds.get(s, {}).get("t", 0) > FUND_EVERY_HOURS * 3600]
    if stale:
        try:
            y.login()
            def f1(s):
                try:
                    return s, y.fundamentals(s + ".NS")
                except Exception:
                    return s, None
            with ThreadPoolExecutor(6) as ex:
                for s, f in ex.map(f1, stale):
                    if f:
                        funds[s] = f
            save(FUND_FILE, funds)
        except Exception as e:
            status["Stock analysis fundamentals (error)"] = str(e)[:100]
    status["Stock analysis (fundamentals)"] = f"{sum(1 for s in symbols if s in funds)} of {len(symbols)} stocks"
    pes = [funds[s]["pe"] for s in symbols if s in funds and funds[s].get("pe") and funds[s]["pe"] > 0]
    median_pe = statistics.median(pes) if pes else None

    stocks = []
    for s in symbols:
        t = tech.get(s)
        if not t:
            continue
        f = funds.get(s, {})
        fs = fundamental(f, median_pe) if f else None
        combined = round((t["score"] + fs["score"]) / 2) if fs else t["score"]
        stocks.append({"symbol": s, "name": f.get("name") or s, "sector": f.get("sector", ""),
                       "tech": t, "fund": fs, "combined": combined,
                       "facts": {k: f.get(k) for k in ("pe", "pb", "roe", "margin", "rev_growth", "eps_growth",
                                                         "de", "div_yield", "mcap", "analyst", "target")}})
    stocks.sort(key=lambda x: -x["combined"])

    # 3) signal watchlist - save new picks and track every past pick
    picks = load(PICKS_FILE, [])
    now = int(time.time())
    today = time.strftime("%Y-%m-%d", time.gmtime(now + 19800))  # India date
    if not any(p["date"] == today for p in picks):
        recent = {p["symbol"] for p in picks if now - p["t"] < REPICK_AFTER_DAYS * 86400}
        chosen = [x for x in stocks if x["fund"] and x["tech"]["score"] >= PICK_MIN_SCORE
                  and x["fund"]["score"] >= PICK_MIN_SCORE and x["symbol"] not in recent
                  and (x["tech"]["rsi"] or 50) <= 75][:PICKS_PER_DAY]  # skip overbought stocks
        for x in chosen:
            picks.append({"date": today, "t": now, "symbol": x["symbol"], "name": x["name"],
                          "price": x["tech"]["price"], "nifty": nifty_price,
                          "tech": x["tech"]["score"], "fund": x["fund"]["score"],
                          "why": (x["tech"]["notes"][:3] + x["fund"]["notes"][:3])})
    price_now = {x["symbol"]: x["tech"]["price"] for x in stocks}
    for p in picks:
        if p["symbol"] in price_now:
            p["now"] = price_now[p["symbol"]]
            p["ret"] = round(100 * (p["now"] / p["price"] - 1), 2)
            if p.get("nifty") and nifty_price:
                p["nifty_ret"] = round(100 * (nifty_price / p["nifty"] - 1), 2)
                p["excess"] = round(p["ret"] - p["nifty_ret"], 2)
            p["best"] = max(p.get("best", p["ret"]), p["ret"])
            p["worst"] = min(p.get("worst", p["ret"]), p["ret"])
    save(PICKS_FILE, picks)
    tracked = [p for p in picks if "ret" in p]
    record = None
    if tracked:
        rets = [p["ret"] for p in tracked]
        ex = [p["excess"] for p in tracked if "excess" in p]
        record = {"count": len(tracked), "avg": round(sum(rets) / len(rets), 2),
                  "win_rate": round(100 * sum(r > 0 for r in rets) / len(rets)),
                  "avg_vs_nifty": round(sum(ex) / len(ex), 2) if ex else None,
                  "best": max(tracked, key=lambda p: p["ret"]), "worst": min(tracked, key=lambda p: p["ret"])}

    # 4) big-move alerts (kept as a log so they can be shown "occasionally")
    alerts = load(ALERTS_FILE, [])
    seen = {(a["symbol"], a["kind"], a["date"]) for a in alerts}
    def add(sym, kind, text, size):
        if (sym, kind, today) not in seen:
            alerts.append({"date": today, "t": now, "symbol": sym, "kind": kind, "text": text, "size": size})
            seen.add((sym, kind, today))
    for x in stocks:
        t = x["tech"]
        if t["r1d"] is not None and abs(t["r1d"]) >= BIG_DAY:
            add(x["symbol"], "day", f"{x['name']} {'jumped' if t['r1d'] > 0 else 'fell'} {abs(t['r1d']):.1f}% in a day",
                t["r1d"])
        if t["r5d"] is not None and abs(t["r5d"]) >= BIG_WEEK:
            add(x["symbol"], "week", f"{x['name']} {'up' if t['r5d'] > 0 else 'down'} {abs(t['r5d']):.1f}% in a week",
                t["r5d"])
        if t.get("vol_surge") and t["vol_surge"] >= 3:
            add(x["symbol"], "volume", f"{x['name']} traded {t['vol_surge']:.1f}x its usual volume", t["vol_surge"])
    for p in tracked:
        if p["ret"] >= PICK_BIG_UP:
            add(p["symbol"], "pick-up", f"Watchlist pick {p['name']} is up {p['ret']:.1f}% since {p['date']}", p["ret"])
        elif p["ret"] <= PICK_BIG_DOWN:
            add(p["symbol"], "pick-down", f"Watchlist pick {p['name']} is down {abs(p['ret']):.1f}% since {p['date']}",
                p["ret"])
    alerts = alerts[-100:]
    save(ALERTS_FILE, alerts)

    return {"stocks": stocks, "median_pe": round(median_pe, 1) if median_pe else None,
            "picks": sorted(picks, key=lambda p: -p["t"])[:60], "record": record,
            "alerts": sorted(alerts, key=lambda a: -a["t"])[:30]}
