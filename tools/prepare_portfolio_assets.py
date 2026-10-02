"""Prepare local portfolio assets without modifying the user's source files."""

from __future__ import annotations

import io
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageChops
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas


REPO = Path(__file__).resolve().parents[1]
PDFTOPPM = Path(
    r"C:\Users\caden\.cache\codex-runtimes\codex-primary-runtime\dependencies"
    r"\native\poppler\Library\bin\pdftoppm.exe"
)
MUSESCORE = Path(r"C:\Program Files\MuseScore 4\bin\MuseScore4.exe")

HEADSHOT_SOURCE = Path(r"C:\Users\caden\Downloads\image0.jpg")
TRICKY_SOURCE = Path(r"C:\Users\caden\OneDrive\Desktop\Music\MuseScore\Tricky.mscz")
CAD_SOURCE = Path(
    r"C:\Users\caden\OneDrive\Desktop\Education\Central Piedmont\Fall 2025"
    r"\CEG 151 - CAD Engineering Technology\CEG 151 - Homework 2-4"
    r"\CEG 151- Homework 4\CEG151-XXX_SITE SHEETwork-LAYOUT - HW4 SUBMITAL.pdf"
)

MUSIC_FILES = {
    Path(r"C:\Users\caden\OneDrive\Desktop\Music\PDFs\semente.pdf"):
        REPO / "assets" / "scores" / "semente.pdf",
    Path(r"C:\Users\caden\OneDrive\Desktop\Music\PDFs\kiss from a rose (2).pdf"):
        REPO / "assets" / "scores" / "kiss-from-a-rose.pdf",
    Path(r"C:\Users\caden\OneDrive\Documents\MuseScore4\Scores\semente_6-18.mp3"):
        REPO / "assets" / "audio" / "semente.mp3",
    Path(r"C:\Users\caden\OneDrive\Documents\MuseScore4\Scores\kiss from a rose 2-25.mp3"):
        REPO / "assets" / "audio" / "kiss-from-a-rose.mp3",
}


def prepare_topo_card_image() -> None:
    source = REPO / "assets" / "images" / "nc-topo-qgis-visualization.png"
    destination = REPO / "assets" / "images" / "nc-topo-project-card.webp"
    with Image.open(source) as original:
        image = original.convert("RGBA")
        white = Image.new("RGB", image.size, "white")
        difference = ImageChops.difference(image.convert("RGB"), white).convert("L")
        alpha = difference.point(
            lambda value: 0
            if value < 5
            else 255
            if value > 18
            else round((value - 5) / 13 * 255)
        )
        image.putalpha(alpha)
        bounds = alpha.getbbox()
        if bounds:
            left, top, right, bottom = bounds
            margin = 24
            bounds = (
                max(0, left - margin),
                max(0, top - margin),
                min(image.width, right + margin),
                min(image.height, bottom + margin),
            )
            image = image.crop(bounds)
        image.thumbnail((2400, 900), Image.Resampling.LANCZOS)
        image.save(destination, "WEBP", quality=90, method=6)


def prepare_headshot() -> None:
    destination = REPO / "assets" / "images" / "caden-trahan-portrait.jpg"
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(HEADSHOT_SOURCE, destination)


def prepare_cad_pdf() -> None:
    destination = REPO / "assets" / "documents" / "civil-engineering-cad-final.pdf"
    destination.parent.mkdir(parents=True, exist_ok=True)
    reader = PdfReader(str(CAD_SOURCE), strict=False)
    writer = PdfWriter()

    for source_page in reader.pages:
        source_page.transfer_rotation_to_content()
        width = float(source_page.mediabox.width)
        height = float(source_page.mediabox.height)

        overlay_bytes = io.BytesIO()
        overlay = canvas.Canvas(overlay_bytes, pagesize=(width, height))
        overlay.setFillColorRGB(1, 1, 1)
        # The source plot carries a tiny local file-path stamp above the sheet
        # border. Cover that plotter artifact while leaving the border intact.
        overlay.rect(0, height - 24, width, 24, stroke=0, fill=1)
        overlay.save()
        overlay_bytes.seek(0)
        source_page.merge_page(PdfReader(overlay_bytes).pages[0])
        # Crop the plotter's date stamp from the printable margin. The sheet
        # border begins below this narrow strip and remains untouched.
        source_page.mediabox.top = height - 18
        source_page.cropbox.top = height - 18
        writer.add_page(source_page)

    writer.add_metadata(
        {
            "/Title": "Civil Engineering CAD Final",
            "/Author": "Caden Trahan",
            "/Subject": "Academic Civil 3D site design sheet",
            "/Creator": "Caden Trahan portfolio",
        }
    )
    with destination.open("wb") as stream:
        writer.write(stream)

    preview = REPO / "assets" / "images" / "civil-engineering-cad-final.webp"
    preview.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="portfolio-cad-preview-") as temp_dir:
        prefix = Path(temp_dir) / "cad-sheet"
        subprocess.run(
            [
                str(PDFTOPPM),
                "-singlefile",
                "-png",
                "-r",
                "96",
                str(destination),
                str(prefix),
            ],
            check=True,
            capture_output=True,
        )
        with Image.open(prefix.with_suffix(".png")) as image:
            image = image.convert("RGB")
            image.thumbnail((2200, 2200), Image.Resampling.LANCZOS)
            image.save(preview, "WEBP", quality=84, method=6)


def copy_music() -> None:
    for source, destination in MUSIC_FILES.items():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def export_tricky_score() -> None:
    destination = REPO / "assets" / "scores" / "pretty-tricky.pdf"
    destination.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [str(MUSESCORE), "-o", str(destination), str(TRICKY_SOURCE)],
        check=True,
        timeout=120,
    )
    if not destination.exists():
        raise RuntimeError("MuseScore completed without exporting Pretty Tricky.")


def main() -> None:
    prepare_headshot()
    prepare_topo_card_image()
    prepare_cad_pdf()
    copy_music()
    export_tricky_score()
    print("Prepared portrait, sanitized CAD PDF, and selected score/audio assets.")


if __name__ == "__main__":
    main()
