import os, re, fitz, openpyxl, datetime
from collections import defaultdict

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PDF_PATH = os.path.join(BASE_DIR, "Catalog", "catalog glassware.pdf")
DB_PATH = os.path.join(BASE_DIR, "database.xlsx")
OUT_DIR = os.path.join(BASE_DIR, "Catalog", "reference_images")

def normalize_sku(raw):
    """Clean SKU from Excel: handle dates, dash prefix, trailing *, whitespace."""
    if isinstance(raw, datetime.datetime):
        return raw.strftime("%Y-%m-%d")
    s = str(raw).strip()
    s = re.sub(r"^-\s*", "", s)
    s = s.rstrip("*")
    return s.strip()

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
sku_set = set(sku_db.keys())
print(f"Database SKUs: {len(sku_set)}")

os.makedirs(OUT_DIR, exist_ok=True)

doc = fitz.open(PDF_PATH)
image_sku_map = defaultdict(set)  # (bbox_tuple, page_idx) -> set of skus
skus_found_total = set()

for page_idx in range(doc.page_count):
    page = doc[page_idx]
    blocks = page.get_text("blocks")
    full_text = page.get_text()

    # Find ALL sku positions by scanning each block's individual words
    sku_positions = []  # (sku, y_center)
    for b in blocks:
        x0, y0, x1, y1, text = b[0], b[1], b[2], b[3], b[4]
        # Split block text into words/tokens
        tokens = re.findall(r'\S+', text)
        for token in tokens:
            token = token.strip().strip('.,;:!?"\'()[]')
            if token in sku_set:
                sku_cy = (y0 + y1) / 2
                sku_positions.append((token, sku_cy))

    # Build set of already-found SKUs
    found_here = {s[0] for s in sku_positions}

    # Also search the full text for any SKU not caught by token split
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

    # Dedup SKU positions (keep first occurrence)
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
        # Filter out very small images (likely icons/decorations)
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
            # Image is considered "above" SKU if its bottom is near or above SKU
            if img["cy"] < sku_cy:
                best = img
            else:
                break
        if best is None:
            best = images[0]

        bk = (round(best["bbox"].x0, 1), round(best["bbox"].y0, 1),
              round(best["bbox"].x1, 1), round(best["bbox"].y1, 1))
        image_sku_map[(bk, page_idx)].add(sku)
        skus_found_total.add(sku)

unmapped = sku_set - skus_found_total
print(f"SKUs mapped: {len(skus_found_total)} / {len(sku_set)}")
print(f"Unmapped: {len(unmapped)}")
print(f"Unique image regions: {len(image_sku_map)}")
if unmapped:
    print(f"\nSample unmapped: {sorted(unmapped)[:20]}")

# Save images
extracted = 0
for (bk, page_idx), skus in sorted(image_sku_map.items()):
    safe_skus = [s.replace("/", "-").replace("\\", "-") for s in skus]
    x0, y0, x1, y1 = bk
    clip = fitz.Rect(x0, y0, x1, y1)
    mat = fitz.Matrix(3, 3)
    page = doc[page_idx]
    pix = page.get_pixmap(matrix=mat, clip=clip)

    for safe_sku in safe_skus:
        out_path = os.path.join(OUT_DIR, f"{safe_sku}.jpg")
        pix.save(out_path)
        extracted += 1

print(f"\nTotal images saved: {extracted}")
doc.close()
