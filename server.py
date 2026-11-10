"""Nation Pulse - home server.

Collects free public sources (Google News, Google Trends, Reddit feeds),
translates Hindi/Punjabi to English, sorts posts by mood and political stance,
and serves the app to phones/tablets on the same Wi-Fi.

Run:  python server.py      then open the address it prints on your phone.
Only uses Python's standard library - nothing to install.
"""
import html
import json
import os
import re
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from email.utils import parsedate_to_datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

PORT = 8000
REFRESH_MINUTES = 30
HERE = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.join(HERE, "app")
DATA_FILE = os.path.join(HERE, "data", "latest.json")
HISTORY_FILE = os.path.join(HERE, "data", "history.json")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) NationPulse/1.0"}

# ---------------------------------------------------------------- sources
GN = "https://news.google.com/rss"
NEWS_FEEDS = [
    ("Google News India", f"{GN}?hl=en-IN&gl=IN&ceid=IN:en"),
    ("Google News India", f"{GN}/headlines/section/topic/NATION?hl=en-IN&gl=IN&ceid=IN:en"),
    ("Google News Punjabi", f"{GN}?hl=pa&gl=IN&ceid=IN:pa"),
    ("Google News India", f"{GN}/search?q=government+OR+Modi+OR+opposition+when:2d&hl=en-IN&gl=IN&ceid=IN:en"),
    ("Google News India", f"{GN}/search?q=Punjab+when:2d&hl=en-IN&gl=IN&ceid=IN:en"),
]
TRENDS_FEEDS = [("India", "IN"), ("Punjab", "IN-PB"), ("Delhi", "IN-DL"), ("Chandigarh", "IN-CH")]
MEME_SUBS = ["IndianDankMemes", "IndianMeyMeys", "desimemes"]
SOCIAL_SUBS = ["india", "IndiaSpeaks", "indianews", "punjab"]

