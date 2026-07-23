# Dinamika Auto-Rename & Template Tool

Tools ini otomatis:
1. **Scan & cocokkan** foto glassware ke SKU di database — pakai AI vision (Gemini cloud), hybrid lokal (EasyOCR + Qwen via Ollama), atau EasyOCR offline
2. **Rename & pindah** foto ke folder sesuai kategori
3. **Generate** kartu produk (SVG + JPG) siap upload ke toko online — foto di-crop otomatis ke objek, di-center, dikasih rounded corners, dan nama produk ditulis otomatis di template

Tiga backend AI bisa dipilih dari sidebar:
- **☁️ Gemini (cloud)** — satu API call Gemini buat OCR + vision analysis. Cepat, akurat, butuh internet.
- **💻 Local (EasyOCR + Qwen)** — EasyOCR buat baca teks, Qwen `qwen3-vl:8b` via Ollama buat analisa visual (bentuk, brand, kategori). 100% offline, tanpa limit, tapi lebih lambat.
- **📷 EasyOCR (OCR Only)** — 100% offline OCR + fuzzy match ke database. Tanpa analisa visual, tanpa Qwen. Paling cepat dan ringan.

## Fitur

| Fitur | Detail |
|-------|--------|
| **Matching 4-tier** | Filename/SKU match → AI OCR/vision → Visual hash → AI compare (kalau ambigu) |
| **Tiga backend AI** | Gemini cloud (cepat), Local EasyOCR+Qwen (100% offline), atau EasyOCR-only (tanpa Qwen) |
| **Auto-crop** | GrabCut buat crop objek utama, buang background berlebih |
| **Rounded corners** | Otomatis dikasih sudut melengkung di foto produk |
| **EXIF rotation** | Betulin otomatis foto yang kebalik dari HP |
| **HEIC support** | Bisa langsung proses foto format HEIC dari iPhone |
| **Multi-angle** | Foto multi-angle disimpan semua, foto skor tertinggi jadi primary |
| **Visual hash cache** | Hash perceptual disimpan biar foto mirip bisa match tanpa AI call |
| **Reassign manual** | Foto skor rendah bisa di-reassign ke SKU yang benar dari GUI |
| **Archive** | Backup output lama dengan timestamp |
| **CLI + GUI** | Bisa pakai terminal atau web browser |

## Persiapan (sekali saja)

### 1. Install dependencies

```bash
pip install -r requirements.txt
playwright install chromium
```

Baris kedua download browser headless (~200MB, sekali aja) yang dipakai buat merender SVG jadi JPG.

### 2. Gemini API Key (gratis)

Buat di https://aistudio.google.com/apikey — login pakai akun Google, tanpa kartu kredit.

Bisa diset lewat environment variable atau langsung dari sidebar GUI:
```bash
export GEMINI_API_KEY="xxxxxxxx"
```

> Free tier Gemini: ~1500 request/hari untuk `gemini-3.5-flash`. Cukup untuk pemakaian normal.

### 3. Ollama (hanya kalau pakai Local backend)

```bash
# Install Ollama: https://ollama.com
# Pull model vision:
ollama pull qwen3-vl:8b
```

Alternatif model ringan: `qwen3-vl:2b` (lebih cepat, akurasi sedikit kurang).

## Alur kerja

