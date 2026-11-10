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
NEWS_FEEDS = [  # (name, url) - English and Punjabi, a spread of outlets from all sides
    ("Google News India", f"{GN}?hl=en-IN&gl=IN&ceid=IN:en"),
    ("Google News India", f"{GN}/headlines/section/topic/NATION?hl=en-IN&gl=IN&ceid=IN:en"),
    ("Google News Punjabi", f"{GN}?hl=pa&gl=IN&ceid=IN:pa"),
    ("Google News India", f"{GN}/search?q=government+OR+Modi+OR+opposition+when:2d&hl=en-IN&gl=IN&ceid=IN:en"),
    ("Google News India", f"{GN}/search?q=Punjab+when:2d&hl=en-IN&gl=IN&ceid=IN:en"),
    ("The Hindu", "https://www.thehindu.com/news/national/feeder/default.rss"),
    ("Indian Express", "https://indianexpress.com/section/india/feed/"),
    ("NDTV", "https://feeds.feedburner.com/ndtvnews-india-news"),
    ("Times of India", "https://timesofindia.indiatimes.com/rssfeeds/-2128936835.cms"),
    ("Hindustan Times", "https://www.hindustantimes.com/feeds/rss/india-news/rssfeed.xml"),
    ("India Today", "https://www.indiatoday.in/rss/1206578"),
    ("News18", "https://www.news18.com/commonfeeds/v1/eng/rss/india.xml"),
    ("Firstpost", "https://www.firstpost.com/commonfeeds/v1/mfp/rss/india.xml"),
    ("ThePrint", "https://theprint.in/category/politics/feed/"),
    ("Scroll", "https://feeds.feedburner.com/ScrollinArticles.rss"),
    ("OpIndia", "https://www.opindia.com/feed/"),
    ("Swarajya", "https://prod-qt-images.s3.amazonaws.com/production/swarajya/feed.xml"),
    ("The Wire", "https://thewire.in/rss"),
    ("Hindustan Times Punjab", "https://www.hindustantimes.com/feeds/rss/cities/chandigarh-news/rssfeed.xml"),
    ("Indian Express Punjab", "https://indianexpress.com/section/cities/chandigarh/feed/"),
    ("Times of India Punjab", "https://timesofindia.indiatimes.com/rssfeeds/-2128816762.cms"),
]
PER_FEED = 30  # newest items taken from each feed
MARKET_NEWS_FEEDS = [
    ("Economic Times Markets", "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms"),
    ("Livemint Markets", "https://www.livemint.com/rss/markets"),
    ("Business Standard Markets", "https://www.business-standard.com/rss/markets-106.rss"),
    ("Moneycontrol", "https://www.moneycontrol.com/rss/marketreports.xml"),
]
MARKET_INDICES = [  # Yahoo Finance symbols (free, no key)
    ("^NSEI", "Nifty 50"), ("^BSESN", "Sensex"), ("^NSEBANK", "Bank Nifty"), ("^CNXIT", "Nifty IT"),
    ("^INDIAVIX", "India VIX (fear gauge)"), ("INR=X", "US Dollar → Rupee"), ("GC=F", "Gold ($/oz)"),
    ("BZ=F", "Brent crude ($/barrel)"),
]
NIFTY50 = """ADANIENT ADANIPORTS APOLLOHOSP ASIANPAINT AXISBANK BAJAJ-AUTO BAJFINANCE BAJAJFINSV BEL BHARTIARTL
CIPLA COALINDIA DRREDDY EICHERMOT ETERNAL GRASIM HCLTECH HDFCBANK HDFCLIFE HEROMOTOCO HINDALCO HINDUNILVR ICICIBANK
INDUSINDBK INFY ITC JIOFIN JSWSTEEL KOTAKBANK LT M&M MARUTI NESTLEIND NTPC ONGC POWERGRID RELIANCE SBILIFE SBIN
SHRIRAMFIN SUNPHARMA TATACONSUM TATAMOTORS TATASTEEL TCS TECHM TITAN TRENT ULTRACEMCO WIPRO""".split()
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
def clean_text(s, n=220):
    s = re.sub(r"<[^>]+>", " ", html.unescape(s or ""))
    s = re.sub(r"\s+", " ", html.unescape(s)).strip()
    return s[:n]


