# Export API — captured payloads from the Notion web client (2026-09-28)

Captured live via BrowserOS fetch hooks on `enqueueTask` / `getTasks`
while driving the real Export dialog (userAction export flows).
All exports go through the async task system:

```
POST /api/v3/enqueueTask   {task: {...}}          → {taskId}
POST /api/v3/getTasks      {taskIds: [<taskId>]}  → poll until state == "success"
GET  <status.exportURL>    (signed S3/file.notion.com URL) → zip bytes
```

## enqueueTask payload — single-page markdown (recursive=false)

```json
{
  "task": {
    "eventName": "partitionedExportBlock",
    "request": {
      "block": {"id": "<page_id>", "spaceId": "<space_id>"},
      "recursive": false,
      "exportOptions": {
        "exportType": "markdown",
        "timeZone": "Asia/Bangkok",
        "locale": "en",
        "collectionViewExportType": "currentView",
        "includeContents": "everything",
        "preferredViewMap": {"<collection_id>": "<view_id>", ...}
      },
      "shouldExportComments": false,
      "spaceId": "<space_id>",
      "eventName": "partitionedExportBlock",
      "rootTaskId": "<uuid>"
    },
    "cellRouting": {"spaceIds": ["<space_id>"]}
  }
}
```

Notes:
- `eventName` in the request is `partitionedExportBlock` (NOT the legacy
  `exportBlock` our dead `Block.extract_markdown()` sends — that legacy
  name may still work but the UI uses partitioned).
- `rootTaskId` is a uuid the client generates (request body includes it;
  the returned taskId differs).
- `preferredViewMap` maps every collection id under the exported tree to
  the view the user is currently looking at. Sending `{}` is accepted
  (dead-code path does it); the UI fills it with current views.

## Option → payload mapping (what each dialog toggle changes)

| Dialog option            | Payload field                            | Values seen |
|--------------------------|------------------------------------------|-------------|
| Export format            | `exportOptions.exportType`               | `pdf`, `html`, `markdown` |
| Database views           | `exportOptions.collectionViewExportType` | `currentView` (menu offers "Current view"/"Everything") |
| Page content             | `exportOptions.includeContents`          | `everything` (menu: "Everything"/"No files" — legacy dead code used `no_files`) |
| Include subpages         | request-level `recursive`                | `true`/`false` |
| Create folders for subpages | `exportOptions.flattenExportFiletree` | present ONLY when recursive=true AND folders=off; absent when folders=on |
| Page format (PDF only)   | `exportOptions.pdfFormat`                | `Letter` (UI: Letter/A4/etc.) |
| Scale percent (PDF only) | not present in payload at 100%           | (UI field exists; not in captured payload) |
| Export comments (HTML only in UI) | `shouldExportComments`          | `false` captured; HTML dialog adds the toggle |

Key observations:
- `flattenExportFiletree` is ABSENT by default (folders ON is the
  default). It appears only when the user turns "Create folders" OFF.
- PDF dialog has `pdfFormat` (page size). HTML/Markdown dialogs have an
  "Export comments" toggle (`shouldExportComments`) which the PDF dialog
  does not show.
- `exportType: "pdf"` still exports database views as CSV inside the zip.
- `timeZone` is the browser's local timezone (affects date rendering in
  PDF/HTML; markdown CSV dates too).

## getTasks polling — response shape

While running:

```json
{"results": [{"id": "<taskId>", "state": "in_progress",
  "eventName": "partitionedExportBlock",
  "request": {...echo of request...},
  "status": {"type": "progress", "exportedCount": 2}}]}
```

On success:

```json
{"results": [{"id": "<taskId>", "state": "success",
  "eventName": "partitionedExportBlock",
  "request": {...},
  "status": {"type": "complete", "pagesExported": 3,
             "exportURL": "https://file.notion.com/f/t/..."}}]}
```

- `pagesExported`: number of pages/files in the zip.
- `exportURL`: signed URL, download directly (no auth headers needed in
  observed captures — plain GET works while signed).
- Poll cadence in UI: ~1s intervals. In-progress responses have
  `status.type: "progress"` + `exportedCount` (or no status early).

## Database export (full-page database, Actions → Export)

Same `partitionedExportBlock` with `block.id` = the collection-view
block id (view URL id, e.g. `c2213276-...?v=4fc28023` → block id
`c2213276-2622-4ad8-ac78-b57ab29fd48e`). Dialog for a database shows the
same options; `exportType` follows the chosen format. Database views
export as `<Name> <hash>.csv` files inside the zip (one per included
view).

## Legacy differences in our dead code (Block.extract_markdown, block.py:437)

- eventName `exportBlock` (old) vs `partitionedExportBlock` (current UI)
- host `https://www.notion.so/api/v3/...` vs current `app.notion.com`
- `includeContents: "no_files"` (UI default is `everything`)
- `timeZone: "America/Los_Angeles"` hardcoded (UI sends local tz)
- polls 5000× at 0.25s, then unzips and returns the single file's text
## LIVE API VERIFICATION (unpy export.py, 2026-09-28)

- `partitionedExportBlock` accepted with `preferredViewMap: {}` — works.
- **`collectionViewExportType` values**: `"currentView"` works;
  `"all"` works; **`"allViews"` HANGS the task forever** (in_progress,
  never finishes — observed >90s twice). The correct "everything" value
  is `"all"`, not `"allViews"`. export.py now maps all→"all".
- Even `currentView` on a database emits BOTH
  `<Name> <blockid>.csv` AND `<Name> <blockid>_all.csv` — the server
  includes a merged `_all.csv` alongside the per-view CSV.
- Markdown non-recursive on a page with inline databases: zip holds
  `Page.md` + one CSV per database (no folder nesting).
- Markdown recursive: files at zip root when "Create folders" OFF
  (`flattenExportFiletree: true`); nested folders when ON.
- PDF single page: zip holds the `.pdf` (verified: "PDF 1.4, 1 pages")
  plus database CSVs.
- HTML recursive: `.html` per page + nested folders + CSVs per database.
- One transient failure mode observed: `getTasks` returning HTTP 520/524
  (Cloudflare) right after enqueue — retrying the export succeeded.
  poll_export_task surfaces these as request errors (client.post raises).
