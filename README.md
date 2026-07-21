# Glassware Auto-Rename & Template Tool

Tools ini otomatis:
1. Baca foto glassware pakai AI vision (Gemini, GRATIS) — baca teks yang terukir/tercetak di gelas DAN kenali bentuknya kalau nggak ada teks.
2. Cocokkan ke SKU di `database.xlsx` (kolom SKU, Brand, Size, OCR Keywords, Vision Keywords, dll).
3. Rename & pindah foto ke folder sesuai `Output Folder` di database.
4. Tempel foto yang sudah di-rename ke template SVG (`Tamplate.svg`) + kasih label SKU/nama otomatis. Sebelum ditempel, foto **otomatis dibetulkan orientasinya (kalau kebalik dari HP), di-crop pas ke objeknya (buang background berlebih), di-center** ke frame template, dan dikasih **rounded corners**.

> **Matching 4-tier**: Tools ini pakai 4 metode bertingkat biar akurat:
> 1. **Filename match** — kalau nama file udah ada SKU, langsung cocok (zero API call)
> 2. **AI OCR/vision** — Gemini baca teks + bentuk, fuzzy match ke database
> 3. **Visual hash** — perceptual hash dibandingin vs foto yang udah pernah di-match
> 4. **Gemini compare** — kalau score 2 kandidat mepet, Gemini pilih yang paling mirip

## Persiapan (sekali saja)

```bash
pip install -r requirements.txt
playwright install chromium
```
Baris kedua download browser headless (~200MB, sekali aja) yang dipakai buat merender SVG jadi JPG dengan akurat (template Canva ini pakai banyak efek/mask yang cuma bisa dirender benar pakai browser beneran).