OUTLET_ALIASES = {  # Google News names -> the names used for direct feeds
    "The Times of India": "Times of India", "The Indian Express": "Indian Express",
    "The Economic Times": "Economic Times", "NDTV.com": "NDTV", "India Today NE": "India Today",
    "The Hindustan Times": "Hindustan Times", "News18.com": "News18", "Firstpost.com": "Firstpost",
}


def read_feed(name, url, per):
    """Read one RSS feed -> list of items (newest first)."""
    root = ET.fromstring(fetch(url))
    out = []
    for it in list(root.iter("item"))[:per]:
        title = clean_text(it.findtext("title"), 300)
        src = it.findtext("source") or ""
        if src and title.endswith(" - " + src):
            title = title[: -len(src) - 3]
        summary = clean_text(it.findtext("description"))
        if summary.lower().startswith(title.lower()[:40]) or "news.google" in url:
            summary = ""  # Google News descriptions just repeat the headline
        src = OUTLET_ALIASES.get(src, src)
        out.append({"title": title, "summary": summary, "source": src or name, "platform": "news",
                    "feed": name, "url": (it.findtext("link") or "").strip(),
                    "time": to_ts(it.findtext("pubDate") or "")})
    return out


def collect_news(status, feeds=NEWS_FEEDS, per=PER_FEED):
    def one(f):
        try:
            return f[0], read_feed(f[0], f[1], per), None
        except Exception as e:
            return f[0], [], str(e)[:80]
    items, seen = [], set()
    with ThreadPoolExecutor(8) as ex:
        results = list(ex.map(one, feeds))
    for name, got, err in results:
        if err:
            status[name + " (error)"] = err
            continue
        n = 0
        for it in got:
            key = re.sub(r"\W+", "", it["title"].lower())[:80]
            if not it["title"] or key in seen:
                continue
            seen.add(key)
            items.append(it)
            n += 1
        status[name] = status.get(name, 0) + n
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


# ---------------------------------------------------------------- AI sorting (free GitHub Models)
# Reads each headline's wording and framing - much better than keywords. Uses GitHub's free AI
# models: inside GitHub Actions the built-in token works; at home it borrows the `gh` login.
# Results are cached so each headline is only sent once. If the AI is unavailable, the keyword
# rules above are used instead.
AI_ENDPOINTS = [  # (address, model) - tried in order until one answers
    ("https://models.github.ai/inference/chat/completions", "openai/gpt-4.1-mini"),
    ("https://models.github.ai/inference/chat/completions", "openai/gpt-4o-mini"),
    ("https://models.inference.ai.azure.com/chat/completions", "gpt-4o-mini"),
]
AI_BATCH = 40
AI_MAX_CALLS = 10          # per update; free limit is ~150 calls a day
AI_CACHE_FILE = os.path.join(HERE, "data", "ai_cache.json")
AI_PROMPT = """You label Indian news headlines and social posts for a dashboard about the national mood.
For each numbered item return one object:
{"i": <number>, "stance": "pro"|"anti"|"neutral"|"none", "govt": "Centre" or a state name or "",
 "kind": "report"|"analysis"|"opinion", "emotion": "joy"|"hope"|"calm"|"fear"|"anger"|"sadness",
 "reason": "<why, at most 12 words>"}

stance = the item's slant toward the government in power that it is about (the Union Government of
India, or a state government when the story is about a state):
- "pro": praises or promotes the government or ruling party, presents its actions or claims as
  achievements without scrutiny, or attacks its critics and the opposition.
- "anti": criticises the government or ruling party, highlights its failures, scandals or broken
  promises, or mainly amplifies opposition or protest attacks on it.
- "neutral": about government, politics or policy but factual, balanced, or independent analysis
  that weighs evidence or both sides.
- "none": not about government, politics or policy (crime, accidents, sport, weather, films,
  business, foreign news not involving India's government).
Judge the wording and framing only, never your own opinion of the parties.
govt: which government the stance concerns ("" when stance is none).
kind: "analysis" for explainers or data-led pieces, "opinion" for columns/editorials, else "report".
emotion: the main feeling the item would cause in Indian readers.
Return ONLY a JSON array with one object per item, no other text."""
_ai = {"token": None, "model": None, "dead": False}


