// Nation Pulse - front end. Reads /api/data from the home server and draws five tabs.
const $ = (s) => document.querySelector(s);
const view = $("#view");
let DATA = null;
let tab = "pulse";
let polSide = "pro";
let newsFilter = "all";
// Online (GitHub Pages) the app reads a saved file; at home it asks the PC server.
const ONLINE = location.hostname.endsWith("github.io");
const DATA_URL = ONLINE ? "data.json" : "/api/data";
if (ONLINE) $("#refresh").style.display = "none";

const TITLES = { pulse: "Mood of the nation", viral: "Most viral today", memes: "Funniest memes",
  politics: "Government vs opposition", markets: "Markets & money", news: "News narratives" };
const STANCE = { pro: "Pro-government", neutral: "Independent / neutral", anti: "Anti-government" };
const STANCE_SHORT = { pro: "Pro-govt", neutral: "Independent", anti: "Anti-govt" };
const EMO = ["joy", "hope", "calm", "fear", "anger", "sadness"];
const EMO_LABEL = { joy: "Joy", hope: "Hope", calm: "Calm", fear: "Worry", anger: "Anger", sadness: "Sadness" };
const LANG = { hi: "Hindi", pa: "Punjabi" };
const PLATFORM = { reddit: "Reddit", instagram: "Instagram", x: "X", facebook: "Facebook" };
const short = (n) => (n >= 1e7 ? (n / 1e7).toFixed(1) + " Cr" : n >= 1e5 ? (n / 1e5).toFixed(1) + " L" : n >= 1e3 ? (n / 1e3).toFixed(1) + "K" : String(n || 0));

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const ago = (ts) => {
  const m = Math.max(0, Math.round((Date.now() / 1000 - ts) / 60));
  if (m < 60) return m + "m ago";
  if (m < 1440) return Math.round(m / 60) + "h ago";
  return Math.round(m / 1440) + "d ago";
};
const pct = (n, t) => (t ? Math.round((100 * n) / t) : 0);
const link = (url) => (url ? `href="${esc(url)}" target="_blank" rel="noopener noreferrer"` : "");

// ---------------------------------------------------------------- data
async function load() {
  try {
    const r = await fetch(DATA_URL, { cache: "no-store" });
    const d = await r.json();
    if (d.loading) {
      view.innerHTML = `<div class="loader"></div><div class="empty">Collecting the first batch of posts…<br>This takes about a minute.</div>`;
      $("#updated").textContent = "First collection running";
      setTimeout(load, 5000);
      return;
    }
    DATA = d;
    $("#refresh").classList.toggle("spin", !!d.busy);
    if (d.busy) setTimeout(load, 6000);
    render();
  } catch (e) {
    $("#updated").textContent = ONLINE ? "No data yet — the first collection is still running." : "Can't reach the server — is it running on your PC?";
    setTimeout(load, 10000);
  }
}

$("#refresh").onclick = async () => {
  $("#refresh").classList.add("spin");
  await fetch("/api/refresh", { method: "POST" }).catch(() => {});
  setTimeout(load, 3000);
};

document.querySelectorAll("#nav button").forEach((b) =>
  (b.onclick = () => {
    tab = b.dataset.tab;
    document.querySelectorAll("#nav button").forEach((x) => x.classList.toggle("active", x === b));
    try { localStorage.setItem("tab", tab); } catch {}
    render();
    window.scrollTo(0, 0);
  })
);
try {
  const saved = localStorage.getItem("tab");
  if (saved && TITLES[saved]) document.querySelector(`#nav button[data-tab="${saved}"]`).click();
} catch {}

function render() {
  $("#title").textContent = TITLES[tab];
  if (!DATA) return;
  const d = new Date(DATA.updated * 1000);
  $("#updated").textContent = `Updated ${d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })} · ${ago(DATA.updated)}`;
  view.innerHTML = (DATA.busy ? `<div class="loader"></div>` : "") + { pulse, viral, memes, politics, markets, news }[tab]();
  // red dot on Markets when there's a big move from the last 24 hours
  const fresh = (DATA.markets?.analysis?.alerts || []).some((x) => Date.now() / 1000 - x.t < 86400);
  document.querySelector('#nav [data-tab="markets"]').classList.toggle("badge", fresh);
  bind();
}

