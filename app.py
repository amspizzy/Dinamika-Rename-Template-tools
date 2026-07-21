"""
GUI (web app lokal) buat tools Dinamika Auto-rename & Template.

Cara jalanin:
    .venv/bin/streamlit run app.py

Ini cuma "pembungkus" tampilan buat match_and_rename.py + generate_svg.py,
logic aslinya tetap sama, jadi kalau mau otak-atik cara kerja AI matching /
generate SVG, tetap edit di file-file itu seperti biasa.
"""

import io
import os
import time
import zipfile
import shutil
import csv
import json

from rapidfuzz import fuzz

import pandas as pd
import streamlit as st
from PIL import Image
from pillow_heif import register_heif_opener

import config

register_heif_opener()

st.set_page_config(page_title="Dinamika Auto-rename & Template", layout="wide")

KEY_FILE = os.path.join(config.BASE_DIR, ".gemini_key")
SETTINGS_FILE = os.path.join(config.BASE_DIR, ".app_settings.json")


def load_app_settings():
    if not os.path.exists(SETTINGS_FILE):
        return {}
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_app_settings(settings):
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2)


def load_saved_api_key():
    if os.path.exists(KEY_FILE):
        with open(KEY_FILE, encoding="utf-8") as f:
            key = f.read().strip()
        if key:
            os.environ["GEMINI_API_KEY"] = key
            return key
    return os.environ.get("GEMINI_API_KEY", "")


def ensure_work_dirs():
    for folder in [
        config.INPUT_DIR,
        config.INPUT_DONE_DIR,
        config.INPUT_REVIEW_DIR,
        config.RENAMED_DIR,
        config.SVG_OUTPUT_DIR,
        config.JPG_OUTPUT_DIR,
        config.REPORT_DIR,
        config.ARCHIVE_DIR,
    ]:
        os.makedirs(folder, exist_ok=True)


def archive_current_output():
    stamp = time.strftime("%Y%m%d_%H%M%S")
    archive_root = os.path.join(config.ARCHIVE_DIR, stamp)
    os.makedirs(archive_root, exist_ok=True)
    moved = 0
    for folder in [config.RENAMED_DIR, config.SVG_OUTPUT_DIR, config.JPG_OUTPUT_DIR, config.REPORT_DIR]:
        if os.path.exists(folder) and os.listdir(folder):
            shutil.move(folder, os.path.join(archive_root, os.path.basename(folder)))
            moved += 1
    ensure_work_dirs()
    return archive_root, moved


ensure_work_dirs()


# ---------------------------------------------------------------- sidebar --
st.sidebar.title("⚙️ Pengaturan")

saved_key = load_saved_api_key()
app_settings = load_app_settings()
api_key_input = st.sidebar.text_input(
    "Gemini API Key", value=saved_key, type="password",
    help="Buat gratis di https://aistudio.google.com/apikey",
)
if st.sidebar.button("Simpan API Key"):
    with open(KEY_FILE, "w", encoding="utf-8") as f:
        f.write(api_key_input.strip())
    os.environ["GEMINI_API_KEY"] = api_key_input.strip()
    st.sidebar.success("Tersimpan.")

gemini_model_options = getattr(config, "GEMINI_MODEL_OPTIONS", [config.GEMINI_MODEL])
saved_model = app_settings.get("gemini_model", config.GEMINI_MODEL)
if saved_model not in gemini_model_options:
    saved_model = config.GEMINI_MODEL
selected_model = st.sidebar.selectbox(
    "Model Gemini",
    options=gemini_model_options,
    index=gemini_model_options.index(saved_model),
    help="Kalau scan gagal karena model tidak tersedia, coba pilih model lain.",
)
config.GEMINI_MODEL = selected_model
if selected_model != app_settings.get("gemini_model"):
    app_settings["gemini_model"] = selected_model
    save_app_settings(app_settings)

st.sidebar.divider()
st.sidebar.caption(f"Database: `{os.path.basename(config.DATABASE_XLSX)}`")
st.sidebar.caption(f"Template: `{os.path.basename(config.TEMPLATE_SVG)}`")

