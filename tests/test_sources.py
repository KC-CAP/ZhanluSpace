from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from zhanlu_worker.sources import (
    MAX_SOURCE_BYTES,
    SourceAcquisitionError,
    acquire_file,
    acquire_url,
    write_staged_source,
)


FIXTURES = Path(__file__).parent / "fixtures" / "sources"
NOW = datetime(2026, 8, 3, 12, 0, tzinfo=UTC)


def test_markdown_file_preserves_headings_and_body() -> None:
    source = acquire_file(FIXTURES / "note.md", now=lambda: NOW)

    assert source.title == "note"
    assert source.normalized_text == "# 混合检索\n\n混合检索结合关键词检索与语义检索。\n"
    assert source.original_name == "note.md"
    assert source.extractor == "markdown-v1"
    assert source.extraction_quality == "high"


def test_txt_removes_utf8_bom_and_normalizes_line_endings(tmp_path: Path) -> None:
    path = tmp_path / "windows.txt"
    path.write_bytes(b"\xef\xbb\xbfalpha\r\nbeta\r\n")

    source = acquire_file(path, now=lambda: NOW)

    assert source.normalized_text == "alpha\nbeta\n"
    assert source.extractor == "text-v1"


def test_file_rejects_unsupported_extension(tmp_path: Path) -> None:
    path = tmp_path / "slides.pptx"
    path.write_bytes(b"not-a-presentation")

    with pytest.raises(SourceAcquisitionError, match="UNSUPPORTED_FILE_TYPE"):
        acquire_file(path, now=lambda: NOW)


def test_file_rejects_content_larger_than_limit(tmp_path: Path) -> None:
    path = tmp_path / "large.txt"
    path.write_bytes(b"x" * (MAX_SOURCE_BYTES + 1))

    with pytest.raises(SourceAcquisitionError, match="SOURCE_TOO_LARGE"):
        acquire_file(path, now=lambda: NOW)


def test_identical_normalized_content_has_same_source_id(tmp_path: Path) -> None:
    first = tmp_path / "first.md"
    second = tmp_path / "second.txt"
    first.write_bytes(b"same\r\ncontent\r\n")
    second.write_bytes(b"\xef\xbb\xbfsame\ncontent")

    first_source = acquire_file(first, now=lambda: NOW)
    second_source = acquire_file(second, now=lambda: NOW)

    assert first_source.content_sha256 == second_source.content_sha256
    assert first_source.source_id == second_source.source_id
    assert first_source.source_id.startswith("source:sha256:")


def test_url_rejects_non_http_scheme_without_making_request() -> None:
    def unexpected_request(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"unexpected request to {request.url}")

    with httpx.Client(transport=httpx.MockTransport(unexpected_request)) as client:
        with pytest.raises(SourceAcquisitionError, match="UNSUPPORTED_URL_SCHEME"):
            acquire_url("file:///C:/private.txt", client=client, now=lambda: NOW)


def test_url_rejects_more_than_five_redirects() -> None:
    def redirect(request: httpx.Request) -> httpx.Response:
        index = int(request.url.path.removeprefix("/redirect/") or "0")
        return httpx.Response(302, headers={"location": f"/redirect/{index + 1}"})

    with httpx.Client(
        transport=httpx.MockTransport(redirect), max_redirects=5
    ) as client:
        with pytest.raises(SourceAcquisitionError, match="TOO_MANY_REDIRECTS"):
            acquire_url("https://example.com/redirect/0", client=client, now=lambda: NOW)


def test_url_rejects_response_larger_than_limit() -> None:
    def oversized(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            content=b"x" * (MAX_SOURCE_BYTES + 1),
        )

    with httpx.Client(transport=httpx.MockTransport(oversized)) as client:
        with pytest.raises(SourceAcquisitionError, match="SOURCE_TOO_LARGE"):
            acquire_url("https://example.com/large", client=client, now=lambda: NOW)


def test_url_surfaces_timeout_as_retryable_error() -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    with httpx.Client(transport=httpx.MockTransport(timeout)) as client:
        with pytest.raises(SourceAcquisitionError, match="SOURCE_TIMEOUT") as caught:
            acquire_url("https://example.com/slow", client=client, now=lambda: NOW)

    assert caught.value.retryable is True


def test_html_extracts_readable_structure_and_discards_active_chrome() -> None:
    html = (FIXTURES / "article.html").read_bytes()

    def article(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            content=html,
        )

    with httpx.Client(transport=httpx.MockTransport(article)) as client:
        source = acquire_url(
            "https://example.com/original", client=client, now=lambda: NOW
        )

    assert source.title == "Hermes 知识工作流"
    assert str(source.source_url) == "https://example.com/original"
    assert str(source.final_url) == "https://example.com/original"
    assert str(source.canonical_url) == "https://example.com/canonical-article"
    assert "# Hermes 知识工作流" in source.normalized_text
    assert "## 步骤" in source.normalized_text
    assert "- 获取素材" in source.normalized_text
    assert "| 阶段 | 结果 |" in source.normalized_text
    assert "window.evil" not in source.normalized_text
    assert "站点导航" not in source.normalized_text
    assert "不能保留" not in source.normalized_text
    assert "版权信息" not in source.normalized_text


def test_staging_is_exclusive_and_keeps_metadata_separate(tmp_path: Path) -> None:
    source_path = FIXTURES / "note.md"
    source = acquire_file(source_path, now=lambda: NOW)
    job_dir = tmp_path / "job"

    write_staged_source(job_dir, source, original_path=source_path)

    assert (job_dir / "input" / "normalized.md").read_text(encoding="utf-8") == (
        source.normalized_text
    )
    metadata = json.loads(
        (job_dir / "input" / "metadata.json").read_text(encoding="utf-8")
    )
    assert metadata["source_id"] == source.source_id
    assert "normalized_text" not in metadata
    assert (job_dir / "input" / "original.md").read_bytes() == source_path.read_bytes()

    with pytest.raises(FileExistsError):
        write_staged_source(job_dir, source, original_path=source_path)
