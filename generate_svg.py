"""
STEP 2: Ambil foto yang sudah di-rename (output/renamed/**), tempel ke template
SVG (ganti foto placeholder + tambah label SKU/nama), simpan ke output/svg/<SKU>.svg

Cara pakai:
    python generate_svg.py
"""

import os
import re
import csv
import base64
from io import BytesIO
from functools import lru_cache

from PIL import Image, ImageOps, ImageFont, ImageDraw
from pillow_heif import register_heif_opener
import numpy as np
import cv2
from lxml import etree as ET
from playwright.sync_api import sync_playwright

import config

register_heif_opener()

SVG_NS = "http://www.w3.org/2000/svg"


def auto_crop_to_subject(image_path, work_size=600, margin_pct=0.15):
    """Betulkan orientasi (EXIF) lalu crop otomatis ke objek utama
    (buang background kosong di sekitarnya), objek jadi center.
    Pakai GrabCut, dikerjakan di resolusi kecil biar cepat lalu
    hasil bbox di-scale balik ke resolusi asli.
    Kalau deteksi gagal/aneh, balikin foto full (nggak dipaksa crop)."""
    pil = Image.open(image_path)
    pil = ImageOps.exif_transpose(pil).convert("RGB")  # fix rotasi dari HP
    w0, h0 = pil.size

    scale = work_size / max(w0, h0)
    small = pil.resize((max(1, int(w0 * scale)), max(1, int(h0 * scale))))
    arr = np.array(small)
    h, w = arr.shape[:2]

    mask = np.zeros((h, w), np.uint8)
    bgd_model = np.zeros((1, 65), np.float64)
    fgd_model = np.zeros((1, 65), np.float64)
    mx, my = int(w * 0.08), int(h * 0.05)
    rect = (mx, my, w - 2 * mx, h - 2 * my)

    try:
        cv2.grabCut(arr, mask, rect, bgd_model, fgd_model, 5, cv2.GC_INIT_WITH_RECT)
    except cv2.error:
        return pil  # gagal segmentasi, pakai foto full apa adanya

    fg_mask = np.where((mask == 2) | (mask == 0), 0, 1).astype("uint8")
    ys, xs = np.where(fg_mask > 0)
    if len(xs) == 0:
        return pil

    x0, x1, y0, y1 = xs.min() / scale, xs.max() / scale, ys.min() / scale, ys.max() / scale
    box_area_ratio = ((x1 - x0) * (y1 - y0)) / (w0 * h0)

    # sanity check: kalau hasil deteksi ngaco (kotak nyaris kosong atau nyaris
    # penuh 1 gambar), jangan dipaksa crop -> pakai foto full
    if box_area_ratio < 0.05 or box_area_ratio > 0.97:
        return pil

    # kasih padding di sekeliling objek biar nggak mepet
    pad_x = (x1 - x0) * margin_pct
    pad_y = (y1 - y0) * margin_pct
    x0, y0 = max(0, x0 - pad_x), max(0, y0 - pad_y)
    x1, y1 = min(w0, x1 + pad_x), min(h0, y1 + pad_y)

    return pil.crop((int(x0), int(y0), int(x1), int(y1)))


def find_placeholder_image_tag(svg_content):
    """Cari tag <image> dengan ukuran (width*height) terbesar -> dianggap
    sebagai foto placeholder produk (bukan elemen dekorasi kecil)."""
    pattern = re.compile(r'<image\s+[^>]*?/>')
    best_match, best_area = None, -1
    for m in pattern.finditer(svg_content):
        tag = m.group(0)
        w = re.search(r'width="([\d.]+)"', tag)
        h = re.search(r'height="([\d.]+)"', tag)
        if not w or not h:
            continue
        area = float(w.group(1)) * float(h.group(1))
        if area > best_area:
            best_area, best_match = area, m
    return best_match  # re.Match object atau None


