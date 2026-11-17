#!/usr/bin/env python3
"""Populate the 28 benchmark piece presentations through the local Wagtail CMS.

The script is idempotent: it updates slides with the expected titles and only
creates missing slides. Credentials are read from MIYP_CMS_USER and
MIYP_CMS_PASSWORD and are never stored in the output manifest.
"""

import hashlib
import json
import os
from pathlib import Path
import re
import sys
import textwrap
from urllib.parse import quote_plus

from PIL import Image, ImageDraw, ImageFont
from playwright.sync_api import sync_playwright


BASE_URL = os.environ.get("MIYP_CMS_BASE_URL", "https://127.0.0.1:8000").rstrip("/")
USERNAME = os.environ.get("MIYP_CMS_USER", "")
PASSWORD = os.environ.get("MIYP_CMS_PASSWORD", "")
VERIFY_ONLY = os.environ.get("MIYP_VERIFY_ONLY", "0") == "1"
ROOT = Path(__file__).resolve().parent
PRESENTATIONS_FILE = ROOT / "presentations.txt"
GENERATED_MEDIA = ROOT / "generated_benchmark_media"
MANIFEST = ROOT / "PRESENTATION_CONTENT_MANIFEST.json"

# Page IDs belong to the controlled database snapshot bundled with TO_RUN.
USER_DEVICE_PAGE_IDS = [
    149, 153, 157, 161, 165, 169, 173, 177, 181, 185, 189, 193, 197, 201,
    205, 209, 213, 217, 221, 225, 229, 233, 237, 241, 245, 249, 253, 257,
]

ANCIENT_IMAGE_IDS = list(range(40, 54))
SLIDE_TITLES = [
    "01 · Object overview",
    "02 · Function and use",
    "03 · Materials and construction",
    "04 · Historical setting",
    "05 · Significance and legacy",
    "06 · Sources and questions",
]

# Four visual slides, one text-led slide, and one document-led slide.  Every
# visual receives a different Wagtail image record; no presentation reuses an
# image between authored slides.
SLIDE_LAYOUTS = [
    {"kind": "image", "stage": "overview"},
    {"kind": "text"},
    {"kind": "image", "stage": "materials"},
    {"kind": "document"},
    {"kind": "image", "stage": "timeline"},
    {"kind": "question", "stage": "comparison"},
]

STAGE_LABELS = {
    "overview": "Object view",
    "materials": "Material detail",
    "timeline": "Historical timeline",
    "comparison": "Visitor comparison",
}


def clean(value):
    return " ".join(str(value or "").split())


def value(attributes, *names, default="Not recorded in the prototype catalogue"):
    for name in names:
        candidate = clean(attributes.get(name, ""))
        if candidate:
            return candidate
    return default


def draftail_body(heading, paragraphs):
    blocks = []
    texts = [heading, *paragraphs]
    for index, text in enumerate(texts):
        digest = hashlib.sha1(f"{heading}:{index}".encode()).hexdigest()[:5]
        blocks.append({
            "key": digest,
            "text": clean(text),
            "type": "header-two" if index == 0 else "unstyled",
            "depth": 0,
            "inlineStyleRanges": [],
            "entityRanges": [],
            "data": {},
        })
    return json.dumps({"blocks": blocks, "entityMap": {}}, ensure_ascii=False)


def draftail_paragraphs(paragraphs):
    blocks = []
    for index, paragraph in enumerate(paragraphs):
        digest = hashlib.sha1(f"paragraph:{index}:{paragraph}".encode()).hexdigest()[:5]
        blocks.append({
            "key": digest,
            "text": clean(paragraph),
            "type": "unstyled",
            "depth": 0,
            "inlineStyleRanges": [],
            "entityRanges": [],
            "data": {},
        })
    return json.dumps({"blocks": blocks, "entityMap": {}}, ensure_ascii=False)