with st.sidebar.expander("Folder & reset"):
    st.caption("Foto baru masuk ke `input/incoming/`. Hasil akhir ada di `output/jpg/`.")
    if st.button("Bersihkan SVG/JPG"):
        for folder in [config.SVG_OUTPUT_DIR, config.JPG_OUTPUT_DIR]:
            if os.path.exists(folder):
                shutil.rmtree(folder)
        ensure_work_dirs()
        st.success("SVG/JPG lama dibersihkan.")
        st.rerun()
    if st.button("Reset scan"):
        for path in [config.RENAMED_DIR, config.REPORT_DIR]:
            if os.path.exists(path):
                shutil.rmtree(path)
        ensure_work_dirs()
        st.success("Report dan hasil rename dibersihkan.")
        st.rerun()
    if st.button("Archive output"):
        archive_root, moved = archive_current_output()
        if moved:
            st.success(f"Output lama dipindah ke `{archive_root}`.")
        else:
            st.info("Tidak ada output yang perlu di-archive.")
        st.rerun()

config.SCAN_DELAY_SECONDS = st.sidebar.number_input(
    "Jeda antar foto saat scan (detik)", value=float(config.SCAN_DELAY_SECONDS),
    min_value=1.0, step=0.5,
    help="Naikkan kalau sering kena 'rate limit' dari Gemini pas scan.",
)

with st.sidebar.expander("Posisi & gaya judul (lanjutan)"):
    st.caption(
        "Default-nya udah dicocokin sama desain Canva. Cuma ubah kalau "
        "kamu ganti template baru & posisinya jadi geser."
    )
    config.TITLE_BASE_FONT_SIZE = st.number_input(
        "Font size dasar", value=config.TITLE_BASE_FONT_SIZE, min_value=8, max_value=80)
    config.TITLE_BASELINE_Y = st.number_input(
        "Posisi Y (baseline)", value=float(config.TITLE_BASELINE_Y))
    config.TITLE_CENTER_X = st.number_input(
        "Posisi X (tengah)", value=float(config.TITLE_CENTER_X))

st.title("🧪 Dinamika Auto-rename & Template")

tab1, tab2 = st.tabs(["1️⃣ Scan & Cocokkan Foto", "2️⃣ Generate Template"])