def cover_fit_image_to_box(img, box_w, box_h, bg_color=(255, 255, 255), border_radius=0):
    """Resize foto (contain-fit) supaya muat di box_w x box_h tanpa crop,
    sisa area diisi bg_color. Balikin sebagai base64 JPEG.
    `img` = objek PIL Image (RGB)."""
    src_w, src_h = img.size
    src_ratio = src_w / src_h
    box_ratio = box_w / box_h

    if src_ratio > box_ratio:
        new_w = int(box_w)
        new_h = int(box_w / src_ratio)
    else:
        new_h = int(box_h)
        new_w = int(box_h * src_ratio)

    img = img.resize((new_w, new_h), Image.LANCZOS)

    canvas = Image.new("RGB", (int(box_w), int(box_h)), bg_color)
    offset_x = (int(box_w) - new_w) // 2
    offset_y = (int(box_h) - new_h) // 2
    canvas.paste(img, (offset_x, offset_y))

    if border_radius > 0:
        mask = Image.new("L", canvas.size, 0)
        draw = ImageDraw.Draw(mask)
        r = int(border_radius)
        draw.rounded_rectangle([(0, 0), (int(box_w) - 1, int(box_h) - 1)],
                               radius=r, fill=255)
        canvas = Image.composite(canvas, Image.new("RGB", canvas.size, bg_color), mask)

    buf = BytesIO()
    canvas.save(buf, format="JPEG", quality=90)
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def strip_original_title(template_content):
    """Hapus vector path judul asli (hasil flatten Canva) dari template.
    Judul asli dikenali sebagai grup <g> level teratas yang punya atribut
    fill="#ffffff" (dipakai khusus utk glyph judul, tervalidasi manual saat
    setup) dan berurutan (contiguous). Kalau strukturnya nggak ketemu/berubah
    total (misal ganti Tamplate.svg dengan desain baru), fungsi ini nggak
    menghapus apa pun & judul lama akan tetap kelihatan -> tanda perlu dicek
    ulang manual sebelum lanjut pakai template baru itu."""
    parser = ET.XMLParser(huge_tree=True)
    root = ET.fromstring(template_content.encode("utf-8"), parser)

    white_idx = [
        i for i, el in enumerate(root)
        if el.tag == f"{{{SVG_NS}}}g" and el.attrib.get("fill") == "#ffffff"
    ]
    if white_idx and white_idx == list(range(min(white_idx), max(white_idx) + 1)):
        for el in [root[i] for i in white_idx]:
            root.remove(el)

    return ET.tostring(root, encoding="unicode")


def embed_title_font(template_content):
    """Suntik @font-face (embed base64) ke dalam SVG biar font judul baru
    render sama persis di semua tempat (preview & rasterize ke JPG), tanpa
    gantung koneksi internet / font sistem."""
    with open(config.TITLE_FONT_PATH, "rb") as f:
        font_b64 = base64.b64encode(f.read()).decode("ascii")
    style = (
        f'<style>@font-face{{font-family:"{config.TITLE_FONT_FAMILY}";'
        f'font-weight:{config.TITLE_FONT_WEIGHT};'
        f'src:url(data:font/ttf;base64,{font_b64}) format("truetype");}}</style>'
    )
    # taruh tepat setelah tag <svg ...> pembuka
    idx = template_content.index(">") + 1
    return template_content[:idx] + style + template_content[idx:]


@lru_cache(maxsize=1)
def _title_font():
    return {
        size: ImageFont.truetype(config.TITLE_FONT_PATH, size)
        for size in range(config.TITLE_MIN_FONT_SIZE, config.TITLE_BASE_FONT_SIZE + 1)
    }


def fit_title_font_size(text):
    """Cari font-size terbesar (mulai dari ukuran asli desain, mengecil kalau
    perlu) supaya nama produk masih muat di lebar banner."""
    fonts = _title_font()
    for size in range(config.TITLE_BASE_FONT_SIZE, config.TITLE_MIN_FONT_SIZE - 1, -1):
        if fonts[size].getlength(text) <= config.TITLE_MAX_WIDTH:
            return size
    return config.TITLE_MIN_FONT_SIZE


def build_title_overlay(name):
    """Bikin elemen <text> judul baru: posisi, warna, font persis sama dengan
    judul asli, font-size otomatis mengecil kalau nama produk kepanjangan."""
    font_size = fit_title_font_size(name)
    return (
        f'<text x="{config.TITLE_CENTER_X}" y="{config.TITLE_BASELINE_Y}" '
        f'text-anchor="middle" '
        f'font-family="{config.TITLE_FONT_FAMILY}" font-weight="{config.TITLE_FONT_WEIGHT}" '
        f'font-size="{font_size}" fill="{config.TITLE_COLOR}">{escape_xml(name)}</text>'
    )