```
┌─────────────────────────────────────────────────┐
│  STEP 1: Upload Foto                            │
│                                                 │
│  Taruh foto ke input/incoming/                  │
│  (atau upload lewat browser di tab 1)           │
└───────────────────┬─────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────────┐
│  STEP 2: Scan & Cocokkan (Tab 1)                │
│                                                 │
│  Klik "Scan & Cocokkan Semua Foto"              │
│                                                 │
│  Untuk tiap foto:                               │
│  ┌───────────────────────────────────────┐      │
│  │ Tier 1: Filename match                │      │
│  │ → Cek nama file ada SKU?              │      │
│  │ → Ya: langsung OK, skip AI            │      │
│  │ → Tidak: lanjut ke Tier 2             │      │
│  └───────────────┬───────────────────────┘      │
│                  ▼                              │
│  ┌───────────────────────────────────────┐      │
 │  │ Tier 2a: OCR — baca teks di foto      │      │
 │  │ → Gemini cloud: jadi 1 dgn Tier 2b   │      │
 │  │ → Local backend: EasyOCR (offline)    │      │
 │  │ → EasyOCR-only mode: selesai di sini  │      │
│  └───────────────┬───────────────────────┘      │
│                  ▼                              │
│  ┌───────────────────────────────────────┐      │
│  │ Tier 2b: Vision — analisa visual      │      │
│  │ → Gemini cloud: Gemini vision full    │      │
│  │ → Local backend: Qwen via Ollama      │      │
│  │   (lokal, 30-60 detik/foto)           │      │
│  │ → Output: brand, size, category,      │      │
│  │   visual_description                  │      │
│  └───────────────┬───────────────────────┘      │
│                  ▼                              │
│  ┌───────────────────────────────────────┐      │
│  │ match_to_database()                   │      │
│  │ → Fuzzy match OCR + vision ke DB     │      │
│  │ → Score 0-130 (6 komponen)           │      │
│  └───────────────┬───────────────────────┘      │
│                  ▼                              │
│  ┌───────────────────────────────────────┐      │
│  │ Tier 3: Visual Hash Match            │      │
│  │ → Perceptual hash vs cache            │      │
│  │ → Bonus score kalau match             │      │
│  └───────────────┬───────────────────────┘      │
│                  ▼                              │
│  ┌───────────────────────────────────────┐      │
│  │ Tier 4: AI Compare                   │      │
│  │ → Kalau top 2 kandidat score mepet   │      │
│  │ → Gemini/Qwen pilih yang paling mirip│      │
│  └───────────────┬───────────────────────┘      │
└───────────────────┬─────────────────────────────┘
                    │
          ┌─────────┴─────────┐
          ▼                   ▼
    ┌──────────┐        ┌──────────┐
    │ Score ≥55│        │ Score <55│
    │   (OK)   │        │ (REVIEW) │
    └────┬─────┘        └────┬─────┘
         │                   │
         ▼                   ▼
┌─────────────────┐  ┌────────────────────┐
│ Foto pindah ke  │  │ Foto pindah ke     │
│ output/renamed/ │  │ output/renamed/    │
│ <kategori>/...  │  │ _perlu_review/     │
│                 │  │                    │
│ Hash disimpan   │  │                    │
│ ke cache JSON   │  │                    │
└────────┬────────┘  └────────┬───────────┘
         │                    │
         ▼                    ▼
┌─────────────────────────────────────────────────┐
│  Report disimpan:                               │
│  output/reports/match_report.csv                │
│                                                 │
│  Semua foto tercatat (OK + REVIEW + ERROR)       │
│  Tiap SKU: foto dengan score tertinggi           │
│  ditandai primary=yes                           │
└───────────────────┬─────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────────┐
│  STEP 3: Reassign Manual (Tab 1, kalau perlu)   │
│                                                 │
│  Foto REVIEW muncul di tabel + preview           │
│  Pilih SKU manual dari dropdown                 │
│  Klik "Terapkan Reassign"                       │
│  → Status jadi OK, siap generate                │
│  → File dihapus dari _perlu_review/             │
└───────────────────┬─────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────────┐
│  STEP 4: Generate Template (Tab 2)              │
│                                                 │
│  Mode "Generate semua" atau "Generate baru aja"  │
│  Klik "Generate"                                │
│                                                 │
│  Untuk tiap produk primary=yes:                 │
│  1. Foto auto-crop ke objek (GrabCut)           │
│  2. Foto di-embed ke template SVG               │
│  3. Foto dikasih rounded corners                │
│  4. Judul/nama produk diganti otomatis           │
│     (path vector judul lama DIHAPUS,             │
│      diganti teks baru pakai Poppins Bold)      │
│  5. SVG disimpan: output/svg/<SKU>.svg           │
│                                                 │
│  Lalu semua SVG di-render ke JPG:               │
│  6. JPG disimpan: output/jpg/<SKU>.jpg           │
│  (siap upload ke marketplace)                    │
└───────────────────┬─────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────────┐
│  STEP 5: Download (Tab 2)                       │
│                                                 │
│  Lihat galeri hasil di browser                  │
│  Download satuan (.jpg) atau semua (.zip)        │
└─────────────────────────────────────────────────┘
```

**Foto berpindah di disk:**
```
input/incoming/  →  output/renamed/<folder>/<SKU>.jpg  (kalau OK, langsung pindah)
                 →  output/renamed/_perlu_review/       (kalau REVIEW, langsung pindah)
                 →  input/review/                       (kalau ERROR: file corrupt/kosong/API gagal)
```

