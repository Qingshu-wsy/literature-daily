"""输出层：单文件 HTML 日报（离线可用）+ Excel 表格。

HTML 与未来的 GUI 共用同一份数据契约（out/data/*.json），
GUI 想省事可以直接用 WebView 加载这份 HTML。
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

HTML_TEMPLATE = r"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title>
<style>
*{box-sizing:border-box;font-family:Arial,"SimSun",sans-serif;font-weight:700}
:root{
  --bg:#f5f6f7; --card:#fff; --line:#e6e8eb; --ink:#1b1f23; --dim:#6b7480;
  --accent:#1f6fb2; --shadow:0 1px 2px rgba(16,24,40,.06),0 1px 3px rgba(16,24,40,.1);
}
html,body{margin:0;height:100%}
body{background:var(--bg);color:var(--ink);font:700 16px/1.55 Arial,"SimSun",sans-serif}
a{color:inherit;text-decoration:none}

/* ---------- 顶栏 ---------- */
header{position:sticky;top:0;z-index:20;background:#fff;border-bottom:1px solid var(--line);
  display:flex;align-items:center;gap:18px;padding:10px 18px;flex-wrap:wrap}
.brand{font-size:16px;font-weight:700;letter-spacing:.3px}
.brand small{font-weight:400;color:var(--dim);margin-left:8px;font-size:12px}
.stats{display:flex;gap:14px;color:var(--dim);font-size:12.5px;flex-wrap:wrap}
.stats b{color:var(--ink);font-size:13px}
.spacer{flex:1}
.tool{display:flex;align-items:center;gap:8px}
input[type=search]{width:230px;padding:7px 10px;border:1px solid var(--line);border-radius:8px;font-size:13px;outline:none;background:#fafbfc}
input[type=search]:focus{border-color:var(--accent);background:#fff}
select,button{font:inherit;font-size:12.5px;padding:6px 10px;border:1px solid var(--line);border-radius:8px;background:#fff;cursor:pointer}
button:hover{border-color:#c9ced6;background:#fafbfc}
button.primary{background:var(--accent);border-color:var(--accent);color:#fff}
button.primary:hover{background:#1a5f9a}

/* ---------- 三栏 ---------- */
main{display:grid;grid-template-columns:214px minmax(0,1fr) 400px;height:calc(100vh - 52px);overflow:hidden}
aside{padding:14px;overflow:auto}
aside.left{border-right:1px solid var(--line);background:#fbfbfc}
aside.right{border-left:1px solid var(--line);background:#fff}
.fgroup{margin-bottom:20px}
.fgroup h4{margin:0 0 8px;font-size:11px;letter-spacing:.8px;text-transform:uppercase;color:var(--dim)}
.fitem{display:flex;align-items:center;gap:8px;padding:5px 6px;border-radius:6px;cursor:pointer;font-size:13px;user-select:none}
.fitem:hover{background:#f0f2f5}
.fitem .dot{width:8px;height:8px;border-radius:50%;flex:none}
.fitem .n{margin-left:auto;color:var(--dim);font-size:11.5px;font-variant-numeric:tabular-nums}
.fitem input{accent-color:var(--accent)}

/* ---------- 列表 ---------- */
.list{padding:14px 18px;overflow:auto}
.card{position:relative;display:flex;gap:0;background:var(--card);border:1px solid var(--line);border-radius:10px;
  margin-bottom:10px;box-shadow:var(--shadow);cursor:pointer;overflow:hidden;transition:border-color .12s,transform .12s}
.card:hover{border-color:#cfd6de}
.card.sel{border-color:var(--accent);box-shadow:0 0 0 2px rgba(31,111,178,.14)}
.card .bar{width:4px;flex:none}
.card .body{padding:11px 13px;min-width:0;flex:1}
.card .meta{display:flex;align-items:center;gap:8px;font-size:11.5px;color:var(--dim);margin-bottom:4px;flex-wrap:wrap}
.tag{font-size:11px;padding:1px 7px;border-radius:999px;color:#fff;font-weight:600;letter-spacing:.2px}
.score{margin-left:auto;font-variant-numeric:tabular-nums;color:#8a6d1f;background:#fdf6e3;border:1px solid #f0e2bd;
  padding:0 6px;border-radius:6px;font-size:11px}
h3.zh{margin:0 0 2px;font-size:15.5px;line-height:1.4;font-weight:650}
h3.zh:hover{color:var(--accent);text-decoration:underline}
p.en{margin:0 0 6px;font-size:12px;color:#8b939d;line-height:1.4;
  display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
p.abs{margin:0 0 7px;font-size:14px;color:#4d5661;line-height:1.65;
  display:block;overflow:visible;white-space:normal;overflow-wrap:anywhere}
.lang-label{display:inline-block;margin-right:6px;color:#6b7480;font-size:11px;font-weight:700}
.en-abstract{color:#66717d!important}
.chips{display:flex;gap:5px;flex-wrap:wrap}
.chip{font-size:11px;color:#5b6673;background:#f2f4f7;border-radius:5px;padding:1px 6px}
.chip.oa{background:#e8f5ec;color:#1f6f3d}

/* ---------- 详情 ---------- */
.detail-empty{color:var(--dim);font-size:13px;padding:30px 6px;text-align:center;line-height:2}
.dtitle{font-size:16px;font-weight:700;line-height:1.45;margin:0 0 6px}
.dtitle-en{font-size:12.5px;color:#8b939d;line-height:1.45;margin-bottom:12px}
.dmeta{font-size:12px;color:var(--dim);margin-bottom:14px;line-height:1.8}
.dmeta b{color:var(--ink);font-weight:600}
.dsec{margin-bottom:14px}
.dsec h5{margin:0 0 6px;font-size:11px;letter-spacing:.8px;text-transform:uppercase;color:var(--dim)}
.dsec p{margin:0;font-size:14px;line-height:1.75;color:#3c454f;white-space:pre-wrap;overflow-wrap:anywhere}
.dsec p.en{color:#6b7480;font-size:12.5px}
.btnrow{display:flex;gap:8px;flex-wrap:wrap;margin:16px 0 10px}
.btnrow a,.btnrow button{display:inline-flex;align-items:center;gap:5px;font-size:12.5px;padding:7px 11px;
  border:1px solid var(--line);border-radius:8px;background:#fff;cursor:pointer}
.btnrow a.primary{background:var(--accent);border-color:var(--accent);color:#fff}
.btnrow a:hover{border-color:#c9ced6}
.btnrow a.primary:hover{background:#1a5f9a}
mark{background:#fff1a8;padding:0 1px;border-radius:2px}

/* ---------- 杂项 ---------- */
.footer{padding:14px 18px 30px;color:#9aa2ab;font-size:11.5px;line-height:1.9}
.hide{display:none}
.empty{text-align:center;color:var(--dim);padding:60px 20px;font-size:13px}
@media (max-width:1000px){main{grid-template-columns:190px minmax(0,1fr)}aside.right{display:none}}
body,body *{font-family:Arial,"SimSun",sans-serif!important;font-weight:700!important}
</style>
</head>
<body>
<header>
  <div class="brand">文献日报 <small id="dateLabel"></small></div>
  <div class="stats" id="stats"></div>
  <div class="spacer"></div>
  <div class="tool">
    <input type="search" id="q" placeholder="搜索标题 / 摘要 / 期刊 / 关键词">
    <select id="sort">
      <option value="score">按相关度</option>
      <option value="date">按日期</option>
      <option value="journal">按期刊</option>
    </select>
    <button id="exportBtn">导出反馈</button>
  </div>
</header>
<main>
  <aside class="left">
    <div class="fgroup"><h4>主题</h4><div id="topicFilters"></div></div>
    <div class="fgroup"><h4>出版社</h4><div id="pubFilters"></div></div>
    <div class="fgroup">
      <h4>已看</h4>
      <label class="fitem"><input type="checkbox" id="hideSeen"> 隐藏已收藏/已忽略</label>
    </div>
  </aside>
  <section class="list" id="list"></section>
  <aside class="right" id="detail">
    <div class="detail-empty">点击左侧任意一条文献<br>在这里看完整中英文摘要<br><br>
      <span style="font-size:11.5px">快捷键：J / K 上下移动 · O 打开官网 · S 收藏 · X 忽略</span>
    </div>
  </aside>
</main>
<div class="footer" id="footer"></div>

<script>
const DATA = /*__DATA__*/{};
const LS_KEY = 'litfb-' + (DATA.date || '');
const LS_HIDDEN = 'lithidden';

function loadJSON(k, d){ try { return JSON.parse(localStorage.getItem(k)) || d; } catch(e){ return d; } }
let fb = loadJSON(LS_KEY, {liked:{}, disliked:{}});
let hidden = loadJSON(LS_HIDDEN, {});

const state = {
  topics: new Set(DATA.topics.map(t => t.name)),
  pubs: new Set(DATA.publishers.map(p => p.name)),
  q: '',
  sort: 'score',
  hideSeen: false,
  sel: null
};

const esc = s => (s || '').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const colorOf = name => (DATA.topics.find(t => t.name === name) || {}).color || '#8a939d';
const topicOf = p => (p.topics && p.topics.length) ? p.topics[0] : '';
const isSeen = doi => !!fb.liked[doi] || !!fb.disliked[doi] || !!hidden[doi];

function matches(p){
  if (!p.topics.some(t => state.topics.has(t))) return false;
  if (!state.pubs.has(p.publisher)) return false;
  if (state.hideSeen && isSeen(p.doi)) return false;
  if (state.q){
    const q = state.q.toLowerCase();
    const hay = [p.title_en, p.title_zh, p.abstract_en, p.abstract_zh, p.journal,
                 (p.authors||[]).join(' '), (p.matched_terms||[]).join(' '), p.doi].join(' ').toLowerCase();
    if (!hay.includes(q)) return false;
  }
  return true;
}

function sortP(list){
  const by = state.sort;
  return list.slice().sort((a,b) => {
    if (by === 'date') return (b.published || '').localeCompare(a.published || '') || b.score - a.score;
    if (by === 'journal') return (a.journal || '').localeCompare(b.journal || '') || b.score - a.score;
    return b.score - a.score || (b.published || '').localeCompare(a.published || '');
  });
}

function hl(text, q){
  const safe = esc(text);
  if (!q) return safe;
  try { return safe.replace(new RegExp('(' + q.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + ')', 'ig'), '<mark>$1</mark>'); }
  catch(e){ return safe; }
}

function cardHTML(p){
  const color = colorOf(topicOf(p));
  const tags = p.topics.map(t => `<span class="tag" style="background:${colorOf(t)}">${esc(t)}</span>`).join('');
  const chips = (p.matched_terms || []).slice(0, 5).map(t => `<span class="chip">${esc(t)}</span>`).join('')
    + (p.is_oa ? '<span class="chip oa">OA</span>' : '');
  const star = fb.liked[p.doi] ? '★' : '☆';
  return `<article class="card ${state.sel === p.doi ? 'sel' : ''}" data-doi="${esc(p.doi)}">
    <div class="bar" style="background:${color}"></div>
    <div class="body">
      <div class="meta">${tags}
        <span>${esc(p.journal)}</span><span>·</span><span>${esc(p.published)}</span>
        <span class="score">${p.score}</span>
        <button class="star" data-star="${esc(p.doi)}" title="收藏"
          style="border:none;background:none;cursor:pointer;font-size:15px;color:#c9a227;padding:0 2px">${star}</button>
      </div>
      <h3 class="zh" data-open="${esc(p.url_publisher)}">${hl(p.title_zh || p.title_en, state.q)}</h3>
      ${p.title_zh ? `<p class="en">${hl(p.title_en, state.q)}</p>` : ''}
      ${p.abstract_zh ? `<p class="abs zh-abstract"><span class="lang-label">中文</span>${hl(p.abstract_zh, state.q)}</p>` : ''}
      ${p.abstract_en ? `<p class="abs en-abstract"><span class="lang-label">English</span>${hl(p.abstract_en, state.q)}</p>` : ''}
      ${!p.abstract_zh && !p.abstract_en ? '<p class="abs">（暂无摘要）</p>' : ''}
      <div class="chips">${chips}</div>
    </div>
  </article>`;
}

function render(){
  const list = sortP(DATA.papers.filter(matches));
  const box = document.getElementById('list');
  if (!list.length){
    box.innerHTML = '<div class="empty">没有符合条件的文献。<br>试试取消左侧筛选，或清空搜索框。</div>';
    return;
  }
  box.innerHTML = list.map(cardHTML).join('');
}

function renderFilters(){
  const tf = document.getElementById('topicFilters');
  tf.innerHTML = DATA.topics.map(t => `<label class="fitem">
      <input type="checkbox" ${state.topics.has(t.name) ? 'checked' : ''} data-topic="${esc(t.name)}">
      <span class="dot" style="background:${t.color}"></span>${esc(t.name)}
      <span class="n">${t.count}</span></label>`).join('');
  const pf = document.getElementById('pubFilters');
  pf.innerHTML = DATA.publishers.map(p => `<label class="fitem">
      <input type="checkbox" ${state.pubs.has(p.name) ? 'checked' : ''} data-pub="${esc(p.name)}">
      ${esc(p.name)}<span class="n">${p.count}</span></label>`).join('');
}

function showDetail(doi){
  state.sel = doi;
  const p = DATA.papers.find(x => x.doi === doi);
  if (!p) return;
  const color = colorOf(topicOf(p));
  const tags = p.topics.map(t => `<span class="tag" style="background:${colorOf(t)}">${esc(t)}</span>`).join(' ');
  const liked = !!fb.liked[doi], disliked = !!fb.disliked[doi];
  document.getElementById('detail').innerHTML = `
    <div style="height:3px;background:${color};border-radius:99px;margin-bottom:14px"></div>
    ${tags}
    <h2 class="dtitle" style="margin-top:8px">${esc(p.title_zh || p.title_en)}</h2>
    ${p.title_zh ? `<div class="dtitle-en">${esc(p.title_en)}</div>` : ''}
    <div class="dmeta">
      <b>${esc(p.journal)}</b> · ${esc(p.publisher)}<br>
      ${esc(p.published)} · ${esc(p.type)} · 相关度 ${p.score} · 被引 ${p.cited_by || 0}
      ${p.is_oa ? ' · <span style="color:#1f6f3d">开放获取</span>' : ''}
    </div>
    <div class="btnrow">
      <a class="primary" href="${esc(p.url_publisher)}" target="_blank" rel="noopener">打开官网</a>
      ${p.url_pdf ? `<a href="${esc(p.url_pdf)}" target="_blank" rel="noopener">PDF 全文</a>` : ''}
      <a href="${esc(p.url_doi || ('https://doi.org/' + p.doi))}" target="_blank" rel="noopener">DOI</a>
      <button data-like="${esc(p.doi)}" style="${liked ? 'border-color:#c9a227;background:#fdf6e3' : ''}">
        ${liked ? '★ 已收藏' : '☆ 收藏'}</button>
      <button data-dislike="${esc(p.doi)}" style="${disliked ? 'border-color:#d99;background:#fdecec' : ''}">
        ${disliked ? '✕ 已忽略' : '✕ 不感兴趣'}</button>
    </div>
    <div class="dsec"><h5>摘要（中文）</h5>
      <p>${esc(p.abstract_zh || '（暂无翻译，见下方英文原文）')}</p></div>
    <div class="dsec"><h5>Abstract（原文）</h5>
      <p class="en">${esc(p.abstract_en || '（该刊未向 Crossref/OpenAlex 提供摘要）')}</p></div>
    <div class="dsec"><h5>命中关键词</h5>
      <p>${(p.matched_terms || []).map(t => `<span class="chip">${esc(t)}</span>`).join(' ') || '—'}</p></div>
    <div class="dsec"><h5>作者</h5>
      <p class="en">${esc((p.authors || []).slice(0, 12).join(', '))}${(p.authors || []).length > 12 ? ' 等' : ''}</p></div>`;
  render();
}

document.addEventListener('click', e => {
  const star = e.target.closest('[data-star]');
  if (star){ e.stopPropagation(); toggleLike(star.dataset.star); return; }
  const open = e.target.closest('[data-open]');
  if (open){ e.stopPropagation(); window.open(open.dataset.open || ('https://doi.org/' + open.closest('.card').dataset.doi), '_blank'); return; }
  const like = e.target.closest('[data-like]');
  if (like){ toggleLike(like.dataset.like); showDetail(like.dataset.like); return; }
  const dis = e.target.closest('[data-dislike]');
  if (dis){ toggleDislike(dis.dataset.dislike); showDetail(dis.dataset.dislike); return; }
  const card = e.target.closest('.card');
  if (card) showDetail(card.dataset.doi);
});

function toggleLike(doi){
  if (fb.liked[doi]) delete fb.liked[doi]; else { fb.liked[doi] = 1; delete fb.disliked[doi]; }
  localStorage.setItem(LS_KEY, JSON.stringify(fb)); render();
}
function toggleDislike(doi){
  if (fb.disliked[doi]) delete fb.disliked[doi]; else { fb.disliked[doi] = 1; delete fb.liked[doi]; }
  localStorage.setItem(LS_KEY, JSON.stringify(fb)); render();
}

document.getElementById('q').addEventListener('input', e => { state.q = e.target.value.trim(); render(); });
document.getElementById('sort').addEventListener('change', e => { state.sort = e.target.value; render(); });
document.getElementById('hideSeen').addEventListener('change', e => { state.hideSeen = e.target.checked; render(); });
document.getElementById('topicFilters').addEventListener('change', e => {
  const t = e.target.dataset.topic; if (!t) return;
  e.target.checked ? state.topics.add(t) : state.topics.delete(t); render();
});
document.getElementById('pubFilters').addEventListener('change', e => {
  const p = e.target.dataset.pub; if (!p) return;
  e.target.checked ? state.pubs.add(p) : state.pubs.delete(p); render();
});

document.getElementById('exportBtn').addEventListener('click', () => {
  const payload = {date: DATA.date, liked: Object.keys(fb.liked), disliked: Object.keys(fb.disliked)};
  const blob = new Blob([JSON.stringify(payload, null, 1)], {type: 'application/json'});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'feedback-' + DATA.date + '.json';
  a.click();
  alert('已导出。把文件放进「feedback」文件夹，下次运行会自动学习你的偏好。');
});

document.addEventListener('keydown', e => {
  if (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT') return;
  const list = sortP(DATA.papers.filter(matches));
  const i = list.findIndex(p => p.doi === state.sel);
  if (e.key === 'j' || e.key === 'J'){ e.preventDefault(); const n = list[Math.min(i + 1, list.length - 1)]; n && showDetail(n.doi); n && document.querySelector(`[data-doi="${CSS.escape(n.doi)}"]`)?.scrollIntoView({block:'nearest'}); }
  if (e.key === 'k' || e.key === 'K'){ e.preventDefault(); const n = list[Math.max(i - 1, 0)]; n && showDetail(n.doi); }
  if (e.key === 'o' || e.key === 'O'){ const p = list[i]; if (p) window.open(p.url_publisher, '_blank'); }
  if (e.key === 's' || e.key === 'S'){ const p = list[i]; if (p){ toggleLike(p.doi); showDetail(p.doi); } }
  if (e.key === 'x' || e.key === 'X'){ const p = list[i]; if (p){ toggleDislike(p.doi); showDetail(p.doi); } }
});

// 初始化
(function init(){
  document.getElementById('dateLabel').textContent = DATA.date + ' · ' + DATA.generated;
  const s = DATA.stats || {};
  document.getElementById('stats').innerHTML =
    `<span>新增 <b>${s.total || 0}</b> 篇</span>` +
    DATA.topics.map(t => `<span>${esc(t.name)} <b>${t.count}</b></span>`).join('') +
    (s.translated ? `<span>已翻译 <b>${s.translated}</b></span>` : '') +
    (s.translated === 0 ? `<span style="color:#b26a00">翻译未启用</span>` : '');
  const f = document.getElementById('footer');
  f.innerHTML = `数据来源：OpenAlex / Crossref · 生成时间 ${DATA.generated}<br>
    收藏与忽略只保存在本机浏览器；点右上角「导出反馈」把 JSON 放进 feedback 文件夹，工具会自动学习你的口味。<br>
    ${s.translated === 0 ? '翻译通道未生效：在 config.yaml 的 translation.backend 填入 deepseek / zhipu 并配置 key 即可启用中文翻译。' : ''}`;
  renderFilters();
  if (DATA.papers.length) showDetail(DATA.papers[0].doi); else render();
})();
</script>
</body>
</html>
"""


