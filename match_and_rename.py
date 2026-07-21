"""
STEP 1: Scan foto pakai AI vision (Gemini), cocokkan ke SKU di database.xlsx,
lalu copy+rename file ke folder output/renamed/<Output Folder>/<SKU>.<ext>

Cara pakai:
    1. Taruh foto-foto mentah di folder input/incoming/
    2. export GEMINI_API_KEY="xxxxxxxx"   (di terminal, sebelum run)
       Buat key gratis di https://aistudio.google.com/apikey
    3. python match_and_rename.py
    4. Cek hasil di output/reports/match_report.csv -> baris dengan status "REVIEW"
       artinya AI kurang yakin, cek manual.
"""

import os
import re
import csv
import json
import base64
import shutil
import sys
import time
from io import BytesIO

import openpyxl
from PIL import Image, ImageOps
from pillow_heif import register_heif_opener
from rapidfuzz import fuzz
from google import genai
from google.genai import types

import config

register_heif_opener()


def load_database():
    wb = openpyxl.load_workbook(config.DATABASE_XLSX, data_only=True)
    ws = wb[config.SHEET_NAME]
    rows = []
    for row in ws.iter_rows(min_row=config.HEADER_ROW + 1, values_only=True):
        if row[0] is None:
            continue
        rows.append({
            "sku": row[0],
            "description": row[1] or "",
            "brand": row[2] or "",
            "category": row[3] or "",
            "size": row[4] or "",
            "ocr_keywords": row[5] or "",
            "vision_keywords": row[6] or "",
            "template": row[7] or "",
            "output_folder": row[8] or "misc",
            "active": row[9],
        })
    return [r for r in rows if r["active"] in (True, 1, "TRUE", "True", None)]


def normalize_size(text):
    """Ambil angka+satuan volume dari teks, dinormalisasi jadi 'X ml'."""
    if not text:
        return None
    text = str(text).lower().replace(",", "")
    m = re.search(r"(\d+(?:\.\d+)?)\s*(ml|l|liter)\b", text)
    if not m:
        return None
    num, unit = m.group(1), m.group(2)
    num = float(num)
    if unit in ("l", "liter"):
        num *= 1000
    if num == int(num):
        num = int(num)
    return f"{num} ml"


def compress_image(image_path, max_dim=1600, quality=80):
    """Resize + kompres gambar sebelum kirim ke API. Balikin (bytes, media_type)."""
    img = ImageOps.exif_transpose(Image.open(image_path)).convert("RGB")
    w, h = img.size
    if max(w, h) > max_dim:
        scale = max_dim / max(w, h)
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return buf.getvalue(), "image/jpeg"


def analyze_image_with_ai(client, image_path):
    """Kirim gambar ke Gemini vision, minta balikin JSON terstruktur.
    Ada retry otomatis untuk semua jenis error (rate limit, network, dll)."""
    img_bytes, media_type = compress_image(image_path)

    prompt = (
        "Kamu sedang menganalisa foto alat gelas laboratorium (glassware) untuk "
        "dicocokkan ke katalog produk. Baca SEMUA teks yang tercetak/terukir di "
        "gambar (merk, ukuran ml, kode) dan amati bentuk visualnya (beaker, "
        "erlenmeyer, botol reagen, labu, dll).\n\n"
        "Balas HANYA dengan JSON valid, tanpa markdown, tanpa penjelasan lain, format:\n"
        '{"extracted_text": "semua teks yang terlihat di gambar, apa adanya", '
        '"brand": "nama merk jika terbaca, atau null", '
        '"size": "ukuran dengan satuan jika terbaca, misal \'500 ml\', atau null", '
        '"category_guess": "jenis alat gelas, misal beaker/erlenmeyer/bottle/flask/dropper/dst", '
        '"visual_description": "deskripsi singkat bentuk & warna dalam bahasa Inggris untuk keperluan pencocokan katalog"}'
    )

    max_retries = 3
    for attempt in range(max_retries):
        try:
            resp = client.models.generate_content(
                model=config.GEMINI_MODEL,
                contents=[
                    types.Part.from_bytes(data=img_bytes, mime_type=media_type),
                    prompt,
                ],
            )
            raw = (resp.text or "").strip()
            raw = re.sub(r"^```json|```$", "", raw.strip(), flags=re.MULTILINE).strip()
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                return {"extracted_text": raw, "brand": None, "size": None,
                         "category_guess": "", "visual_description": raw}
        except Exception as e:
            if attempt < max_retries - 1:
                wait = 2 ** attempt * 3  # 3, 6 detik
                print(f"  error: {e}, retry {attempt + 1}/{max_retries} dalam {wait}s...")
                time.sleep(wait)
                continue
            raise
    raise RuntimeError("Gagal setelah beberapa kali retry.")


