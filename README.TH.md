# unpy-mcp — Notion MCP Server + CLI

> **unpy** = **un**official Notion **p**ython — ไคลเอนต์แบบ cookie สำหรับ internal API ของ Notion

**ภาษาอื่น:** [English](README.md) | [ไทย](README.TH.md) | [日本語](README.JA.md)

---

ไคลเอนต์ Python 3.12+ แบบ non-official สำหรับ internal API (v3) ของ Notion
มี 3 แพ็กเกจใน repo เดียว:

- **unpy-mcp** — MCP server (25 tools) สำหรับ Claude Desktop, Cursor, VS Code, Codex, Claude Code
- **unpy-cli** — เครื่องมือ command line (25 คำสั่ง ครบความสามารถเท่ากัน)
- **unpy-core** — Python library สำหรับต่อยอดในโค้ดของคุณเอง

ทุกอย่างขับเคลื่อนด้วย cookie `token_v2` จาก browser session ของ Notion ที่
ล็อกอินอยู่ — จึง **ใช้ได้กับบัญชี Guest** ซึ่ง official API ทำไม่ได้

> ⚠️ **ข้อควรระวัง**: โปรเจกต์นี้ใช้ internal API ที่ไม่ได้เป็นทางการของ Notion
> ไม่ใช่ official API — อาจพังเมื่อ Notion เปลี่ยนแปลง และการใช้งานต้องอยู่ใน
> ขอบเขต ToS ของ Notion โดยความเสี่ยงเป็นของผู้ใช้ ดู [docs/adr/](docs/adr/)
> สำหรับการตัดสินใจด้านดีไซน์

---

## สารบัญ

