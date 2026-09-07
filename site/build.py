"""data/ 以下の抽出結果から、GitHub Pages 用の静的サイトを docs/ に生成する。

  python site/build.py

出力:
  docs/index.html          … 一覧＋検索（クライアントサイド全文検索）
  docs/companies/<code>.html … 会社ごとの「事業の内容」ページ
  docs/search.json         … 検索インデックス
"""
from __future__ import annotations

import html
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DOCS = ROOT / "docs"
PORTAL_URL = "https://git-san-934.github.io/portal/"

CSS = """
:root { color-scheme: light dark; }
* { box-sizing: border-box; }
body { margin: 0; font: 15px/1.7 system-ui, "Hiragino Kaku Gothic ProN", "Noto Sans JP", sans-serif;
  background: #fafafa; color: #1a1a1a; }
@media (prefers-color-scheme: dark) { body { background: #14161a; color: #e8e8e8; } a { color: #7fb3ff; } }
main { max-width: 860px; margin: 0 auto; padding: 24px 18px 80px; }
h1 { font-size: 1.4rem; margin: 0 0 4px; }
.sub { color: #888; font-size: .86rem; margin-bottom: 20px; }
#q { width: 100%; padding: 11px 13px; font-size: 1rem; border: 1px solid #bbb; border-radius: 8px;
  background: transparent; color: inherit; }
.card { display: block; padding: 14px 16px; margin-top: 10px; border: 1px solid #ddd; border-radius: 10px;
  text-decoration: none; color: inherit; background: rgba(127,127,127,.04); }
.card:hover { border-color: #888; }
.card .code { font-variant-numeric: tabular-nums; color: #888; font-size: .85rem; }
.card .name { font-weight: 600; font-size: 1.05rem; }
.card .snip { color: #666; font-size: .9rem; margin-top: 4px; }
@media (prefers-color-scheme: dark) { .card .snip { color: #aaa; } }
.count { color: #888; font-size: .85rem; margin-top: 14px; }
article { white-space: pre-wrap; word-break: break-word; }
.back { display: inline-block; margin-bottom: 16px; font-size: .9rem; }
.quote { border-left: 3px solid #bbb; padding-left: 12px; color: #888; font-size: .88rem; margin: 0 0 20px; }
mark { background: #ffe066; color: #1a1a1a; border-radius: 2px; padding: 0 1px; }
mark.active { background: #ff8c1a; color: #fff; box-shadow: 0 0 0 2px #ff8c1a; }
@media (prefers-color-scheme: dark) { mark { background: #8a6d00; color: #fff; }
  mark.active { background: #ff8c1a; color: #111; } }
#mnav { display: inline; white-space: nowrap; }
#mnav button { font: inherit; padding: 1px 8px; margin-left: 4px; cursor: pointer;
  border: 1px solid #bbb; border-radius: 6px; background: transparent; color: inherit; }
"""