// ---------------------------------------------------------------- pieces
function itemHTML(i, showStance = true) {
  return `<a class="item" ${link(i.url)}>
    <div class="t">${esc(i.title)}</div>
    ${i.original ? `<div class="orig">${esc(i.original)}</div>` : ""}
    <div class="meta">
      ${showStance && i.stance ? `<span class="pill ${i.stance}">${STANCE_SHORT[i.stance]}${i.govt ? " · " + esc(i.govt) : ""}</span>` : ""}
      ${i.kind && i.kind !== "report" ? `<span class="tag">${i.kind === "analysis" ? "Analysis" : "Opinion"}</span>` : ""}
      <span>${esc(i.source)}</span><span>·</span><span>${ago(i.time)}</span>
      ${i.lang ? `<span class="tag">Translated from ${LANG[i.lang] || "Punjabi"}</span>` : ""}
      ${PLATFORM[i.platform] ? `<span class="tag">${PLATFORM[i.platform]}</span>` : ""}
    </div>
    ${showStance ? whyHTML(i) : ""}
  </a>`;
}

function whyHTML(i) {
  if (!i.why || !i.why.length) return "";
  return i.by === "ai"
    ? `<div class="why"><span class="tag">AI</span> ${esc(i.why.join(", "))}</div>`
    : `<div class="why">Keywords: <b>${esc(i.why.join(", "))}</b></div>`;
}

function stackHTML(s, labels = true) {
  const t = s.pro + s.neutral + s.anti;
  return `<div class="stack">
    ${["pro", "neutral", "anti"].map((k) => {
      const p = pct(s[k], t);
      const c = { pro: "var(--pro)", neutral: "var(--neu)", anti: "var(--anti)" }[k];
      return p ? `<div style="width:${p}%;background:${c}">${labels && p > 8 ? p + "%" : ""}</div>` : "";
    }).join("")}
  </div>`;
}