# =============================================================== TAB 1 =====
with tab1:
    st.subheader("Upload foto produk")
    uploads = st.file_uploader(
        "Bisa pilih banyak foto sekaligus (JPG/PNG/HEIC/WEBP)",
        type=["jpg", "jpeg", "png", "webp", "heic", "bmp"],
        accept_multiple_files=True,
    )
    if uploads:
        for uf in uploads:
            dest = os.path.join(config.INPUT_DIR, uf.name)
            with open(dest, "wb") as f:
                f.write(uf.getbuffer())
        st.success(f"{len(uploads)} foto masuk ke folder `input/incoming/`.")

    VALID_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".heic"}
    existing = []
    if os.path.isdir(config.INPUT_DIR):
        existing = [f for f in os.listdir(config.INPUT_DIR)
                    if not f.startswith(".")
                    and os.path.isfile(os.path.join(config.INPUT_DIR, f))
                    and os.path.splitext(f)[1].lower() in VALID_EXT]

    already_ok = set()
    if os.path.exists(config.REPORT_CSV):
        with open(config.REPORT_CSV, encoding="utf-8") as _f:
            for _row in csv.DictReader(_f):
                if _row.get("status") == "OK":
                    already_ok.add(_row["original_filename"])

    new_files = [f for f in existing if f not in already_ok]

    st.caption(f"Total foto di `input/incoming/`: **{len(existing)}** "
               f"({len(already_ok)} sudah di-scan, **{len(new_files)}** baru)")
    if existing:
        with st.expander("Lihat foto yang menunggu di-scan"):
            cols = st.columns(6)
            for i, fname in enumerate(existing):
                try:
                    img = Image.open(os.path.join(config.INPUT_DIR, fname))
                    img.thumbnail((160, 160))
                    cols[i % 6].image(img, caption=fname, width='stretch')
                except Exception:
                    cols[i % 6].caption(fname)

    st.divider()

    disabled = not os.environ.get("GEMINI_API_KEY") or not new_files
    if not os.environ.get("GEMINI_API_KEY"):
        st.warning("Isi & simpan Gemini API Key dulu di sidebar kiri.")

    if st.button("🔍 Scan & Cocokkan Semua Foto", type="primary", disabled=disabled):
        if not new_files:
            st.info("Tidak ada foto baru yang perlu di-scan.")
            st.rerun()

        import match_and_rename as mr

        from google import genai

        client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        db_rows = mr.load_database()
        sku_set = {str(r["sku"]) for r in db_rows}
        hash_cache = mr.load_hash_cache()
        st.write(f"Database dimuat: **{len(db_rows)}** SKU aktif.")

        os.makedirs(os.path.dirname(config.REPORT_CSV), exist_ok=True)

        old_rows = []
        if os.path.exists(config.REPORT_CSV):
            with open(config.REPORT_CSV, encoding="utf-8") as _f:
                for _row in csv.DictReader(_f):
                    old_rows.append([
                        _row.get("original_filename", ""), _row.get("matched_sku", ""),
                        _row.get("description", ""), _row.get("score", 0),
                        _row.get("status", ""), _row.get("ai_raw", ""),
                        _row.get("final_path", ""), _row.get("primary", ""),
                    ])

        new_rows = []
        total = len(new_files)
        progress = st.progress(0.0)
        status_box = st.empty()

        for i, fname in enumerate(new_files):
            status_box.info(f"Menganalisa **{fname}** ...  ({i + 1}/{total})")
            path = os.path.join(config.INPUT_DIR, fname)

            if os.path.getsize(path) == 0:
                review_path = mr.unique_dest_path(config.INPUT_REVIEW_DIR, fname)
                shutil.move(path, review_path)
                new_rows.append([fname, "", "", 0, "ERROR", "File kosong", review_path, ""])
                progress.progress((i + 1) / total)
                continue
            try:
                Image.open(path).verify()
            except Exception:
                review_path = mr.unique_dest_path(config.INPUT_REVIEW_DIR, fname)
                shutil.move(path, review_path)
                new_rows.append([fname, "", "", 0, "ERROR", "File gambar corrupt/tidak valid", review_path, ""])
                progress.progress((i + 1) / total)
                continue

            fn_row, fn_score, fn_method = mr.extract_sku_from_filename(fname, db_rows, sku_set)
            ext = os.path.splitext(fname)[1] or ".jpg"

            if fn_row:
                row = fn_row
                score = fn_score
                status = "OK"
                sku = row["sku"]
                dest_folder = os.path.join(config.RENAMED_DIR, row["output_folder"])
                dest_path = mr.unique_dest_path(dest_folder, f"{sku}{ext}")
                shutil.move(path, dest_path)
                mr.add_to_hash_cache(hash_cache, str(sku), dest_path)
                ai_raw = json.dumps({"match_method": fn_method}, ensure_ascii=False)
            else:
                vh_sku, vh_score = mr.match_by_visual_hash(path, hash_cache)

                if i > 0:
                    time.sleep(config.SCAN_DELAY_SECONDS)
                try:
                    ai_result = mr.analyze_image_with_ai(client, path)
                except Exception as e:
                    review_path = mr.unique_dest_path(config.INPUT_REVIEW_DIR, fname)
                    shutil.move(path, review_path)
                    new_rows.append([fname, "", "", 0, "ERROR", str(e), review_path, ""])
                    progress.progress((i + 1) / total)
                    continue

                vh_bonus = vh_score if vh_sku else 0
                row, score = mr.match_to_database(ai_result, db_rows, vh_bonus, vh_sku)
                ai_raw = json.dumps(ai_result, ensure_ascii=False)

                sorted_candidates = []
                ai_category = (ai_result.get("category_guess") or "").lower().strip()
                for r in db_rows:
                    s = 0.0
                    size_norm = mr.normalize_size(ai_result.get("size") or ai_result.get("extracted_text", ""))
                    if size_norm and mr.normalize_size(r["size"]) == size_norm:
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
                    # category match / mismatch
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
                        ref_path = os.path.join(config.RENAMED_DIR, ts["output_folder"], f"{ts_sku}.jpg")
                        if os.path.exists(ref_path):
                            ref_paths.append(ref_path)
                    if ref_paths:
                        best_idx = mr.compare_with_gemini(client, path, ref_paths)
                        if best_idx >= 0:
                            chosen = top_skus[best_idx]
                            row = chosen
                            score = sorted_candidates[best_idx][1]

                if row and score >= config.MIN_MATCH_SCORE:
                    status = "OK"
                    sku = row["sku"]
                    dest_folder = os.path.join(config.RENAMED_DIR, row["output_folder"])
                    dest_path = mr.unique_dest_path(dest_folder, f"{sku}{ext}")
                    shutil.move(path, dest_path)
                    mr.add_to_hash_cache(hash_cache, str(sku), dest_path)
                else:
                    status = "REVIEW"
                    sku = row["sku"] if row else ""
                    dest_folder = os.path.join(config.RENAMED_DIR, "_perlu_review")
                    dest_path = mr.unique_dest_path(dest_folder, fname)
                    shutil.move(path, dest_path)

            new_rows.append([
                fname, sku, row["description"] if row else "", score, status,
                ai_raw, dest_path, "",
            ])
            progress.progress((i + 1) / total)

        mr.save_hash_cache(hash_cache)

        all_rows = old_rows + new_rows
        for row in all_rows:
            row[7] = ""
        mr.mark_primary_photo(all_rows)

        with open(config.REPORT_CSV, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["original_filename", "matched_sku", "description", "score",
                        "status", "ai_raw", "final_path", "primary"])
            w.writerows(all_rows)

        n_new_ok = sum(1 for r in new_rows if r[4] == "OK")
        n_new_review = sum(1 for r in new_rows if r[4] == "REVIEW")
        n_new_err = sum(1 for r in new_rows if r[4] == "ERROR")
        status_box.success(
            f"Selesai scan {total} foto baru. "
            f"OK: {n_new_ok} | Review: {n_new_review} | Error: {n_new_err} "
            f"(+ {len(old_rows)} hasil lama tetap tersimpan)"
        )
        st.rerun()

    if os.path.exists(config.REPORT_CSV):
        st.subheader("Hasil pencocokan terakhir")
        df = pd.read_csv(config.REPORT_CSV)
        n_ok = (df["status"] == "OK").sum()
        n_review = (df["status"] == "REVIEW").sum()
        n_err = (df["status"] == "ERROR").sum()
        c1, c2, c3 = st.columns(3)
        c1.metric("✅ Cocok (OK)", n_ok)
        c2.metric("⚠️ Perlu review", n_review)
        c3.metric("❌ Error", n_err)

        show_cols = ["original_filename", "matched_sku", "description", "score", "status", "primary"]
        st.dataframe(df[show_cols], width='stretch', hide_index=True)

        if n_review > 0:
            st.warning(
                f"{n_review} foto skornya rendah, tersimpan di "
                f"`output/renamed/_perlu_review/` — pilih SKU manual di bawah "
                f"biar bisa ikut generate template."
            )

            import match_and_rename as mr
            db_rows = mr.load_database()
            sku_options = {f"{r['sku']} — {r['description']}": r for r in db_rows}

            st.subheader("Reassign foto REVIEW ke SKU")
            review_df = df[df["status"] == "REVIEW"].reset_index(drop=True)
            selections = {}
            for idx, row in review_df.iterrows():
                fname = row["original_filename"]
                src_path = row.get("final_path", "")
                c1, c2 = st.columns([1, 3])
                with c1:
                    if src_path and os.path.exists(str(src_path)):
                        st.image(str(src_path), caption=fname, width=200)
                    else:
                        st.caption(fname)
                with c2:
                    label = st.selectbox(
                        f"Pilih SKU untuk **{fname}**",
                        options=["—"] + list(sku_options.keys()),
                        key=f"review_sku_{idx}",
                    )
                    selections[fname] = (label, src_path)

            if st.button("Terapkan Reassign", type="primary"):
                assigned = 0
                for fname, (label, src_path) in selections.items():
                    if label == "—" or not src_path or not os.path.exists(str(src_path)):
                        continue
                    chosen = sku_options[label]
                    sku = chosen["sku"]
                    ext = os.path.splitext(fname)[1] or ".jpg"
                    dest_folder = os.path.join(config.RENAMED_DIR, chosen["output_folder"])
                    dest_path = mr.unique_dest_path(dest_folder, f"{sku}{ext}")
                    shutil.copy2(str(src_path), dest_path)
                    os.remove(str(src_path))
                    new_primary = "yes" if not any(
                        r["matched_sku"] == sku and r["primary"] == "yes"
                        for _, r in df.iterrows()
                    ) else ""

                    df.loc[df["original_filename"] == fname, "matched_sku"] = sku
                    df.loc[df["original_filename"] == fname, "description"] = chosen["description"]
                    df.loc[df["original_filename"] == fname, "score"] = 100
                    df.loc[df["original_filename"] == fname, "status"] = "OK"
                    df.loc[df["original_filename"] == fname, "final_path"] = dest_path
                    df.loc[df["original_filename"] == fname, "primary"] = new_primary
                    assigned += 1

                if assigned > 0:
                    df.to_csv(config.REPORT_CSV, index=False)
                    st.success(f"{assigned} foto berhasil di-reassign ke SKU yang benar!")
                    st.rerun()
                else:
                    st.info("Tidak ada foto yang dipilih untuk di-reassign.")