INDEX_JS = """
const box = document.getElementById('q');
const list = document.getElementById('list');
const count = document.getElementById('count');
const note = document.getElementById('note');
let data = [];          // [{code,name,snip}]  … 軽い一覧（即表示）
let bodies = null;       // {code: 本文}        … 本文検索用（初回検索時に遅延読込）
let bodiesLoading = false;
const MAX_ROWS = 300;

fetch('index.json').then(r => r.json()).then(d => { data = d; render(''); });

function loadBodies(){
  if (bodies || bodiesLoading) return;
  bodiesLoading = true;
  note.textContent = '本文検索データを読み込み中…';
  fetch('bodies.json').then(r => r.json()).then(d => {
    bodies = d; bodiesLoading = false; note.textContent = '';
    render(box.value);
  }).catch(() => { bodiesLoading = false; note.textContent = '本文データの読み込みに失敗しました。'; });
}
function esc(s){ return s.replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }
function escRe(s){ return s.replace(/[.*+?^${}()|[\\]\\\\]/g, '\\\\$&'); }
// スペース（半角・全角）区切りで複数語に分解。すべてを含む行だけヒット（AND 検索）。
function termsOf(q){ return q.trim().toLowerCase().split(/[\\s\\u3000]+/).filter(Boolean); }
function hl(text, terms){
  if (!terms.length) return esc(text);
  const re = new RegExp('(' + terms.map(escRe).join('|') + ')', 'gi');
  let out = '', last = 0, m;
  while ((m = re.exec(text))){
    if (m.index === re.lastIndex){ re.lastIndex++; continue; }
    out += esc(text.slice(last, m.index)) + '<mark>' + esc(m[0]) + '</mark>';
    last = m.index + m[0].length;
  }
  return out + esc(text.slice(last));
}
function render(q){
  const terms = termsOf(q);
  if (terms.length) loadBodies();
  const hits = data.filter(c => {
    if (!terms.length) return true;
    const body = (bodies && bodies[c.code]) || c.snip;
    const hay = (c.name + ' ' + c.code + ' ' + body).toLowerCase();
    return terms.every(t => hay.includes(t));
  });
  count.textContent = hits.length + ' 件' + (hits.length > MAX_ROWS ? `（先頭 ${MAX_ROWS} 件を表示）` : '');
  list.innerHTML = hits.slice(0, MAX_ROWS).map(c => {
    const body = (bodies && bodies[c.code]) || c.snip;
    let snip = '';
    if (terms.length){
      const bl = body.toLowerCase();
      let best = -1;
      for (const t of terms){ const i = bl.indexOf(t); if (i >= 0 && (best < 0 || i < best)) best = i; }
      if (best >= 0) snip = (best>40?'…':'') + body.slice(Math.max(0,best-40), best+80) + '…';
    }
    if (!snip) snip = body.slice(0, 90) + '…';
    const qs = terms.length ? '?q=' + encodeURIComponent(terms.join(' ')) : '';
    return `<a class="card" href="companies/${encodeURIComponent(c.code)}.html${qs}">
      <div class="code">${esc(c.code)}</div>
      <div class="name">${hl(c.name, terms)}</div>
      <div class="snip">${hl(snip, terms)}</div></a>`;
  }).join('');
}
box.addEventListener('input', () => render(box.value));
"""

# 会社ページ用: ?q=... が付いていたら本文中の一致語（複数可）をハイライトして辿れるようにする
DETAIL_JS = """
(function(){
  const raw = (new URLSearchParams(location.search).get('q') || '').trim();
  const terms = raw.toLowerCase().split(/[\\s\\u3000]+/).filter(Boolean);
  const art = document.querySelector('article');
  const nav = document.getElementById('mnav');
  if (!terms.length || !art) return;
  function esc(s){ return s.replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }
  function escRe(s){ return s.replace(/[.*+?^${}()|[\\]\\\\]/g, '\\\\$&'); }
  const text = art.textContent;
  const re = new RegExp('(' + terms.map(escRe).join('|') + ')', 'gi');
  let out = '', last = 0, m;
  while ((m = re.exec(text))){
    if (m.index === re.lastIndex){ re.lastIndex++; continue; }
    out += esc(text.slice(last, m.index)) + '<mark>' + esc(m[0]) + '</mark>';
    last = m.index + m[0].length;
  }
  out += esc(text.slice(last));
  art.innerHTML = out;
  const marks = [...art.querySelectorAll('mark')];
  if (!marks.length) return;
  let mi = 0;
  const cnt = document.createElement('span');
  function focus(n){
    marks[mi].classList.remove('active');
    mi = (n + marks.length) % marks.length;
    marks[mi].classList.add('active');
    marks[mi].scrollIntoView({ block: 'center', behavior: 'smooth' });
    cnt.textContent = ' ' + (mi + 1) + ' / ' + marks.length + ' ';
  }
  nav.textContent = '「' + terms.join(' ') + '」';
  nav.appendChild(cnt);
  const mk = (label, d) => { const b = document.createElement('button');
    b.textContent = label; b.onclick = () => focus(mi + d); nav.appendChild(b); };
  mk('‹ 前', -1); mk('次 ›', 1);
  marks[0].classList.add('active');
  cnt.textContent = ' 1 / ' + marks.length + ' ';
  marks[0].scrollIntoView({ block: 'center' });
})();
"""


