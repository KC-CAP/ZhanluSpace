"""Acquire untrusted inputs and normalize them before knowledge compilation."""

from __future__ import annotations

import hashlib
import shutil
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import httpx
from bs4 import BeautifulSoup, Tag
from pydantic import BaseModel, ConfigDict, HttpUrl


MAX_SOURCE_BYTES = 10 * 1024 * 1024
REQUEST_TIMEOUT_SECONDS = 20.0
MAX_REDIRECTS = 5
SUPPORTED_FILE_SUFFIXES = {".md": "markdown-v1", ".txt": "text-v1"}


class SourceAcquisitionError(Exception):
    """A stable, user-presentable failure while acquiring a source."""

    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        self.code = code
        self.retryable = retryable
        super().__init__(f"{code}: {message}")


class NormalizedSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str
    kind: Literal["file", "web"]
    title: str
    normalized_text: str
    content_sha256: str
    original_name: str | None
    source_url: HttpUrl | None
    final_url: HttpUrl | None
    canonical_url: HttpUrl | None
    retrieved_at: datetime
    extractor: str
    extraction_quality: Literal["high", "medium", "low"]


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _normalize_text(value: str) -> str:
    normalized = value.removeprefix("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    return normalized.rstrip() + "\n"


def _identity(normalized_text: str) -> tuple[str, str]:
    digest = hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()
    return digest, f"source:sha256:{digest}"


def acquire_file(
    path: Path | str,
    *,
    now: Callable[[], datetime] = _utc_now,
) -> NormalizedSource:
    candidate = Path(path)
    if candidate.is_symlink():
        raise SourceAcquisitionError("SYMLINK_NOT_ALLOWED", "file input cannot be a symlink")
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as error:
        raise SourceAcquisitionError("SOURCE_NOT_FOUND", str(error)) from error
    if not resolved.is_file():
        raise SourceAcquisitionError("SOURCE_NOT_FILE", "file input must be a regular file")

    suffix = resolved.suffix.lower()
    extractor = SUPPORTED_FILE_SUFFIXES.get(suffix)
    if extractor is None:
        raise SourceAcquisitionError(
            "UNSUPPORTED_FILE_TYPE", f"unsupported file extension: {suffix or '<none>'}"
        )
    if resolved.stat().st_size > MAX_SOURCE_BYTES:
        raise SourceAcquisitionError(
            "SOURCE_TOO_LARGE", f"file exceeds {MAX_SOURCE_BYTES} bytes"
        )
    try:
        text = resolved.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as error:
        raise SourceAcquisitionError(
            "INVALID_TEXT_ENCODING", "file must be UTF-8 text"
        ) from error

    normalized_text = _normalize_text(text)
    digest, source_id = _identity(normalized_text)
    return NormalizedSource(
        source_id=source_id,
        kind="file",
        title=resolved.stem,
        normalized_text=normalized_text,
        content_sha256=digest,
        original_name=resolved.name,
        source_url=None,
        final_url=None,
        canonical_url=None,
        retrieved_at=now(),
        extractor=extractor,
        extraction_quality="high",
    )


def acquire_url(
    url: str,
    *,
    client: httpx.Client | None = None,
    now: Callable[[], datetime] = _utc_now,
) -> NormalizedSource:
    parsed_url = httpx.URL(url)
    if parsed_url.scheme not in {"http", "https"}:
        raise SourceAcquisitionError(
            "UNSUPPORTED_URL_SCHEME", "only http and https URLs are supported"
        )

    owned_client = client is None
    active_client = client or httpx.Client(
        follow_redirects=True,
        max_redirects=MAX_REDIRECTS,
        timeout=REQUEST_TIMEOUT_SECONDS,
        headers={"User-Agent": "ZhanluKnowledge/0.1"},
    )
    try:
        with active_client.stream(
            "GET",
            parsed_url,
            follow_redirects=True,
            timeout=REQUEST_TIMEOUT_SECONDS,
        ) as response:
            response.raise_for_status()
            declared_length = response.headers.get("content-length")
            if declared_length is not None and int(declared_length) > MAX_SOURCE_BYTES:
                raise SourceAcquisitionError(
                    "SOURCE_TOO_LARGE", f"response exceeds {MAX_SOURCE_BYTES} bytes"
                )
            content = bytearray()
            for chunk in response.iter_bytes():
                content.extend(chunk)
                if len(content) > MAX_SOURCE_BYTES:
                    raise SourceAcquisitionError(
                        "SOURCE_TOO_LARGE", f"response exceeds {MAX_SOURCE_BYTES} bytes"
                    )
            media_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
            if media_type not in {"text/html", "application/xhtml+xml", "text/plain"}:
                raise SourceAcquisitionError(
                    "UNSUPPORTED_WEB_CONTENT", f"unsupported content type: {media_type}"
                )
            encoding = response.encoding or "utf-8"
            try:
                decoded = bytes(content).decode(encoding)
            except (LookupError, UnicodeDecodeError) as error:
                raise SourceAcquisitionError(
                    "INVALID_TEXT_ENCODING", "web response could not be decoded"
                ) from error
            final_url = response.url
    except httpx.TooManyRedirects as error:
        raise SourceAcquisitionError(
            "TOO_MANY_REDIRECTS", "web source exceeded five redirects"
        ) from error
    except httpx.TimeoutException as error:
        raise SourceAcquisitionError(
            "SOURCE_TIMEOUT", "web source timed out", retryable=True
        ) from error
    except httpx.HTTPStatusError as error:
        retryable = error.response.status_code >= 500
        raise SourceAcquisitionError(
            "SOURCE_HTTP_ERROR",
            f"web source returned HTTP {error.response.status_code}",
            retryable=retryable,
        ) from error
    except httpx.HTTPError as error:
        raise SourceAcquisitionError(
            "SOURCE_NETWORK_ERROR", "web source request failed", retryable=True
        ) from error
    finally:
        if owned_client:
            active_client.close()

    if media_type == "text/plain":
        title = final_url.path.rsplit("/", 1)[-1] or final_url.host or "Web source"
        normalized_text = _normalize_text(decoded)
        canonical_url: str | None = None
        extractor = "web-text-v1"
    else:
        title, normalized_text, canonical_url = _extract_html(decoded, final_url)
        extractor = "html-readable-v1"

    digest, source_id = _identity(normalized_text)
    return NormalizedSource(
        source_id=source_id,
        kind="web",
        title=title,
        normalized_text=normalized_text,
        content_sha256=digest,
        original_name=None,
        source_url=str(parsed_url),
        final_url=str(final_url),
        canonical_url=canonical_url,
        retrieved_at=now(),
        extractor=extractor,
        extraction_quality="high" if len(normalized_text.strip()) >= 20 else "medium",
    )


def _extract_html(html: str, final_url: httpx.URL) -> tuple[str, str, str | None]:
    soup = BeautifulSoup(html, "html.parser")
    canonical_tag = soup.find("link", rel=lambda value: value and "canonical" in value)
    canonical_value = canonical_tag.get("href") if isinstance(canonical_tag, Tag) else None
    canonical_url = str(final_url.join(canonical_value)) if canonical_value else None
    title = soup.title.get_text(" ", strip=True) if soup.title else ""

    for element in soup.find_all(
        ["script", "style", "nav", "footer", "form", "noscript", "svg", "canvas"]
    ):
        element.decompose()

    root = soup.find("article") or soup.find("main") or soup.body or soup
    if not title:
        first_heading = root.find(["h1", "h2"])
        title = first_heading.get_text(" ", strip=True) if first_heading else "Web source"

    blocks: list[str] = []
    for element in root.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "table"]):
        if element.name == "table":
            rows = [
                [cell.get_text(" ", strip=True) for cell in row.find_all(["th", "td"])]
                for row in element.find_all("tr")
            ]
            rows = [row for row in rows if row]
            if rows:
                blocks.append("| " + " | ".join(rows[0]) + " |")
                blocks.append("| " + " | ".join("---" for _ in rows[0]) + " |")
                blocks.extend("| " + " | ".join(row) + " |" for row in rows[1:])
            continue
        text = element.get_text(" ", strip=True)
        if not text:
            continue
        if element.name and element.name.startswith("h"):
            blocks.append(f"{'#' * int(element.name[1])} {text}")
        elif element.name == "li":
            blocks.append(f"- {text}")
        else:
            blocks.append(text)

    if not blocks:
        blocks.append(root.get_text("\n", strip=True))
    return title, _normalize_text("\n\n".join(blocks)), canonical_url


def write_staged_source(
    job_dir: Path,
    source: NormalizedSource,
    *,
    original_path: Path | None = None,
) -> None:
    job_dir.mkdir(parents=True, exist_ok=False)
    input_dir = job_dir / "input"
    input_dir.mkdir()
    (input_dir / "normalized.md").write_text(
        source.normalized_text, encoding="utf-8", newline="\n"
    )
    (input_dir / "metadata.json").write_text(
        source.model_dump_json(exclude={"normalized_text"}, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    if original_path is not None:
        resolved = original_path.resolve(strict=True)
        destination = input_dir / f"original{resolved.suffix.lower()}"
        shutil.copyfile(resolved, destination)
