import os

import match_and_rename as mr
import generate_svg as gs


def test_normalize_size_handles_ml_liter_and_empty():
    assert mr.normalize_size("Beaker 500 ml") == "500 ml"
    assert mr.normalize_size("Bottle 1 L") == "1000 ml"
    assert mr.normalize_size("No size") is None
    assert mr.normalize_size("") is None


def test_unique_dest_path_adds_suffix_when_file_exists(tmp_path):
    folder = tmp_path / "out"
    folder.mkdir()
    existing = folder / "SKU.jpg"
    existing.write_bytes(b"x")

    assert mr.unique_dest_path(str(folder), "SKU.jpg") == os.path.join(str(folder), "SKU_2.jpg")


def test_mark_primary_photo_chooses_highest_score_per_sku():
    rows = [
        ["a.jpg", "SKU1", "desc", 60, "OK", "{}", "a-out.jpg", ""],
        ["b.jpg", "SKU1", "desc", 80, "OK", "{}", "b-out.jpg", ""],
        ["c.jpg", "SKU2", "desc", 70, "OK", "{}", "c-out.jpg", ""],
        ["d.jpg", "SKU3", "desc", 90, "REVIEW", "{}", "d-out.jpg", ""],
    ]

    mr.mark_primary_photo(rows)

    assert rows[0][7] == "no"
    assert rows[1][7] == "yes"
    assert rows[2][7] == "yes"
    assert rows[3][7] == ""


def test_match_to_database_uses_size_brand_and_keywords():
    db_rows = [
        {
            "sku": "BK100",
            "description": "Beaker Low Form, 100 ml",
            "brand": "Iwaki",
            "category": "Beaker",
            "size": "100 ml",
            "ocr_keywords": "iwaki 100 ml beaker",
            "vision_keywords": "clear glass cylindrical beaker with spout",
        },
        {
            "sku": "BT500",
            "description": "Bottle Reagent, 500 ml",
            "brand": "Duran",
            "category": "Bottle",
            "size": "500 ml",
            "ocr_keywords": "duran 500 ml bottle",
            "vision_keywords": "amber glass reagent bottle screw cap",
        },
    ]
    ai_result = {
        "extracted_text": "IWAKI 100 ml",
        "brand": "Iwaki",
        "size": "100 ml",
        "category_guess": "beaker",
        "visual_description": "clear glass cylindrical beaker with spout",
    }

    row, score = mr.match_to_database(ai_result, db_rows)

    assert row["sku"] == "BK100"
    assert score >= 55


def test_dedupe_primary_rows_keeps_highest_score_per_sku():
    rows = [
        {"matched_sku": "SKU1", "score": "60", "final_path": "a.jpg"},
        {"matched_sku": "SKU1", "score": "90", "final_path": "b.jpg"},
        {"matched_sku": "SKU2", "score": "70", "final_path": "c.jpg"},
    ]

    deduped = gs.dedupe_primary_rows(rows)

    assert {r["matched_sku"] for r in deduped} == {"SKU1", "SKU2"}
    assert next(r for r in deduped if r["matched_sku"] == "SKU1")["final_path"] == "b.jpg"
