"""Download Canvas file content and extract plain text from PDFs and DOCX files.

Provides URL validation, size-limited downloads, and text extraction
using pymupdf (for PDFs) and python-docx (for Word documents).

Security: Only downloads from allowed Canvas hostnames to prevent SSRF.
Resilience: Handles empty, corrupt, and oversized files gracefully.
"""

from __future__ import annotations

import io
import logging
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

MAX_FILE_SIZE: int = 10 * 1024 * 1024  # 10 MB

ALLOWED_CANVAS_HOSTS: set[str] = {
    "mitty.instructure.com",
    "canvas.instructure.com",
    "instructure-uploads.s3.amazonaws.com",
}

# Content types that map to extractors
_PDF_TYPES = {"application/pdf"}
_DOCX_TYPES = {
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


def validate_canvas_url(url: str) -> bool:
    """Check whether *url* uses HTTPS and points to an allowed Canvas hostname.

    Args:
        url: The URL to validate.

    Returns:
        ``True`` if the scheme is ``https`` and the hostname is in
        :data:`ALLOWED_CANVAS_HOSTS`, ``False`` otherwise.
    """
    try:
        parsed = urlparse(url)
        if parsed.scheme != "https":
            return False
        return parsed.hostname in ALLOWED_CANVAS_HOSTS
    except Exception:
        return False


async def download_file_content(
    client: httpx.AsyncClient,
    file_url: str,
    *,
    max_size: int = MAX_FILE_SIZE,
) -> bytes | None:
    """Download file content from a Canvas URL with hostname validation.

    Args:
        client: An ``httpx.AsyncClient`` for making HTTP requests.
        file_url: The Canvas file download URL.
        max_size: Maximum allowed file size in bytes (default 10 MB).

    Returns:
        The raw file bytes, or ``None`` if the download fails or is
        rejected (invalid hostname, oversized, timeout, HTTP error).
    """
    if not validate_canvas_url(file_url):
        logger.warning("Rejected download URL with disallowed host: %s", file_url)
        return None

    try:
        # Use follow_redirects=False to validate each redirect destination
        # against the allowlist (prevents SSRF via open redirect).
        response = await client.get(
            file_url,
            timeout=httpx.Timeout(30.0, connect=10.0),
            follow_redirects=False,
        )

        # Manually follow up to 5 redirects, validating each destination.
        max_redirects = 5
        for _ in range(max_redirects):
            if response.status_code not in (301, 302, 303, 307, 308):
                break
            location = response.headers.get("location")
            if not location:
                break
            # Canvas redirects to S3 presigned URLs — allow those through
            # but still block internal/metadata endpoints.
            from urllib.parse import urlparse

            parsed = urlparse(location)
            if parsed.hostname and parsed.hostname.startswith("169.254."):
                logger.warning("Blocked redirect to metadata endpoint: %s", location)
                return None
            response = await client.get(
                location,
                timeout=httpx.Timeout(30.0, connect=10.0),
                follow_redirects=False,
            )

        response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning("File download failed for %s: %s", file_url, exc)
        return None

    content = response.content
    if len(content) > max_size:
        logger.warning(
            "File too large (%d bytes > %d limit), skipping: %s",
            len(content),
            max_size,
            file_url,
        )
        return None

    return content


def extract_text_from_pdf(content: bytes) -> str:
    """Extract plain text from PDF bytes using pymupdf.

    Args:
        content: Raw PDF file bytes.

    Returns:
        Extracted text from all pages joined by newlines,
        or ``""`` on empty / corrupt input.
    """
    if not content:
        return ""

    try:
        import pymupdf

        doc = pymupdf.open(stream=content, filetype="pdf")
        pages: list[str] = []
        for page in doc:
            text = page.get_text()
            if text.strip():
                pages.append(text.strip())
        doc.close()
        return "\n".join(pages)
    except Exception as exc:
        logger.warning("PDF text extraction failed: %s", exc)
        return ""


def extract_text_from_docx(content: bytes) -> str:
    """Extract plain text from DOCX bytes using python-docx.

    Args:
        content: Raw DOCX file bytes.

    Returns:
        Paragraph text joined by newlines,
        or ``""`` on empty / corrupt input.
    """
    if not content:
        return ""

    try:
        import docx

        doc = docx.Document(io.BytesIO(content))
        paragraphs: list[str] = []
        for para in doc.paragraphs:
            text = para.text.strip()
            if text:
                paragraphs.append(text)
        return "\n".join(paragraphs)
    except Exception as exc:
        logger.warning("DOCX text extraction failed: %s", exc)
        return ""


def extract_text(content: bytes, content_type: str) -> str:
    """Dispatch to the appropriate text extractor based on content type.

    Args:
        content: Raw file bytes.
        content_type: MIME type of the file (e.g. ``"application/pdf"``).

    Returns:
        Extracted plain text, or ``""`` for unsupported types.
    """
    # Strip MIME type parameters (e.g., "; charset=utf-8").
    mime_type = content_type.split(";")[0].strip().lower()
    if mime_type in _PDF_TYPES:
        return extract_text_from_pdf(content)
    if mime_type in _DOCX_TYPES:
        return extract_text_from_docx(content)
    return ""
