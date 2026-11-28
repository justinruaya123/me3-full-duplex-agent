"""Bounded local page extraction and rendering for visual file citations."""

import base64
import io
import math
import os
import subprocess
from contextlib import closing, contextmanager
from pathlib import Path

IMAGE_SUFFIXES = {".png", ".jpeg", ".jpg"}
VISUAL_SUFFIXES = IMAGE_SUFFIXES | {".pdf"}
MAX_PAGES = 1024
MAX_TEXT = 24_000
MAX_PIXELS = 24_000_000
EDGE = 1600


@contextmanager
def document(data):
    try:
        import pypdfium2 as pdf
    except ImportError as exc:
        raise RuntimeError("PDF support requires the ME3 context extra") from exc
    try:
        with closing(pdf.PdfDocument(data)) as doc:
            if not 0 < len(doc) <= MAX_PAGES:
                raise ValueError("PDF exceeds the supported page count")
            yield doc
    except pdf.PdfiumError as exc:
        raise ValueError("Unreadable or protected PDF") from exc


def page_text(page):
    with closing(page.get_textpage()) as text:
        if text.count_chars() > MAX_TEXT:
            raise ValueError("PDF page exceeds the text limit")
        return (
            text.get_text_bounded().replace("\r\n", "\n").replace("\r", "\n").strip()
            or "[Image-only page]"
        )


def page_image(data):
    try:
        from PIL import Image, ImageOps
    except ImportError as exc:
        raise RuntimeError("Image support requires the ME3 context extra") from exc
    try:
        with Image.open(io.BytesIO(data), formats=("JPEG", "PNG")) as original:
            if original.width * original.height > MAX_PIXELS:
                raise ValueError("Image exceeds the pixel limit")
            image = ImageOps.exif_transpose(original).convert("RGBA")
            image.thumbnail((EDGE, EDGE))
            white = Image.new("RGB", image.size, "white")
            white.paste(image, mask=image.getchannel("A"))
            return white
    except (Image.DecompressionBombError, OSError) as exc:
        raise ValueError("Unreadable or oversized image") from exc


def pages(name, data, number=None):
    if Path(name).suffix.lower() in IMAGE_SUFFIXES:
        if number not in (None, 1):
            raise ValueError("Invalid image page")
        page_image(data)
        yield 1, "[Image]"
        return
    with document(data) as doc:
        if number is not None and not 1 <= number <= len(doc):
            raise ValueError("Invalid PDF page")
        for n in range(1, len(doc) + 1) if number is None else (number,):
            with closing(doc[n - 1]) as page:
                yield n, page_text(page)


def checked_box(box):
    if (
        not isinstance(box, (list, tuple))
        or len(box) != 4
        or not all(type(v) is int and 0 <= v <= 1000 for v in box)
        or box[0] >= box[2]
        or box[1] >= box[3]
    ):
        raise ValueError("Invalid visual citation box")
    return box


def pdf_image(data, number):
    with document(data) as doc, closing(doc[number - 1]) as page:
        w, h = page.get_size()
        if not all(math.isfinite(v) and v > 0 for v in (w, h)):
            raise ValueError("Invalid PDF page dimensions")
        with closing(page.render(scale=EDGE / max(w, h))) as bitmap:
            return bitmap.to_pil().convert("RGB")


def render(name, data, number, box=None, *, mark=False):
    if Path(name).suffix.lower() in IMAGE_SUFFIXES:
        image = page_image(data)
    else:
        image = pdf_image(data, number)
    if box is not None:
        left, top, right, bottom = checked_box(box)
        rect = (
            left * image.width // 1000,
            top * image.height // 1000,
            math.ceil(right * image.width / 1000),
            math.ceil(bottom * image.height / 1000),
        )
        if mark:
            from PIL import ImageDraw

            ImageDraw.Draw(image).rectangle(
                (rect[0], rect[1], rect[2] - 1, rect[3] - 1), outline="#006dba", width=3
            )
        else:
            image = image.crop(rect)
    stream = io.BytesIO()
    if box is not None:
        image.save(stream, format="PNG")
    else:
        image.save(stream, format="JPEG", quality=84)
        if stream.tell() > 700_000:
            raise ValueError("Rendered page exceeds the inference image budget")
    return stream.getvalue()


def attachment(jpeg):
    return {
        "type": "image",
        "mimeType": "image/jpeg",
        "data": base64.b64encode(jpeg).decode("ascii"),
    }


def ocr_terms(name, data, number, native_text):
    """Recognize search terms. The original page supplies all visual evidence."""
    jpeg = io.BytesIO()
    with pdf_image(data, number) as image:
        image.save(jpeg, format="JPEG", quality=84)
    try:
        run = subprocess.run(
            ["tesseract", "stdin", "stdout", "-l", "eng", "--psm", "11"],
            input=jpeg.getvalue(),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=True,
            timeout=30,
            env={**os.environ, "OMP_THREAD_LIMIT": "1"},
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            "Install Tesseract with English data or index with --no-ocr"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"PDF OCR timed out on {name}, page {number}") from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            f"Tesseract failed on {name}, page {number}. Check English OCR data."
        ) from exc
    text = run.stdout.decode("utf-8")
    if len(text) > MAX_TEXT:
        raise ValueError("PDF OCR page exceeds the text limit")
    native = native_text.casefold()
    return "\n".join(
        line
        for line in text.splitlines()
        if line.strip() and line.casefold() not in native
    )
