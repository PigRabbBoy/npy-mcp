"""Export Pages/Databases to PDF/HTML/Markdown via Notion's async export
task system (captured live from the web client — see
docs/notes/export-api-capture.md)."""

import io
import os
import time
import zipfile

from .settings import API_BASE_URL
from .utils import extract_id

EXPORT_FORMATS = ("pdf", "html", "markdown")
DATABASE_VIEW_MODES = ("current", "all")
PAGE_CONTENT_MODES = ("everything", "no_files")
PDF_FORMATS = ("Letter", "Legal", "Tabloid", "A0", "A1", "A2", "A3", "A4", "A5", "A6")

POLL_INTERVAL = 1.0


class ExportError(Exception):
    """Raised when an export task fails or times out."""


def build_export_options(
    format="markdown",
    recursive=False,
    database_views="current",
    page_content="everything",
    create_folders=True,
    pdf_format="Letter",
    export_comments=False,
    timezone=None,
    locale="en",
):
    """
    Map user-facing options onto the `exportOptions` block the Notion web
    client sends with a `partitionedExportBlock` task.

    - `format`: "pdf" | "html" | "markdown"
    - `recursive`: include subpages (request-level `recursive`)
    - `database_views`: "current" | "all" → `collectionViewExportType`
    - `page_content`: "everything" | "no_files" → `includeContents`
    - `create_folders`: when False AND recursive, the payload carries
      `flattenExportFiletree: true` (folders-on is the default: field absent)
    - `pdf_format`: PDF page size (pdf only)
    - `export_comments`: `shouldExportComments`
    - `timezone`: IANA name; None = local timezone (what the UI sends)
    """
    if format not in EXPORT_FORMATS:
        raise ValueError(
            "format must be one of {}, got {!r}".format(EXPORT_FORMATS, format)
        )
    if database_views not in DATABASE_VIEW_MODES:
        raise ValueError(
            "database_views must be one of {}, got {!r}".format(
                DATABASE_VIEW_MODES, database_views
            )
        )
    if page_content not in PAGE_CONTENT_MODES:
        raise ValueError(
            "page_content must be one of {}, got {!r}".format(
                PAGE_CONTENT_MODES, page_content
            )
        )
    if format == "pdf" and pdf_format not in PDF_FORMATS:
        raise ValueError(
            "pdf_format must be one of {}, got {!r}".format(PDF_FORMATS, pdf_format)
        )

    if timezone is None:
        from tzlocal import get_localzone

        timezone = str(get_localzone())

    options = {
        "exportType": format,
        "timeZone": timezone,
        "locale": locale,
        "collectionViewExportType": (
            "currentView" if database_views == "current" else "all"
        ),
        "includeContents": page_content,
        "preferredViewMap": {},
    }
    if format == "pdf":
        options["pdfFormat"] = pdf_format
    if recursive and not create_folders:
        options["flattenExportFiletree"] = True
    return options


def build_export_task(block_id, space_id, options, recursive, export_comments):
    """Build the full `enqueueTask` payload for a partitioned export."""
    from uuid import uuid4

    request = {
        "block": {"id": block_id, "spaceId": space_id},
        "recursive": recursive,
        "exportOptions": options,
        "shouldExportComments": export_comments,
        "spaceId": space_id,
        "eventName": "partitionedExportBlock",
        "rootTaskId": str(uuid4()),
    }
    return {
        "task": {
            "eventName": "partitionedExportBlock",
            "request": request,
            "cellRouting": {"spaceIds": [space_id]},
        }
    }


def poll_export_task(client, task_id, timeout=120.0):
    """
    Poll `getTasks` until the export task finishes. Returns the task's
    `status` dict (with `exportURL`). Raises ExportError on failure or
    timeout.
    """
    deadline = time.monotonic() + timeout
    while True:
        response = client.post("getTasks", {"taskIds": [task_id]}).json()
        results = response.get("results") or []
        if results:
            task = results[0]
            state = task.get("state")
            if state == "success":
                return task.get("status") or {}
            if state not in (None, "in_progress"):
                raise ExportError(
                    "Export task {} failed: {}".format(task_id, state)
                )
        if time.monotonic() >= deadline:
            raise ExportError(
                "Export task {} did not finish within {:.0f}s — retry with a "
                "higher timeout for large pages".format(task_id, timeout)
            )
        time.sleep(POLL_INTERVAL)


def unpack_export_zip(zip_bytes):
    """
    Unpack an export zip in memory. Returns (files, single_file_bytes):
    `files` is {path: bytes} for every entry; when the zip holds exactly
    one file, `single_file_bytes` is its content (else None).
    """
    files = {}
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        for info in z.infolist():
            if info.is_dir():
                continue
            files[info.filename] = z.read(info)
    single = next(iter(files.values())) if len(files) == 1 else None
    return files, single


