"""Unit tests for unpy.export — option mapping, task building, polling,
zip unpacking, and file writing (export feature)."""

import io
import time
import zipfile

import pytest

from unpy.export import (
    ExportError,
    build_export_options,
    build_export_task,
    export_block,
    poll_export_task,
    unpack_export_zip,
    write_export_files,
)


class TestBuildExportOptions:
    def test_defaults_match_ui(self):
        opts = build_export_options()
        assert opts["exportType"] == "markdown"
        assert opts["collectionViewExportType"] == "currentView"
        assert opts["includeContents"] == "everything"
        assert opts["preferredViewMap"] == {}
        assert "flattenExportFiletree" not in opts
        assert "pdfFormat" not in opts
        assert opts["timeZone"]  # local tz resolved

    def test_pdf_carries_pdf_format(self):
        opts = build_export_options(format="pdf")
        assert opts["pdfFormat"] == "Letter"

    def test_recursive_no_folders_sets_flatten(self):
        opts = build_export_options(recursive=True, create_folders=False)
        assert opts["flattenExportFiletree"] is True

    def test_recursive_with_folders_omits_flatten(self):
        opts = build_export_options(recursive=True, create_folders=True)
        assert "flattenExportFiletree" not in opts

    def test_non_recursive_folders_off_ignores_flatten(self):
        opts = build_export_options(recursive=False, create_folders=False)
        assert "flattenExportFiletree" not in opts

    def test_all_views(self):
        opts = build_export_options(database_views="all")
        assert opts["collectionViewExportType"] == "all"

    def test_no_files(self):
        opts = build_export_options(page_content="no_files")
        assert opts["includeContents"] == "no_files"

    def test_explicit_timezone(self):
        opts = build_export_options(timezone="Asia/Bangkok")
        assert opts["timeZone"] == "Asia/Bangkok"

    def test_invalid_format(self):
        with pytest.raises(ValueError):
            build_export_options(format="docx")

    def test_invalid_pdf_format(self):
        with pytest.raises(ValueError):
            build_export_options(format="pdf", pdf_format="A99")

    def test_invalid_database_views(self):
        with pytest.raises(ValueError):
            build_export_options(database_views="some")


class TestBuildExportTask:
    def test_matches_captured_shape(self):
        task = build_export_task(
            "blk", "spc", build_export_options(), False, False
        )
        assert task["task"]["eventName"] == "partitionedExportBlock"
        req = task["task"]["request"]
        assert req["block"] == {"id": "blk", "spaceId": "spc"}
        assert req["recursive"] is False
        assert req["shouldExportComments"] is False
        assert req["spaceId"] == "spc"
        assert req["eventName"] == "partitionedExportBlock"
        assert req["rootTaskId"]
        assert task["task"]["cellRouting"] == {"spaceIds": ["spc"]}


class TestPollExportTask:
    def _client_with_tasks(self, responses):
        calls = []

        class FakeClient:
            def post(self, endpoint, data):
                calls.append((endpoint, data))
                idx = min(len(calls) - 1, len(responses) - 1)
                resp = responses[idx]

                class R:
                    def json(self):
                        return resp

                return R()

        return FakeClient(), calls

    def test_success_returns_status(self):
        responses = [
            {"results": [{"state": "in_progress"}]},
            {
                "results": [
                    {
                        "state": "success",
                        "status": {"type": "complete", "exportURL": "https://x"},
                    }
                ]
            },
        ]
        client, calls = self._client_with_tasks(responses)
        status = poll_export_task(client, "t1", timeout=5)
        assert status == {"type": "complete", "exportURL": "https://x"}
        assert calls[0][0] == "getTasks"
        assert calls[0][1] == {"taskIds": ["t1"]}

    def test_timeout_raises(self, monkeypatch):
        monkeypatch.setattr(time, "sleep", lambda s: None)
        client, _ = self._client_with_tasks(
            [{"results": [{"state": "in_progress"}]}]
        )
        with pytest.raises(ExportError, match="did not finish"):
            poll_export_task(client, "t1", timeout=0.05)

    def test_failed_state_raises(self, monkeypatch):
        monkeypatch.setattr(time, "sleep", lambda s: None)
        client, _ = self._client_with_tasks(
            [{"results": [{"state": "failed"}]}]
        )
        with pytest.raises(ExportError, match="failed"):
            poll_export_task(client, "t1", timeout=1)


class TestUnpackExportZip:
    def test_single_file(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("Page 1 abc123.md", "# Hello")
        files, single = unpack_export_zip(buf.getvalue())
        assert list(files) == ["Page 1 abc123.md"]
        assert single == b"# Hello"

    def test_multi_file(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("Page 1 a.md", "# A")
            z.writestr("Page 1 a/Row 2 b.csv", "Name\nA")
        files, single = unpack_export_zip(buf.getvalue())
        assert len(files) == 2
        assert single is None


class TestWriteExportFiles:
    def test_nested_paths(self, tmp_path):
        files = {
            "Doc a.md": b"# doc",
            "Doc a/Row 2 b.csv": b"Name\nx",
        }
        written = write_export_files(files, str(tmp_path))
        assert len(written) == 2
        assert (tmp_path / "Doc a.md").read_bytes() == b"# doc"
        assert (tmp_path / "Doc a" / "Row 2 b.csv").read_bytes() == b"Name\nx"


class TestExportBlockFlow:
    def test_full_flow_single_md(self, tmp_path, monkeypatch):
        from uuid import uuid4

        zip_buf = io.BytesIO()
        with zipfile.ZipFile(zip_buf, "w") as z:
            z.writestr("Doc a.md", b"# Doc")

        class FakeResponse:
            status_code = 200

            def json(self):
                return {"taskId": "t1"}

        class FakeSession:
            def get(self, url, timeout=None):
                assert "file.notion.com" in url

                class R:
                    content = zip_buf.getvalue()

                    def raise_for_status(self):
                        pass

                return R()

        posts = []

        class FakeSpace:
            id = "spc"

        class FakeClient:
            session = FakeSession()
            current_space = FakeSpace()

            def post(self, endpoint, data):
                posts.append((endpoint, data))
                if endpoint == "enqueueTask":
                    return FakeResponse()
                if endpoint == "getTasks":
                    body = {
                        "results": [
                            {
                                "state": "success",
                                "status": {
                                    "type": "complete",
                                    "pagesExported": 1,
                                    "exportURL": "https://file.notion.com/f/t/x",
                                },
                            }
                        ]
                    }

                    class R:
                        def json(self):
                            return body

                    return R()

        monkeypatch.setattr(time, "sleep", lambda s: None)
        result = export_block(
            FakeClient(), str(uuid4()), output_dir=str(tmp_path), timeout=5
        )
        # enqueue payload shape
        endpoint, payload = posts[0]
        assert endpoint == "enqueueTask"
        task = payload["task"]
        block_id = task["request"]["block"]["id"]
        assert task["eventName"] == "partitionedExportBlock"
        assert task["request"]["block"]["spaceId"] == "spc"
        # files written
        assert len(result["files"]) == 1
        assert result["output_dir"] == str(tmp_path)
        assert (tmp_path / "Doc a.md").read_bytes() == b"# Doc"
        # single-file markdown text returned inline
        assert result["text"] == "# Doc"

    def test_requires_space(self):
        from uuid import uuid4

        class FakeClient:
            current_space = None

        with pytest.raises(ExportError, match="Current Space"):
            export_block(FakeClient(), str(uuid4()))