def ai_token():
    if _ai["token"] is None:
        tok = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_MODELS_TOKEN") or ""
        if not tok:
            import subprocess
            for exe in ("gh", r"C:\Program Files\GitHub CLI\gh.exe"):
                try:
                    tok = subprocess.run([exe, "auth", "token"], capture_output=True, text=True,
                                         timeout=10).stdout.strip()
                    if tok:
                        break
                except Exception:
                    pass
        _ai["token"] = tok
    return _ai["token"]


def ai_call(text):
    """Send one batch to the AI; tries each model until one answers."""
    endpoints = [_ai["model"]] if _ai["model"] else AI_ENDPOINTS
    last = None
    for url, model in endpoints:
        body = {"model": model, "temperature": 0,
                "messages": [{"role": "system", "content": AI_PROMPT}, {"role": "user", "content": text}]}
        req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers={
            "Authorization": "Bearer " + ai_token(), "Content-Type": "application/json",
            "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "nation-pulse"})
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                raw = r.read().decode("utf-8", "replace")
            try:
                out = json.loads(raw)["choices"][0]["message"]["content"]
            except Exception:
                raise RuntimeError(f"unexpected reply {r.status}: {raw[:120]!r}")
            _ai["model"] = (url, model)
            return out
        except urllib.error.HTTPError as e:
            last = (last + " | " if last else "") + f"{model}: HTTP {e.code} {e.read()[:150]!r}"
            if e.code == 429:  # daily/minute limit reached - stop for this round
                raise RuntimeError(last)
        except Exception as e:
            last = (last + " | " if last else "") + f"{model}: {str(e)[:150]}"
    print("AI call failed:", last)
    raise RuntimeError(last)


def item_key(it):
    import hashlib
    return hashlib.sha1(it["title"].lower().encode("utf-8")).hexdigest()[:16]


def ai_classify(items, status):
    """Label items with the AI (cached). Returns how many items have AI labels."""
    try:
        cache = json.load(open(AI_CACHE_FILE, encoding="utf-8"))
    except Exception:
        cache = {}
    if ai_token() and not _ai["dead"]:
        todo = [it for it in items if item_key(it) not in cache]
        # likely-political and newest first, so the limited calls go where they matter
        todo.sort(key=lambda it: (not it.get("political"), -it["time"]))
        calls = 0
        for start in range(0, len(todo), AI_BATCH):
            if calls >= AI_MAX_CALLS:
                break
            batch = todo[start:start + AI_BATCH]
            lines = []
            for n, it in enumerate(batch, 1):
                extra = f" — {it['summary'][:180]}" if it.get("summary") else ""
                lines.append(f"{n}. {it['title']}{extra} [{it['source']}]")
            try:
                raw = ai_call("\n".join(lines))
                calls += 1
                arr = json.loads(raw[raw.index("["): raw.rindex("]") + 1])
                for r in arr:
                    n = int(r.get("i", 0))
                    if 1 <= n <= len(batch) and r.get("stance") in ("pro", "anti", "neutral", "none"):
                        cache[item_key(batch[n - 1])] = {
                            "s": r["stance"], "g": str(r.get("govt") or "")[:30],
                            "k": r.get("kind") if r.get("kind") in ("report", "analysis", "opinion") else "report",
                            "e": r.get("emotion") if r.get("emotion") in EMOTIONS or r.get("emotion") == "calm" else "calm",
                            "r": str(r.get("reason") or "")[:120], "t": int(time.time())}
            except Exception as e:
                status["AI sorting (error)"] = str(e)[:400]
                if "429" in str(e) or "401" in str(e) or "403" in str(e):
                    _ai["dead"] = "401" in str(e) or "403" in str(e)
                    break
            time.sleep(4)  # stay under the per-minute limit
        week_ago = time.time() - 7 * 86400
        cache = {k: v for k, v in cache.items() if v["t"] > week_ago}
        try:
            json.dump(cache, open(AI_CACHE_FILE, "w", encoding="utf-8"), ensure_ascii=False)
        except Exception:
            pass
    done = 0
    for it in items:
        c = cache.get(item_key(it))
        if not c:
            it["by"] = "keywords"
            continue
        it.update(stance=None if c["s"] == "none" else c["s"], govt=c["g"], kind=c["k"],
                  emotion=c["e"], why=[c["r"]] if c["r"] else [], by="ai")
        done += 1
    status["AI sorting"] = f"{done} of {len(items)} posts" + (f" ({_ai['model'][1]})" if _ai["model"] else "")
    return done


# ---------------------------------------------------------------- markets
BULL = [r"\bsurg", r"\brall", r"\bgain", r"\bjump", r"record high", r"\brise", r"\brises\b", r"\bsoar",
        r"\bclimb", r"\bbull", r"\bup\b", r"\bhigher\b", r"\bupgrade", r"\bbuy\b", r"\binflow", r"\brecover"]
BEAR = [r"\bfall", r"\bslump", r"\bcrash", r"\bdeclin", r"\bdrop", r"\bplung", r"\bslid", r"\bdown\b",
        r"\bbear", r"sell.?off", r"\blos(e|es|ses)\b", r"\blower\b", r"\bdowngrade", r"\boutflow", r"\bwea?k",
        r"\btumbl", r"\bsink", r"\bsell\b", r"\bpressure"]


def yahoo(url):
    return json.loads(fetch(url, 20).decode("utf-8"))


def pct_change(a, b):
    return round(100 * (a - b) / b, 2) + 0.0 if a is not None and b else None


def index_quote(sym, name):
    d = yahoo("https://query1.finance.yahoo.com/v8/finance/chart/" + urllib.parse.quote(sym)
              + "?range=3mo&interval=1d")["chart"]["result"][0]
    pts = [(t, c) for t, c in zip(d.get("timestamp") or [], d["indicators"]["quote"][0].get("close") or []) if c]
    while len(pts) > 2 and abs(pts[-1][1] - pts[-2][1]) < 1e-9:
        pts.pop()  # holidays repeat the last close - ignore those bars
    closes = [c for _, c in pts]
    last = d["meta"].get("regularMarketPrice") or closes[-1]
    prev = closes[-2] if len(closes) > 1 else None
    if abs(closes[-1] - last) > 1e-6 * last:
        prev = closes[-1]  # today's bar not in the series yet
    return {"symbol": sym, "name": name, "price": round(last, 2),
            "day": pct_change(last, prev),
            "month": pct_change(last, closes[-22] if len(closes) > 22 else closes[0]),
            "three_month": pct_change(last, closes[0]),
            "spark": [round(c, 2) for c in closes[-60:]],
            "as_of": pts[-1][0] if pts else None}


def collect_markets(status):
    out = {"indices": [], "gainers": [], "losers": [], "breadth": None, "news": [], "summary": ""}
    with ThreadPoolExecutor(6) as ex:
        futs = {ex.submit(index_quote, s, n): n for s, n in MARKET_INDICES}
        for f, n in futs.items():
            try:
                out["indices"].append(f.result())
            except Exception as e:
                status[f"Market {n} (error)"] = str(e)[:80]
    order = [n for _, n in MARKET_INDICES]
    out["indices"].sort(key=lambda q: order.index(q["name"]))
    # Nifty 50 movers
    movers = []
    syms = [s + ".NS" for s in NIFTY50]
    for i in range(0, len(syms), 20):
        try:
            res = yahoo("https://query1.finance.yahoo.com/v7/finance/spark?range=5d&interval=1d&symbols="
                        + urllib.parse.quote(",".join(syms[i:i + 20])))["spark"]["result"]
            for r in res:
                resp = (r.get("response") or [{}])[0]
                closes = [c for c in (resp.get("indicators", {}).get("quote", [{}])[0].get("close") or []) if c]
                last = resp.get("meta", {}).get("regularMarketPrice") or (closes[-1] if closes else None)
                prev = closes[-2] if len(closes) > 1 else None
                if closes and last and abs(closes[-1] - last) > 1e-9:
                    prev = closes[-1]
                ch = pct_change(last, prev)
                if ch is not None:
                    movers.append({"symbol": r["symbol"].replace(".NS", ""), "price": round(last, 2), "day": ch})
        except Exception as e:
            status["Market movers (error)"] = str(e)[:80]
    movers.sort(key=lambda m: -m["day"])
    out["gainers"] = movers[:5]
    out["losers"] = movers[::-1][:5]
    if movers:
        out["breadth"] = {"up": sum(m["day"] > 0 for m in movers), "down": sum(m["day"] < 0 for m in movers),
                          "total": len(movers)}
    status["Market prices"] = len(out["indices"]) + len(movers)
    # market news + tone
    news = collect_news(status, MARKET_NEWS_FEEDS, 15)
    bull = bear = 0
    for it in news:
        t = it["title"].lower()
        b, s = len(hits(BULL, t)), len(hits(BEAR, t))
        it["tone"] = "bullish" if b > s else "bearish" if s > b else "neutral"
        bull += it["tone"] == "bullish"
        bear += it["tone"] == "bearish"
    out["news"] = sorted(news, key=lambda x: -x["time"])[:40]
    out["news_tone"] = {"bullish": bull, "bearish": bear, "neutral": len(news) - bull - bear}
    # one-line summary
    idx = {q["name"]: q for q in out["indices"]}
    parts = []
    for n in ("Nifty 50", "Sensex"):
        q = idx.get(n)
        if q and q["day"] is not None:
            parts.append(f"{n} {'up' if q['day'] >= 0 else 'down'} {abs(q['day'])}% at {q['price']:,.0f}")
    if out["breadth"]:
        parts.append(f"{out['breadth']['up']} of {out['breadth']['total']} Nifty stocks rose")
    q = idx.get("US Dollar → Rupee")
    if q:
        parts.append(f"rupee at {q['price']:.2f} per dollar")
    out["summary"] = "; ".join(parts) + "." if parts else ""
    nifty = idx.get("Nifty 50")
    score = (nifty["day"] if nifty and nifty["day"] is not None else 0) * 40 + \
        (100 * (bull - bear) / max(1, bull + bear)) * 0.5
    out["mood"] = {"score": max(-100, min(100, round(score))),
                   "label": "Bullish" if score > 15 else "Bearish" if score < -15 else "Flat / cautious"}
    if nifty and nifty.get("as_of"):
        out["as_of"] = nifty["as_of"]
    return out


# ---------------------------------------------------------------- Instagram, X, Facebook (Apify free plan)
# Apify gives $5 of free usage a month. We scrape once a day, small amounts (~$3.25/month),
# and stop completely once the month's usage passes APIFY_BUDGET_USD.
APIFY_BUDGET_USD = 4.50
SOCIAL_EVERY_HOURS = 22
SOCIAL_CACHE_FILE = os.path.join(HERE, "data", "social_cache.json")
APIFY_JOBS = [
    {"name": "Instagram", "platform": "instagram", "actor": "apify~instagram-hashtag-scraper", "max_usd": 0.06,
     "input": {"hashtags": ["india", "indianpolitics"], "resultsType": "posts", "resultsLimit": 10}},
    {"name": "Instagram memes", "platform": "instagram", "meme": True, "actor": "apify~instagram-hashtag-scraper",
     "max_usd": 0.04, "input": {"hashtags": ["indianmemes"], "resultsType": "posts", "resultsLimit": 10}},
    {"name": "X", "platform": "x", "actor": "kaitoeasyapi~twitter-x-data-tweet-scraper-pay-per-result-cheapest",
     "max_usd": 0.03, "input": {"searchTerms": ["(Modi OR government OR BJP OR Congress OR opposition) India min_faves:500",
                                               "Punjab min_faves:100"],
                                "maxItems": 20, "queryType": "Top", "lang": "en"}},
    {"name": "Facebook", "platform": "facebook", "actor": "alfalfa~facebook-posts-scraper", "max_usd": 0.04,
     "input": {"startUrls": [{"url": "https://www.facebook.com/BJP4India"},
                             {"url": "https://www.facebook.com/INCIndia"},
                             {"url": "https://www.facebook.com/AamAadmiParty"},
                             {"url": "https://www.facebook.com/NDTV"},
                             {"url": "https://www.facebook.com/IndiaToday"}],
               "resultsLimit": 2, "onlyPostsNewerThan": "2 days"}},
]


def apify(path, token, body=None, timeout=60):
    url = "https://api.apify.com/v2/" + path
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8") if body is not None else None,
                                 headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def num(*vals):
    for v in vals:
        if isinstance(v, (int, float)) and v >= 0:
            return int(v)
    return 0


def social_item(job, r):
    """Turn one scraped record into the app's common post format."""
    p = job["platform"]
    if p == "instagram":
        text, who = r.get("caption") or "", "@" + (r.get("ownerUsername") or "instagram")
        likes, comments = num(r.get("likesCount")), num(r.get("commentsCount"))
        shares, views = num(r.get("sharesCount"), r.get("reshareCount")), num(r.get("videoViewCount"), r.get("videoPlayCount"))
        image, ts = r.get("displayUrl"), r.get("timestamp")
    elif p == "x":
        a = r.get("author") or {}
        text, who = r.get("text") or "", "@" + (a.get("userName") or "x")
        likes, comments = num(r.get("likeCount")), num(r.get("replyCount"))
        shares, views = num(r.get("retweetCount")) + num(r.get("quoteCount")), num(r.get("viewCount"))
        media = r.get("media") or []
        image = (media[0].get("media_url_https") or media[0].get("url")) if media and isinstance(media[0], dict) else None
        ts = r.get("createdAt")
    else:
        text, who = r.get("text") or "", r.get("pageName") or (r.get("user") or {}).get("name") or "Facebook"
        likes, comments = num(r.get("likes"), r.get("topReactionsCount")), num(r.get("comments"))
        shares, views = num(r.get("shares")), num(r.get("viewsCount"), r.get("videoPostViewCount"))
        media = r.get("media") or []
        image = media[0].get("thumbnail") if media and isinstance(media[0], dict) else None
        ts = r.get("time")
    text = re.sub(r"\s+", " ", text).strip()
    if not text and not image:
        return None
    t = to_ts(ts) if isinstance(ts, str) else (int(ts) if isinstance(ts, (int, float)) else int(time.time()))
    return {"title": text[:280] or "(image post)", "source": who, "platform": p, "url": r.get("url"),
            "image": image, "time": t, "likes": likes, "comments": comments, "shares": shares, "views": views,
            "engagement": likes + 2 * comments + 3 * shares, "meme": bool(job.get("meme"))}


def collect_social(status):
    """Instagram, X and Facebook via Apify - at most once a day, within the free $5."""
    try:
        cache = json.load(open(SOCIAL_CACHE_FILE, encoding="utf-8"))
    except Exception:
        cache = {"t": 0, "items": []}
    token = os.environ.get("APIFY_TOKEN", "").strip()
    if not token:
        status["Instagram/X/Facebook"] = "not set up (no Apify token)"
        return cache["items"]
    if time.time() - cache.get("t", 0) < SOCIAL_EVERY_HOURS * 3600:
        status["Instagram/X/Facebook"] = f"{len(cache['items'])} posts (saved, refreshed daily)"
        return cache["items"]
    try:
        lim = apify("users/me/limits", token)["data"]
        used = float(lim.get("current", {}).get("monthlyUsageUsd") or 0)
        cap = float(lim.get("limits", {}).get("maxMonthlyUsageUsd") or 5)
        status["Apify free credit used"] = f"${used:.2f} of ${cap:.2f}"
        if used >= min(APIFY_BUDGET_USD, cap - 0.4):
            status["Instagram/X/Facebook"] = "paused - this month's free credit is nearly used up"
            return cache["items"]
    except Exception as e:
        status["Apify (error)"] = str(e)[:100]
        return cache["items"]
    items = []
    for job in APIFY_JOBS:
        try:
            path = (f"acts/{job['actor']}/run-sync-get-dataset-items?timeout=240"
                    f"&maxTotalChargeUsd={job['max_usd']}&maxItems=60")
            rows = apify(path, token, job["input"], timeout=300)
            got = [x for x in (social_item(job, r) for r in rows if isinstance(r, dict) and not r.get("error")) if x]
            items += got
            status[job["name"]] = len(got)
        except urllib.error.HTTPError as e:
            status[job["name"] + " (error)"] = f"HTTP {e.code} {e.read()[:120]!r}"
        except Exception as e:
            status[job["name"] + " (error)"] = str(e)[:100]
    if items:  # only replace the saved copy when we actually got something
        cache = {"t": int(time.time()), "items": items}
        json.dump(cache, open(SOCIAL_CACHE_FILE, "w", encoding="utf-8"), ensure_ascii=False)
    return cache["items"]


def outlet_table(items, n=16):
    by = {}
    for it in items:
        if it.get("stance") and it["platform"] == "news":
            by.setdefault(it["source"], Counter())[it["stance"]] += 1
    rows = [{"source": s, "pro": c["pro"], "neutral": c["neutral"], "anti": c["anti"],
             "total": sum(c.values())} for s, c in by.items()]
    rows.sort(key=lambda r: -r["total"])
    return [r for r in rows if r["total"] >= 2][:n]


# ---------------------------------------------------------------- main build
_lock = threading.Lock()
STATE = {"data": None, "busy": False}


def build():
    status, t0 = {}, time.time()
    with ThreadPoolExecutor(5) as ex:
        f_news = ex.submit(collect_news, status)
        f_trends = ex.submit(collect_trends, status)
        f_reddit = ex.submit(collect_reddit_all, status)
        f_markets = ex.submit(collect_markets, status)
        f_apify = ex.submit(collect_social, status)
        news = f_news.result()
        trends = f_trends.result()
        memes, social = f_reddit.result()
        markets = f_markets.result()
        apify_posts = [dict(p) for p in f_apify.result()]

    news = [classify(i) for i in translate_items(news)]   # keyword rules first (backup)
    big3 = translate_items([p for p in apify_posts if not p.get("meme")])
    social = [classify(i) for i in translate_items(social)] + [classify(i) for i in big3]
    insta_memes = translate_items([p for p in apify_posts if p.get("meme") and p.get("image")])
    for n_, m in enumerate(sorted(insta_memes, key=lambda m: -m["engagement"])):
        m["rank"] = n_
    memes = memes + insta_memes
    ai_classify(news + social, status)                       # AI labels replace them where available
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
    reddit_top = sorted((s for s in social if s.get("platform") == "reddit" and s["rank"] < 8),
                        key=lambda s: s["rank"])[:20]
    top_social = {p: sorted([s for s in social if s.get("platform") == p], key=lambda s: -s["engagement"])[:12]
                  for p in ("instagram", "x", "facebook")}

    data = {
        "updated": int(time.time()), "took": round(time.time() - t0, 1), "status": status,
        "mood": mood,
        "stance": {"pro": stance["pro"], "neutral": stance["neutral"], "anti": stance["anti"]},
        "viral": viral, "reddit_top": reddit_top, "top_social": top_social,
        "memes": memes[:60],
        "political": {k: sorted([i for i in political if i["stance"] == k], key=lambda x: -x["time"])[:60]
                      for k in ("pro", "neutral", "anti")},
        "topics": topics(news),
        "news": sorted(news, key=lambda x: -x["time"])[:200],
        "outlets": outlet_table(news),
        "markets": markets,
    }
    for lst in (data["news"], *data["political"].values()):
        for it in lst:
            it.pop("summary", None)  # keep the file small
    # history for the trend chart
    hist = []
    if os.path.exists(HISTORY_FILE):
        try:
            hist = json.load(open(HISTORY_FILE, encoding="utf-8"))
        except Exception:
            hist = []
    nifty = next((q for q in markets["indices"] if q["name"] == "Nifty 50"), None)
    hist.append({"t": data["updated"], "mood": mood["index"], **data["stance"], "emotions": mood["emotions"],
                 "nifty": nifty["price"] if nifty else None, "market": markets.get("mood", {}).get("score")})
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