def presentation_texts(title, attributes):
    ancient = "Civilisation" in attributes
    period = value(attributes, "Approximate Date", "Year / Period")
    origin = value(attributes, "Civilisation", "Manufacturer / Origin")
    kind = value(attributes, "Measurement Type", "Component Type")
    material = value(attributes, "Material")
    setting = value(attributes, "Region / Findspot", "Vehicle / Application")
    scale = value(attributes, "Unit / Scale", "Vehicle / Application")
    description = value(attributes, "Description")
    function = value(attributes, "Function", "Measurement Type")
    significance = value(
        attributes,
        "Technological Significance",
        default=(
            "It documents the effort to make measurement repeatable across craft, "
            "building, exchange and administration."
        ),
    )
    sources = value(attributes, "Information Source")
    image_source = value(attributes, "Image Source")
    image_licence = value(attributes, "Image Licence")

    if ancient:
        operation = (
            f"The catalogue classifies the object as {kind.lower()}. Its recorded unit or scale is "
            f"{scale}. A shared reference allowed a quantity to be checked and communicated instead "
            "of depending only on an individual judgement."
        )
        context = (
            f"The object is associated with {origin} and is dated {period}. Its recorded context is "
            f"{setting}. Reading it alongside other standards helps visitors compare how communities "
            "made length, mass, capacity or depth consistent."
        )
    else:
        operation = (
            f"Its recorded function was to {function.rstrip('.').lower()}. The relevant vehicle or "
            f"application is {scale}. Considering the component separately from the complete vehicle "
            "makes the relationship between a design decision and the driving experience easier to see."
        )
        context = (
            f"The component is associated with {origin} in {period}. Its vehicle or application was "
            f"{setting}. This places it within a period when specialist automotive systems were rapidly "
            "replacing practices inherited from bicycles, carriages and general machinery."
        )

    return [
        (
            "Object overview",
            [
                f"{title} is catalogued as {kind.lower()} from {origin}, dating to {period}. {description}",
                f"This presentation separates the object into function, material, context and significance. "
                f"The catalogue associates it with {setting}.",
            ],
        ),
        (
            "Function and use",
            [
                operation,
                "Look for the part of the object that carries out this task: a marked edge, a calibrated "
                "volume, a bearing surface, a linkage, or another working feature. Its form provides clues "
                "about the actions expected from its user.",
            ],
        ),
        (
            "Materials and construction",
            [
                f"The recorded material is {material}. Material affects weight, durability, precision, "
                "manufacture and the kinds of wear that survive for later study.",
                f"For {title}, construction should be read together with its purpose as {kind.lower()}. "
                "Surface marks, joints and changes of section can reveal how makers balanced practical "
                "requirements with the tools and resources available to them.",
            ],
        ),
        (
            "Historical setting",
            [
                context,
                "The object is therefore evidence for both technology and organisation. It shows that a "
                "working system depends on shared knowledge: people must understand how an artefact is "
                "made, how it is read and what result others will accept.",
            ],
        ),
        (
            "Significance and legacy",
            [
                significance,
                f"The lasting value of {title} is not only its age or rarity. It makes an otherwise abstract "
                "technical practice visible and gives visitors a point of comparison with later standards, "
                "components and interfaces.",
            ],
        ),
        (
            "Sources and questions",
            [
                f"Catalogue sources: {sources}. Image source: {image_source}. Recorded image licence: "
                f"{image_licence}.",
                "Visitor prompt: which feature communicates the object's purpose most clearly? Compare its "
                "material, scale and method of use with another piece in the exhibition. What changed, and "
                "what problem remained the same?",
            ],
        ),
    ]


def font(size, bold=False):
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    path = Path("/usr/share/fonts/truetype/dejavu") / name
    return ImageFont.truetype(str(path), size) if path.exists() else ImageFont.load_default()


def wrapped(draw, xy, text, line_width, used_font, fill, spacing=12, max_lines=None):
    lines = textwrap.wrap(clean(text), width=line_width)
    if max_lines:
        lines = lines[:max_lines]
    x, y = xy
    for line in lines:
        draw.text((x, y), line, font=used_font, fill=fill)
        bbox = draw.textbbox((x, y), line, font=used_font)
        y = bbox[3] + spacing
    return y