# ---------------------------------------------------------------- word lists
GOV = r"\b(modi|pm|prime minister|government|govt|centre|central|union minister|minister|ministry|bjp|nda|cabinet|amit shah|nadda|parliament|lok sabha|rajya sabha|congress|opposition|rahul gandhi|kharge|india bloc|election|chief minister|cm|bill|scheme|budget|gst|aap|kejriwal|bhagwant mann|tmc|mamata|policy|law|supreme court|eci|election commission)\b"
GOV_ACTOR = r"\b(bjp|modi|pm|amit shah|nadda|government|govt|centre|union minister|nda)\b"
OPP_ACTOR = r"\b(congress|rahul|opposition|india bloc|kharge|tmc|mamata|aap|kejriwal|sp|akhilesh|dmk|stalin)\b"
FOREIGN = r"\b(israel|netanyahu|gaza|trump|white house|ukraine|zelensk|putin|russia|kremlin|meloni|italy|starmer|britain|uk pm|germany|france|macron|china'?s xi|xi jinping|japan|canada|carney|eisenkot|iran|nepal|bangladesh|sri lanka|pakistan)\b"
INDIA_MARK = r"\b(india|indian|modi|bjp|congress|delhi|punjab|mumbai|bihar|kerala|keralam|tamil|tn|uttar pradesh|haryana|gujarat|bengal|karnataka|odisha|lok sabha|rajya sabha|new delhi|aap|centre)\b"
PRO = [
    r"inaugurat", r"\blaunch", r"\blauds?\b", r"\bhails?\b", r"historic", r"\brecord\b", r"milestone",
    r"\bboost", r"achiev", r"success(ful)?\b", r"welfare", r"empower", r"transform", r"viksit bharat",
    r"atmanirbhar", r"self.reliant", r"foundation stone", r"\bdedicates?\b", r"\bpraise", r"applaud",
    r"first.ever", r"world'?s largest", r"proud", r"strengthen", r"surge", r"growth", r"benefit",
    r"\bapproves?\b", r"crore projects?", r"\bthanks? (pm|modi)", r"vision", r"\bunveil",
]
ANTI = [
    r"\bslams?\b", r"\battacks? (on )?(govt|government|centre|modi|bjp|pm)", r"critici[sz]", r"\baccus",
    r"protest", r"\bscam", r"corrupt", r"\bfail", r"\bblames?\b", r"unemploy", r"inflation",
    r"price rise", r"\bjibe", r"dig at", r"hits out", r"\bflays?\b", r"\blash", r"condemn",
    r"resign", r"betray", r"dictator", r"undemocratic", r"\bmisuse", r"vote chori", r"vote theft",
    r"walkout", r"outrage", r"agitation", r"cover.up", r"\blies\b", r"jumla", r"\bmuzzl", r"\bsilence",
    r"\bquestions? (govt|government|centre|modi|pm)", r"\bdemands?\b", r"\bslammed\b", r"\bdeni(ed|al)\b",
    r"\bfarmers'? (protest|stir)", r"murder of democracy", r"\btarget(s|ed)? (govt|centre|modi|bjp)",
    r"smell(s|ing)? a plot", r"conspira", r"\balleg", r"bulldoz", r"tactics", r"\bmanipulat", r"\bstruggl",
]
ATTACK = r"(slam|attack|critici|accus|blame|jibe|dig at|hits out|flay|lash|condemn|target|question|demand|alleg|smell)"
NEUTRAL = [
    r"explained", r"analysis", r"what it means", r"fact.check", r"data shows", r"\breport\b",
    r"\bstudy\b", r"survey", r"\bexplainer", r"\bwhy\b", r"\bhow\b", r"opinion", r"\bexplain",
    r"\bdecoded", r"in charts", r"by the numbers", r"\bq&a\b",
]
EMOTIONS = {
    "anger": [r"anger", r"angry", r"outrage", r"fury", r"furious", r"protest", r"slam", r"violence",
              r"\bclash", r"\briot", r"condemn", r"murder", r"assault", r"\brape", r"lynch", r"\bmob\b"],
    "fear": [r"\bfear", r"worr", r"concern", r"threat", r"\balert", r"warning", r"panic", r"\brisk",
             r"crisis", r"terror", r"scare", r"flood", r"pollution", r"\baqi\b", r"cyclone", r"smog",
             r"blast", r"virus", r"outbreak", r"earthquake"],
    "joy": [r"\bwins?\b", r"\bwon\b", r"celebrat", r"\bjoy", r"victory", r"happy", r"\bgold\b",
            r"medal", r"proud", r"festival", r"diwali", r"wedding", r"blockbuster", r"champion",
            r"\bhit\b", r"triumph", r"\bcentury\b"],
    "sadness": [r"\bdies\b", r"\bdied\b", r"death", r"\bdead\b", r"mourn", r"tragedy", r"\bloss\b",
                r"grief", r"accident", r"passes away", r"killed", r"suicide", r"funeral", r"tribute"],
    "hope": [r"\bhope", r"\bplan\b", r"\blaunch", r"boost", r"growth", r"reform", r"improve",
             r"opportunit", r"invest", r"recover", r"\bjobs\b", r"\bnew\b", r"breakthrough", r"progress"],
}
STOP = set("""a an the of to in on for and or but with by at from as is are was were be been it its this that
these those after before over into about up out new says said say will can could would may might not no
has have had amid among more than his her their our your you we they he she them who what when where why how
india indian india's news live updates today day year years first one two three us also just all video watch
check latest top week report big set get gets make makes take takes back now still being under against
while during within near via per mr ms dr vs ji yet top news""".split())

# Only English and Punjabi are kept. Punjabi (Gurmukhi script) is translated to English;
# anything in another Indian script (Hindi, Tamil, Telugu, Kannada, Malayalam, Bengali, ...) is dropped.
NON_LATIN = re.compile(r"[਀-੿]")  # Gurmukhi (Punjabi)
OTHER_INDIC = re.compile(r"[ऀ-৿઀-෿]")


def lang_ok(text):
    return bool(text) and not OTHER_INDIC.search(text)