# =============================================================== TAB 2 =====
with tab2:
    st.subheader("Generate SVG + JPG dari foto yang sudah dicocokkan")

    if not os.path.exists(config.REPORT_CSV):
        st.info("Scan foto dulu di tab pertama sebelum generate.")
    else:
        df = pd.read_csv(config.REPORT_CSV)
        ready_rows = df[(df["status"] == "OK") & (df["primary"] == "yes")]
        ready_rows = ready_rows.sort_values("score", ascending=False).drop_duplicates("matched_sku")

        def _file_exists(p):
            return os.path.exists(str(p)) if pd.notna(p) else False

        has_file = ready_rows["final_path"].apply(_file_exists)
        missing_count = len(has_file[~has_file])
        ready_rows = ready_rows[has_file]

        if missing_count > 0:
            st.warning(f"{missing_count} file foto tidak ditemukan di disk, dilewati.")
        st.caption(f"Produk siap di-generate: **{len(ready_rows)}**")

        existing_svgs = set()
        if os.path.isdir(config.SVG_OUTPUT_DIR):
            existing_svgs = {os.path.splitext(f)[0] for f in os.listdir(config.SVG_OUTPUT_DIR) if f.endswith(".svg")}

        new_skus = [r for _, r in ready_rows.iterrows() if r["matched_sku"] not in existing_svgs]

        gen_mode = st.radio(
            "Mode generate",
            ["🎨 Generate semua", "🆕 Generate baru aja"],
            horizontal=True,
            disabled=ready_rows.empty,
        )

        if st.button("Generate", type="primary", disabled=ready_rows.empty):
            import shutil
            import generate_svg as gs

            if gen_mode == "🎨 Generate semua":
                for d in [config.SVG_OUTPUT_DIR, config.JPG_OUTPUT_DIR]:
                    if os.path.exists(d):
                        shutil.rmtree(d)
                    os.makedirs(d, exist_ok=True)
                rows_to_gen = ready_rows.to_dict("records")
            else:
                os.makedirs(config.SVG_OUTPUT_DIR, exist_ok=True)
                os.makedirs(config.JPG_OUTPUT_DIR, exist_ok=True)
                rows_to_gen = new_skus

            if not rows_to_gen:
                st.info("Tidak ada produk baru yang perlu di-generate.")
                st.rerun()

            with open(config.TEMPLATE_SVG, encoding="utf-8") as f:
                template_content = f.read()
            template_content = gs.strip_original_title(template_content)
            template_content = gs.embed_title_font(template_content)

            progress = st.progress(0.0)
            status_box = st.empty()
            for i, r in enumerate(rows_to_gen):
                status_box.info(f"Generate **{r['matched_sku']}** ... ({i + 1}/{len(rows_to_gen)})")
                found = r.get("final_path")
                if not found or not os.path.exists(found):
                    progress.progress((i + 1) / len(rows_to_gen))
                    continue
                out_path = os.path.join(config.SVG_OUTPUT_DIR, f"{r['matched_sku']}.svg")
                try:
                    gs.generate_one(template_content, found, r["matched_sku"], r["description"], "", out_path)
                except Exception as e:
                    st.error(f"Gagal generate {r['matched_sku']}: {e}")
                progress.progress((i + 1) / len(rows_to_gen))

            status_box.info("Merender ke JPG (siap upload toko online)...")
            gs.rasterize_svg_folder_to_jpg(config.SVG_OUTPUT_DIR, config.JPG_OUTPUT_DIR)
            status_box.success(f"Selesai generate {len(rows_to_gen)} produk.")
            st.rerun()

        jpg_files = []
        if os.path.isdir(config.JPG_OUTPUT_DIR):
            jpg_files = sorted(f for f in os.listdir(config.JPG_OUTPUT_DIR) if f.lower().endswith(".jpg"))

        if jpg_files:
            st.divider()
            st.subheader(f"Hasil ({len(jpg_files)} gambar) — siap upload ke toko online")

            zip_buf = io.BytesIO()
            with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
                for fname in jpg_files:
                    zf.write(os.path.join(config.JPG_OUTPUT_DIR, fname), fname)
            st.download_button(
                "⬇️ Download semua (.zip)", data=zip_buf.getvalue(),
                file_name="hasil_jpg.zip", mime="application/zip",
            )

            cols = st.columns(4)
            for i, fname in enumerate(jpg_files):
                path = os.path.join(config.JPG_OUTPUT_DIR, fname)
                with cols[i % 4]:
                    st.image(path, caption=fname, width='stretch')
                    with open(path, "rb") as f:
                        st.download_button("Download", f.read(), file_name=fname,
                                            mime="image/jpeg", key=f"dl_{fname}")