def stream_export_zip_to_files(zip_bytes, output_dir):
    """Stream an export zip to disk entry-by-entry (v2, low-RAM).

    Instead of materializing every file as bytes in a dict (v1 buffers the
    whole archive in RAM), each entry is written directly to its target
    path as it is read from the zip stream. Returns (written paths, text)
    — `text` is only set when the archive held exactly one file.
    """
    written = []
    single = None
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        entries = [i for i in z.infolist() if not i.is_dir()]
        for info in entries:
            target = os.path.join(
                output_dir, *info.filename.replace("\\", "/").split("/")
            )
            os.makedirs(os.path.dirname(target) or output_dir, exist_ok=True)
            with open(target, "wb") as f:
                f.write(z.read(info))
            written.append(target)
        single = entries[0] if len(entries) == 1 else None
        single_bytes = (
            written[0] if len(written) == 1 else None
        )
    return written, single


def write_export_files(files, output_dir):
    """
    Write {relative_path: bytes} under `output_dir`, creating folders as
    needed. Returns the list of written absolute paths.
    """
    written = []
    for rel_path, content in files.items():
        target = os.path.join(output_dir, *rel_path.replace("\\", "/").split("/"))
        os.makedirs(os.path.dirname(target) or output_dir, exist_ok=True)
        with open(target, "wb") as f:
            f.write(content)
        written.append(target)
    return written


SINGLE_FILE_EXTENSIONS = {"pdf": ".pdf", "html": ".html", "markdown": ".md"}


def _single_file_name(client, block_id, ext):
    """Filename for a non-zip (single-file) export: the block's title when
    available, else the block id — e.g. "Doc a.pdf"."""
    stem = ""
    try:
        from .block import Block

        block = Block(client, block_id)
        raw = block.get(["properties", "title"]) or []
        stem = "".join(
            seg[0] for seg in raw
            if isinstance(seg, list) and seg and isinstance(seg[0], str)
            and not str(seg[0]).startswith("‣")
        ).strip()
    except Exception:
        stem = ""
    from .utils import slugify

    stem = slugify(stem or block_id)
    return stem + ext


def _write_single_file_export(content, output_dir, client, block_id, fmt):
    """A non-zip exportURL response (single page: Notion serves the file
    itself, e.g. %PDF bytes) is written as-is, never unzipped (issue #42).
    Returns (written paths, decoded text or None)."""
    ext = SINGLE_FILE_EXTENSIONS.get(fmt or "", "")
    target = os.path.join(output_dir, _single_file_name(client, block_id, ext))
    with open(target, "wb") as f:
        f.write(content)
    text = None
    if fmt in ("markdown", "html"):
        try:
            text = content.decode("utf-8")
        except (UnicodeDecodeError, AttributeError):
            text = None
    return [target], text


def export_block(
    client,
    block_id,
    format="markdown",
    recursive=False,
    output_dir=None,
    database_views="current",
    page_content="everything",
    create_folders=True,
    pdf_format="Letter",
    export_comments=False,
    timezone=None,
    timeout=120.0,
):
    """
    Run a full export: enqueue the task, poll until done, download the
    zip, unpack it, and write the files under `output_dir`.

    Returns a dict:
    - {"files": [absolute paths], "output_dir": output_dir}
    - plus "text" when the zip contained exactly one file (markdown
      single page) — the decoded text for direct consumption.
    """
    block_id = extract_id(block_id)
    space_id = client.current_space.id if client.current_space else None
    if not space_id:
        raise ExportError("Export requires a Current Space")

    options = build_export_options(
        format=format,
        recursive=recursive,
        database_views=database_views,
        page_content=page_content,
        create_folders=create_folders,
        pdf_format=pdf_format,
        export_comments=export_comments,
        timezone=timezone,
    )
    payload = build_export_task(block_id, space_id, options, recursive, export_comments)

    task_id = client.post("enqueueTask", payload).json()["taskId"]
    status = poll_export_task(client, task_id, timeout=timeout)

    export_url = status.get("exportURL")
    if not export_url:
        raise ExportError("Export task finished without an exportURL")

    zip_response = client.session.get(export_url, timeout=120)
    zip_response.raise_for_status()

    output_dir = output_dir or os.getcwd()
    os.makedirs(output_dir, exist_ok=True)
    body = zip_response.content
    if not zipfile.is_zipfile(io.BytesIO(body)):
        # single-file export: Notion serves the file itself (e.g. one page
        # as PDF) instead of a zip — write it as-is (issue #42)
        written, text = _write_single_file_export(body, output_dir, client, block_id, format)
    else:
        # v2: stream entry-by-entry to disk (RAM stays flat even for huge
        # zips); UNPY_LEGACY=1 keeps the v1 in-memory unpack
        from .config import legacy_mode

        text = None
        if legacy_mode():
            files, single = unpack_export_zip(body)
            written = write_export_files(files, output_dir)
            if single is not None:
                try:
                    text = single.decode("utf-8")
                except UnicodeDecodeError:
                    pass
        else:
            written, _ = stream_export_zip_to_files(body, output_dir)
            if len(written) == 1:
                try:
                    with open(written[0], "rb") as f:
                        text = f.read().decode("utf-8")
                except (UnicodeDecodeError, OSError):
                    text = None

    result = {"files": written, "output_dir": output_dir}
    if text is not None:
        result["text"] = text
    return result