def match_to_database(ai_result, db_rows, visual_hash_bonus=0, visual_hash_sku=None):
    """Cocokkan hasil analisa AI ke baris database, kembalikan (row, score, method).
    visual_hash_bonus = tambahan score dari visual hash match.
    visual_hash_sku = SKU dari visual hash match."""
    size_norm = normalize_size(ai_result.get("size") or ai_result.get("extracted_text", ""))
    brand_guess = (ai_result.get("brand") or "").lower()
    ai_category = (ai_result.get("category_guess") or "").lower().strip()
    text_blob = " ".join(filter(None, [
        ai_result.get("category_guess", ""),
        ai_result.get("visual_description", ""),
        ai_result.get("extracted_text", ""),
    ])).lower()

    best_row, best_score = None, -1
    for row in db_rows:
        score = 0.0
        # 1) ukuran exact match -> bobot besar
        if size_norm and normalize_size(row["size"]) == size_norm:
            score += config.SIZE_EXACT_BONUS
        # 2) brand fuzzy
        if brand_guess and row["brand"]:
            score += (fuzz.partial_ratio(brand_guess, row["brand"].lower()) / 100) * config.BRAND_WEIGHT
        # 3) kecocokan teks/vision keywords
        candidates_text = f"{row['vision_keywords']} {row['ocr_keywords']} {row['description']} {row['category']}".lower()
        score += (fuzz.token_set_ratio(text_blob, candidates_text) / 100) * config.TEXT_MATCH_WEIGHT
        # 4) category match / mismatch penalty
        db_category = (row.get("category") or "").lower().strip()
        if ai_category and db_category:
            cat_ratio = fuzz.ratio(ai_category, db_category)
            if cat_ratio >= 80:
                score += config.CATEGORY_MATCH_BONUS
            elif cat_ratio < 40:
                score -= config.CATEGORY_MISMATCH_PENALTY
        # 5) visual hash bonus (capped to VISUAL_HASH_WEIGHT)
        if visual_hash_sku and str(row["sku"]) == str(visual_hash_sku):
            score += min(visual_hash_bonus, config.VISUAL_HASH_WEIGHT)

        if score > best_score:
            best_row, best_score = row, score

    return best_row, round(best_score, 1)


def extract_sku_from_filename(filename, db_rows, sku_set):
    """Coba extract SKU dari nama file.

    1. Strip extension
    2. Hapus trailing multi-angle: _2, _3, dll
    3. Hapus trailing single letter setelah spasi: ' C', ' A', ' B'
    4. Cari exact match di database
    5. Kalau ga ada, coba fuzzy match (>85)

    Return (row, score, method) atau (None, 0, None).
    """
    base = os.path.splitext(filename)[0]
    candidate = re.sub(r"_\d+$", "", base)
    candidate = re.sub(r"\s+[A-Z]$", "", candidate)
    candidate = candidate.strip()

    if not candidate:
        return None, 0, None

    if candidate in sku_set:
        for row in db_rows:
            if str(row["sku"]) == candidate:
                return row, 100, "filename_exact"

    best_row, best_score = None, -1
    for row in db_rows:
        sku_str = str(row["sku"])
        score = fuzz.ratio(candidate.lower(), sku_str.lower())
        if score > best_score:
            best_row, best_score = row, score

    if best_score >= 85:
        return best_row, round(best_score, 1), "filename_fuzzy"

    return None, 0, None


def unique_dest_path(folder, filename):
    os.makedirs(folder, exist_ok=True)
    dest = os.path.join(folder, filename)
    base, ext = os.path.splitext(filename)
    i = 2
    while os.path.exists(dest):
        dest = os.path.join(folder, f"{base}_{i}{ext}")
        i += 1
    return dest