function lineChart(points, key, opts = {}) {
  // points: [{t, ...}]; draws a simple SVG line chart
  const W = 600, H = 150, P = 24;
  if (points.length < 2)
    return `<div class="empty" style="padding:24px 0">The trend line appears after a few updates.</div>`;
  const lo = opts.min ?? Math.min(...points.map((p) => p[key])), hi = opts.max ?? Math.max(...points.map((p) => p[key]));
  const x = (i) => P + (i * (W - 2 * P)) / (points.length - 1);
  const y = (v) => H - P - ((v - lo) / (hi - lo || 1)) * (H - 2 * P);
  const path = points.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p[key]).toFixed(1)}`).join("");
  const zero = opts.zero ? `<line x1="${P}" x2="${W - P}" y1="${y(0)}" y2="${y(0)}" stroke="var(--line)" stroke-dasharray="4 4"/>` : "";
  const fmt = (t) => new Date(t * 1000).toLocaleString([], { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
  return `<svg class="chart" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">
    ${zero}
    <path d="${path}" stroke="${opts.color || "var(--accent)"}" stroke-width="2.5" vector-effect="non-scaling-stroke"/>
    <circle cx="${x(points.length - 1)}" cy="${y(points.at(-1)[key])}" r="4" fill="${opts.color || "var(--accent)"}" stroke="none"/>
  </svg>
  <div class="scale"><span>${fmt(points[0].t)}</span><span>${fmt(points.at(-1).t)}</span></div>`;
}

// ---------------------------------------------------------------- tabs
function pulse() {
  const m = DATA.mood, s = DATA.stance, total = s.pro + s.neutral + s.anti;
  const emoTotal = Object.values(m.emotions).reduce((a, b) => a + b, 0);
  const hist = (DATA.history || []).slice(-60);
  const histShare = hist.map((h) => {
    const t = h.pro + h.neutral + h.anti || 1;
    return { t: h.t, anti: Math.round((100 * h.anti) / t), pro: Math.round((100 * h.pro) / t) };
  });
  return `
  ${briefHTML()}
  <div class="grid two">
    <div class="card">
      <h2>Overall mood</h2><p class="muted">From ${m.sample} news headlines and social posts</p>
      <div class="mood">
        <div class="big" style="color:${m.index >= 0 ? "var(--joy)" : "var(--anger)"}">${m.index > 0 ? "+" : ""}${m.index}</div>
        <div><div class="label">${esc(m.label)}</div><div class="muted">Scale −100 (angry) to +100 (upbeat)</div></div>
      </div>
      <div class="gauge"><i style="left:${(m.index + 100) / 2}%"></i></div>
      <div class="scale"><span>Angry</span><span>Mixed</span><span>Upbeat</span></div>
    </div>
    <div class="card">
      <h2>Emotions in the conversation</h2><p class="muted">Share of all posts</p>
      <div class="bars">
        ${EMO.map((e) => `<div class="bar-row"><span>${EMO_LABEL[e]}</span>
          <div class="track"><div class="fill" style="width:${pct(m.emotions[e] || 0, emoTotal)}%;background:var(--${e})"></div></div>
          <span class="n">${pct(m.emotions[e] || 0, emoTotal)}%</span></div>`).join("")}
      </div>
    </div>
    <div class="card">
      <h2>Political tone</h2><p class="muted">${total} posts about government and politics</p>
      ${stackHTML(s)}
      <div class="legend">
        <span style="--c:var(--pro)">${STANCE.pro} · ${s.pro}</span>
        <span style="--c:var(--neu)">${STANCE.neutral} · ${s.neutral}</span>
        <span style="--c:var(--anti)">${STANCE.anti} · ${s.anti}</span>
      </div>
    </div>
    <div class="card">
      <h2>Mood over time</h2><p class="muted">One point per update</p>
      ${lineChart(hist, "mood", { min: -100, max: 100, zero: true })}
    </div>
    <div class="card">
      <h2>Anti-government share over time</h2><p class="muted">Rising line = more criticism of government</p>
      ${lineChart(histShare, "anti", { min: 0, max: 100, color: "var(--anti)" })}
    </div>
    <div class="card">
      <h2>What India is talking about</h2><p class="muted">Most-mentioned words in headlines — tap for details in News</p>
      <div class="chips">${DATA.topics.slice(0, 12).map((t) => `<button class="chip" data-goto="news">${esc(t.word)} <b>${t.count}</b></button>`).join("")}</div>
    </div>
  </div>
  <div class="note"><b>How the sorting works:</b> an AI reads each headline and its summary and judges its framing:
  <b>pro-government</b> (praises the government or attacks its critics), <b>anti-government</b> (criticises it or amplifies
  attacks on it) or <b>independent</b> (factual, balanced or analytical). It also notes which government — the Centre or a
  state — and gives a one-line reason, marked <span class="tag">AI</span>. Posts the AI hasn't reached yet use keyword
  rules and show the keywords. ${esc(DATA.status?.["AI sorting"] ? "This round: AI sorted " + DATA.status["AI sorting"] + "." : "")}
  It's an estimate of tone, not a fact-check.</div>
  ${sources()}`;
}

// ---------------------------------------------------------------- today's brief (summary on the front page)
function briefHTML() {
  const d = DATA, lines = [];
  const m = d.mood, emo = Object.entries(m.emotions || {}).filter(([k]) => k !== "calm").sort((a, b) => b[1] - a[1]);
  const tops = (d.topics || []).slice(0, 3).map((t) => t.word);
  const feel = emo.length ? EMO_LABEL[emo[0][0]].toLowerCase() + (emo[1] ? " and " + EMO_LABEL[emo[1][0]].toLowerCase() : "") : "calm";
  lines.push(["🧭", `Mood is <b>${esc(m.label.toLowerCase())}</b> (${m.index > 0 ? "+" : ""}${m.index}). Strongest feelings: ${esc(feel)}.`]);
  if (tops.length) lines.push(["📰", `Most talked-about: <b>${tops.map((w) => esc(w[0].toUpperCase() + w.slice(1))).join(", ")}</b>.`]);

  const s = d.stance, tot = s.pro + s.neutral + s.anti;
  if (tot) {
    const h = d.history || [], prev = h.length > 1 ? h[h.length - 2] : null;
    let trend = "";
    if (prev) {
      const before = prev.anti / Math.max(1, prev.pro + prev.neutral + prev.anti), now = s.anti / tot;
      trend = now > before + 0.03 ? " Criticism of government is <b>rising</b>." : now < before - 0.03 ? " Criticism of government is <b>easing</b>." : "";
    }
    const lean = s.anti > s.pro * 1.3 ? "leans critical of government" : s.pro > s.anti * 1.3 ? "leans pro-government" : "is fairly balanced";
    lines.push(["⚖️", `Political coverage ${lean}: ${pct(s.pro, tot)}% pro, ${pct(s.neutral, tot)}% independent, ${pct(s.anti, tot)}% anti.${trend}`]);
  }

  const v = (d.viral || [])[0];
  const soc = Object.values(d.top_social || {}).flat().sort((a, b) => b.engagement - a.engagement)[0];
  const vt = v ? (v.title.length > 55 ? v.title.slice(0, 55) + "…" : v.title) : "";
  if (v || soc) lines.push(["🔥", [v ? `Top search: <b>${esc(vt[0].toUpperCase() + vt.slice(1))}</b> (${esc(v.traffic)} searches)` : "",
    soc ? `most-engaged post: ${esc(soc.source)} on ${PLATFORM[soc.platform]} (${short(soc.likes)} likes)` : ""].filter(Boolean).join("; ") + "."]);

  const mk = d.markets;
  if (mk && mk.indices?.length) {
    const n = mk.indices.find((q) => q.name === "Nifty 50");
    const a = mk.analysis, big = (a?.alerts || []).filter((x) => Date.now() / 1000 - x.t < 86400).sort((p, q) => Math.abs(q.size) - Math.abs(p.size))[0];
    let t = `Markets: <b>${esc(mk.mood.label.toLowerCase())}</b>`;
    if (n) t += `, Nifty ${Math.abs(n.day ?? 0) < 0.05 ? "flat" : (n.day > 0 ? "up " : "down ") + Math.abs(n.day).toFixed(2) + "%"} (${n.month >= 0 ? "+" : ""}${n.month}% this month)`;
    if (a?.record?.count && Math.abs(a.record.avg) >= 0.01) t += `; watchlist picks ${a.record.avg >= 0 ? "+" : ""}${a.record.avg}% on average`;
    if (big) t += `; biggest move: ${esc(big.text)}`;
    lines.push(["📈", t + "."]);
  }
  return `<div class="card brief">
    <h2>Today's brief</h2>
    ${lines.map(([ic, t]) => `<div class="bline"><span>${ic}</span><p>${t}</p></div>`).join("")}
  </div>`;
}

function sources() {
  const st = DATA.status || {};
  const ok = Object.entries(st).filter(([k]) => !k.includes("(error)") && !k.startsWith("AI"));
  const bad = Object.keys(st).filter((k) => k.includes("(error)")).map((k) => k.replace(" (error)", ""));
  return `<div class="note"><b>Sources this round:</b> ${ok.map(([k, v]) => `${esc(k)} (${v})`).join(", ")}
  ${bad.length ? `<br><b>Didn't respond:</b> ${esc(bad.join(", "))} — they'll be retried next refresh.` : ""}
  ${st["Instagram/X/Facebook"] ? `<br><b>Instagram, X, Facebook:</b> ${esc(st["Instagram/X/Facebook"])}` : ""}
  ${st["Apify free credit used"] ? ` · free credit used ${esc(st["Apify free credit used"])}` : ""}</div>`;
}

function socialCard(p, title) {
  const list = (DATA.top_social || {})[p] || [];
  return `<div class="card">
    <h2>${title}</h2><p class="muted">Most liked, commented and shared — collected once a day</p>
    ${list.length ? list.map((s) => `<a class="social" ${link(s.url)}>
      ${s.image ? `<img src="${esc(s.image)}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.remove()">` : ""}
      <div><div class="t">${esc(s.title.length > 160 ? s.title.slice(0, 160) + "…" : s.title)}</div>
        <div class="meta">${s.stance ? `<span class="pill ${s.stance}">${STANCE_SHORT[s.stance]}</span>` : ""}
          <span>${esc(s.source)}</span><span>·</span><span>${ago(s.time)}</span></div>
        <div class="eng">❤ ${short(s.likes)} · 💬 ${short(s.comments)} · ↻ ${short(s.shares)}${s.views ? ` · ▶ ${short(s.views)}` : ""}</div>
      </div></a>`).join("") : `<div class="empty">Not collected yet — appears after the daily update.</div>`}
  </div>`;
}

function viral() {
  const tr = DATA.viral || [], rd = DATA.reddit_top || [];
  const hasSocial = Object.values(DATA.top_social || {}).some((l) => l.length);
  return `${hasSocial ? `<div class="grid auto" style="margin-bottom:14px">
    ${socialCard("x", "Top on X")}${socialCard("instagram", "Top on Instagram")}${socialCard("facebook", "Top on Facebook")}
  </div>` : ""}
  <div class="grid two">
    <div class="card">
      <h2>Top Google searches</h2><p class="muted">India, Punjab, Delhi and Chandigarh — English and Punjabi only</p>
      ${tr.length ? tr.map((t, n) => `<a class="trend" ${link(t.news[0]?.url || t.url)}>
        <div class="rank">${n + 1}</div>
        <div><div class="t" style="font-weight:700">${esc(t.title)}</div>
          <div class="traffic">${esc(t.traffic)} searches <span class="tag">${esc((t.regions || ["India"]).join(", "))}</span>${t.lang ? ` <span class="tag">Translated from Punjabi</span>` : ""}</div>
          ${t.news[0] ? `<div class="rel">${esc(t.news[0].title)} — ${esc(t.news[0].source)}</div>` : ""}</div>
        ${t.image ? `<img src="${esc(t.image)}" alt="" loading="lazy" referrerpolicy="no-referrer">` : "<span></span>"}
      </a>`).join("") : `<div class="empty">No trends this round.</div>`}
    </div>
    <div class="card">
      <h2>Most upvoted on Reddit today</h2><p class="muted">Top posts from Indian communities in the last 24 hours</p>
      ${rd.length ? rd.map((i) => itemHTML(i, false)).join("") : `<div class="empty">Reddit didn't respond this round.</div>`}
    </div>
  </div>`;
}

function memes() {
  const ms = DATA.memes || [];
  if (!ms.length) return `<div class="empty">No memes this round — Reddit may be limiting requests. Tap refresh in a few minutes.</div>`;
  return `<p class="muted" style="margin:0 0 12px">Top-voted today on Indian meme communities</p>
  <div class="memes">${ms.map((m) => `<a class="meme" ${link(m.url)}>
    <img src="${esc(m.image)}" alt="${esc(m.title)}" loading="lazy" referrerpolicy="no-referrer" onerror="this.closest('.meme').remove()">
    <div class="cap">${esc(m.title)}${m.is_video ? " ▶" : ""}<div class="meta">${esc(m.source)} · ${ago(m.time)}${m.lang ? " · translated" : ""}</div></div>
  </a>`).join("")}</div>`;
}

function politics() {
  const p = DATA.political, s = DATA.stance;
  return `
  <div class="seg phone-only">${["pro", "neutral", "anti"].map((k) =>
    `<button data-side="${k}" class="${polSide === k ? "on" : ""}">${STANCE_SHORT[k]} (${s[k]})</button>`).join("")}</div>
  <div class="grid three">
    ${["pro", "neutral", "anti"].map((k) => `<div class="card pol-col ${k} ${polSide === k ? "" : "hide"}">
      <div class="col-head"><h2>${STANCE[k]}</h2><span class="n">${s[k]}</span></div>
      ${p[k].length ? p[k].map((i) => itemHTML(i, false).replace(/<\/a>$/, `${i.govt ? `<div class="why">About: <b>${esc(i.govt)} government</b></div>` : ""}${whyHTML(i)}</a>`)).join("")
        : `<div class="empty">Nothing here this round.</div>`}
    </div>`).join("")}
  </div>
  ${outlets()}`;
}

function outlets() {
  const rows = DATA.outlets || [];
  if (!rows.length) return "";
  return `<div class="section-title">Who says what — tone of each outlet's political stories</div>
  <div class="card">
    ${rows.map((r) => `<div class="outlet">
      <div class="oname">${esc(r.source)} <span class="muted">${r.total}</span></div>
      ${stackHTML(r, false)}
    </div>`).join("")}
    <div class="legend" style="margin-top:8px">
      <span style="--c:var(--pro)">Pro-govt</span><span style="--c:var(--neu)">Independent</span><span style="--c:var(--anti)">Anti-govt</span>
    </div>
    <p class="muted" style="margin-top:8px">Based only on today's headlines, so small numbers can swing a lot.</p>
  </div>`;
}

// ---------------------------------------------------------------- markets
const fmt = (n, d = 2) => (n == null ? "–" : Number(n).toLocaleString("en-IN", { maximumFractionDigits: d, minimumFractionDigits: d }));
const chg = (n) => (n == null ? `<span class="muted">–</span>` : `<span class="${n > 0 ? "up" : n < 0 ? "down" : "muted"}">${n > 0 ? "▲" : n < 0 ? "▼" : ""} ${Math.abs(n).toFixed(2)}%</span>`);

function spark(vals, color) {
  if (!vals || vals.length < 2) return "";
  const W = 120, H = 34, lo = Math.min(...vals), hi = Math.max(...vals);
  const p = vals.map((v, i) => `${i ? "L" : "M"}${((i * W) / (vals.length - 1)).toFixed(1)},${(H - 2 - ((v - lo) / (hi - lo || 1)) * (H - 4)).toFixed(1)}`).join("");
  return `<svg class="spark" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none"><path d="${p}" stroke="${color}" stroke-width="2" vector-effect="non-scaling-stroke"/></svg>`;
}

