# unpy-mcp — Notion MCP Server + CLI

> **unpy** = **un**official Notion **p**ython — ログイン済み Notion セッションの Cookie を使ったクライアント

**他の言語:** [English](README.md) | [ไทย](README.TH.md) | [日本語](README.JA.md)

---

Notion の内部 API（v3）向けの非公式 Python 3.12+ クライアント。1 つのリポジトリに
3 パッケージ：

- **unpy-mcp** — MCP サーバー（25 ツール）。Claude Desktop、Cursor、VS Code、Codex、Claude Code に対応
- **unpy-cli** — コマンドラインツール（25 コマンド、MCP と同等の機能）
- **unpy-core** — 単体で使える Python ライブラリ

すべて `token_v2` Cookie（ログイン済み Notion ブラウザセッションのもの）で動作するため、
**Guest ユーザーでも使えます** — 公式 API ではできません。

> ⚠️ **注意**：本プロジェクトは Notion の非公開内部 API を使用しており、公式 API では
> ありません。Notion の変更で動かなくなる可能性があり、Notion の ToS の範囲内での
> ご利用は自己責任となります。設計上の判断は [docs/adr/](docs/adr/) を参照してください。

---

## 目次

1. [クイックスタート](#クイックスタート)
2. [AI にできること](#ai-にできること)
3. [CLI](#cli)
4. [token_v2 の取得方法](#token_v2-の取得方法)
5. [スペース ID の設定](#スペース-id-の設定)
6. [リモート（HTTP）— チーム共有](#リモートhttp- チーム共有)
7. [Python ライブラリ](#python-ライブラリ)
8. [エージェント用 AI スキル](#エージェント用-ai-スキル)
9. [開発](#開発)

---

## クイックスタート

**コマンド 1 つ** — インストーラーは `uvx` の有無を確認し（なければインストール）、
どの AI クライアントに設定するかを尋ね、`NOTION_TOKEN_V2` の取得手順を案内して、
各クライアントの設定ファイルを書き込みます（既存の MCP サーバーは保持され、
編集前にバックアップを作成）：

**macOS / Linux：**
```bash
curl -fsSL https://raw.githubusercontent.com/PigRabbBoy/npy-mcp/master/scripts/install.sh | bash
```

**Windows（PowerShell）：**
```powershell
irm https://raw.githubusercontent.com/PigRabbBoy/npy-mcp/master/scripts/install.ps1 | iex
```

インストーラーの質問：
1. **どの AI クライアントに？** — 複数選択可：Claude Desktop、Claude Code、Cursor、
   VS Code、Codex、opencode、Windsurf
2. **`NOTION_TOKEN_V2`** — 画面上で手順を案内（DevTools → Application →
   Cookies → `token_v2`）
3. **`NOTION_SPACE_ID`** — 任意。複数ワークスペースがある場合の探し方を案内
4. **書き込みツールを有効にする？** — オプトイン（`NOTION_ALLOW_WRITE`）、デフォルトは読み取り専用

完了したら AI クライアントを完全に再起動して、試してみてください：
> 「Notion で project status に関するページを探して」 — 以上です。

**スクリプト / CI での利用？** フラグでプロンプトをスキップできます：
```bash
curl -fsSL https://raw.githubusercontent.com/PigRabbBoy/npy-mcp/master/scripts/install.sh | bash -s -- \
  --client claude-desktop --client cursor \
  --token "v03%3AeyJ..." --allow-write
```

**アンインストール：**
```bash
curl -fsSL https://raw.githubusercontent.com/PigRabbBoy/npy-mcp/master/scripts/uninstall.sh | bash
```

<details>
<summary>手動設定したい場合（クライアント別設定、Docker、pip）</summary>

**uvx（インストール不要）** — [uv](https://docs.astral.sh/uv/) を一度インストール：
`curl -LsSf https://astral.sh/uv/install.sh | sh`

**Claude Desktop**（macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`、Windows: `%APPDATA%\Claude\claude_desktop_config.json`）/ **Cursor**（`.cursor/mcp.json`）/ **Claude Code**（`.mcp.json`）：
```json
{
  "mcpServers": {
    "unpy-mcp": {
      "command": "uvx",
      "args": ["--refresh", "--from", "git+https://github.com/PigRabbBoy/npy-mcp@v1.0.2#subdirectory=packages/unpy-mcp", "unpy-mcp"],
      "env": {
        "NOTION_TOKEN_V2": "v03%3AeyJ..."
      }
    }
  }
}
```

**VS Code**（`.vscode/mcp.json`）— 同じ形ですが `"type": "stdio"` を付け、`"servers"` キーの下に置きます：
```json
{
  "servers": {
    "unpy-mcp": {
      "type": "stdio",
      "command": "uvx",
      "args": ["--refresh", "--from", "git+https://github.com/PigRabbBoy/npy-mcp@v1.0.2#subdirectory=packages/unpy-mcp", "unpy-mcp"],
      "env": { "NOTION_TOKEN_V2": "v03%3AeyJ..." }
    }
  }
}
```

**Codex**（`~/.codex/config.toml`）：
```toml
[mcp_servers.unpy-mcp]
command = "uvx"
args = ["--refresh", "--from", "git+https://github.com/PigRabbBoy/npy-mcp@v1.0.2#subdirectory=packages/unpy-mcp", "unpy-mcp"]
env = { NOTION_TOKEN_V2 = "v03%3AeyJ..." }
```

**Docker**（Python/uv 不要）— 上記と同じ設定でコマンドを docker にするだけ：
```json
{
  "mcpServers": {
    "unpy-mcp": {
      "command": "docker",
      "args": ["run", "--rm", "-i", "-e", "NOTION_TOKEN_V2", "pigrabbboy/npy-mcp:latest", "--transport", "stdio"],
      "env": { "NOTION_TOKEN_V2": "v03%3AeyJ..." }
    }
  }
}
```

**pip install**（Python 開発者向け）：
```bash
pip install "git+https://github.com/PigRabbBoy/npy-mcp@v1.0.2#subdirectory=packages/unpy-mcp"
```
設定には `"command": "python"`、`"args": ["-m", "unpy_mcp"]` を使用してください。
</details>

<details>
<summary>💡 書き込み権限について（作成・更新・削除）</summary>

サーバーは**読み取り専用**（読み取り 8 ツール）で起動します。インストーラーが
書き込みの有効化を尋ねます。後で変更するには `env` に 1 行追加するか、
インストーラーを再実行：

```json
"env": {
  "NOTION_TOKEN_V2": "v03%3AeyJ...",
  "NOTION_ALLOW_WRITE": "1"
}
```

意図的な設計です：明示的にオプトインしない限り、AI がワークスペースを
編集できません。[ADR-0005](docs/adr/0005-read-write-scope-gated.md) を参照。
</details>

---

## AI にできること

全 **25 ツール**（読み取り 8 + 書き込み 17）：

| 読み取り — 常に利用可能 | |
|---|---|
| `search` | ワークスペース全体のページ/ブロックを検索 |
| `get_page` | ページの内容を Markdown または JSON で取得（階層の深さを制御） |
| `get_block` | URL/ID で単一ブロックを取得 |
| `get_image` | 画像/ファイルブロックをダウンロードしてインラインで返す |
| `list_pages` | 最近のページ（ワークスペース全体または親配下） |
| `get_database` | スキーマ + サンプル行（`full_schema` で全定義をダンプ、プロビジョニング用） |
| `query_database` | 行のフィルタ/ソート — 数式（formula）とロールアップを完全に評価 |
| `get_comments` | ページ/ブロック上のコメントスレッドを読む |

| 書き込み — `NOTION_ALLOW_WRITE=1` が必要 | |
|---|---|
| `create_page` | 親の下に新しいページを作成 |
| `append_blocks` | ページにブロックを追加（13 種類） |
| `update_block` | テキスト編集 / チェックボックス切替 |
| `delete_block` | ゴミ箱へ移動 / 完全削除 |
| `move_block` | ブロックを別の親へ移動 |
| `add_alias` | ページのエイリアスを別の親に作成 |
| `add_database_row` / `update_database_row` / `delete_database_row` | 行の管理 |
| `create_database` / `add_column` | **relation / formula / rollup** 列付きデータベースをプロビジョニング |
| `create_media` | URL またはローカルファイルから画像/ファイルを添付 |
| `create_embed` | 20 プロバイダーの埋め込み（YouTube、Figma、Maps…） |
| `create_table` / `create_columns` | テーブルブロック / カラムレイアウト |
| `import_csv` | CSV → インラインデータベース |
| `add_comment` | ページにコメント（新規スレッドまたは返信） |

完全なリファレンス：[`TOOLS.md`](packages/unpy-mcp/skills/unpy-mcp/TOOLS.md)

<details>
<summary><b>スキーマプロビジョニングの例</b> — リレーション、数式、ロールアップ</summary>

```json
[
  {"name": "Task", "type": "title"},
  {"name": "Project", "type": "relation",
   "target_database_id": "<db url or id>",
   "limit": 1, "reverse_name": "Tasks"},
  {"name": "Done", "type": "checkbox"},
  {"name": "Status", "type": "formula",
   "expression": "if({\"Done\"}, \"✅ done\", \"⬜ open\")"},
  {"name": "Budget Rollup", "type": "rollup",
   "relation_property": "Project", "target_property": "Budget",
   "aggregation": "sum"}
]
```

- **`reverse_name`** を付けると本物の**双方向同期リレーション**になります —
  対象データベース側にもミラーのプロパティが作成され（Notion 本家のクライアントと
  同じ形で 1 つのトランザクションに書き込み）、行レベルのリンクも両側に反映されます。
- 日付は ISO 文字列（`"2026-01-31"`、`"2026-01-31T14:30"`）を受け付けます。
- `files` プロパティはローカルパスを受け付け（Notion へ自動アップロード）。
</details>

---

## CLI

ターミナル派の方へ。同じ機能の 25 コマンド：

```bash
# ソースからインストール（`unpy` コマンドが使えるようになります）
git clone https://github.com/PigRabbBoy/npy-mcp.git && cd unpy-mcp
uv sync
export NOTION_TOKEN_V2="v03%3AeyJ..."
uv run unpy --help
```

```bash
# 読み取り
uv run unpy search "project"                    # ページ/ブロックを検索
uv run unpy get-page <PAGE_ID> --depth 2        # ページツリーを markdown で
uv run unpy list-pages                          # 最近のトップレベルページ
uv run unpy get-database <DB_ID> --sample 5     # スキーマ + サンプル行
uv run unpy query-database <DB_ID> --limit 20   # 行を取得
uv run unpy get-image <BLOCK_ID>                # 画像をダウンロード
uv run unpy get-comments <PAGE_ID>              # コメントを読む

# 書き込み（NOTION_ALLOW_WRITE=1 が必要）
uv run unpy create-page <PARENT_ID> --title "New Page"
uv run unpy append-blocks <PAGE_ID> --blocks '[{"type":"todo","text":"Ship it"}]'
uv run unpy add-database-row <DB_ID> --properties '{"Name":"New row","Status":"Todo"}'
uv run unpy create-database <PARENT_ID> --title "Tasks" \
  --columns '[{"name":"Name","type":"title"},{"name":"Done","type":"checkbox"}]'
uv run unpy add-comment <PAGE_ID> --text "Look at this"

# 認証
uv run unpy auth whoami && uv run unpy auth spaces
```

> ヒント：`source .venv/bin/activate` を一度実行すれば `uv run` を省略できます。

全オプションは `unpy <command> --help` で確認できます。書き込みコマンドは
`NOTION_ALLOW_WRITE=1` なしでは実行を拒否します。

---

## token_v2 の取得方法

1. Chrome で [app.notion.com](https://app.notion.com) を開く（ログイン済み）
2. **F12** → **Application** タブ → **Cookies** → `https://app.notion.com`
3. `token_v2` の **Value** をコピー — `v03%3A...` で始まる長い文字列です

> 🔐 **セキュリティ**：`token_v2` = Notion アカウントへの完全なアクセス権です。
> git へのコミットや共有は絶対にしないでください。無効化するには Notion →
> Settings → Log out of all sessions。トークンは定期的に失効します —
> `401 Unauthorized` が出たら同じ方法で再取得してください。

---

## スペース ID の設定

トークンが**複数のワークスペース**にアクセスできる場合のみ必要です。それ以外は
スキップ — 最初に見つかったスペースを使用します。

```bash
# スペース一覧を表示（* が現在のもの）
uv run unpy auth spaces

# デフォルトを設定（~/.config/unpy-mcp/config.toml に保存）
uv run unpy auth use-space <SPACE_ID>
```

または環境変数 / MCP 設定で：`"NOTION_SPACE_ID": "<space-id>"`

解決順序：`NOTION_SPACE_ID` 環境変数 → `~/.config/unpy-mcp/config.toml` → トークンデータの最初のスペース

<details>
<summary>スペース ID のその他の探し方</summary>

**ブラウザ DevTools：** F12 → Network → Notion のページを開く →
`api/v3/loadUserContent` を探す → レスポンス内の `"space": {...}` の下のキーが
スペース ID です。

スペース ID は UUID 形式：`22222222-2222-4222-8222-222222222222`
</details>

---

## リモート（HTTP）— チーム共有

Bearer 認証付きの HTTP サーバーとして 1 台共有：

```bash
NOTION_TOKEN_V2="your-token" \
NOTION_MCP_AUTH_TOKEN="shared-secret" \
python -m unpy_mcp --transport http --host 0.0.0.0 --port 8000
```

Bearer トークンは平文で送られるため、TLS（リバースプロキシ）の背後で運用してください。
実際のホスト名に対して DNS リバインディング保護を有効にするには
`NOTION_MCP_ALLOWED_HOSTS="mcp.example.com:*"` を設定します（ループバックへの
バインドは自動的に保護されます）。

AI クライアントから接続：

```json
{
  "mcpServers": {
    "unpy-mcp": {
      "url": "http://your-server:8000/mcp",
      "headers": { "Authorization": "Bearer shared-secret" }
    }
  }
}
```

<details>
<summary>マルチクライアント：1 サーバーでユーザーごとのトークン</summary>

各クライアントは `X-Notion-Token` ヘッダーで自分の Notion トークンを送れます —
サーバーはトークンごとに（キャッシュされた）個別の `NotionClient` を構築します：

```bash
curl -X POST http://localhost:8000/mcp \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer shared-secret" \
  -H "X-Notion-Token: v03%3AeyJ..." \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
```

ヘッダーなし → サーバーの `NOTION_TOKEN_V2` にフォールバック。
</details>

<details>
<summary><b>Docker でのデプロイ</b></summary>

```bash
# ビルド済みイメージを取得（推奨）
docker pull pigrabbboy/npy-mcp:latest

# 自分でビルド（リポジトリルートから）
docker build -t unpy-mcp -f packages/unpy-mcp/Dockerfile .

# HTTP サーバーとして実行
docker run -d -p 8000:8000 \
  -e NOTION_TOKEN_V2="your-token_v2" \
  -e NOTION_MCP_AUTH_TOKEN="shared-secret" \
  -e NOTION_ALLOW_WRITE=0 \
  pigrabbboy/npy-mcp:latest

# または docker compose
cd packages/unpy-mcp && cp .env.example .env && docker compose up -d
```
</details>

---

## Python ライブラリ

`unpy-core` をコードから直接使う：

```python
from unpy.client import NotionClient

client = NotionClient(token_v2="v03%3AeyJ...")

# 読み取り
page = client.get_block("<PAGE_URL_OR_ID>")
print(page.title_plaintext)

# 数式/ロールアップを評価しながらデータベースをクエリ
from unpy.collection import CollectionQuery
cv = client.get_collection_view("<DB_URL>")
for row in cv.build_query().execute():
    print(row.title, row.get_property("Budget Rollup"))

# 書き込み（プロパティはスラッグ名。双方向リレーションは自動同期）
row = cv.collection.add_row(Name="My row", Status="Todo")
row.Done = True
```

---

## エージェント用 AI スキル

エージェントがどのツールをいつ使うべきか分かる、すぐに使えるスキル：

```bash
# unpy-mcp スキル：ツール選択、ワークフロー、書き込みの安全規則
cp -r packages/unpy-mcp/skills/unpy-mcp ~/.claude/skills/unpy-mcp   # Claude Code
cp -r packages/unpy-mcp/skills/unpy-mcp ~/.config/opencode/skills/    # opencode
# （~/.agents/skills/ も同様）

# release スキル：バージョニング、changelog、タグ付け
cp -r packages/unpy-mcp/skills/release ~/.claude/skills/release
```

- `SKILL.md` — どのツールをいつ使うか、よくあるワークフロー、書き込みの安全規則
- `TOOLS.md` — 25 ツールの完全リファレンス（引数、型、例、エラーメッセージ）

---

## 開発

```bash
uv sync --extra dev                       # 開発依存込みでインストール
python -m pytest tests/ -v                # 126 テスト。Notion への実アクセスなし
python run_smoke_test.py --page <URL> --token <TOKEN_V2>   # 実 Notion との結合テスト
```

```
unpy-mcp/
├── packages/
│   ├── unpy-core/src/unpy/        ← コアライブラリ
│   │   ├── client.py              ← NotionClient（HTTP、認証、トランザクション）
│   │   ├── block.py               ← Block + 38 サブクラス
│   │   ├── collection.py          ← データベース、行、クエリビルダー
│   │   ├── store.py               ← RecordStore（スレッドセーフなキャッシュ）
│   │   ├── markdown.py            ← リッチテキスト ↔ CommonMark
│   │   ├── auth.py                ← トークン + スペースの解決
│   │   └── operations.py          ← トランザクション操作ビルダー
│   ├── unpy-cli/src/unpy_cli/     ← CLI（Typer、25 コマンド）
│   └── unpy-mcp/src/unpy_mcp/     ← MCP サーバー（25 ツール、stdio + HTTP）
├── tests/                         ← 126 テスト（pytest + vcr.py）
├── docs/adr/                      ← アーキテクチャ決定記録 8 本
├── CONTEXT.md                     ← ドメイン用語集
├── scripts/                       ← ワンコマンドのインストーラー/アンインストーラー
└── run_smoke_test.py              ← 実 Notion との結合テスト
```

## 設計上の判断

主要な判断は [docs/adr/](docs/adr/) を参照：
1. 「Database」が正式な用語（「Collection」ではない）
2. Current Space はクライアント初期化時に固定（実行時の切替なし）
3. `getBlockExport` によるサーバーサイド Markdown エクスポート
4. シングルユーザー認証、ブラウザキャプチャなし
5. 書き込みは `NOTION_ALLOW_WRITE=1` でゲート

## License

MIT