"""
Konfigurasi tool Dinamika Auto-rename.
Ubah nilai di bawah sesuai kebutuhan kamu.
"""
import os

# ---- PATH ----
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE_XLSX = os.path.join(BASE_DIR, "database.xlsx")   # file excel database SKU
TEMPLATE_SVG = os.path.join(BASE_DIR, "Tamplate.svg")     # template Canva/SVG
CATALOG_REF_DIR = os.path.join(BASE_DIR, "Catalog", "reference_images") # gambar katalog
INPUT_ROOT = os.path.join(BASE_DIR, "input")
INPUT_DIR = os.path.join(INPUT_ROOT, "incoming")            # taruh/upload foto baru di sini
INPUT_DONE_DIR = os.path.join(INPUT_ROOT, "done")           # foto asli yang sudah OK
INPUT_REVIEW_DIR = os.path.join(INPUT_ROOT, "review")       # foto asli yang perlu dicek
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
RENAMED_DIR = os.path.join(OUTPUT_DIR, "renamed")           # hasil rename
SVG_OUTPUT_DIR = os.path.join(OUTPUT_DIR, "svg")            # hasil svg per produk (master, editable)
JPG_OUTPUT_DIR = os.path.join(OUTPUT_DIR, "jpg")            # hasil jpg per produk (siap upload toko online)
REPORT_DIR = os.path.join(OUTPUT_DIR, "reports")
REPORT_CSV = os.path.join(REPORT_DIR, "match_report.csv")
ARCHIVE_DIR = os.path.join(OUTPUT_DIR, "archives")

# ---- CANVAS ----
CANVAS_WIDTH = 810   # samain dengan viewBox Tamplate.svg
CANVAS_HEIGHT = 810
JPG_QUALITY = 90

# ---- EXCEL SHEET & KOLOM ----
SHEET_NAME = "Price List"       # nama sheet di database.xlsx
HEADER_ROW = 2                  # baris ke berapa headernya (1-indexed): SKU, Description, Brand, Category, Size, OCR Keywords, Vision Keywords, Template, Output Folder, Active

# ---- AI VISION (Gemini API - GRATIS, rate limited) ----
# Set API key di environment variable GEMINI_API_KEY (JANGAN ditulis langsung di sini)
# Buat key gratis di: https://aistudio.google.com/apikey (tanpa kartu kredit)
GEMINI_MODEL = "gemini-3.5-flash"
GEMINI_MODEL_OPTIONS = [
    "gemini-3.5-flash",
    "gemini-3.5-flash-lite",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.0-flash",
]
# Free tier saat ini ±10 request/menit (Google beberapa kali motong kuota
# gratis sejak akhir 2025) -> jeda 6.5 detik = ±9 request/menit, masih ada
# sedikit margin aman. Kalau masih sering kena rate limit, naikkan lagi.

# ---- AI BACKEND ----
# Pilihan backend: "gemini" (cloud), "local" (Gemini OCR + Qwen via Ollama),
# atau "easyocr" (100% offline, EasyOCR + fuzzy match ke database)
AI_BACKEND_OPTIONS = ["gemini", "local", "easyocr"]
AI_BACKEND = "easyocr"

# ---- LOCAL AI (Ollama) ----
OLLAMA_BASE_URL = "http://localhost:11434"
OLLAMA_MODEL = "qwen3-vl:2b"
OLLAMA_MODEL_OPTIONS = [
    "qwen3-vl:2b",
    "qwen3-vl:8b",
    "llava:7b",
    "llava:13b",
    "moondream",
    "minicpm-v",
    "gemma3:4b",
    "gemma3:12b",
]

# ---- EASYOCR (Mode 100% offline) ----
EASYOCR_LANGUAGES = ["en"]
EASYOCR_GPU = True

# ---- SCAN ----
SCAN_DELAY_SECONDS = 6.5

# ---- MATCHING ----
MIN_MATCH_SCORE = 55            # skor minimum (0-100) biar dianggap "match". Di bawah ini -> masuk folder review manual
BRAND_WEIGHT = 20
SIZE_EXACT_BONUS = 35
TEXT_MATCH_WEIGHT = 25
VISUAL_HASH_WEIGHT = 20        # skor dari visual similarity (perceptual hash)
CATEGORY_MATCH_BONUS = 10      # bonus kalau AI category_guess cocok sama database category
CATEGORY_MISMATCH_PENALTY = 35 # penalty besar kalau AI category_guess GA cocok
REF_VISUAL_WEIGHT = 20         # skor dari visual similarity vs Catalog/reference_images/ (gambar katalog)
SKU_MATCH_MIN_LEN = 4         # minimal panjang SKU (karakter) untuk direct match auto-OK

# ---- VISUAL SIMILARITY ----
IMAGE_HASH_CACHE = os.path.join(OUTPUT_DIR, "renamed", "image_hashes.json")
HASH_DISTANCE_THRESHOLD = 12    # max hamming distance untuk dianggap match (0-64, makin kecil makin strict)
VISUAL_AMBIGUITY_GAP = 15       # kalau selisih skor top1 vs top2 < 15, AI compare jalan. >15 skip, irit 1 call per foto.

# ---- SVG OUTPUT: judul (nama produk) ----
# Judul asli di Tamplate.svg berupa vector path hasil export Canva (bukan teks
# yang bisa diedit). Tool ini otomatis MENGHAPUS path judul lama & MENGGANTI
# dengan teks baru (bukan nambah label baru di atasnya), pakai font persis
# yang sama (Poppins Bold) biar nyatu sama desain asli.
TITLE_FONT_PATH = os.path.join(BASE_DIR, "fonts", "Poppins-Bold.ttf")
TITLE_FONT_FAMILY = "Poppins"
TITLE_FONT_WEIGHT = 700
TITLE_BASE_FONT_SIZE = 28       # ukuran asli di desain Canva
TITLE_MIN_FONT_SIZE = 16        # batas paling kecil kalau nama produk kepanjangan
TITLE_COLOR = "#ffffff"
TITLE_CENTER_X = 405            # tengah horizontal canvas (viewBox 810 lebar)
TITLE_BASELINE_Y = 728.4        # baseline vertikal, sama persis posisi judul asli
TITLE_MAX_WIDTH = 740           # lebar maksimum teks (canvas 810 dikurangi margin kiri-kanan)

# ---- IMAGE ROUNDED CORNERS ----
IMAGE_BORDER_RADIUS = 15        # px corner radius untuk gambar produk (0 = sharp)