# ---------------------------------------------------------------- helpers
def fetch(url, timeout=20):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


_tcache = {}
_tlock = threading.Lock()


def translate(text):
    """Translate Hindi/Punjabi text to English with Google's free endpoint. Returns (english, lang)."""
    if not text or not NON_LATIN.search(text):
        return text, None
    with _tlock:
        if text in _tcache:
            return _tcache[text]
    try:
        url = ("https://translate.googleapis.com/translate_a/single?client=gtx&sl=auto&tl=en&dt=t&q="
               + urllib.parse.quote(text[:1500]))
        data = json.loads(fetch(url, 15).decode("utf-8"))
        out = ("".join(seg[0] for seg in data[0] if seg and seg[0]), data[2] if len(data) > 2 else "hi")
    except Exception:
        out = (None, "hi")  # translation failed -> item gets skipped
    with _tlock:
        _tcache[text] = out
    return out


def to_ts(s):
    try:
        return int(parsedate_to_datetime(s).timestamp())
    except Exception:
        try:
            return int(time.mktime(time.strptime(s[:19], "%Y-%m-%dT%H:%M:%S")))
        except Exception:
            return int(time.time())


def hits(patterns, text):
    found = []
    for p in patterns:
        m = re.search(p, text)
        if m:
            found.append(full_word(text, m))
    return found


def full_word(text, m):
    """Grow a stem match like 'inaugurat' to the whole word 'inaugurate'."""
    s, e = m.start(), m.end()
    while s > 0 and text[s - 1].isalnum():
        s -= 1
    while e < len(text) and text[e].isalnum():
        e += 1
    return text[s:e].strip()


def classify(item):
    """Adds political stance + emotion to an item, with the words that triggered it."""
    t = item["title"].lower()
    foreign = re.search(FOREIGN, t) and not re.search(INDIA_MARK, t)
    item["political"] = bool(re.search(GOV, t)) and not foreign
    pro, anti, neu = hits(PRO, t), hits(ANTI, t), hits(NEUTRAL, t)
    # Who is speaking decides the direction: the party named just before the attack word.
    # "BJP slams Congress" = pro-government, "Congress targets BJP" = anti-government.
    if anti:
        # For each negative word, find who is named just before it (within ~30 letters).
        # Attack words ("slams") take the side of the speaker; other negative words
        # ("failed", "scam") count against whoever is named.
        new_pro, new_anti = list(pro), []
        for p in ANTI:
            for m in re.finditer(p, t):
                win = t[max(0, m.start() - 30):m.start()]
                actors = [(a.start(), "gov") for a in re.finditer(GOV_ACTOR, win)] + \
                         [(a.start(), "opp") for a in re.finditer(OPP_ACTOR, win)]
                actor = max(actors)[1] if actors else None
                word = full_word(t, m)
                if re.match(ATTACK, m.group(0).strip()):
                    (new_pro if actor == "gov" else new_anti).append(word)
                else:
                    (new_pro if actor == "opp" else new_anti).append(word)
        pro, anti = new_pro, new_anti
    elif pro and re.search(OPP_ACTOR, t) and not re.search(GOV_ACTOR, t[:re.search(OPP_ACTOR, t).start()]):
        anti, pro = ["opposition speaking"], []
    if "blame game" in t:  # both sides attacking each other
        pro, anti, neu = [], [], ["blame game between parties"]
    if not item["political"]:
        item["stance"] = None
    elif len(anti) > len(pro):
        item["stance"] = "anti"
    elif len(pro) > len(anti):
        item["stance"] = "pro"
    else:
        item["stance"] = "neutral"
    if item["stance"] == "neutral" and not neu:
        neu = ["balanced or factual wording"]
    item["why"] = {"pro": pro, "anti": anti, "neutral": neu}.get(item["stance"], [])
    scores = {k: len(hits(v, t)) for k, v in EMOTIONS.items()}
    best = max(scores, key=scores.get)
    item["emotion"] = best if scores[best] else "calm"
    return item


