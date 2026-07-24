import os, re, fitz, openpyxl, datetime, glob
from collections import defaultdict

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CATALOG_DIR = os.path.join(BASE_DIR, "Catalog")
DB_PATH = os.path.join(BASE_DIR, "database.xlsx")
OUT_DIR = os.path.join(CATALOG_DIR, "reference_images")

SKIP_CATEGORIES = {"glassware"}  # sudah pernah di-extract


def normalize_sku(raw):
    if isinstance(raw, datetime.datetime):
        return raw.strftime("%Y-%m-%d")
    s = str(raw).strip()
    s = re.sub(r"^-\s*", "", s)
    s = s.rstrip("*")
    return s.strip()


def load_database():
    wb = openpyxl.load_workbook(DB_PATH, data_only=True)
    ws = wb["Price List"]
    sku_db = {}
    for row in ws.iter_rows(min_row=3, values_only=True):
        if row[0] is None:
            continue
        sku = normalize_sku(row[0])
        if not sku:
            continue
        sku_db[sku] = {
            "category": (row[3] or "").strip(),
            "brand": (row[2] or "").strip(),
            "size": (row[4] or "").strip(),
        }
    return sku_db


def extract_category_from_filename(pdf_name):
    m = re.search(r'-\s*(\w+\s*\w*)\s*\.pdf$', pdf_name, re.I)
    if m:
        return m.group(1).strip().lower()
    return ""


def process_pdf(pdf_path, sku_set, sku_db):
    print(f"\n  Membaca {os.path.basename(pdf_path)} ...")
    doc = fitz.open(pdf_path)
    image_sku_map = defaultdict(set)
    skus_found = set()

    for page_idx in range(doc.page_count):
        page = doc[page_idx]
        blocks = page.get_text("blocks")
        full_text = page.get_text()

        sku_positions = []
        for b in blocks:
            x0, y0, x1, y1, text = b[0], b[1], b[2], b[3], b[4]
            tokens = re.findall(r'\S+', text)
            for token in tokens:
                token = token.strip().strip('.,;:!?"\'()[]')
                if token in sku_set:
                    sku_cy = (y0 + y1) / 2
                    sku_positions.append((token, sku_cy))

        found_here = {s[0] for s in sku_positions}
        for sku in sku_set:
            if sku in found_here:
                continue
            if sku in full_text:
                try:
                    rects = page.search_for(sku)
                    for rect in rects:
                        sku_positions.append((sku, (rect.y0 + rect.y1) / 2))
                except:
                    pass

        if not sku_positions:
            continue

        seen_sku = set()
        deduped = []
        for s, y in sku_positions:
            if s not in seen_sku:
                seen_sku.add(s)
                deduped.append((s, y))
        sku_positions = deduped

        images = []
        for img in page.get_images(full=True):
            xref = img[0]
            bbox = page.get_image_bbox(img)
            if bbox.is_empty or bbox.is_infinite:
                continue
            w = bbox.x1 - bbox.x0
            h = bbox.y1 - bbox.y0
            if w < 30 or h < 30:
                continue
            images.append({
                "xref": xref,
                "bbox": bbox,
                "cy": (bbox.y0 + bbox.y1) / 2,
            })

        if not images:
            continue

        images.sort(key=lambda x: x["cy"])

        for sku, sku_cy in sku_positions:
            best = None
            for img in images:
                if img["cy"] < sku_cy:
                    best = img
                else:
                    break
            if best is None:
                best = images[0]

            bk = (round(best["bbox"].x0, 1), round(best["bbox"].y0, 1),
                  round(best["bbox"].x1, 1), round(best["bbox"].y1, 1))
            image_sku_map[(bk, page_idx)].add(sku)
            skus_found.add(sku)

    doc.close()

    extracted = 0
    for (bk, page_idx), skus in sorted(image_sku_map.items()):
        safe_skus = [s.replace("/", "-").replace("\\", "-") for s in skus]
        x0, y0, x1, y1 = bk
        clip = fitz.Rect(x0, y0, x1, y1)
        mat = fitz.Matrix(3, 3)
        doc2 = fitz.open(pdf_path)
        page = doc2[page_idx]
        pix = page.get_pixmap(matrix=mat, clip=clip)
        for safe_sku in safe_skus:
            out_path = os.path.join(OUT_DIR, f"{safe_sku}.jpg")
            pix.save(out_path)
            extracted += 1
        doc2.close()

    return skus_found, extracted


def main():
    print("=== Extract Reference Images dari Katalog ===\n")

    sku_db = load_database()
    sku_set = set(sku_db.keys())
    print(f"Total SKU di database: {len(sku_set)}")

    os.makedirs(OUT_DIR, exist_ok=True)

    existing = set()
    for f in os.listdir(OUT_DIR):
        name, ext = os.path.splitext(f)
        if ext.lower() == ".jpg":
            existing.add(name)
    print(f"Reference images sudah ada: {len(existing)}")

    pdf_pattern = os.path.join(CATALOG_DIR, "*KATALOG*.pdf")
    all_pdfs = sorted(glob.glob(pdf_pattern))
    print(f"Total PDF ditemukan: {len(all_pdfs)}")

    total_skus_found = set()
    total_extracted = 0

    for pdf_path in all_pdfs:
        cat = extract_category_from_filename(os.path.basename(pdf_path))
        if cat in SKIP_CATEGORIES:
            print(f"  Skip {os.path.basename(pdf_path)} (sudah di-extract sebelumnya)")
            continue

        skus_found, extracted = process_pdf(pdf_path, sku_set, sku_db)
        total_skus_found.update(skus_found)
        total_extracted += extracted

        print(f"  -> {len(skus_found)} SKU matched, {extracted} images saved")

    print(f"\n=== Selesai ===")
    print(f"Total SKU ditemukan di semua PDF: {len(total_skus_found)} / {len(sku_set)}")
    print(f"Total images disimpan: {total_extracted}")
    unmapped = sku_set - total_skus_found
    if unmapped:
        print(f"SKU tidak ditemukan di katalog: {len(unmapped)}")


if __name__ == "__main__":
    main()