1. [เริ่มใช้งานเร็ว ๆ](#เริ่มใช้งานเร็ว-ๆ)
2. [AI ของคุณทำอะไรได้บ้าง](#ai-ของคุณทำอะไรได้บ้าง)
3. [CLI](#cli)
4. [วิธีเอา token_v2](#วิธีเอา-token_v2)
5. [ตั้งค่า space ID](#ตั้งค่า-space-id)
6. [ใช้งานระยะไกล (HTTP) — แชร์ทีม](#ใช้งานระยะไกล-http--แชร์ทีม)
7. [Python library](#python-library)
8. [AI skills สำหรับ agent](#ai-skills-สำหรับ-agent)
9. [การพัฒนา](#การพัฒนา)

---

## เริ่มใช้งานเร็ว ๆ

**คำสั่งเดียว** — ตัวติดตั้งจะตรวจหา `uvx` (ถ้าไม่มีจะติดตั้งให้), ถามว่าจะตั้งค่า
AI client ตัวไหนบ้าง, แนะนำวิธีเอา `NOTION_TOKEN_V2` แล้วเขียน config ให้แต่ละ
client (MCP servers เดิมไม่ถูกแตะ มี backup ก่อนแก้ไฟล์ทุกครั้ง):

**macOS / Linux:**
```bash
curl -fsSL https://raw.githubusercontent.com/PigRabbBoy/npy-mcp/master/scripts/install.sh | bash
```

**Windows (PowerShell):**
```powershell
irm https://raw.githubusercontent.com/PigRabbBoy/npy-mcp/master/scripts/install.ps1 | iex
```

ตัวติดตั้งจะถาม:
1. **จะลงให้ AI client ตัวไหน?** — เลือกได้หลายตัว: Claude Desktop, Claude Code,
   Cursor, VS Code, Codex, opencode, Windsurf
2. **`NOTION_TOKEN_V2`** — มีวิธีทำบนหน้าจอบอก (DevTools → Application →
   Cookies → `token_v2`)
3. **`NOTION_SPACE_ID`** — ไม่บังคับ; บอกวิธีหาถ้าคุณอยู่หลาย workspace
4. **เปิด write tools ไหม?** — opt-in (`NOTION_ALLOW_WRITE`), ค่าเริ่มต้นอ่านอย่างเดียว

จากนั้น restart AI client แบบปิดสนิทแล้วลองถาม:
> "หาหน้าเกี่ยวกับ project status ใน Notion" — เท่านี้เอง

**เขียน script / ใช้ใน CI?** ใช้ flags เพื่อข้ามคำถาม:
```bash
curl -fsSL https://raw.githubusercontent.com/PigRabbBoy/npy-mcp/master/scripts/install.sh | bash -s -- \
  --client claude-desktop --client cursor \
  --token "v03%3AeyJ..." --allow-write
```

**ถอนการติดตั้ง:**
```bash
curl -fsSL https://raw.githubusercontent.com/PigRabbBoy/npy-mcp/master/scripts/uninstall.sh | bash
```

<details>
<summary>อยากตั้งค่าเอง? (config ราย client, Docker, pip)</summary>

**uvx (ไม่ต้องติดตั้งอะไร)** — ติดตั้ง [uv](https://docs.astral.sh/uv/) ครั้งเดียว:
`curl -LsSf https://astral.sh/uv/install.sh | sh`

**Claude Desktop** (`~/Library/Application Support/Claude/claude_desktop_config.json` บน macOS, `%APPDATA%\Claude\claude_desktop_config.json` บน Windows) / **Cursor** (`.cursor/mcp.json`) / **Claude Code** (`.mcp.json`):
```json
{
  "mcpServers": {
    "unpy-mcp": {
      "command": "uvx",
      "args": ["--refresh", "--from", "git+https://github.com/PigRabbBoy/npy-mcp#subdirectory=packages/unpy-mcp", "unpy-mcp"],
      "env": {
        "NOTION_TOKEN_V2": "v03%3AeyJ..."
      }
    }
  }
}
```

**VS Code** (`.vscode/mcp.json`) — เหมือนกันแต่ใส่ `"type": "stdio"` และอยู่ใต้ key `"servers"`:
```json
{
  "servers": {
    "unpy-mcp": {
      "type": "stdio",
      "command": "uvx",
      "args": ["--refresh", "--from", "git+https://github.com/PigRabbBoy/npy-mcp#subdirectory=packages/unpy-mcp", "unpy-mcp"],
      "env": { "NOTION_TOKEN_V2": "v03%3AeyJ..." }
    }
  }
}
```

**Codex** (`~/.codex/config.toml`):
```toml
[mcp_servers.unpy-mcp]
command = "uvx"
args = ["--refresh", "--from", "git+https://github.com/PigRabbBoy/npy-mcp#subdirectory=packages/unpy-mcp", "unpy-mcp"]
env = { NOTION_TOKEN_V2 = "v03%3AeyJ..." }
```

**Docker** (ไม่ต้องมี Python/uv) — config เดิมแต่เปลี่ยน command เป็น docker:
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

**pip install** (สำหรับคนเขียน Python):
```bash
pip install "git+https://github.com/PigRabbBoy/npy-mcp#subdirectory=packages/unpy-mcp"
```
แล้วใช้ `"command": "python"`, `"args": ["-m", "unpy_mcp"]` ใน config
</details>

<details>
<summary>💡 เรื่องสิทธิ์เขียน (สร้าง/แก้ไข/ลบ)</summary>

Server เริ่มแบบ **อ่านอย่างเดียว** (8 read tools) ตัวติดตั้งจะถามว่าจะเปิด
write ไหม ถ้าอยากเปลี่ยนทีหลัง ให้เพิ่มบรรทัดเดียวใน `env` หรือรันตัวติดตั้ง
ซ้ำ:

```json
"env": {
  "NOTION_TOKEN_V2": "v03%3AeyJ...",
  "NOTION_ALLOW_WRITE": "1"
}
```

ออกแบบไว้แบบนี้ตั้งใจ: ป้องกันไม่ให้ AI แก้ workspace ของคุณ เว้นแต่คุณ
เปิดเองชัดเจน ดู [ADR-0005](docs/adr/0005-read-write-scope-gated.md)
</details>

---

## AI ของคุณทำอะไรได้บ้าง

ครบทั้งหมด **25 tools** (อ่าน 8 + เขียน 17):

| อ่าน — ใช้ได้เสมอ | |
|---|---|
| `search` | ค้นหา page/block ทั่วทั้ง workspace |
| `get_page` | เนื้อหา page เป็น Markdown หรือ JSON (คุมความลึกได้) |
| `get_block` | block เดี่ยวจาก URL/ID |
| `get_image` | ดาวน์โหลดรูป/ไฟล์แล้วส่งกลับแบบ inline |
| `list_pages` | page ล่าสุด (ทั้ง workspace หรือใต้ parent ใด ๆ) |
| `get_database` | schema + sample rows (`full_schema` ดึงทุกอย่าง ใช้ทำ provisioning) |
| `query_database` | กรอง/เรียง rows — formula และ rollup ถูกคำนวณเต็มรูปแบบ |
| `get_comments` | อ่าน thread comment บน page/block |

| เขียน — ต้องมี `NOTION_ALLOW_WRITE=1` | |
|---|---|
| `create_page` | สร้าง page ใหม่ใต้ parent |
| `append_blocks` | เพิ่ม block (13 ชนิด) ลง page |
| `update_block` | แก้ข้อความ / กด checkbox |
| `delete_block` | ลบถังขยะ หรือลบถาวร |
| `move_block` | ย้าย block ไปก้อนอื่น |
| `add_alias` | ทำ alias ของ page ไปอีก parent |
| `add_database_row` / `update_database_row` / `delete_database_row` | จัดการ rows |
| `create_database` / `add_column` | สร้าง database พร้อมคอลัมน์ **relation / formula / rollup** |
| `create_media` | แนบรูป/ไฟล์จาก URL หรืออัปโหลดจากเครื่อง |
| `create_embed` | ฝังเนื้อหา 20 providers (YouTube, Figma, Maps…) |
| `create_table` / `create_columns` | block ตาราง / layout แบบคอลัมน์ |
| `import_csv` | CSV → inline database |
| `add_comment` | คอมเมนต์บน page (thread ใหม่หรือตอบ) |

คู่มือเต็ม: [`TOOLS.md`](packages/unpy-mcp/skills/unpy-mcp/TOOLS.md)

<details>
<summary><b>ตัวอย่างการสร้าง schema</b> — relation, formula, rollup</summary>

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

- **`reverse_name`** สร้าง relation แบบ **two-way sync ของจริง** — property
  mirror จะถูกสร้างบน database ปลายทาง (เขียนใน transaction เดียว เหมือนที่
  client ของ Notion เองทำ) และการ link row จะ propagate สองฝั่ง
- วันที่รับ ISO string (`"2026-01-31"`, `"2026-01-31T14:30"`)
- property `files` รับ local path (อัปโหลดขึ้น Notion ให้อัตโนมัติ)
</details>

---

## CLI

ชอบ terminal? ความสามารถเท่ากันทุกอย่าง 25 คำสั่ง:

```bash
# ติดตั้งจากซอร์ส (ได้คำสั่ง `unpy`)
git clone https://github.com/PigRabbBoy/npy-mcp.git && cd unpy-mcp
uv sync
export NOTION_TOKEN_V2="v03%3AeyJ..."
uv run unpy --help
```

```bash
# อ่าน
uv run unpy search "project"                    # ค้นหา page/block
uv run unpy get-page <PAGE_ID> --depth 2        # ต้นไม้ page เป็น markdown
uv run unpy list-pages                          # page ระดับบนล่าสุด
uv run unpy get-database <DB_ID> --sample 5     # schema + sample rows
uv run unpy query-database <DB_ID> --limit 20   # ดึง rows
uv run unpy get-image <BLOCK_ID>                # ดาวน์โหลดรูป
uv run unpy get-comments <PAGE_ID>              # อ่านคอมเมนต์

# เขียน (ต้องมี NOTION_ALLOW_WRITE=1)
uv run unpy create-page <PARENT_ID> --title "New Page"
uv run unpy append-blocks <PAGE_ID> --blocks '[{"type":"todo","text":"Ship it"}]'
uv run unpy add-database-row <DB_ID> --properties '{"Name":"New row","Status":"Todo"}'
uv run unpy create-database <PARENT_ID> --title "Tasks" \
  --columns '[{"name":"Name","type":"title"},{"name":"Done","type":"checkbox"}]'
uv run unpy add-comment <PAGE_ID> --text "Look at this"

# Auth
uv run unpy auth whoami && uv run unpy auth spaces
```

> เคล็ดลับ: `source .venv/bin/activate` ครั้งเดียว แล้วตัด `uv run` ทิ้งได้เลย

ดู option ทั้งหมดด้วย `unpy <command> --help` คำสั่งเขียนจะปฏิเสธทำงานถ้า
ไม่ได้ตั้ง `NOTION_ALLOW_WRITE=1`

---

## วิธีเอา token_v2

1. เปิด [app.notion.com](https://app.notion.com) ใน Chrome (ล็อกอินแล้ว)
2. **F12** → แท็บ **Application** → **Cookies** → `https://app.notion.com`
3. คัดลอก **Value** ของ `token_v2` — string ยาวที่ขึ้นต้นด้วย `v03%3A...`

> 🔐 **ความปลอดภัย**: `token_v2` = สิทธิ์เข้าถึงบัญชี Notion ของคุณเต็มรูปแบบ
> ห้าม commit ลง git หรือแชร์กับใคร ทำหมดอายุได้โดยไปที่ Notion → Settings →
> Log out of all sessions โทเคนจะหมดอายุเป็นระยะ — ถ้าเจอ `401 Unauthorized`
> ให้เอาใหม่ด้วยวิธีเดียวกัน

---

## ตั้งค่า space ID

จำเป็นเฉพาะเมื่อโทเคนของคุณเห็น **หลาย workspace** ไม่งั้นข้ามได้ — จะใช้
space แรกที่เจอ

```bash
# ดูรายการ space ของคุณ (* คือตัวปัจจุบัน)
uv run unpy auth spaces

# ตั้งค่า default (บันทึกที่ ~/.config/unpy-mcp/config.toml)
uv run unpy auth use-space <SPACE_ID>
```

หรือผ่าน env var / MCP config: `"NOTION_SPACE_ID": "<space-id>"`

ลำดับการอ่านค่า: `NOTION_SPACE_ID` env → `~/.config/unpy-mcp/config.toml` → space แรกใน token data

<details>
<summary>วิธีหา space ID แบบอื่น</summary>

**Browser DevTools:** F12 → Network → เปิด page ใน Notion → หา
`api/v3/loadUserContent` → ใน response, key ใต้ `"space": {...}` คือ
space ID ของคุณ

space ID หน้าตาเป็น UUID: `1b6d9f59-d372-43b7-8cfc-332e473b1f2c`
</details>

---

## ใช้งานระยะไกล (HTTP) — แชร์ทีม

รัน server คืนเดียวแชร์กันทั้งทีม ผ่าน HTTP + Bearer auth:

```bash
NOTION_TOKEN_V2="your-token" \
NOTION_MCP_AUTH_TOKEN="shared-secret" \
python -m unpy_mcp --transport http --host 0.0.0.0 --port 8000
```

ชี้ AI client มาที่ server:

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
<summary>หลาย client: server เดียว โทเคนรายคน</summary>

แต่ละ client ส่ง Notion token ของตัวเองผ่าน header `X-Notion-Token` ได้ —
server จะสร้าง `NotionClient` แยก (แบบ cache) ให้แต่ละโทเคน:

```bash
curl -X POST http://localhost:8000/mcp \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer shared-secret" \
  -H "X-Notion-Token: v03%3AeyJ..." \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
```

ไม่ส่ง header → ใช้ `NOTION_TOKEN_V2` ของ server เป็นค่าเริ่มต้น
</details>

<details>
<summary><b>ติดตั้งด้วย Docker</b></summary>

```bash
# ดึง image สำเร็จรูป (แนะนำ)
docker pull pigrabbboy/npy-mcp:latest

# หรือ build เอง (จาก root ของ repo)
docker build -t unpy-mcp -f packages/unpy-mcp/Dockerfile .

# รันเป็น HTTP server
docker run -d -p 8000:8000 \
  -e NOTION_TOKEN_V2="your-token_v2" \
  -e NOTION_MCP_AUTH_TOKEN="shared-secret" \
  -e NOTION_ALLOW_WRITE=0 \
  pigrabbboy/npy-mcp:latest

# หรือใช้ docker compose
cd packages/unpy-mcp && cp .env.example .env && docker compose up -d
```
</details>

---

## Python library

ใช้ `unpy-core` ตรง ๆ ในโค้ดของคุณ:

```python
from unpy.client import NotionClient

client = NotionClient(token_v2="v03%3AeyJ...")

# อ่าน
page = client.get_block("<PAGE_URL_OR_ID>")
print(page.title_plaintext)

# query database พร้อมคำนวณ formula/rollup
from unpy.collection import CollectionQuery
cv = client.get_collection_view("<DB_URL>")
for row in cv.build_query().execute():
    print(row.title, row.get_property("Budget Rollup"))

# เขียน (property ใช้ชื่อ slug; relation แบบ two-way sync ทั้งสองฝั่ง)
row = cv.collection.add_row(Name="My row", Status="Todo")
row.Done = True
```

---

## AI skills สำหรับ agent

Skill พร้อมใช้ ช่วยให้ agent รู้ว่าควรใช้ tool ไหนเมื่อไหร่:

```bash
# unpy-mcp skill: การเลือก tool, workflow, ความปลอดภัยด้านการเขียน
cp -r packages/unpy-mcp/skills/unpy-mcp ~/.claude/skills/unpy-mcp   # Claude Code
cp -r packages/unpy-mcp/skills/unpy-mcp ~/.config/opencode/skills/    # opencode
# (รูปแบบเดียวกันกับ ~/.agents/skills/)

# release skill: จัดการเวอร์ชัน, changelog, tag
cp -r packages/unpy-mcp/skills/release ~/.claude/skills/release
```

- `SKILL.md` — tool ไหนใช้เมื่อไหร่, workflow ที่พบบ่อย, กติกาความปลอดภัย
- `TOOLS.md` — คู่มือเต็ม 25 tools (args, types, ตัวอย่าง, error messages)

---

## การพัฒนา

```bash
uv sync --extra dev                       # ติดตั้งพร้อม dev deps
python -m pytest tests/ -v                # 126 tests ไม่ต้องเรียก Notion จริง
python run_smoke_test.py --page <URL> --token <TOKEN_V2>   # ทดสอบเชื่อม Notion จริง
```

```
unpy-mcp/
├── packages/
│   ├── unpy-core/src/unpy/        ← Core library
│   │   ├── client.py              ← NotionClient (HTTP, auth, transactions)
│   │   ├── block.py               ← Block + 38 subclasses
│   │   ├── collection.py          ← Database, row, query builder
│   │   ├── store.py               ← RecordStore (cache thread-safe)
│   │   ├── markdown.py            ← rich-text ↔ CommonMark
│   │   ├── auth.py                ← แก้ปัญหา token + space
│   │   └── operations.py          ← ตัวสร้าง transaction op
│   ├── unpy-cli/src/unpy_cli/     ← CLI (Typer, 25 commands)
│   └── unpy-mcp/src/unpy_mcp/     ← MCP server (25 tools, stdio + HTTP)
├── tests/                         ← 126 tests (pytest + vcr.py)
├── docs/adr/                      ← Architecture Decision Records 8 ฉบับ
├── CONTEXT.md                     ← อภิธานศัพท์ของ domain
├── scripts/                       ← installer + uninstaller คำสั่งเดียว
└── run_smoke_test.py              ← ทดสอบเชื่อม Notion จริง
```

## การตัดสินใจด้านดีไซน์

ดู [docs/adr/](docs/adr/) สำหรับการตัดสินใจหลัก:
1. ใช้คำว่า "Database" เป็นศัพท์หลัก (ไม่ใช่ "Collection")
2. Current Space ผูกตอน init (ไม่สลับกลางทาง)
3. ส่งออก Markdown ฝั่ง server ผ่าน `getBlockExport`
4. Auth ผู้ใช้เดียว ไม่ดึงข้อมูลจาก browser
5. สิทธิ์เขียนถูก gate ด้วย `NOTION_ALLOW_WRITE=1`

## License

MIT