def page(title: str, body: str, *, depth: int = 0) -> str:
    prefix = "../" * depth
    return (
        "<!doctype html><html lang=\"ja\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        f"<title>{html.escape(title)}</title>"
        f"<link rel=\"stylesheet\" href=\"{prefix}style.css\"></head><body><main>"
        f"{body}"
        "</main></body></html>"
    )


def load_companies() -> list[dict]:
    companies = []
    for meta_path in sorted(DATA.glob("*/meta.json")):
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        business = (meta_path.parent / "business.md").read_text(encoding="utf-8")
        seccode = meta.get("seccode", "")
        short = seccode[:-1] if len(seccode) == 5 else (seccode or meta_path.parent.name)
        companies.append({
            "code": short,
            "name": meta.get("filer_name") or meta.get("filer_name_en") or short,
            "name_en": meta.get("filer_name_en", ""),
            "doc_id": meta.get("doc_id", ""),
            "period_start": meta.get("period_start", ""),
            "period_end": meta.get("period_end", ""),
            "business_md": business,
        })
    return companies


def build() -> None:
    if DOCS.exists():
        shutil.rmtree(DOCS)
    (DOCS / "companies").mkdir(parents=True)

    (DOCS / "style.css").write_text(CSS, encoding="utf-8")
    companies = load_companies()

    # 検索インデックス（本文からは出典行を除いた素のテキスト）
    #   index.json  … 会社名/コード/抜粋のみ。軽いので初回に読み込む。
    #   bodies.json … 全文。本文検索時だけ遅延読込（Pages の gzip 転送に任せる）。
    index, bodies = [], {}
    for c in companies:
        body_lines = [ln for ln in c["business_md"].splitlines()
                      if not ln.startswith(("#", ">"))]
        body = " ".join(body_lines).strip()
        index.append({"code": c["code"], "name": c["name"], "snip": body[:120]})
        bodies[c["code"]] = body
    (DOCS / "index.json").write_text(
        json.dumps(index, ensure_ascii=False), encoding="utf-8")
    (DOCS / "bodies.json").write_text(
        json.dumps(bodies, ensure_ascii=False), encoding="utf-8")

    # 一覧ページ
    index_body = (
        "<h1>有価証券報告書 事業の内容ビューア</h1>"
        f"<div class=\"sub\">EDINET の有価証券報告書から「事業の内容」を抽出。"
        f"<a href=\"{PORTAL_URL}\">ポータルへ戻る</a></div>"
        "<input id=\"q\" type=\"search\" "
        "placeholder=\"会社名・証券コード・本文で検索（スペース区切りで AND 検索）\" autofocus>"
        "<div id=\"note\" class=\"count\"></div>"
        "<div id=\"count\" class=\"count\"></div><div id=\"list\"></div>"
        f"<script>{INDEX_JS}</script>"
    )
    (DOCS / "index.html").write_text(page("事業の内容ビューア", index_body), encoding="utf-8")

    # 会社ページ
    for c in companies:
        # business_md の先頭2行(見出し・出典)を整形して表示
        lines = c["business_md"].splitlines()
        quote = next((ln.lstrip("> ").strip() for ln in lines if ln.startswith(">")), "")
        rest = "\n".join(ln for ln in lines if not ln.startswith(("#", ">"))).strip()
        period = f"{c['period_start']}〜{c['period_end']}".strip("〜")
        body = (
            "<a class=\"back\" href=\"../index.html\">← 一覧へ</a>"
            f"<h1>{html.escape(c['name'])}"
            f"<span class=\"code\"> {html.escape(c['code'])}</span></h1>"
            f"<div class=\"sub\">事業の内容 ／ 対象期間 {html.escape(period)} "
            "<span id=\"mnav\"></span></div>"
            f"<p class=\"quote\">{html.escape(quote)}</p>"
            f"<article>{html.escape(rest)}</article>"
            f"<script>{DETAIL_JS}</script>"
        )
        (DOCS / "companies" / f"{c['code']}.html").write_text(
            page(f"{c['name']} 事業の内容", body, depth=1), encoding="utf-8")

    # Jekyll を無効化（_ で始まるパスなどをそのまま配信）
    (DOCS / ".nojekyll").write_text("", encoding="utf-8")
    print(f"生成完了: {len(companies)} 社 -> {DOCS}")


if __name__ == "__main__":
    build()
