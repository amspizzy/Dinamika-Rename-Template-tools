"""
Local AI backend via Ollama (Qwen VL, LLaVA, dll) buat analisa visual
glassware + compare gambar.

Requires:
    - Ollama running (https://ollama.com)
    - Model vision di-pull (contoh: ollama pull qwen3-vl:8b)
"""

import base64
import json
import re
from io import BytesIO

import requests
from PIL import Image, ImageOps


def _image_to_base64(image_path: str, max_dim: int = 1600, quality: int = 80) -> str:
    img = ImageOps.exif_transpose(Image.open(image_path)).convert("RGB")
    w, h = img.size
    if max(w, h) > max_dim:
        scale = max_dim / max(w, h)
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def analyze_image(image_path: str, base_url: str, model: str) -> dict:
    b64 = _image_to_base64(image_path)

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

    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": prompt,
                "images": [b64],
            }
        ],
        "format": "json",
        "stream": False,
    }

    try:
        resp = requests.post(
            f"{base_url.rstrip('/')}/api/chat", json=payload, timeout=120
        )
        resp.raise_for_status()
    except Exception as e:
        return {
            "extracted_text": "",
            "brand": None,
            "size": None,
            "category_guess": "",
            "visual_description": "",
            "_error": str(e),
        }

    raw = resp.json().get("message", {}).get("content", "")
    raw = re.sub(r"^```json|```$", "", raw.strip(), flags=re.MULTILINE).strip()

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {
            "extracted_text": raw,
            "brand": None,
            "size": None,
            "category_guess": "",
            "visual_description": raw,
        }


def compare_images(
    input_path: str, reference_paths: list[str], base_url: str, model: str
) -> int:
    b64 = _image_to_base64(input_path, max_dim=800, quality=70)

    ref_images = []
    for rp in reference_paths[:5]:
        try:
            ref_images.append(_image_to_base64(rp, max_dim=400, quality=60))
        except Exception:
            continue

    if not ref_images:
        return -1

    ref_labels = [f"Foto {i+1}" for i in range(len(ref_images))]

    prompt = (
        f"Saya punya foto produk glassware laboratorium (foto pertama). "
        f"Ada {len(ref_images)} foto referensi: {', '.join(ref_labels)}.\n\n"
        f" mana dari {', '.join(ref_labels)} yang menunjukkan produk SAMA "
        f"dengan foto pertama? Balas HANYA dengan nomor foto, misal: 2"
    )

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt, "images": [b64] + ref_images}],
        "stream": False,
    }

    try:
        resp = requests.post(
            f"{base_url.rstrip('/')}/api/chat", json=payload, timeout=120
        )
        resp.raise_for_status()
        data = resp.json()
        raw = data.get("message", {}).get("content", "")
        m = re.search(r"\d+", raw)
        if m:
            idx = int(m.group()) - 1
            if 0 <= idx < len(reference_paths):
                return idx
    except Exception:
        pass
    return -1