def generated_illustration(title, attributes, stage, piece_index):
    GENERATED_MEDIA.mkdir(exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    output = GENERATED_MEDIA / f"{slug}-{stage}.png"
    if output.exists():
        return output

    digest = hashlib.sha256(f"{title}:{stage}:{piece_index}".encode()).digest()
    base = (45 + digest[0] // 4, 55 + digest[1] // 5, 70 + digest[2] // 5)
    accent = (150 + digest[3] // 3, 110 + digest[4] // 3, 55 + digest[5] // 3)
    pale = tuple(min(255, channel + 95) for channel in base)
    white = (247, 249, 252)
    width, height = 1600, 1200
    image = Image.new("RGB", (width, height), base)
    draw = ImageDraw.Draw(image)

    for y in range(height):
        factor = y / height
        colour = tuple(int(channel * (1 - 0.28 * factor)) for channel in base)
        draw.line((0, y, width, y), fill=colour)
    title_font = font(56, bold=True)
    heading_font = font(38, bold=True)
    body_font = font(29)
    small_font = font(25)
    wrapped(draw, (80, 55), title, 42, title_font, white, 8, 2)
    draw.text((82, 205), STAGE_LABELS[stage].upper(), font=small_font, fill=accent)

    if stage == "overview":
        # A schematic object view. Cars receive a chassis outline; measurement
        # objects receive a calibrated artefact silhouette.
        if "Civilisation" in attributes:
            draw.rounded_rectangle((280, 350, 1320, 760), radius=75, outline=white, width=22)
            for mark in range(13):
                x = 330 + mark * 78
                length = 105 if mark % 3 == 0 else 62
                draw.line((x, 350, x, 350 + length), fill=accent, width=12)
            draw.ellipse((690, 475, 910, 695), outline=pale, width=18)
        else:
            draw.rounded_rectangle((210, 350, 1390, 810), radius=100, outline=white, width=18)
            draw.line((340, 680, 1260, 680), fill=white, width=28)
            for cx in (430, 1170):
                draw.ellipse((cx - 125, 625, cx + 125, 875), outline=white, width=28)
                draw.ellipse((cx - 55, 695, cx + 55, 805), outline=accent, width=20)
            draw.rounded_rectangle((610, 465, 990, 700), radius=36, outline=accent, width=24)
        footer = value(attributes, "Measurement Type", "Component Type")

    elif stage == "materials":
        material = value(attributes, "Material")
        radii = (245, 175, 105)
        colours = (white, accent, pale)
        for radius, colour in zip(radii, colours):
            draw.ellipse((470 - radius, 620 - radius, 470 + radius, 620 + radius), outline=colour, width=22)
        for offset in range(7):
            y = 405 + offset * 68
            draw.rounded_rectangle((820, y, 1400, y + 38), radius=18, fill=(accent if offset % 2 else pale))
        draw.text((270, 930), "FORM", font=heading_font, fill=white)
        draw.text((815, 930), "MATERIAL", font=heading_font, fill=white)
        footer = material

    elif stage == "timeline":
        period = value(attributes, "Approximate Date", "Year / Period")
        origin = value(attributes, "Civilisation", "Manufacturer / Origin")
        y = 640
        draw.line((180, y, 1420, y), fill=white, width=18)
        nodes = [280, 800, 1320]
        labels = ["CONTEXT", period.upper(), "LEGACY"]
        for number, (x, label) in enumerate(zip(nodes, labels), 1):
            draw.ellipse((x - 58, y - 58, x + 58, y + 58), fill=accent, outline=white, width=10)
            draw.text((x - 15, y - 26), str(number), font=heading_font, fill=white)
            wrapped(draw, (x - 175, y + 100), label, 19, body_font, white, 5, 2)
        footer = origin

    else:  # comparison
        kind = value(attributes, "Measurement Type", "Component Type")
        draw.rounded_rectangle((170, 350, 715, 850), radius=45, outline=white, width=16)
        draw.rounded_rectangle((885, 350, 1430, 850), radius=45, outline=pale, width=16)
        draw.text((375, 485), "A", font=font(112, bold=True), fill=accent)
        draw.text((1090, 485), "B", font=font(112, bold=True), fill=accent)
        draw.line((730, 600, 870, 600), fill=accent, width=18)
        draw.text((755, 500), "?", font=font(100, bold=True), fill=white)
        wrapped(draw, (250, 730), "THIS PIECE", 17, body_font, white, 5, 1)
        wrapped(draw, (990, 730), "ANOTHER ERA", 17, body_font, white, 5, 1)
        footer = f"Compare function and form · {kind}"

    wrapped(draw, (80, 1020), footer, 75, body_font, white, 8, 2)
    draw.text(
        (80, 1145),
        "Interpretive benchmark illustration · not an object photograph",
        font=font(21),
        fill=accent,
    )
    image.save(output, "PNG", optimize=True)
    return output


def generated_fact_sheet(title, attributes, piece_index):
    """Create a piece-specific two-page PDF without adding a runtime dependency."""
    GENERATED_MEDIA.mkdir(exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    output = GENERATED_MEDIA / f"{slug}-fact-sheet.pdf"
    if output.exists():
        return output

    digest = hashlib.sha256(f"pdf:{title}:{piece_index}".encode()).digest()
    accent = (85 + digest[0] // 3, 70 + digest[1] // 3, 80 + digest[2] // 3)
    pages = []
    for page_number in (1, 2):
        sheet = Image.new("RGB", (1240, 1754), (249, 247, 242))
        draw = ImageDraw.Draw(sheet)
        draw.rectangle((0, 0, 1240, 170), fill=accent)
        draw.text((72, 54), "MIYP · OBJECT FACT SHEET", font=font(34, bold=True), fill=(255, 255, 255))
        draw.text((1085, 58), f"{page_number}/2", font=font(28), fill=(255, 255, 255))
        y = wrapped(draw, (72, 225), title, 35, font(52, bold=True), (35, 40, 48), 10, 3) + 35
        if page_number == 1:
            sections = [
                ("Period", value(attributes, "Approximate Date", "Year / Period")),
                ("Origin", value(attributes, "Civilisation", "Manufacturer / Origin")),
                ("Type", value(attributes, "Measurement Type", "Component Type")),
                ("Material", value(attributes, "Material")),
                ("Context", value(attributes, "Region / Findspot", "Vehicle / Application")),
            ]
        else:
            sections = [
                ("Interpretive note", value(attributes, "Description")),
                ("Technical significance", value(attributes, "Technological Significance", "Function")),
                ("Visitor questions", "Which feature best explains the object's purpose? How would its use, material or interface differ in another period?"),
                ("Catalogue source", value(attributes, "Information Source")),
            ]
        for heading, paragraph in sections:
            draw.text((75, y), heading.upper(), font=font(25, bold=True), fill=accent)
            y = wrapped(draw, (75, y + 48), paragraph, 70, font(28), (45, 48, 55), 11, 7) + 38
        draw.line((72, 1645, 1168, 1645), fill=accent, width=3)
        draw.text(
            (72, 1670),
            "Generated for the controlled thesis benchmark from the prototype catalogue record.",
            font=font(20),
            fill=(75, 78, 84),
        )
        pages.append(sheet)
    pages[0].save(output, "PDF", resolution=150.0, save_all=True, append_images=pages[1:])
    return output


def log_in(page):
    page.goto(f"{BASE_URL}/cms/login/", wait_until="domcontentloaded")
    page.locator('input[name="username"]').fill(USERNAME)
    page.locator('input[name="password"]').fill(PASSWORD)
    page.locator('button[type="submit"], input[type="submit"]').first.click()
    page.wait_for_url(re.compile(r".*/cms/(pages/)?$"), timeout=20_000)


def scrape_pieces(page):
    paths = [line.strip() for line in PRESENTATIONS_FILE.read_text().splitlines() if line.strip()]
    if len(paths) != len(USER_DEVICE_PAGE_IDS):
        raise RuntimeError(f"Expected 28 presentation paths, found {len(paths)}")
    pieces = []
    for index, path in enumerate(paths):
        page.goto(BASE_URL + path, wait_until="domcontentloaded")
        first = page.locator(".presentation-slide").first
        title = clean(first.locator("h2").inner_text())
        attributes = {}
        for row in first.locator("tr").all():
            cells = [clean(item) for item in row.locator("th,td").all_inner_texts()]
            if len(cells) >= 2 and cells[0] != "Attribute":
                attributes[cells[0]] = cells[1]
        pieces.append({
            "index": index,
            "path": path,
            "title": title,
            "attributes": attributes,
            "parent_page_id": USER_DEVICE_PAGE_IDS[index],
        })
        print(f"Inventory {index + 1:02d}/28: {title}", flush=True)
    return pieces


def find_image(page, title):
    subject = title.split("—", 1)[-1]
    search_words = [
        word for word in re.findall(r"[^\W_]+", subject, flags=re.UNICODE)
        if len(word) > 1 and word.isalpha()
    ]
    search_query = " ".join(search_words[:3]) or title
    page.goto(
        f"{BASE_URL}/cms/images/chooser/results/?q={quote_plus(search_query)}",
        wait_until="domcontentloaded",
    )
    for text, full_title, href in page.locator('a[href*="/cms/images/chooser/chosen/"]').evaluate_all(
        "els => els.map(a => [(a.innerText || '').trim(), a.getAttribute('title') || '', a.getAttribute('href')])"
    ):
        if clean(text) == title or clean(full_title) == title:
            match = re.search(r"/chosen/(\d+)/", href or "")
            if match:
                return int(match.group(1))
    return None


def upload_image(page, title, path, description):
    image_id = find_image(page, title)
    if image_id:
        return image_id
    page.goto(f"{BASE_URL}/cms/images/add/", wait_until="domcontentloaded")
    page.locator('input[name="title"]').fill(title)
    page.locator('input[name="description"]').fill(description)
    page.locator('input[name="file"]').set_input_files(str(path))
    page.get_by_role("button", name="Upload").click()
    page.wait_for_timeout(1_000)
    image_id = find_image(page, title)
    if image_id is None:
        raise RuntimeError(f"Wagtail did not retain the uploaded image: {title}")
    return image_id


def find_document(page, title):
    subject = title.split("—", 1)[-1]
    search_words = [
        word for word in re.findall(r"[^\W_]+", subject, flags=re.UNICODE)
        if len(word) > 1 and word.isalpha()
    ]
    # A single distinctive word is more reliable than an AND query when a
    # catalogue title contains punctuation such as X-Frame or Auburn/Duesenberg.
    search_query = search_words[0] if search_words else title
    page.goto(
        f"{BASE_URL}/cms/documents/?q={quote_plus(search_query)}",
        wait_until="domcontentloaded",
    )
    for text, full_title, href in page.locator('a[href*="/cms/documents/"]').evaluate_all(
        "els => els.map(a => [(a.innerText || '').trim(), a.getAttribute('title') || '', a.getAttribute('href')])"
    ):
        if clean(text) != title and clean(full_title) != title:
            continue
        match = re.search(r"/cms/documents/(?:edit/)?(\d+)/", href or "")
        if match:
            return int(match.group(1))
    return None


def upload_document(page, title, path):
    document_id = find_document(page, title)
    if document_id:
        return document_id
    page.goto(f"{BASE_URL}/cms/documents/add/", wait_until="domcontentloaded")
    page.locator('input[name="title"]').fill(title)
    page.locator('input[name="file"]').set_input_files(str(path))
    page.get_by_role("button", name="Upload").click()
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_timeout(800)
    document_id = find_document(page, title)
    if document_id is None:
        raise RuntimeError(f"Wagtail did not retain the uploaded document: {title}")
    return document_id


def child_pages(page, parent_id):
    page.goto(f"{BASE_URL}/cms/pages/{parent_id}/", wait_until="domcontentloaded")
    result = {}
    for text, href in page.locator('a[href$="/edit/"]').evaluate_all(
        "els => els.map(a => [(a.innerText || '').trim(), a.getAttribute('href')])"
    ):
        match = re.fullmatch(r"/cms/pages/(\d+)/edit/", href or "")
        if match and clean(text):
            result[clean(text)] = int(match.group(1))
    return result


def configure_stream_block(page, block_kind, document_id=None, question=None):
    """Replace the live StreamField block while retaining Wagtail's form state."""
    count = int(page.locator('input[name="content-count"]').input_value())
    reusable = None
    if block_kind:
        for index in range(count):
            type_field = page.locator(f'input[name="content-{index}-type"]')
            deleted_field = page.locator(f'input[name="content-{index}-deleted"]')
            if (
                reusable is None
                and type_field.count()
                and type_field.input_value() == block_kind
                and (not deleted_field.count() or not deleted_field.input_value())
            ):
                reusable = index

    for index in range(count):
        if index == reusable:
            continue
        deleted = page.locator(f'input[name="content-{index}-deleted"]')
        if deleted.count():
            deleted.evaluate('(element) => { element.value = "1"; }')

    if not block_kind:
        return None
    if reusable is None:
        page.locator('#content-root button[title="Insert a block"]').last.click()
        option_name = "Document" if block_kind == "document" else "Interactive question"
        page.get_by_role("option", name=option_name).click()
        page.wait_for_timeout(150)
        reusable = count

    deleted = page.locator(f'input[name="content-{reusable}-deleted"]')
    if deleted.count():
        deleted.evaluate('(element) => { element.value = ""; }')

    if block_kind == "document":
        page.locator(f'input[name="content-{reusable}-value"]').evaluate(
            '(element, value) => { element.value = value; }',
            str(document_id),
        )
    else:
        prompt, _answer = question
        page.locator(f'input[name="content-{reusable}-value-question"]').fill(prompt)
    return reusable


def publish_slide(
    page,
    parent_id,
    page_id,
    title,
    body,
    image_id=None,
    caption="",
    document_id=None,
    question=None,
):
    adding = page_id is None
    if adding:
        url = f"{BASE_URL}/cms/pages/add/main_app/slideshowslidepage/{parent_id}/"
    else:
        url = f"{BASE_URL}/cms/pages/{page_id}/edit/"
    page.goto(url, wait_until="domcontentloaded")
    page.locator('input[name="title"]').fill(title)
    if adding:
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
        page.locator('input[name="slug"]').evaluate(
            '(element, value) => { element.value = value; element.dispatchEvent(new Event("change", {bubbles: true})); }',
            slug,
        )
    page.locator('input[name="time_seconds"]').fill("8")
    details = page.locator('input[name="show_details"]')
    if details.is_checked():
        details.uncheck()

    total = int(page.locator('input[name="gallery_images-TOTAL_FORMS"]').input_value())
    if image_id is not None:
        if total == 0:
            page.locator("#id_gallery_images-ADD").click()
            total = 1
        page.locator('input[name="gallery_images-0-image"]').evaluate(
            '(element, value) => { element.value = value; element.dispatchEvent(new Event("change", {bubbles: true})); }',
            str(image_id),
        )
        page.locator('input[name="gallery_images-0-caption"]').fill(caption)
        for form_index in range(1, total):
            delete = page.locator(f'input[name="gallery_images-{form_index}-DELETE"]')
            if delete.count():
                delete.evaluate('(element) => { element.checked = true; element.value = "on"; }')
    else:
        for form_index in range(total):
            delete = page.locator(f'input[name="gallery_images-{form_index}-DELETE"]')
            if delete.count():
                delete.evaluate('(element) => { element.checked = true; element.value = "on"; }')

    block_kind = "document" if document_id else ("question" if question else None)
    block_index = configure_stream_block(
        page,
        block_kind,
        document_id=document_id,
        question=question,
    )

    # Assign Draftail's hidden JSON value immediately before submission. The
    # editor's React state can otherwise rewrite a programmatically assigned
    # value while the image formset is being updated.
    page.locator('button[name="action-publish"]').evaluate(
        '''(button, values) => {
            const body = document.querySelector('input[name="body"]');
            body.value = values.body;
            if (values.answerName) {
                document.querySelector(`input[name="${values.answerName}"]`).value = values.answer;
            }
            button.click();
        }''',
        {
            "body": body,
            "answerName": (
                f"content-{block_index}-value-answer"
                if question and block_index is not None
                else ""
            ),
            "answer": (
                draftail_paragraphs([question[1]])
                if question
                else ""
            ),
        },
    )
    page.wait_for_url(f"**/cms/pages/{parent_id}/", timeout=30_000, wait_until="domcontentloaded")


def main():
    if not USERNAME or not PASSWORD:
        raise SystemExit("Set MIYP_CMS_USER and MIYP_CMS_PASSWORD before running this script")
    if not PRESENTATIONS_FILE.exists():
        raise SystemExit(f"Missing {PRESENTATIONS_FILE}")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path="/usr/bin/google-chrome",
            headless=True,
        )
        context = browser.new_context(ignore_https_errors=True)
        context.route(
            "**/*",
            lambda route: route.abort()
            if route.request.resource_type in {"font", "media"}
            else route.continue_(),
        )
        page = context.new_page()
        log_in(page)
        pieces = scrape_pieces(page)

        if not VERIFY_ONLY:
            for index, piece in enumerate(pieces):
                piece["visuals"] = {}
                for stage in ("overview", "materials", "timeline", "comparison"):
                    if stage == "overview" and index < 14:
                        image_id = ANCIENT_IMAGE_IDS[index]
                        image_kind = "existing collection image"
                    else:
                        asset = generated_illustration(
                            piece["title"], piece["attributes"], stage, index
                        )
                        image_title = (
                            f"Benchmark visual — {piece['title']} — {STAGE_LABELS[stage]}"
                        )
                        image_id = upload_image(
                            page,
                            image_title,
                            asset,
                            "Unique generated interpretive graphic for the controlled thesis benchmark; "
                            "not an object photograph.",
                        )
                        image_kind = "generated interpretive benchmark illustration"
                    piece["visuals"][stage] = {
                        "image_id": image_id,
                        "image_kind": image_kind,
                    }
                    print(
                        f"Media {index + 1:02d}/28, {stage}: image {image_id} for {piece['title']}",
                        flush=True,
                    )

                pdf_asset = generated_fact_sheet(piece["title"], piece["attributes"], index)
                document_title = f"Benchmark fact sheet — {piece['title']}"
                piece["document_id"] = upload_document(
                    page,
                    document_title,
                    pdf_asset,
                )
                print(
                    f"Document {index + 1:02d}/28: document {piece['document_id']} "
                    f"for {piece['title']}",
                    flush=True,
                )

            for piece_index, piece in enumerate(pieces):
                children = child_pages(page, piece["parent_page_id"])
                panels = presentation_texts(piece["title"], piece["attributes"])
                fallback_page = children.get("Slide 1") if SLIDE_TITLES[0] not in children else None
                for slide_index, (cms_title, panel, layout) in enumerate(
                    zip(SLIDE_TITLES, panels, SLIDE_LAYOUTS)
                ):
                    heading, paragraphs = panel
                    page_id = children.get(cms_title)
                    if slide_index == 0 and page_id is None:
                        page_id = fallback_page

                    visual = piece["visuals"].get(layout.get("stage", ""))
                    question = None
                    if layout["kind"] == "question":
                        question = (
                            "Which design choice most clearly communicates this object's purpose?",
                            "Compare its material, scale and method of use with another object in the "
                            "exhibition. Different answers are possible when they are supported by "
                            "visible evidence from the two pieces.",
                        )
                    publish_slide(
                        page,
                        piece["parent_page_id"],
                        page_id,
                        cms_title,
                        draftail_body(heading, paragraphs),
                        image_id=visual["image_id"] if visual else None,
                        caption=(
                            f"{piece['title']} — {STAGE_LABELS[layout['stage']]} — "
                            f"{visual['image_kind']}"
                            if visual
                            else ""
                        ),
                        document_id=(
                            piece["document_id"] if layout["kind"] == "document" else None
                        ),
                        question=question,
                    )
                    children[cms_title] = page_id or -1
                    print(
                        f"Published {piece_index + 1:02d}/28, slide {slide_index + 1}/6: "
                        f"{piece['title']} — {heading} ({layout['kind']})",
                        flush=True,
                    )

        # Verify the same anonymous representation exercised by the benchmark.
        # Curator sessions include additional page-title preview markup.
        verification_context = browser.new_context(ignore_https_errors=True)
        verification_page = verification_context.new_page()
        verification = []
        all_image_urls = set()
        for piece in pieces:
            verification_page.goto(BASE_URL + piece["path"], wait_until="domcontentloaded")
            count = verification_page.locator(".presentation-slide").count()
            authored = verification_page.locator('.presentation-slide[data-track-index]')
            headings = [clean(text) for text in authored.locator("h2").all_inner_texts()]
            image_urls = authored.locator("img").evaluate_all(
                "els => els.map(img => new URL(img.currentSrc || img.src, document.baseURI).pathname)"
            )
            document_urls = authored.locator('a[href$=".pdf"], object[data*=".pdf"]').evaluate_all(
                "els => els.map(el => new URL(el.href || el.data, document.baseURI).pathname)"
            )
            questions = authored.locator(".mip-question").count()
            if count != 7 or len(headings) != 6:
                raise RuntimeError(
                    f"Verification failed for {piece['title']}: "
                    f"slides={count}, headings={len(headings)}"
                )
            if len(image_urls) != 4 or len(set(image_urls)) != 4:
                raise RuntimeError(
                    f"Media verification failed for {piece['title']}: "
                    f"images={len(image_urls)}, unique_images={len(set(image_urls))}"
                )
            if len(set(document_urls)) != 1:
                raise RuntimeError(
                    f"Document verification failed for {piece['title']}: "
                    f"document_urls={document_urls}"
                )
            duplicate_urls = set(image_urls) & all_image_urls
            if duplicate_urls:
                raise RuntimeError(
                    f"Cross-presentation image reuse for {piece['title']}: "
                    f"{sorted(duplicate_urls)}"
                )
            all_image_urls.update(image_urls)
            if questions != 1:
                raise RuntimeError(
                    f"Question verification failed for {piece['title']}: questions={questions}"
                )
            verification.append({
                "title": piece["title"],
                "path": piece["path"],
                "slides": count,
                "authored_headings": headings,
                "slide_layouts": [layout["kind"] for layout in SLIDE_LAYOUTS],
                "authored_images": len(image_urls),
                "unique_image_urls": len(set(image_urls)),
                "authored_documents": len(set(document_urls)),
                "interactive_question_blocks": questions,
                "source": piece["attributes"].get("Information Source", ""),
            })
            print(
                f"Verified 7 slides, 4 unique images and 1 PDF: {piece['title']}",
                flush=True,
            )
        verification_context.close()

        MANIFEST.write_text(
            json.dumps({
                "purpose": "Controlled populated-content performance benchmark",
                "automatic_details_slides_per_piece": 1,
                "authored_slides_per_piece": 6,
                "total_slides_per_piece": 7,
                "content_pattern": [layout["kind"] for layout in SLIDE_LAYOUTS],
                "image_reuse_within_or_between_presentations": False,
                "presentations": verification,
            }, ensure_ascii=False, indent=2) + "\n"
        )
        browser.close()

    print(f"OK! Populated and verified 28 presentations. Manifest: {MANIFEST}", flush=True)


if __name__ == "__main__":
    main()