function markets() {
  const m = DATA.markets;
  if (!m || !m.indices?.length) return `<div class="empty">Market data didn't load this round — it will retry at the next update.</div>`;
  const asOf = m.as_of ? new Date(m.as_of * 1000).toLocaleDateString([], { weekday: "short", day: "numeric", month: "short" }) : "";
  const b = m.breadth, t = m.news_tone || {};
  const hist = (DATA.history || []).filter((h) => h.nifty).slice(-60);
  return `
  <div class="grid two">
    <div class="card">
      <h2>Market mood</h2><p class="muted">Last trading session${asOf ? " · " + asOf : ""}</p>
      <div class="mood">
        <div class="big" style="color:${m.mood.score >= 0 ? "var(--joy)" : "var(--anger)"}">${m.mood.score > 0 ? "+" : ""}${m.mood.score}</div>
        <div><div class="label">${esc(m.mood.label)}</div><div class="muted">From Nifty's move and market-news tone</div></div>
      </div>
      <p style="margin:14px 0 0">${esc(m.summary)}</p>
    </div>
    <div class="card">
      <h2>Breadth & news tone</h2><p class="muted">How many big stocks rose, and how market news reads</p>
      ${b ? `<div class="bar-row"><span>Nifty 50</span><div class="track"><div class="fill" style="width:${pct(b.up, b.total)}%;background:var(--joy)"></div></div><span class="n">${b.up}/${b.total}</span></div>` : ""}
      <div class="stack" style="margin-top:14px">
        ${[["bullish", "var(--joy)"], ["neutral", "var(--calm)"], ["bearish", "var(--anger)"]].map(([k, c]) => {
          const tot = (t.bullish || 0) + (t.neutral || 0) + (t.bearish || 0), p = pct(t[k] || 0, tot);
          return p ? `<div style="width:${p}%;background:${c}">${p > 10 ? p + "%" : ""}</div>` : "";
        }).join("")}
      </div>
      <div class="legend"><span style="--c:var(--joy)">Bullish ${t.bullish || 0}</span><span style="--c:var(--calm)">Neutral ${t.neutral || 0}</span><span style="--c:var(--anger)">Bearish ${t.bearish || 0}</span></div>
    </div>
  </div>
  <div class="section-title">Indices, rupee & commodities</div>
  <div class="tickers">
    ${m.indices.map((q) => `<div class="card ticker">
      <div class="tname">${esc(q.name)}</div>
      <div class="tprice">${fmt(q.price)}</div>
      <div class="trow">${chg(q.day)} <span class="muted">day</span></div>
      ${spark(q.spark, q.three_month >= 0 ? "var(--joy)" : "var(--anger)")}
      <div class="trow muted">1 month ${chg(q.month)}</div>
    </div>`).join("")}
  </div>
  <div class="grid two" style="margin-top:14px">
    <div class="card"><h2>Top gainers</h2><p class="muted">Nifty 50 stocks, last session</p>
      ${(m.gainers || []).map((s) => `<div class="mover"><span>${esc(s.symbol)}</span><span class="muted">₹${fmt(s.price)}</span>${chg(s.day)}</div>`).join("")}</div>
    <div class="card"><h2>Top losers</h2><p class="muted">Nifty 50 stocks, last session</p>
      ${(m.losers || []).map((s) => `<div class="mover"><span>${esc(s.symbol)}</span><span class="muted">₹${fmt(s.price)}</span>${chg(s.day)}</div>`).join("")}</div>
  </div>
  ${analysisHTML(m.analysis)}
  ${hist.length > 1 ? `<div class="card" style="margin-top:14px"><h2>Nifty 50 at each update</h2><p class="muted">Builds up as the app keeps running</p>${lineChart(hist, "nifty", { color: "var(--hope)" })}</div>` : ""}
  <div class="section-title">Market news</div>
  <div class="card">${(m.news || []).map((n) => `<a class="item" ${link(n.url)}>
    <div class="t">${esc(n.title)}</div>
    <div class="meta"><span class="pill ${n.tone === "bullish" ? "bull" : n.tone === "bearish" ? "bear" : "flat"}">${esc(n.tone)}</span>
    <span>${esc(n.source)}</span><span>·</span><span>${ago(n.time)}</span></div></a>`).join("")}</div>
  <div class="note">Prices and company figures from Yahoo Finance (free, may be delayed). Bullish/bearish tone is based on headline
  wording. Scores, the watchlist and alerts come from fixed rules, not a person's judgement. <b>This is not investment advice</b> —
  for real money decisions, talk to a SEBI-registered adviser.</div>`;
}