# ---------------------------------------------------------------- collectors
def collect_news(status):
    items, seen = [], set()
    for name, url in NEWS_FEEDS:
        try:
            root = ET.fromstring(fetch(url))
            n = 0
            for it in root.iter("item"):
                title = html.unescape(it.findtext("title") or "")
                src = it.findtext("source") or ""
                if src and title.endswith(" - " + src):
                    title = title[: -len(src) - 3]
                key = re.sub(r"\W+", "", title.lower())[:80]
                if not title or key in seen:
                    continue
                seen.add(key)
                items.append({"title": title, "source": src or name, "platform": "news",
                              "feed": name, "url": it.findtext("link"),
                              "time": to_ts(it.findtext("pubDate") or "")})
                n += 1
            status[name] = status.get(name, 0) + n
        except Exception as e:
            status[name + " (error)"] = str(e)[:80]
    return items


def collect_trends(status):
    """Top Google searches for India, Punjab, Delhi and Chandigarh - English/Punjabi only."""
    ns = {"ht": "https://trends.google.com/trending/rss"}
    merged = {}
    for region, geo in TRENDS_FEEDS:
        try:
            root = ET.fromstring(fetch("https://trends.google.com/trending/rss?geo=" + geo))
        except Exception as e:
            status[f"Google Trends {region} (error)"] = str(e)[:80]
            continue
        kept = 0
        for it in root.iter("item"):
            title = it.findtext("title") or ""
            all_news = [{"title": html.unescape(ni.findtext("ht:news_item_title", "", ns)),
                         "url": ni.findtext("ht:news_item_url", "", ns),
                         "source": ni.findtext("ht:news_item_source", "", ns)}
                        for ni in it.findall("ht:news_item", ns)]
            news = [n for n in all_news if lang_ok(n["title"])]
            # skip searches in other languages, or whose coverage is only in other languages
            if not lang_ok(title) or (all_news and not news):
                continue
            traffic = it.findtext("ht:approx_traffic", "", ns)
            num = int(re.sub(r"\D", "", traffic) or 0)
            key = title.lower().strip()
            if key in merged:
                merged[key]["regions"].append(region)
                if num > merged[key]["traffic_num"]:
                    merged[key].update(traffic=traffic, traffic_num=num)
                continue
            merged[key] = {"title": title, "traffic": traffic, "traffic_num": num, "regions": [region],
                           "image": it.findtext("ht:picture", "", ns), "news": news[:3],
                           "platform": "search", "source": "Google Trends",
                           "url": f"https://trends.google.com/trends/explore?geo={geo}&q=" + urllib.parse.quote(title),
                           "time": to_ts(it.findtext("pubDate") or "")}
            kept += 1
        status[f"Google Trends {region}"] = kept
    out = sorted(merged.values(), key=lambda x: (-x["traffic_num"], -len(x["regions"])))
    return out


def collect_reddit_all(status):
    """Reddit limits fast requests, so ask one subreddit at a time with pauses."""
    memes, social = [], []
    for i, sub in enumerate(MEME_SUBS + SOCIAL_SUBS):
        if i:
            time.sleep(7)
        got = collect_reddit(sub, status, limit=25 if sub in MEME_SUBS else 40)
        if got:
            REDDIT_CACHE[sub] = got
        else:  # blocked this round: reuse the last good copy
            got = REDDIT_CACHE.get(sub, [])
        (memes if sub in MEME_SUBS else social).extend(got)
    try:
        json.dump(REDDIT_CACHE, open(REDDIT_CACHE_FILE, "w", encoding="utf-8"), ensure_ascii=False)
    except Exception:
        pass
    return memes, social


REDDIT_CACHE_FILE = os.path.join(HERE, "data", "reddit_cache.json")
try:
    REDDIT_CACHE = json.load(open(REDDIT_CACHE_FILE, encoding="utf-8"))
    # drop anything older than 2 days
    REDDIT_CACHE = {k: v for k, v in REDDIT_CACHE.items() if v and time.time() - v[0]["time"] < 172800}
