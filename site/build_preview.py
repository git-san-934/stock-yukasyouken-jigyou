"""ダブルクリックで開ける 1 ファイル完結のプレビュー (preview.html) を作る。

サーバー不要・ネット不要。GitHub に上げる前に「どう見えるか」を確認する用途。
本番サイトは site/build.py（docs/）のほう。
"""
from __future__ import annotations

import html
import json
from pathlib import Path

from build import CSS, load_companies

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    companies = load_companies()
    payload = []
    for c in companies:
        body_lines = [ln for ln in c["business_md"].splitlines()
                      if not ln.startswith(("#", ">"))]
        payload.append({
            "code": c["code"],
            "name": c["name"],
            "period": f"{c['period_start']}〜{c['period_end']}".strip("〜"),
            "doc_id": c["doc_id"],
            "body": "\n".join(body_lines).strip(),
        })

    data_json = json.dumps(payload, ensure_ascii=False)
    doc = f"""<!doctype html><html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>事業の内容ビューア（プレビュー）</title>
<style>{CSS}
.preview-badge {{ position: fixed; top: 0; right: 0; background: #d97706; color: #fff;
  font-size: .72rem; padding: 3px 10px; border-bottom-left-radius: 8px; }}
article {{ margin-top: 12px; }}
</style></head><body>
<div class="preview-badge">PREVIEW</div><main>
<h1>有価証券報告書 事業の内容ビューア</h1>
<div class="sub">EDINET の有価証券報告書から「事業の内容」を抽出（これは公開前のプレビューです）</div>
<input id="q" type="search" placeholder="会社名・証券コード・本文で検索（スペース区切りで AND 検索）" autofocus>
<div id="count" class="count"></div><div id="list"></div>
<div id="detail" hidden></div>
<script>
const DATA = {data_json};
const box=document.getElementById('q'), list=document.getElementById('list'),
      count=document.getElementById('count'), detail=document.getElementById('detail');
function esc(s){{return s.replace(/[&<>"]/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}}[c]));}}
function escRe(s){{return s.replace(/[.*+?^${{}}()|[\\]\\\\]/g,'\\\\$&');}}
function termsOf(q){{return q.trim().toLowerCase().split(/[\\s\\u3000]+/).filter(Boolean);}}
function hl(text,terms){{
  if(!terms.length) return esc(text);
  const re=new RegExp('('+terms.map(escRe).join('|')+')','gi');
  let out='',last=0,m;
  while((m=re.exec(text))){{
    if(m.index===re.lastIndex){{ re.lastIndex++; continue; }}
    out+=esc(text.slice(last,m.index))+'<mark>'+esc(m[0])+'</mark>';
    last=m.index+m[0].length;
  }}
  return out+esc(text.slice(last));
}}
let marks=[], mi=0;
function focusMark(n){{
  if(!marks.length) return;
  marks[mi]&&marks[mi].classList.remove('active');
  mi=(n+marks.length)%marks.length;
  const m=marks[mi]; m.classList.add('active');
  m.scrollIntoView({{block:'center',behavior:'smooth'}});
  const c=document.getElementById('mcount'); if(c) c.textContent=(mi+1)+' / '+marks.length;
}}
function render(term){{
  detail.hidden=true; list.hidden=false; count.hidden=false;
  const terms=termsOf(term||'');
  const hits=DATA.filter(c=>{{
    if(!terms.length) return true;
    const hay=(c.name+' '+c.code+' '+c.body).toLowerCase();
    return terms.every(t=>hay.includes(t));
  }});
  count.textContent=hits.length+' 件';
  list.innerHTML=hits.map(c=>{{
    let snip='';
    if(terms.length){{
      const bl=c.body.toLowerCase(); let best=-1;
      for(const t of terms){{const i=bl.indexOf(t); if(i>=0&&(best<0||i<best)) best=i;}}
      if(best>=0) snip=(best>40?'…':'')+c.body.slice(Math.max(0,best-40),best+80)+'…';
    }}
    if(!snip) snip=c.body.slice(0,90)+'…';
    return `<a class="card" href="#${{encodeURIComponent(c.code)}}">
      <div class="code">${{esc(c.code)}}</div><div class="name">${{hl(c.name,terms)}}</div>
      <div class="snip">${{hl(snip,terms)}}</div></a>`;
  }}).join('');
}}
function show(code){{
  const c=DATA.find(x=>x.code===code); if(!c) return render('');
  const terms=termsOf(box.value);
  list.hidden=true; count.hidden=true; detail.hidden=false;
  detail.innerHTML=`<a class="back" href="#">← 一覧へ</a>
    <h1>${{esc(c.name)}}<span class="code"> ${{esc(c.code)}}</span></h1>
    <div class="sub">事業の内容 ／ 対象期間 ${{esc(c.period)}}
      <span id="mnav"></span></div>
    <p class="quote">出典: 有価証券報告書 (EDINET 書類ID ${{esc(c.doc_id)}})</p>
    <article>${{hl(c.body,terms)}}</article>`;
  marks=[...detail.querySelectorAll('article mark')]; mi=0;
  const nav=document.getElementById('mnav');
  if(marks.length){{
    nav.innerHTML=`「${{esc(terms.join(' '))}}」<span id="mcount"></span>`
      +`<button id="mprev">‹ 前</button><button id="mnext">次 ›</button>`;
    document.getElementById('mprev').onclick=()=>focusMark(mi-1);
    document.getElementById('mnext').onclick=()=>focusMark(mi+1);
    focusMark(0);
  }} else {{
    window.scrollTo(0,0);
  }}
}}
function route(){{
  const h=decodeURIComponent(location.hash.replace(/^#/,''));
  if(h) show(h); else render(box.value);
}}
box.addEventListener('input',()=>{{ if(location.hash) location.hash=''; else render(box.value); }});
window.addEventListener('hashchange',route);
route();
</script></main></body></html>"""

    out = ROOT / "preview.html"
    out.write_text(doc, encoding="utf-8")
    print(f"生成: {out}")


if __name__ == "__main__":
    main()