// ---------------------------------------------------------------- stock analysis
let stockSort = "combined";
const scoreColor = (s) => (s >= 70 ? "var(--joy)" : s >= 50 ? "var(--hope)" : s >= 35 ? "var(--fear)" : "var(--anger)");
const pctv = (v) => (v == null ? "–" : (v * 100).toFixed(1) + "%");

function analysisHTML(a) {
  if (!a || !a.stocks?.length) return "";
  const recentAlerts = (a.alerts || []).filter((x) => Date.now() / 1000 - x.t < 3 * 86400)
    .sort((p, q) => (q.kind.startsWith("pick") - p.kind.startsWith("pick")) || Math.abs(q.size) - Math.abs(p.size)).slice(0, 6);
  const rec = a.record;
  const sorted = [...a.stocks].sort((x, y) =>
    stockSort === "tech" ? y.tech.score - x.tech.score : stockSort === "fund" ? (y.fund?.score ?? -1) - (x.fund?.score ?? -1)
    : stockSort === "day" ? (y.tech.r1d ?? 0) - (x.tech.r1d ?? 0) : y.combined - x.combined);
  return `
  <div class="section-title" id="big-moves">⚡ Big moves</div>
  <div class="card">
    ${recentAlerts.length ? recentAlerts.map((x) => `<div class="alert ${x.size >= 0 ? "pos" : "neg"}">
        <span class="big-ic">${x.kind === "volume" ? "📊" : x.size >= 0 ? "🚀" : "📉"}</span>
        <div><div class="t">${esc(x.text)}</div><div class="muted" style="font-size:12px">${esc(x.date)}</div></div></div>`).join("")
      : `<div class="muted">No unusually big moves in the last 3 days. Alerts appear here when a Nifty 50 stock moves ±4% in a day,
         ±10% in a week, trades 3× its usual volume, or a watchlist pick gains 15% / loses 10%.</div>`}
  </div>

  <div class="section-title">Signal watchlist — saved and tracked</div>
  <div class="grid two">
    <div class="card">
      <h2>Track record</h2><p class="muted">Every stock the rules have picked, priced from the day it was picked</p>
      ${rec ? `<div class="stats">
          <div><div class="sv ${rec.avg >= 0 ? "up" : "down"}">${rec.avg >= 0 ? "+" : ""}${rec.avg}%</div><div class="sl">average return</div></div>
          <div><div class="sv">${rec.win_rate}%</div><div class="sl">picks in profit</div></div>
          <div><div class="sv ${(rec.avg_vs_nifty ?? 0) >= 0 ? "up" : "down"}">${rec.avg_vs_nifty == null ? "–" : (rec.avg_vs_nifty >= 0 ? "+" : "") + rec.avg_vs_nifty + "%"}</div><div class="sl">vs Nifty 50</div></div>
          <div><div class="sv">${rec.count}</div><div class="sl">picks tracked</div></div>
        </div>
        <p class="muted" style="margin:10px 0 0;font-size:12px">Best: ${esc(rec.best.name)} ${rec.best.ret >= 0 ? "+" : ""}${rec.best.ret}% ·
        Worst: ${esc(rec.worst.name)} ${rec.worst.ret >= 0 ? "+" : ""}${rec.worst.ret}%</p>`
        : `<div class="muted">The first picks are saved at the next update.</div>`}
    </div>
    <div class="card">
      <h2>How picks are chosen</h2>
      <p class="muted" style="margin:0">Once a day, the top 5 Nifty 50 stocks where <b>both</b> the technical and fundamental
      scores are 60 or more, skipping overbought stocks (RSI above 75) and anything picked in the last 7 days. The price that
      day is saved, then tracked against the Nifty 50. It's a test of the rules, not advice to buy.</p>
    </div>
  </div>
  <div class="card" style="margin-top:14px">
    ${(a.picks || []).length ? `<div class="ptable">
      <div class="prow phead"><span>Stock</span><span>Picked</span><span>Then → now</span><span>Return</span></div>
      ${a.picks.map((p) => `<div class="prow">
        <span><b>${esc(p.symbol)}</b><br><span class="muted" style="font-size:11px">T ${p.tech} · F ${p.fund}</span></span>
        <span class="muted">${esc(p.date)}</span>
        <span>₹${fmt(p.price, 0)} → ₹${fmt(p.now ?? p.price, 0)}</span>
        <span>${chg(p.ret ?? 0)}${p.excess != null ? `<br><span class="muted" style="font-size:11px">${p.excess >= 0 ? "+" : ""}${p.excess}% vs Nifty</span>` : ""}</span>
      </div>`).join("")}</div>` : `<div class="muted">No picks yet.</div>`}
  </div>

  <div class="section-title">Stock analysis — Nifty 50</div>
  <div class="chips" style="margin-bottom:12px">
    ${[["combined", "Overall"], ["tech", "Technical"], ["fund", "Fundamental"], ["day", "Today's move"]].map(([k, l]) =>
      `<button class="chip ${stockSort === k ? "on" : ""}" data-sort="${k}">${l}</button>`).join("")}
  </div>
  <div class="grid auto">
    ${sorted.map((x) => `<div class="card stock" data-stock>
      <div class="shead">
        <div><div class="sname">${esc(x.symbol)}</div><div class="muted" style="font-size:12px">${esc(x.name)}${x.sector ? " · " + esc(x.sector) : ""}</div></div>
        <div style="text-align:right"><div class="sprice">₹${fmt(x.tech.price)}</div>${chg(x.tech.r1d)}</div>
      </div>
      <div class="scores">
        ${scoreBar("Technical", x.tech.score, x.tech.label)}
        ${x.fund ? scoreBar("Fundamental", x.fund.score, x.fund.label) : `<div class="muted" style="font-size:12px">Fundamentals unavailable</div>`}
      </div>
      <div class="sdetail">
        ${spark(x.tech.spark, (x.tech.r3m ?? 0) >= 0 ? "var(--joy)" : "var(--anger)")}
        <div class="kv">
          <span>RSI (14)</span><b>${x.tech.rsi ?? "–"}</b>
          <span>50 / 200-day avg</span><b>₹${fmt(x.tech.sma50, 0)} / ₹${fmt(x.tech.sma200, 0)}</b>
          <span>MACD</span><b>${esc(x.tech.macd)}</b>
          <span>1m / 3m / 6m</span><b>${chg(x.tech.r1m)} ${chg(x.tech.r3m)} ${chg(x.tech.r6m)}</b>
          <span>52-week range</span><b>₹${fmt(x.tech.lo52, 0)} – ₹${fmt(x.tech.hi52, 0)}</b>
          <span>Volatility (yearly)</span><b>${x.tech.volatility ?? "–"}%</b>
          <span>P/E · P/B</span><b>${x.facts.pe ? x.facts.pe.toFixed(1) : "–"} · ${x.facts.pb ? x.facts.pb.toFixed(1) : "–"}</b>
          <span>ROE · margin</span><b>${pctv(x.facts.roe)} · ${pctv(x.facts.margin)}</b>
          <span>Revenue · earnings growth</span><b>${pctv(x.facts.rev_growth)} · ${pctv(x.facts.eps_growth)}</b>
          <span>Debt / equity</span><b>${x.facts.de != null ? (x.facts.de / 100).toFixed(2) : "–"}</b>
          <span>Dividend yield</span><b>${pctv(x.facts.div_yield)}</b>
          ${x.facts.analyst ? `<span>Analysts' consensus</span><b>${esc(x.facts.analyst.replace("_", " "))}${x.facts.target ? ` · target ₹${fmt(x.facts.target, 0)}` : ""}</b>` : ""}
        </div>
        <div class="why"><b>Technical:</b> ${esc(x.tech.notes.join(", "))}</div>
        ${x.fund ? `<div class="why"><b>Fundamental:</b> ${esc(x.fund.notes.join(", "))}</div>` : ""}
      </div>
      <div class="more muted">Tap for details</div>
    </div>`).join("")}
  </div>
  <p class="muted" style="font-size:12px">Technical score (0–100): trend vs 50/200-day averages, MACD, momentum, RSI, distance from 52-week high.
  Fundamental score (0–100): ROE, profit margin, revenue & earnings growth, debt, and P/E compared with the Nifty median${a.median_pe ? ` (${a.median_pe})` : ""}.</p>`;
}