Kamu juga butuh **Gemini API key gratis** (buat di https://aistudio.google.com/apikey — tinggal login pakai akun Google, tanpa kartu kredit), lalu set sebagai environment variable:

```bash
# Mac/Linux
export GEMINI_API_KEY="xxxxxxxx"

# Windows PowerShell
$env:GEMINI_API_KEY="xxxxxxxx"
```

> Free tier Gemini dibatasi ~20 request/hari per model. Script ini pakai filename match + visual hash buat **hemat quota** — foto yang udah ada SKU di nama atau udah pernah di-match, ga perlu AI call.

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
│  │ → Ya: langsung OK, skip AI           │      │
│  │ → Tidak: lanjut ke Tier 2            │      │
│  └───────────────┬───────────────────────┘      │
│                  ▼                              │
│  ┌───────────────────────────────────────┐      │
│  │ Tier 2: AI OCR/Brand/Size            │      │
│  │ → Gemini baca teks + bentuk           │      │
│  │ → Fuzzy match ke database             │      │
│  │ → Score 0-100                         │      │
│  └───────────────┬───────────────────────┘      │
│                  ▼                              │
│  ┌───────────────────────────────────────┐      │
│  │ Tier 3: Visual Hash Match            │      │
│  │ → Perceptual hash vs cache            │      │
│  │ → Bonus score kalau match             │      │
│  └───────────────┬───────────────────────┘      │
│                  ▼                              │
│  ┌───────────────────────────────────────┐      │
│  │ Tier 4: Gemini Compare               │      │
│  │ → Kalau top 2 kandidat score mepet    │      │
│  │ → Gemini pilih yang paling mirip      │      │
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
│ /Glassware/...  │  │ /_perlu_review/    │
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

Foto asli tidak pernah dihapus, hanya dipindah. Sekarang file hanya ada di **satu tempat** — tidak ada duplikat antara `input/done/` dan `output/renamed/`.

## Cara pakai

1. Taruh semua foto mentah yang mau di-scan ke folder `input/incoming/`
2. Jalankan GUI:
   ```bash
   .venv/bin/streamlit run app.py
   ```
   Atau lewat command line:
   ```bash
   python match_and_rename.py
   ```
3. Scan & cocokkan foto di tab 1 (GUI) atau otomatis (CLI)
4. Reassign foto REVIEW kalau perlu (pilih SKU manual)
5. Generate SVG + JPG di tab 2 (GUI) atau jalankan:
   ```bash
   python generate_svg.py
   ```
6. Download hasil dari tab 2 atau ambil langsung dari `output/jpg/`

## Matching detail

### Tier 1: Filename Match
Kalau nama file mengandung SKU (misal `NESSLER100S C.jpg` → `NESSLER100S`):
- Hapus trailing suffix: `_2`, `_3` (multi-angle), ` A`, ` B`, ` C` (angle indicator)
- Cari exact match di database → score 100
- Kalau ga ada, fuzzy match (>85) → score mengikuti fuzzy
- **Zero API call** — sangat cepat

### Tier 2: AI OCR/Brand/Size Match
- Gemini vision baca teks + bentuk dari foto
- 3 sinyal dihitung:
  - **Size exact match**: +35 poin
  - **Brand fuzzy match**: +0-20 poin
  - **Text/keyword fuzzy match**: +0-25 poin

### Tier 3: Visual Hash Match
- Perceptual hash (pHash) dihitung untuk setiap foto
- Dibandingkan vs semua hash di cache (`output/renamed/image_hashes.json`)
- Kalau Hamming distance < 12 → bonus +0-20 poin
- **Zero API call** — sangat cepat

### Tier 4: Gemini Visual Compare
- Trigger kalau top 2 kandidat score beda < 10 poin
- Kirim foto + 2-3 foto referensi ke Gemini
- Gemini pilih mana yang paling mirip
- **1 API call** — akurat untuk kasus ambiguous

### Score formula
```
total_score = size_bonus (0-35) + brand_score (0-20) + text_score (0-25) + visual_hash_bonus (0-20)
max = 100
```
Score ≥ 55 → OK | Score < 55 → REVIEW

## Struktur folder

```
glassware_tool/
├── config.py              <- pengaturan (path, threshold, posisi judul, matching weights)
├── match_and_rename.py    <- step 1: scan AI + rename + visual hash
├── generate_svg.py        <- step 2: tempel ke template + rounded corners
├── app.py                 <- GUI web (Streamlit)
├── database.xlsx          <- database 817+ SKU
├── Tamplate.svg           <- template Canva
├── fonts/Poppins-Bold.ttf <- font untuk judul
├── requirements.txt       <- dependencies
├── input/
│   ├── incoming/          <- taruh/upload foto baru di sini
│   ├── done/              <- (legacy) foto asli yang sudah cocok OK
│   └── review/            <- foto asli yang error/corrupt/API gagal
└── output/
    ├── renamed/
    │   ├── <kategori>/<SKU>.jpg (+ SKU_2.jpg dst kalau multi-angle)
    │   ├── _perlu_review/   <- skor rendah, cek manual
    │   └── image_hashes.json <- cache visual hash untuk matching
    ├── reports/match_report.csv
    ├── svg/<SKU>.svg            <- master, editable di Canva
    ├── jpg/<SKU>.jpg            <- siap upload ke toko online
    └── archives/<tanggal>/      <- backup output lama dari tombol Archive output
```

## Konfigurasi

### Matching weights (`config.py`)
```python
SIZE_EXACT_BONUS = 35       # bonus untuk size exact match
BRAND_WEIGHT = 20           # max score dari brand fuzzy match
TEXT_MATCH_WEIGHT = 25      # max score dari text/keyword fuzzy match
VISUAL_HASH_WEIGHT = 20     # max score dari visual hash match
MIN_MATCH_SCORE = 55        # threshold untuk OK vs REVIEW
```

### Visual similarity (`config.py`)
```python
IMAGE_HASH_CACHE = "output/renamed/image_hashes.json"
HASH_DISTANCE_THRESHOLD = 12    # max hamming distance untuk match (0-64)
VISUAL_AMBIGUITY_GAP = 10       # selisih score top1 vs top2 → trigger Gemini compare
```

### Image rounded corners (`config.py`)
```python
IMAGE_BORDER_RADIUS = 15    # px corner radius (0 = sharp/tajam)
```

### Judul template (`config.py`)
```python
TITLE_BASE_FONT_SIZE = 28
TITLE_MIN_FONT_SIZE = 16
TITLE_COLOR = "#ffffff"
TITLE_CENTER_X = 405
TITLE_BASELINE_Y = 728.4
TITLE_MAX_WIDTH = 740
```

## GUI (web app lokal)

Selain lewat command line, sekarang ada juga tampilan GUI berbasis browser:

```bash
.venv/bin/streamlit run app.py
```

Ini otomatis buka tab browser baru berisi dashboard buat:
- Upload foto & scan/cocokkan (tab 1) — progress & tabel hasil kelihatan langsung
- Generate SVG + JPG (tab 2) — galeri hasil + tombol download satuan/semua (.zip)
- Bersihkan hasil generate, reset scan, atau archive output lama dari sidebar `Folder & reset`

API key Gemini bisa diisi & disimpan langsung dari sidebar (nggak perlu `export` manual tiap buka terminal baru).
Model Gemini juga bisa dipilih dari sidebar. Kalau scan gagal karena model tidak tersedia untuk API key kamu, coba ganti ke model lain dari dropdown itu.

## Testing

Jalankan test cepat tanpa memanggil API Gemini:

```bash
.venv/bin/python -m pytest
```

## Dependencies

```
google-genai       <- Gemini AI vision
openpyxl           <- Excel database
rapidfuzz          <- Fuzzy string matching
pillow             <- Image I/O + manipulation
pillow-heif        <- HEIC support
opencv-python-headless <- Auto-crop (GrabCut)
numpy              <- Array math
imagehash          <- Perceptual hashing (visual similarity)
playwright         <- Browser automation (SVG → JPG)
lxml               <- SVG/XML manipulation
streamlit          <- Web UI
pandas             <- Data manipulation
pytest             <- Testing
```