def escape_xml(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def generate_one(template_content, image_path, sku, name, size, out_path):
    tag_match = find_placeholder_image_tag(template_content)
    if not tag_match:
        raise RuntimeError("Tidak ketemu tag <image> placeholder di template.")

    tag = tag_match.group(0)
    w = float(re.search(r'width="([\d.]+)"', tag).group(1))
    h = float(re.search(r'height="([\d.]+)"', tag).group(1))

    new_b64 = cover_fit_image_to_box(auto_crop_to_subject(image_path), w, h,
                                     border_radius=config.IMAGE_BORDER_RADIUS)

    x = re.search(r'x="([\d.]+)"', tag)
    y = re.search(r'y="([\d.]+)"', tag)
    x_val = x.group(1) if x else "0"
    y_val = y.group(1) if y else "0"
    rect_tag = (f'<rect x="{x_val}" y="{y_val}" width="{w}" height="{h}" '
                f'fill="white"/>')
    new_tag = rect_tag + re.sub(
        r'xlink:href="data:image/[^;]+;base64,[^"]+"',
        f'xlink:href="data:image/jpeg;base64,{new_b64}"',
        tag,
    )

    new_content = template_content[:tag_match.start()] + new_tag + template_content[tag_match.end():]

    title = build_title_overlay(name)
    new_content = new_content.replace("</svg>", title + "</svg>")

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(new_content)


def rasterize_svg_folder_to_jpg(svg_dir, jpg_dir):
    """Render semua .svg di svg_dir jadi .jpg (siap upload toko online),
    pakai 1 instance browser headless biar cepat (bukan buka-tutup per file)."""
    os.makedirs(jpg_dir, exist_ok=True)
    svg_files = [f for f in os.listdir(svg_dir) if f.lower().endswith(".svg")]
    if not svg_files:
        return

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": config.CANVAS_WIDTH, "height": config.CANVAS_HEIGHT})
        for fname in svg_files:
            svg_path = os.path.join(svg_dir, fname)
            with open(svg_path, encoding="utf-8") as f:
                svg_content = f.read()
            html = f'<html><body style="margin:0;padding:0;">{svg_content}</body></html>'
            page.set_content(html)
            page.wait_for_timeout(150)
            el = page.query_selector("svg")
            out_path = os.path.join(jpg_dir, os.path.splitext(fname)[0] + ".jpg")
            el.screenshot(path=out_path, type="jpeg", quality=config.JPG_QUALITY)
            print(f"  JPG: {out_path}")
        browser.close()


def dedupe_primary_rows(rows):
    """Pastikan 1 SKU cuma digenerate 1 kali, pilih foto primary skor tertinggi."""
    by_sku = {}
    for r in rows:
        sku = r["matched_sku"]
        prev = by_sku.get(sku)
        if prev is None or float(r.get("score") or 0) > float(prev.get("score") or 0):
            by_sku[sku] = r
    return list(by_sku.values())


def main():
    if not os.path.exists(config.REPORT_CSV):
        print(f"Belum ada {config.REPORT_CSV}. Jalankan match_and_rename.py dulu.")
        return

    with open(config.TEMPLATE_SVG, encoding="utf-8") as f:
        template_content = f.read()
    template_content = strip_original_title(template_content)
    template_content = embed_title_font(template_content)

    with open(config.REPORT_CSV, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = dedupe_primary_rows([
            r for r in reader if r["status"] == "OK" and r.get("primary") == "yes"
        ])

    if not rows:
        print("Tidak ada baris berstatus OK di match_report.csv.")
        return

    os.makedirs(config.SVG_OUTPUT_DIR, exist_ok=True)

    for r in rows:
        sku = r["matched_sku"]
        found = r.get("final_path")
        if not found or not os.path.exists(found):
            print(f"Lewati {sku}: file hasil rename tidak ditemukan ({found}).")
            continue

        out_path = os.path.join(config.SVG_OUTPUT_DIR, f"{sku}.svg")
        try:
            generate_one(template_content, found, sku, r["description"], "", out_path)
            print(f"Generated: {out_path}")
        except Exception as e:
            print(f"Gagal generate {sku}: {e}")

    print(f"\nSVG selesai: {config.SVG_OUTPUT_DIR}")
    print("Merender ke JPG (siap upload toko online)...")
    rasterize_svg_folder_to_jpg(config.SVG_OUTPUT_DIR, config.JPG_OUTPUT_DIR)
    print(f"\nSelesai. SVG (master, editable): {config.SVG_OUTPUT_DIR}")
    print(f"JPG (siap upload): {config.JPG_OUTPUT_DIR}")


if __name__ == "__main__":
    main()
