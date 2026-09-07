# 有価証券報告書 事業の内容ビューア

EDINET の有価証券報告書から「事業の内容」を抽出し、GitHub Pages の静的サイトで
検索・閲覧できるようにする。要件は [`開発.md`](開発.md) を参照。

現状は **MVP**（開発.md の ①〜③(1)、④）。定量分析・要約などは今後追加。

## 仕組み

```
scripts/list_targets.py
EDINET API v2 ──► 書類一覧を約500日さかのぼり、有価証券報告書(docTypeCode=120)で
   │             証券コードを持つ提出者を全部収集（≒4,000社） → cache/_targets.json
   ▼  scripts/update_all.py --all
   │  各社の最新 docID について（既取得ぶんはスキップ）
   ▼  書類取得API type=5 (CSV)
XBRL CSV ──► jpcrp_cor:DescriptionOfBusinessTextBlock を取り出し HTML→テキスト化
   │
   ▼  data/<証券コード>/{business.md, meta.json}   ← リポジトリにコミット
   ▼  site/build.py
docs/  index.html / companies/<code>.html / index.json（軽い一覧）/ bodies.json（本文）
   │   ← docs/ はコミットせず GitHub Actions でビルドして Pages へ
   ▼  GitHub Pages で公開 → ポータルサイトにリンク追加
```

`companies.txt` の手動メンテは不要（除外指定にのみ使う）。

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
# 対象銘柄を EDINET から収集（cache/_targets.json）
python scripts/list_targets.py

# 全提出者ぶんを取り込む（初回は数千件・2〜4時間。中断しても再実行で続きから）
python scripts/update_all.py --all --drop-csv
#   --limit 300 --offset 0   … 分割実行したいとき
#   --use-cached-manifest    … 収集済みリストを使い回す
#   失敗した銘柄は cache/_failures.json に記録される

# 1 銘柄だけ試す
python scripts/run_pipeline.py 285A

# サイト生成（docs/ に出力・コミットはしない）
python site/build.py

# ローカル確認
python -m http.server -d docs 8000
```

`companies.txt` は通常編集不要。除外したい銘柄は行頭に `-` を付ける（例 `-1234`）。

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
| `scripts/list_targets.py` | 書類一覧をさかのぼり有報提出者を全収集 → `cache/_targets.json` |
| `scripts/find_doc.py` | 証券コード（secCode）→ 最新の有報 docID（単発用） |
| `scripts/extract_business.py` | CSV から「事業の内容」を抽出 |
| `scripts/htmltext.py` | テキストブロック(HTML断片)の簡易テキスト化 |
| `scripts/run_pipeline.py` | 1 銘柄分の一連処理 |
| `scripts/update_all.py` | `--all` で全提出者、無指定で `companies.txt` を更新 |
| `site/build.py` | 静的サイト生成 |
| `data/` | 抽出結果（**コミット対象**） |
| `docs/` | 生成された公開サイト（コミットしない・CI でビルド） |
| `cache/` | EDINET ダウンロードキャッシュ・対象リスト（Git 管理外） |

## 今後の検討（開発.md ③(2)「それ以外は相談」）

- 財務3表の一覧化（XBRL の数値タグ、今期/前期/増減率）— コードのみ・無料
- 事業等のリスク / MD&A など他テキストブロックの抽出
- 定量レッドフラグ（株式報酬費用、希薄化株式数の推移 等）
- 3 行要約（中学生向け）— Gemini 無料枠 or NotebookLM
- 四半期／半期報告書、新規上場時の目論見書