Foto asli tidak pernah dihapus, hanya dipindah. File hanya ada di **satu tempat** — tidak ada duplikat.

## Cara pakai

### GUI (web browser) — direkomendasikan

```bash
.venv/bin/streamlit run app.py
```

Akses dari HP (satu WiFi):
```bash
.venv/bin/streamlit run app.py --server.address 0.0.0.0
```
Lalu buka `http://<IP-KOMPUTER>:8501` dari HP.

1. Upload foto lewat browser (Tab 1) atau taruh manual di `input/incoming/`
2. Pilih backend AI di sidebar (Gemini cloud / Local / EasyOCR-only)
3. Isi Gemini API Key di sidebar (wajib hanya untuk mode Gemini cloud)
4. Klik **"Scan & Cocokkan Semua Foto"**
5. Kalau ada foto REVIEW, reassign manual ke SKU yang benar
6. Generate template di Tab 2 → download JPG atau ZIP

### CLI (terminal)

```bash
# Scan & cocokkan
python match_and_rename.py

# Generate template (jalanin setelah scan selesai)
python generate_svg.py
```

## Backend AI

| Mode | OCR | Vision | Kecepatan | Internet | Biaya |
|------|-----|--------|-----------|----------|-------|
| **☁️ Gemini (cloud)** | Gemini (1 API call) | Gemini (sama 1 call) | ~5 detik/foto | Wajib | Gratis (1500/hari) |
| **💻 Local (EasyOCR + Qwen)** | EasyOCR (offline) | Qwen `qwen3-vl:8b` via Ollama | ~30-60 detik/foto | Tidak perlu | Gratis (tanpa limit) |
| **📷 EasyOCR (OCR Only)** | EasyOCR (offline) | — (fuzzy match saja) | ~3-5 detik/foto | Tidak perlu | Gratis (tanpa limit) |

### Mode Gemini (cloud)
Satu request Gemini vision → dapat OCR + brand + size + category + visual description. Cepat, akurat, recommended kalau ada internet.

### Mode Local (EasyOCR + Qwen)
Hybrid:
1. **EasyOCR** dikirim foto → dapat extracted_text (offline, 1-3 detik)
2. **Qwen `qwen3-vl:8b`** via Ollama → analisa bentuk, brand, size, category, visual description (lokal, 30-60 detik)
3. Hasil OCR dari EasyOCR digabung dengan vision dari Qwen → match ke database

### Mode EasyOCR (OCR Only)
100% offline OCR tanpa AI vision:
1. **EasyOCR** baca teks dari foto (1-3 detik)
2. **Fuzzy match** OCR text langsung ke database SKU
3. Tanpa API call, tanpa Qwen, tanpa GPU — paling ringan dan cepat.

## Matching detail

### Tier 1: Filename Match (0 API call)
Kalau nama file mengandung SKU (misal `NESSLER100S C.jpg` → `NESSLER100S`):
- Hapus trailing suffix: `_2`, `_3` (multi-angle), ` A`, ` B`, ` C` (angle indicator)
- Cari exact match di database → score 100, langsung OK
- Kalau ga ada, fuzzy match (>85) → score mengikuti fuzzy
- **Zero API call** — sangat cepat

### Tier 2: AI OCR + Vision
**Mode Gemini cloud:** Satu request Gemini vision → JSON berisi extracted_text, brand, size, category_guess, visual_description.

**Mode Local:** Dua tahap:
- **EasyOCR**: foto diproses offline → string teks (1-3 detik)
- **Qwen vision**: foto dikirim ke Qwen via Ollama → JSON brand, size, category, visual_description (lokal)

**Mode EasyOCR (OCR Only):** Satu tahap:
- **EasyOCR** baca teks → fuzzy match langsung ke database. Tanpa vision.

Keduanya lalu di-fuzzy match ke database dengan 6 komponen scoring + SKU direct auto-match:

| Komponen | Bobot | Contoh |
|----------|-------|--------|
| Size exact match | +35 | "500 ml" cocok persis |
| Brand fuzzy match | 0–20 | "Iwaki" vs "iwaki" → 20 |
| Text/keyword fuzzy | 0–25 | OCR + vision keywords vs DB |
| Category match | +10 | sama-sama "beaker" |
| Category mismatch | –35 | "beaker" vs "bottle" |
| Ref visual bonus | 0–20 | pHash match vs Catalog/reference_images/ |