except Exception:
    REDDIT_CACHE = {}


def collect_reddit(sub, status, sort="top", limit=25):
    atom = "{http://www.w3.org/2005/Atom}"
    media = "{http://search.yahoo.com/mrss/}"
    url = f"https://www.reddit.com/r/{sub}/{sort}/.rss?t=day&limit={limit}"
    out = []
    try:
        try:
            raw = fetch(url)
        except urllib.error.HTTPError as e:
            if e.code != 429:
                raise
            time.sleep(30)
            raw = fetch(url)
        root = ET.fromstring(raw)
        for rank, e in enumerate(root.findall(atom + "entry")):
            content = html.unescape(e.findtext(atom + "content") or "")
            img = None
            th = e.find(media + "thumbnail")
            m = re.search(r'<img src="([^"]+)"', content)
            if m:
                img = m.group(1)
            elif th is not None:
                img = th.get("url")
            link = e.find(atom + "link")
            out.append({"title": html.unescape(e.findtext(atom + "title") or ""),
                        "source": "r/" + sub, "platform": "reddit", "rank": rank,
                        "url": link.get("href") if link is not None else None,
                        "image": img, "is_video": "[video]" in content and "v.redd.it" in content,
                        "time": to_ts(e.findtext(atom + "updated") or e.findtext(atom + "published") or "")})
        status["r/" + sub] = len(out)
    except Exception as e:
        status["r/" + sub + " (error)"] = str(e)[:80]
    return out


def translate_items(items):
    items = [it for it in items if lang_ok(it.get("title"))]  # English + Punjabi only
    def work(it):
        eng, lang = translate(it["title"])
        if lang:
            it["original"], it["lang"] = it["title"], "pa"
            it["title"] = eng
        return it
    with ThreadPoolExecutor(8) as ex:
        done = list(ex.map(work, items))
    return [it for it in done if it["title"]]  # drop items whose translation failed


def topics(items, n=14):
    words, docs = Counter(), {}
    for it in items:
        toks = set(w for w in re.findall(r"[a-z][a-z'\-]{2,}", it["title"].lower())
                   if w not in STOP and not w.endswith("'s"))
        for w in toks:
            words[w] += 1
            docs.setdefault(w, []).append(it)
    out = []
    for w, c in words.most_common(60):
        if c < 3:
            break
        group = docs[w]
        st = Counter(i.get("stance") for i in group if i.get("stance"))
        out.append({"word": w, "count": c, "pro": st["pro"], "neutral": st["neutral"], "anti": st["anti"],
                    "headlines": [{"title": g["title"], "url": g["url"], "source": g["source"],
                                   "stance": g.get("stance")} for g in group[:6]]})
        if len(out) >= n:
            break
    return out


def mood_of(items):
    emo = Counter(i["emotion"] for i in items)
    pos = emo["joy"] + emo["hope"]
    neg = emo["anger"] + emo["fear"] + emo["sadness"]
    idx = round(100 * (pos - neg) / max(1, pos + neg))
    label = ("Upbeat" if idx > 30 else "Hopeful" if idx > 10 else "Mixed" if idx >= -10
             else "Tense" if idx >= -30 else "Angry / anxious")
    return {"index": idx, "label": label, "emotions": dict(emo), "sample": len(items)}


# ---------------------------------------------------------------- main build
_lock = threading.Lock()
STATE = {"data": None, "busy": False}