function scoreBar(label, s, word) {
  return `<div class="sbar"><span>${label}</span><div class="track"><div class="fill" style="width:${s}%;background:${scoreColor(s)}"></div></div>
    <span class="n" style="color:${scoreColor(s)}">${s}</span></div><div class="slabel" style="color:${scoreColor(s)}">${esc(word)}</div>`;
}

function news() {
  const list = DATA.news.filter((n) => newsFilter === "all" || n.stance === newsFilter || (newsFilter === "other" && !n.stance));
  return `
  <div class="section-title" style="margin-top:4px">Big stories and how they're covered</div>
  <div class="grid auto">
    ${DATA.topics.map((t, n) => `<div class="card topic" data-topic="${n}">
      <div class="head"><span class="word">${esc(t.word)}</span><span class="muted">${t.count} headlines</span></div>
      ${t.pro + t.neutral + t.anti ? stackHTML(t, false) + `<div class="muted" style="font-size:12px;margin-top:6px">
        ${t.pro} pro · ${t.neutral} independent · ${t.anti} anti</div>` : `<div class="muted" style="font-size:12px;margin-top:6px">Not political</div>`}
      <div class="heads">${t.headlines.map((h) => itemHTML({ ...h, time: DATA.updated }, true).replace(/<span>·<\/span><span>[^<]*<\/span>/, "")).join("")}</div>
    </div>`).join("")}
  </div>
  <div class="section-title">Latest headlines</div>
  <div class="chips" style="margin-bottom:12px">
    ${[["all", "All"], ["pro", "Pro-govt"], ["neutral", "Independent"], ["anti", "Anti-govt"], ["other", "Non-political"]].map(([k, l]) =>
      `<button class="chip ${newsFilter === k ? "on" : ""}" data-filter="${k}">${l}</button>`).join("")}
  </div>
  <div class="card">${list.length ? list.map((i) => itemHTML(i)).join("") : `<div class="empty">No headlines in this group.</div>`}</div>`;
}

function bind() {
  view.querySelectorAll("[data-side]").forEach((b) => (b.onclick = () => { polSide = b.dataset.side; render(); }));
  view.querySelectorAll("[data-filter]").forEach((b) => (b.onclick = () => { newsFilter = b.dataset.filter; render(); }));
  view.querySelectorAll("[data-topic]").forEach((c) => (c.onclick = (e) => { if (!e.target.closest("a")) c.classList.toggle("open"); }));
  view.querySelectorAll("[data-sort]").forEach((b) => (b.onclick = () => { stockSort = b.dataset.sort; render(); }));
  view.querySelectorAll("[data-stock]").forEach((c) => (c.onclick = () => c.classList.toggle("open")));
  view.querySelectorAll("[data-goto]").forEach((b) => (b.onclick = () => document.querySelector(`#nav button[data-tab="${b.dataset.goto}"]`).click()));
}

load();
setInterval(load, 5 * 60 * 1000);