### Tier 3: Visual Hash Match (0 API call)
- Perceptual hash (pHash) dihitung untuk setiap foto
- Dibandingkan vs semua hash di cache (`output/renamed/image_hashes.json`)
- Kalau Hamming distance < 12 → bonus +0–20 poin
- **Zero API call** — sangat cepat
- Satu SKU bisa punya banyak hash (multi-angle)

### Tier 4: AI Compare (1 API call, hanya jika ambigu)
- Trigger kalau top 2 kandidat score beda < 15 poin (`VISUAL_AMBIGUITY_GAP`)
- Kirim foto baru + hingga 5 foto referensi ke AI
- Gemini/Qwen pilih mana yang paling mirip
- **1 API call** — akurat untuk kasus ambiguous

### SKU Auto-Match: Direct Match (0 API call)
- Sebelum scoring, semua token dari `extracted_text` dibandingkan ke SKU database
- Kalau **exact match** 1 SKU → langsung score 100, OK tanpa scoring
- Contoh: OCR baca "1000BK10" → token `1000BK10` cocok SKU di DB → auto 100
- **Zero API call** — override seluruh scoring

### Brand/Category OCR Fallback
- Kalau AI vision (Gemini/Qwen) balikin brand/category null/empty
- Dicek dari OCR text: cari nama brand kategori database di extracted_text
- Contoh: OCR "500 ml Iwaki beaker" → brand="iwaki", category="beaker"

### Score formula
```
total_score = size_exact (0/35)
            + brand_fuzzy (0–20)
            + text_fuzzy (0–25)
            + category_match (0/10) atau mismatch (-35)
            + visual_hash_bonus (0–20)     ← dari hasil scan sebelumnya
            + ref_visual_bonus (0–20)      ← dari Catalog/reference_images/ (PDF katalog)
max = 130, praktis max ~110
```
Atau **SKU Auto-Match**: kalau extracted_text mengandung SKU database (exact token match) → **score 100**, skip seluruh scoring.
**Score ≥ 55 → OK** | **Score < 55 → REVIEW**

## GUI (web app)

Jalankan dengan `.venv/bin/streamlit run app.py`.

### Sidebar
- **AI Backend** — pilih Gemini cloud / Local EasyOCR+Qwen / EasyOCR-only
- **Gemini API Key** — isi & simpan (hanya untuk mode Gemini cloud)
- **Model Gemini** — pilih model (hanya di mode cloud)
- **Ollama URL** — alamat Ollama server (hanya di mode local)
- **Model Vision** — nama model Ollama (hanya di mode local)
- **Bahasa OCR** — pilih bahasa untuk EasyOCR (en, id, dll) (mode local & easyocr-only)
- **Gunakan GPU** — centang untuk akselerasi GPU/CUDA (mode local & easyocr-only)
- **Folder & reset** — bersihkan SVG/JPG, reset scan, archive output
- **Posisi & gaya judul** — atur font size, posisi X/Y judul di template
- **Jeda antar foto** — atur delay antar scan (naikkan kalau kena rate limit Gemini)

### Tab 1: Scan & Cocokkan Foto
- Upload foto (JPG/PNG/HEIC/WEBP)
- Lihat preview foto yang menunggu
- Progress bar + status tiap foto
- Tabel hasil match (OK / REVIEW / ERROR)
- Reassign manual untuk foto REVIEW

### Tab 2: Generate Template
- Pilih mode: generate semua atau hanya yang baru
- Generate SVG + render ke JPG (via Playwright)
- Galeri hasil + download satuan atau ZIP semua

## Konfigurasi

Semua pengaturan ada di `config.py`. Bisa juga diubah dari sidebar GUI (nilai dari sidebar override config.py saat runtime).

### Matching weights
```python
SIZE_EXACT_BONUS = 35       # bonus untuk size exact match
BRAND_WEIGHT = 20           # max score dari brand fuzzy match
TEXT_MATCH_WEIGHT = 25      # max score dari text/keyword fuzzy match
VISUAL_HASH_WEIGHT = 20     # max score dari visual hash match (cache hasil scan)
CATEGORY_MATCH_BONUS = 10   # bonus kalau category cocok
CATEGORY_MISMATCH_PENALTY = 35 # penalty kalau category beda
REF_VISUAL_WEIGHT = 20      # max score dari visual match vs Catalog/reference_images/
SKU_MATCH_MIN_LEN = 5       # minimal panjang SKU (karakter) untuk direct match auto-OK
MIN_MATCH_SCORE = 55        # threshold OK vs REVIEW
```