def build():
    status, t0 = {}, time.time()
    with ThreadPoolExecutor(3) as ex:
        f_news = ex.submit(collect_news, status)
        f_trends = ex.submit(collect_trends, status)
        f_reddit = ex.submit(collect_reddit_all, status)
        news = f_news.result()
        trends = f_trends.result()
        memes, social = f_reddit.result()

    news = [classify(i) for i in translate_items(news)]
    social = [classify(i) for i in translate_items(social)]
    memes = translate_items([m for m in memes if m.get("image")])
    memes.sort(key=lambda m: m["rank"])  # Reddit's own "top today" order
    trends = translate_items(trends)
    for t in trends:  # translate Punjabi coverage headlines too
        for n in t["news"]:
            n["title"] = translate(n["title"])[0] or n["title"]

    everything = news + social
    political = [i for i in everything if i["stance"]]
    stance = Counter(i["stance"] for i in political)
    mood = mood_of(everything)

    viral = trends[:25]
    reddit_top = sorted((s for s in social if s["rank"] < 8), key=lambda s: s["rank"])[:20]

    data = {
        "updated": int(time.time()), "took": round(time.time() - t0, 1), "status": status,
        "mood": mood,
        "stance": {"pro": stance["pro"], "neutral": stance["neutral"], "anti": stance["anti"]},
        "viral": viral, "reddit_top": reddit_top,
        "memes": memes[:60],
        "political": {k: sorted([i for i in political if i["stance"] == k], key=lambda x: -x["time"])[:60]
                      for k in ("pro", "neutral", "anti")},
        "topics": topics(news),
        "news": sorted(news, key=lambda x: -x["time"])[:120],
    }
    # history for the trend chart
    hist = []
    if os.path.exists(HISTORY_FILE):
        try:
            hist = json.load(open(HISTORY_FILE, encoding="utf-8"))
        except Exception:
            hist = []
    hist.append({"t": data["updated"], "mood": mood["index"], **data["stance"], "emotions": mood["emotions"]})
    hist = hist[-500:]
    data["history"] = hist
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    json.dump(hist, open(HISTORY_FILE, "w", encoding="utf-8"))
    json.dump(data, open(DATA_FILE, "w", encoding="utf-8"), ensure_ascii=False)
    return data


def refresh():
    with _lock:
        if STATE["busy"]:
            return
        STATE["busy"] = True
    try:
        print(time.strftime("%H:%M"), "collecting...")
        STATE["data"] = build()
        d = STATE["data"]
        print(f"  done in {d['took']}s: {len(d['news'])} news, {len(d['memes'])} memes, "
              f"{len(d['viral'])} trends, mood {d['mood']['index']} ({d['mood']['label']})")
    except Exception as e:
        print("  refresh failed:", e)
    finally:
        STATE["busy"] = False


def loop():
    while True:
        refresh()
        time.sleep(REFRESH_MINUTES * 60)


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=APP_DIR, **kw)

    def log_message(self, *a):
        pass

    def end_headers(self):
        self.send_header("Cache-Control", "no-cache")  # always pick up app updates
        super().end_headers()

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/api/data"):
            d = STATE["data"]
            if d is None and os.path.exists(DATA_FILE):
                d = json.load(open(DATA_FILE, encoding="utf-8"))
            if d is None:
                return self._json({"loading": True}, 202)
            return self._json({**d, "busy": STATE["busy"]})
        return super().do_GET()

    def do_POST(self):
        if self.path.startswith("/api/refresh"):
            threading.Thread(target=refresh, daemon=True).start()
            return self._json({"ok": True})
        self.send_error(404)


def local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


if __name__ == "__main__":
    import sys
    if "--once" in sys.argv:
        # Used by the GitHub timer: collect once, save the results next to the app, exit.
        d = build()
        json.dump(d, open(os.path.join(APP_DIR, "data.json"), "w", encoding="utf-8"), ensure_ascii=False)
        print(f"done in {d['took']}s: {len(d['news'])} news, {len(d['memes'])} memes, "
              f"{len(d['viral'])} trends, mood {d['mood']['index']}")
        print("sources:", json.dumps(d["status"]))
        sys.exit(0)
    threading.Thread(target=loop, daemon=True).start()
    print("\nNation Pulse is running.")
    print(f"  On this PC:            http://localhost:{PORT}")
    print(f"  On phone/tablet (Wi-Fi): http://{local_ip()}:{PORT}\n")
    print("Keep this window open. Press Ctrl+C to stop.\n")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