def _json_for_html(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False).replace("</", "<\\/")


def filter_papers_to_topics(papers: list[dict], topics_cfg: list[dict]) -> list[dict]:
    selected_names = {topic["name"] for topic in topics_cfg}
    filtered: list[dict] = []
    for paper in papers:
        matched = [name for name in paper.get("topics") or [] if name in selected_names]
        if matched:
            filtered.append({**paper, "topics": matched})
    return filtered


def render_html(payload: dict) -> str:
    html = HTML_TEMPLATE.replace("__TITLE__", f"文献日报 {payload['date']}")
    return html.replace("/*__DATA__*/{}", _json_for_html(payload))


def write_html(payload: dict, path: Path) -> Path:
    html = render_html(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
    return path


# ---------------------------------------------------------------- Excel

def write_excel(papers: list[dict], path: Path, topics: list[dict]) -> Path:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = "文献日报"

    headers = [
        "序号", "主题", "相关度", "中文标题", "英文标题", "期刊", "出版社", "发表日期",
        "类型", "命中关键词", "中文摘要", "英文摘要", "作者", "DOI", "官网链接", "OA全文", "收藏",
    ]
    widths = [5, 12, 8, 46, 46, 26, 10, 11, 8, 26, 60, 60, 30, 26, 30, 30, 6]

    head_fill = PatternFill("solid", fgColor="1F2D3D")
    head_font = Font(color="FFFFFF", bold=True, size=10.5)
    thin = Side(style="thin", color="D9DEE5")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    link_font = Font(color="1155CC", underline="single", size=10.5)
    body_font = Font(size=10.5)
    wrap = Alignment(wrap_text=True, vertical="top")
    center = Alignment(horizontal="center", vertical="center")

    ws.append(headers)
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
    for c in ws[1]:
        c.fill = head_fill
        c.font = head_font
        c.alignment = center
        c.border = border

    color_map = {t["name"]: t["color"] for t in topics}

    for idx, p in enumerate(papers, start=1):
        first_topic = p["topics"][0] if p.get("topics") else ""
        ws.append([
            idx,
            " / ".join(p.get("topics") or []),
            p.get("score", 0),
            p.get("title_zh") or "",
            p.get("title_en", ""),
            p.get("journal", ""),
            p.get("publisher", ""),
            p.get("published", ""),
            p.get("type", ""),
            "、".join(p.get("matched_terms") or [])[:200],
            p.get("abstract_zh") or "",
            p.get("abstract_en") or "",
            ", ".join((p.get("authors") or [])[:10]),
            p.get("doi", ""),
            p.get("url_publisher", ""),
            p.get("url_pdf") or p.get("oa_url") or "",
            "",
        ])
        row = ws.max_row
        for c in ws[row]:
            c.border = border
            c.font = body_font
            c.alignment = wrap

        ws.cell(row=row, column=1).alignment = center
        ws.cell(row=row, column=3).alignment = center
        ws.cell(row=row, column=17).alignment = center

        if first_topic:
            hexc = color_map.get(first_topic, "#8A939D").lstrip("#")
            fill = PatternFill("solid", fgColor=hexc)
            cell = ws.cell(row=row, column=2)
            cell.fill = fill
            cell.font = Font(color="FFFFFF", bold=True, size=10.5)
            cell.alignment = center

        tcell = ws.cell(row=row, column=4)
        if p.get("url_publisher"):
            tcell.hyperlink = p["url_publisher"]
            tcell.font = link_font
        lcell = ws.cell(row=row, column=15)
        if p.get("url_publisher"):
            lcell.hyperlink = p["url_publisher"]
            lcell.value = "打开官网"
            lcell.font = link_font
        pcell = ws.cell(row=row, column=16)
        if p.get("url_pdf") or p.get("oa_url"):
            pcell.hyperlink = p.get("url_pdf") or p.get("oa_url")
            pcell.value = "PDF"
            pcell.font = link_font

        ws.row_dimensions[row].height = 76

    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:Q{ws.max_row}"

    # 第二页：使用说明
    ws2 = wb.create_sheet("说明")
    notes = [
        ["文献日报 · 说明"],
        [""],
        ["1. 第 4 列“中文标题”和第 15 列“打开官网”都是超链接，点击直达出版社页面（需校园网门户已登录）。"],
        ["2. 第 11/12 列是中文摘要与英文原文摘要；中文摘要只翻了前 700 字符，够判断相关性。"],
        ["3. “相关度”= 关键词命中分 + 期刊分层分 + 综述分 + 你的收藏偏好分，用于排序，不代表论文质量。"],
        ["4. 第 17 列“收藏”留空，供你自己打标记；也可以直接在 HTML 日报里点☆。"],
        ["5. 想调整方向：改 config.yaml 的 topics（anchors 决定“必须命中什么才算这个主题”，query 决定拿去检索的布尔式）。"],
        ["6. 想调整灵敏度：改 scoring.min_score（调高更干净，调低更多但更杂）；单个方向可在 topic 里写 min_score 单独放宽。"],
        ["7. 每个方向有独立配额（output.max_per_topic），冷门方向不会被热门方向挤掉。"],
    ]
    for r in notes:
        ws2.append(r)
    ws2.column_dimensions["A"].width = 110
    ws2["A1"].font = Font(bold=True, size=13)

    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path


def build_payload(
    papers: list[dict],
    topics_cfg: list[dict],
    date_str: str,
    net: dict | None = None,
    translated: int = 0,
) -> dict:
    topic_counts = {}
    for p in papers:
        for t in p.get("topics") or []:
            topic_counts[t] = topic_counts.get(t, 0) + 1
    pub_counts = {}
    for p in papers:
        pub_counts[p.get("publisher", "Other")] = pub_counts.get(p.get("publisher", "Other"), 0) + 1

    topics = [
        {"name": t["name"], "color": t.get("color", "#8A939D"), "count": topic_counts.get(t["name"], 0)}
        for t in topics_cfg
    ]
    publishers = [{"name": k, "count": v} for k, v in sorted(pub_counts.items(), key=lambda x: -x[1])]

    return {
        "date": date_str,
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "mode": (net or {}).get("mode", ""),
        "stats": {"total": len(papers), "translated": translated},
        "topics": topics,
        "publishers": publishers,
        "papers": papers,
    }