### Visual similarity
```python
HASH_DISTANCE_THRESHOLD = 12    # max hamming distance (0-64)
VISUAL_AMBIGUITY_GAP = 15       # selisih score top1 vs top2 → trigger compare (15 = cukup mepet baru compare)
```

### Image processing
```python
IMAGE_BORDER_RADIUS = 15    # px corner radius (0 = sharp/tajam)
CANVAS_WIDTH = 810          # lebar template
CANVAS_HEIGHT = 810         # tinggi template
JPG_QUALITY = 90            # kualitas JPEG output
```

### Judul template
```python
TITLE_BASE_FONT_SIZE = 28   # ukuran font asli desain
TITLE_MIN_FONT_SIZE = 16    # minimal kalau nama kepanjangan
TITLE_CENTER_X = 405        # posisi X tengah
TITLE_BASELINE_Y = 728.4    # posisi Y baseline
TITLE_MAX_WIDTH = 740       # lebar maks teks
TITLE_COLOR = "#ffffff"     # warna putih
```

## Struktur folder

```
dinamika_tool/
├── config.py              <- pengaturan (path, threshold, matching weights)
├── match_and_rename.py    <- step 1: scan AI + rename + visual hash
├── generate_svg.py        <- step 2: tempel foto ke template + rounded corners
├── easyocr_ocr.py         <- EasyOCR wrapper (offline OCR, reader di-cache)
├── extract_pdf_images.py  <- Extract gambar produk dari PDF katalog ke Catalog/reference_images/
├── local_ai.py            <- Local AI backend (Qwen via Ollama)
├── app.py                 <- GUI web (Streamlit)
├── database.xlsx          <- database SKU (Excel)
├── Tamplate.svg           <- template Canva
├── fonts/
│   └── Poppins-Bold.ttf   <- font untuk judul produk
├── Catalog/
│   ├── reference_images/  <- foto referensi untuk AI visual compare
│   └── catalog glassware.pdf
├── requirements.txt       <- Python dependencies
├── .app_settings.json     <- settings tersimpan dari sidebar
├── .gemini_key            <- API key tersimpan (kalau disimpan dari sidebar)
├── tests/
│   └── test_match_and_rename.py
├── input/
│   ├── incoming/          <- taruh/upload foto baru di sini
│   ├── done/              <- foto asli yang sudah OK
│   └── review/            <- foto error/corrupt/API gagal
└── output/
    ├── renamed/
    │   ├── <kategori>/<SKU>.jpg  (+ _2.jpg dst kalau multi-angle)
    │   ├── _perlu_review/       <- skor rendah, cek manual
    │   └── image_hashes.json    <- cache perceptual hash
    ├── reports/
    │   └── match_report.csv     <- laporan hasil scan
    ├── svg/<SKU>.svg            <- master, editable di Canva
    ├── jpg/<SKU>.jpg            <- siap upload toko online
    └── archives/<tanggal>/      <- backup output lama
```

## Testing

```bash
.venv/bin/python -m pytest
```

Test cepat tanpa memanggil API AI — hanya uji fungsi lokal (normalize_size, unique_dest_path, mark_primary_photo, match_to_database, dedupe_primary_rows).

## Extract gambar dari PDF katalog

Gunakan `Catalog/catalog glassware.pdf` sebagai sumber foto referensi untuk
AI Compare (Tier 4). Script ini otomatis mencocokkan SKU dari database ke
gambar di PDF dan mengekstraknya ke `Catalog/reference_images/`:

```bash
.venv/bin/python extract_pdf_images.py
```

Hasil: ~93% SKU berhasil dipetakan. Sisanya fallback ke `output/renamed/`.
Jalanin ulang kalau ada SKU baru atau ganti PDF katalog.

## Dependencies

```
google-genai              <- Gemini AI vision
openpyxl                  <- Excel database
rapidfuzz                 <- Fuzzy string matching
pillow                    <- Image I/O + manipulation
pillow-heif               <- HEIC support (iPhone photos)
opencv-python-headless    <- Auto-crop (GrabCut)
numpy                     <- Array math
imagehash                 <- Perceptual hashing
playwright                <- Browser automation (SVG → JPG)
lxml                      <- SVG/XML manipulation
streamlit                 <- Web UI
pandas                    <- Data manipulation
requests                  <- Ollama API calls
easyocr                   <- Offline OCR (mode local & easyocr-only)
pytest                    <- Testing
```
