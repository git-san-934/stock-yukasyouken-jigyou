# 有価証券報告書 事業の内容ビューア

EDINET の有価証券報告書から「事業の内容」を抽出し、GitHub Pages の静的サイトで
検索・閲覧できるようにする。要件は [`開発.md`](開発.md) を参照。

現状は **MVP**（開発.md の ①〜③(1)、④）。定量分析・要約などは今後追加。

## 仕組み

```
companies.txt  対象銘柄（証券コード）
   │
   ▼  scripts/update_all.py
EDINET API v2 ──► 書類一覧を日付でさかのぼり、対象の最新「有価証券報告書」を特定
   │             （documents.json の secCode で直接絞り込み）
   ▼  書類取得API type=5 (CSV)
XBRL CSV ──► jpcrp_cor:DescriptionOfBusinessTextBlock を取り出し HTML→テキスト化
   │
   ▼  data/<証券コード>/{business.md, meta.json}
   ▼  site/build.py
docs/  index.html（検索）/ companies/<code>.html / search.json
   │
   ▼  GitHub Pages で公開 → ポータルサイトにリンク追加
```

LLM もサーバーも使わない。完全無料。

## セットアップ

1. EDINET API キー（無料）を取得: https://api.edinet-fsa.go.jp/
2. `.env` に記入（`.gitignore` 済み）:
   ```
   EDINET_API_KEY=xxxxxxxx
   ```
3. 依存インストール:
   ```
   pip install -r requirements.txt
   ```

## 使い方（ローカル）

```bash
# 1 銘柄だけ試す
python scripts/run_pipeline.py 285A

# companies.txt の全銘柄を更新（既存銘柄は直近 90 日だけ確認）
python scripts/update_all.py
python scripts/update_all.py --full    # 全銘柄フルスキャン

# サイト生成（docs/ に出力）
python site/build.py

# ローカル確認
python -m http.server -d docs 8000
```

銘柄を増やすには `companies.txt` に証券コードを 1 行ずつ追加。

## GitHub Pages 公開手順（初回のみ）

1. GitHub にリポジトリを作成して push
2. Settings → Secrets and variables → Actions に `EDINET_API_KEY` を登録
3. Settings → Pages → Source を **GitHub Actions** に設定
4. Actions タブで `update` ワークフローを手動実行（以降は毎日自動）
5. 公開 URL をポータル（https://git-san-934.github.io/portal/ ）に追加

## ファイル構成

| パス | 役割 |
|---|---|
| `scripts/edinet_common.py` | EDINET API 呼び出し・書類一覧キャッシュ |
| `scripts/find_doc.py` | 証券コード（secCode）→ 最新の有報 docID |
| `scripts/extract_business.py` | CSV から「事業の内容」を抽出 |
| `scripts/htmltext.py` | テキストブロック(HTML断片)の簡易テキスト化 |
| `scripts/run_pipeline.py` | 1 銘柄分の一連処理 |
| `scripts/update_all.py` | `companies.txt` 全銘柄の更新 |
| `site/build.py` | 静的サイト生成 |
| `data/` | 抽出結果（コミット対象） |
| `docs/` | 生成された公開サイト（コミット対象） |
| `cache/` | EDINET ダウンロードキャッシュ（Git 管理外） |

## 今後の検討（開発.md ③(2)「それ以外は相談」）

- 財務3表の一覧化（XBRL の数値タグ、今期/前期/増減率）— コードのみ・無料
- 事業等のリスク / MD&A など他テキストブロックの抽出
- 定量レッドフラグ（株式報酬費用、希薄化株式数の推移 等）
- 3 行要約（中学生向け）— Gemini 無料枠 or NotebookLM
- 四半期／半期報告書、新規上場時の目論見書