def compute_image_hash(image_path):
    """Hitung perceptual hash (pHash) dari gambar. Return string hash."""
    import imagehash
    img = ImageOps.exif_transpose(Image.open(image_path)).convert("RGB")
    return str(imagehash.phash(img))


def load_hash_cache():
    """Load hash cache dari JSON file. Return dict {sku: hash_string}."""
    if not os.path.exists(config.IMAGE_HASH_CACHE):
        return {}
    try:
        with open(config.IMAGE_HASH_CACHE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def save_hash_cache(cache):
    """Simpan hash cache ke JSON file."""
    os.makedirs(os.path.dirname(config.IMAGE_HASH_CACHE), exist_ok=True)
    with open(config.IMAGE_HASH_CACHE, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2)


def match_by_visual_hash(image_path, hash_cache):
    """Bandingin foto baru sama semua hash di cache.
    Return (best_sku, best_score) atau (None, 0).
    Score = max(0, 100 - (distance * 100 / 64))."""
    import imagehash
    if not hash_cache:
        return None, 0

    input_hash = imagehash.hex_to_hash(compute_image_hash(image_path))
    best_sku, best_score = None, 0

    for sku, hash_str in hash_cache.items():
        try:
            cached_hash = imagehash.hex_to_hash(hash_str)
            distance = input_hash - cached_hash
            score = max(0, 100 - (distance * 100 / 64))
            if score > best_score:
                best_sku, best_score = sku, round(score, 1)
        except Exception:
            continue

    return best_sku, best_score


def add_to_hash_cache(hash_cache, sku, image_path):
    """Tambah hash ke cache. Satu SKU bisa punya beberapa hash (multi-angle)."""
    h = compute_image_hash(image_path)
    if sku in hash_cache:
        existing = hash_cache[sku]
        if isinstance(existing, list):
            if h not in existing:
                existing.append(h)
        else:
            hash_cache[sku] = [existing, h]
    else:
        hash_cache[sku] = h


def compare_with_gemini(client, input_path, reference_paths):
    """Kirim foto baru + foto referensi ke Gemini, minta pilih mana yang paling mirip.
    Return index (0-based) foto paling mirip, atau -1 kalau gagal."""
    img_bytes, media_type = compress_image(input_path, max_dim=800, quality=70)

    ref_parts = []
    for i, rp in enumerate(reference_paths[:5]):
        try:
            rb, rm = compress_image(rp, max_dim=400, quality=60)
            ref_parts.append(types.Part.from_bytes(data=rb, mime_type=rm))
        except Exception:
            continue

    if not ref_parts:
        return -1

    ref_labels = [f"Foto {i+1}" for i in range(len(ref_parts))]
    prompt = (
        f"Saya punya foto produk glassware laboratorium (foto pertama). "
        f"Ada {len(ref_parts)} foto referensi: {', '.join(ref_labels)}.\n\n"
        f" mana dari {', '.join(ref_labels)} yang menunjukkan produk SAMA "
        f"dengan foto pertama? Balas HANYA dengan nomor foto, misal: 2"
    )

    contents = [
        types.Part.from_bytes(data=img_bytes, mime_type=media_type),
        *ref_parts,
        prompt,
    ]

    try:
        resp = client.models.generate_content(
            model=config.GEMINI_MODEL,
            contents=contents,
        )
        raw = (resp.text or "").strip()
        m = re.search(r"\d+", raw)
        if m:
            idx = int(m.group()) - 1
            if 0 <= idx < len(reference_paths):
                return idx
    except Exception:
        pass
    return -1


def main():
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("ERROR: set dulu environment variable GEMINI_API_KEY sebelum jalanin script ini.")
        print("Buat API key gratis di: https://aistudio.google.com/apikey")
        print('Contoh (Mac/Linux): export GEMINI_API_KEY="xxxxxxxx"')
        print('Contoh (Windows PowerShell): $env:GEMINI_API_KEY="xxxxxxxx"')
        sys.exit(1)

    client = genai.Client(api_key=api_key)
    db_rows = load_database()
    print(f"Database dimuat: {len(db_rows)} SKU aktif.")

    os.makedirs(config.INPUT_DIR, exist_ok=True)
    os.makedirs(config.INPUT_DONE_DIR, exist_ok=True)
    os.makedirs(config.INPUT_REVIEW_DIR, exist_ok=True)

    VALID_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".heic"}
    image_files = [
        f for f in os.listdir(config.INPUT_DIR)
        if os.path.isfile(os.path.join(config.INPUT_DIR, f))
        and not f.startswith(".")
        and (os.path.splitext(f)[1].lower() in VALID_EXT or os.path.splitext(f)[1] == "")
    ]
    if not image_files:
        print(f"Tidak ada file di {config.INPUT_DIR}. Taruh foto dulu di situ.")
        return

    os.makedirs(os.path.dirname(config.REPORT_CSV), exist_ok=True)
    report_rows = []
    sku_set = {str(r["sku"]) for r in db_rows}
    hash_cache = load_hash_cache()

    for i, fname in enumerate(image_files):
        path = os.path.join(config.INPUT_DIR, fname)
        print(f"Menganalisa {fname} ...")

        if os.path.getsize(path) == 0:
            print(f"  skip: file kosong")
            review_path = unique_dest_path(config.INPUT_REVIEW_DIR, fname)
            shutil.move(path, review_path)
            report_rows.append([fname, "", "", 0, "ERROR", "File kosong", review_path, ""])
            continue
        try:
            Image.open(path).verify()
        except Exception:
            print(f"  skip: file gambar corrupt/tidak valid")
            review_path = unique_dest_path(config.INPUT_REVIEW_DIR, fname)
            shutil.move(path, review_path)
            report_rows.append([fname, "", "", 0, "ERROR", "File gambar corrupt/tidak valid", review_path, ""])
            continue

        fn_row, fn_score, fn_method = extract_sku_from_filename(fname, db_rows, sku_set)
        ext = os.path.splitext(fname)[1] or ".jpg"

        if fn_row:
            row = fn_row
            score = fn_score
            status = "OK"
            sku = row["sku"]
            dest_folder = os.path.join(config.RENAMED_DIR, row["output_folder"])
            dest_path = unique_dest_path(dest_folder, f"{sku}{ext}")
            shutil.move(path, dest_path)
            add_to_hash_cache(hash_cache, str(sku), dest_path)
            print(f"  -> {sku}  (filename match, score {score})  dipindah ke {dest_path}")
            ai_raw = json.dumps({"match_method": fn_method}, ensure_ascii=False)
        else:
            vh_sku, vh_score = match_by_visual_hash(path, hash_cache)

            if i > 0:
                time.sleep(config.SCAN_DELAY_SECONDS)
            try:
                ai_result = analyze_image_with_ai(client, path)
            except Exception as e:
                print(f"  gagal analisa AI: {e}")
                review_path = unique_dest_path(config.INPUT_REVIEW_DIR, fname)
                shutil.move(path, review_path)
                report_rows.append([fname, "", "", 0, "ERROR", str(e), review_path, ""])
                continue

            vh_bonus = vh_score if vh_sku else 0
            row, score = match_to_database(ai_result, db_rows, vh_bonus, vh_sku)
            ai_raw = json.dumps(ai_result, ensure_ascii=False)

            sorted_candidates = []
            ai_category = (ai_result.get("category_guess") or "").lower().strip()
            for r in db_rows:
                s = 0.0
                if size_norm := normalize_size(ai_result.get("size") or ai_result.get("extracted_text", "")):
                    if normalize_size(r["size"]) == size_norm:
                        s += config.SIZE_EXACT_BONUS
                brand_guess = (ai_result.get("brand") or "").lower()
                if brand_guess and r["brand"]:
                    s += (fuzz.partial_ratio(brand_guess, r["brand"].lower()) / 100) * config.BRAND_WEIGHT
                text_blob = " ".join(filter(None, [
                    ai_result.get("category_guess", ""),
                    ai_result.get("visual_description", ""),
                    ai_result.get("extracted_text", ""),
                ])).lower()
                candidates_text = f"{r['vision_keywords']} {r['ocr_keywords']} {r['description']} {r['category']}".lower()
                s += (fuzz.token_set_ratio(text_blob, candidates_text) / 100) * config.TEXT_MATCH_WEIGHT
                db_category = (r.get("category") or "").lower().strip()
                if ai_category and db_category:
                    cat_ratio = fuzz.ratio(ai_category, db_category)
                    if cat_ratio >= 80:
                        s += config.CATEGORY_MATCH_BONUS
                    elif cat_ratio < 40:
                        s -= config.CATEGORY_MISMATCH_PENALTY
                if vh_sku and str(r["sku"]) == str(vh_sku):
                    s += min(vh_bonus, config.VISUAL_HASH_WEIGHT)
                sorted_candidates.append((r, round(s, 1)))
            sorted_candidates.sort(key=lambda x: x[1], reverse=True)

            if (len(sorted_candidates) >= 2
                    and sorted_candidates[0][1] - sorted_candidates[1][1] < config.VISUAL_AMBIGUITY_GAP
                    and sorted_candidates[0][1] >= config.MIN_MATCH_SCORE):
                top_skus = [sorted_candidates[0][0], sorted_candidates[1][0]]
                ref_paths = []
                for ts in top_skus:
                    ts_sku = str(ts["sku"])
                    if ts_sku in hash_cache:
                        h = hash_cache[ts_sku]
                        if isinstance(h, list):
                            ref_paths.append(os.path.join(config.RENAMED_DIR, ts["output_folder"], f"{ts_sku}.jpg"))
                        else:
                            ref_paths.append(os.path.join(config.RENAMED_DIR, ts["output_folder"], f"{ts_sku}.jpg"))
                if ref_paths:
                    print(f"  -> ambiguity detected (top1={sorted_candidates[0][1]}, top2={sorted_candidates[1][1]}), Gemini compare...")
                    best_idx = compare_with_gemini(client, path, ref_paths)
                    if best_idx >= 0:
                        chosen = top_skus[best_idx]
                        row = chosen
                        score = sorted_candidates[best_idx][1]
                        print(f"  -> Gemini pilih: {chosen['sku']} (score {score})")

            if row and score >= config.MIN_MATCH_SCORE:
                status = "OK"
                sku = row["sku"]
                dest_folder = os.path.join(config.RENAMED_DIR, row["output_folder"])
                dest_path = unique_dest_path(dest_folder, f"{sku}{ext}")
                shutil.move(path, dest_path)
                add_to_hash_cache(hash_cache, str(sku), dest_path)
                print(f"  -> {sku}  (AI match, score {score})  dipindah ke {dest_path}")
            else:
                status = "REVIEW"
                sku = row["sku"] if row else ""
                dest_folder = os.path.join(config.RENAMED_DIR, "_perlu_review")
                dest_path = unique_dest_path(dest_folder, fname)
                shutil.move(path, dest_path)
                print(f"  -> skor rendah ({score}), masuk folder _perlu_review. Kandidat terdekat: {sku}")

        report_rows.append([
            fname, sku, row["description"] if row else "", score, status,
            ai_raw, dest_path, "",
        ])

    save_hash_cache(hash_cache)

    mark_primary_photo(report_rows)

    with open(config.REPORT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["original_filename", "matched_sku", "description", "score", "status",
                    "ai_raw", "final_path", "primary"])
        w.writerows(report_rows)

    print(f"\nSelesai. Laporan lengkap: {config.REPORT_CSV}")


def mark_primary_photo(report_rows):
    """Kalau 1 SKU punya beberapa foto (multi-angle, biasa buat upload toko
    online), semua foto TETAP disimpan apa adanya (SKU.jpg, SKU_2.jpg, dst).
    Yang ditandai di sini cuma mana yang jadi 'foto utama' (skor tertinggi)
    -> itu yang dipakai generate_svg.py buat bikin kartu produk/template."""
    from collections import defaultdict
    by_sku = defaultdict(list)
    for idx, row in enumerate(report_rows):
        fname, sku, desc, score, status, ai_raw, dest_path, primary = row
        if status == "OK" and sku:
            by_sku[sku].append(idx)

    for sku, indices in by_sku.items():
        best_idx = max(indices, key=lambda i: float(report_rows[i][3]))
        report_rows[best_idx][7] = "yes"
        for i in indices:
            if i != best_idx:
                report_rows[i][7] = "no"
        if len(indices) > 1:
            print(f"  SKU {sku}: {len(indices)} foto (multi-angle) disimpan semua, "
                  f"foto utama buat template = skor {report_rows[best_idx][3]}")


if __name__ == "__main__":
    main()
