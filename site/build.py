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
"""

INDEX_JS = """
const box = document.getElementById('q');
const list = document.getElementById('list');
const count = document.getElementById('count');
let data = [];
fetch('search.json').then(r => r.json()).then(d => { data = d; render(''); });
function esc(s){ return s.replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }
function render(term){
  term = term.trim().toLowerCase();
  const hits = data.filter(c =>
    !term ||
    c.name.toLowerCase().includes(term) ||
    c.code.toLowerCase().includes(term) ||
    c.body.toLowerCase().includes(term));
  count.textContent = hits.length + ' 件';
  list.innerHTML = hits.map(c => {
    let snip = '';
    if (term){
      const i = c.body.toLowerCase().indexOf(term);
      if (i >= 0) snip = (i>40?'…':'') + c.body.slice(Math.max(0,i-40), i+80) + '…';
    }
    if (!snip) snip = c.body.slice(0, 90) + '…';
    return `<a class="card" href="companies/${encodeURIComponent(c.code)}.html">
      <div class="code">${esc(c.code)}</div>
      <div class="name">${esc(c.name)}</div>
      <div class="snip">${esc(snip)}</div></a>`;
  }).join('');
}
box.addEventListener('input', () => render(box.value));
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
    search = []
    for c in companies:
        body_lines = [ln for ln in c["business_md"].splitlines()
                      if not ln.startswith(("#", ">"))]
        body = " ".join(body_lines).strip()
        search.append({"code": c["code"], "name": c["name"], "body": body})
    (DOCS / "search.json").write_text(
        json.dumps(search, ensure_ascii=False), encoding="utf-8")

    # 一覧ページ
    index_body = (
        "<h1>有価証券報告書 事業の内容ビューア</h1>"
        f"<div class=\"sub\">EDINET の有価証券報告書から「事業の内容」を抽出。"
        f"<a href=\"{PORTAL_URL}\">ポータルへ戻る</a></div>"
        "<input id=\"q\" type=\"search\" placeholder=\"会社名・証券コード・本文で検索\" autofocus>"
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
            f"<div class=\"sub\">事業の内容 ／ 対象期間 {html.escape(period)}</div>"
            f"<p class=\"quote\">{html.escape(quote)}</p>"
            f"<article>{html.escape(rest)}</article>"
        )
        (DOCS / "companies" / f"{c['code']}.html").write_text(
            page(f"{c['name']} 事業の内容", body, depth=1), encoding="utf-8")

    # Jekyll を無効化（_ で始まるパスなどをそのまま配信）
    (DOCS / ".nojekyll").write_text("", encoding="utf-8")
    print(f"生成完了: {len(companies)} 社 -> {DOCS}")


if __name__ == "__main__":
    build()
