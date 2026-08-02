import os
import sqlite3
from contextlib import closing
from typing import Dict, List

from flask import Flask, flash, g, redirect, render_template, request, url_for

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE = os.path.join(BASE_DIR, "data.db")

app = Flask(__name__)
app.config["SECRET_KEY"] = "bandarabbas-asphalt-secret"
app.config["DATABASE"] = DATABASE

REGIONS = ["منطقه یک", "منطقه دو", "منطقه سه", "منطقه چهار"]
DISTRICT_NAMES = ["ناحیه یک", "ناحیه دو", "ناحیه سه"]

CATEGORIES = {
    "execution": {
        "title": "رعایت مراحل اجرایی",
        "color": "#1f77b4",
        "items": [
            ("execution_1", "کاتر زنی"),
            ("execution_2", "غرقاب"),
            ("execution_3", "زیرسازی"),
            ("execution_4", "متراکم سازی زیرسازی با غلتک موتوری"),
            ("execution_5", "قیر پاشی"),
            ("execution_6", "روکش آسفالت"),
        ],
    },
    "equipment": {
        "title": "تجهیزات",
        "color": "#d62728",
        "items": [
            ("equipment_1", "کاتر"),
            ("equipment_2", "غلتک موتوری"),
            ("equipment_3", "غلتک دستی"),
            ("equipment_4", "ماله"),
            ("equipment_5", "مینی لودر"),
            ("equipment_6", "بیل پارویی"),
            ("equipment_7", "لوازم ایمنی و ترافیکی"),
        ],
    },
    "workforce": {
        "title": "نیروی اجرایی و نظارتی",
        "color": "#2ca02c",
        "items": [
            ("workforce_1", "کارگر ساده"),
            ("workforce_2", "آسفالت کار"),
            ("workforce_3", "کارگر کاتر زن"),
            ("workforce_4", "ناظر خدمات شهری"),
            ("workforce_5", "ناظر مقیم عمرانی"),
        ],
    },
}

CATEGORY_ORDER = list(CATEGORIES.keys())
ALL_ITEM_CODES = [code for cat in CATEGORIES.values() for code, _ in cat["items"]]
MAX_SCORE = len(ALL_ITEM_CODES) * 5


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(_error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = sqlite3.connect(app.config["DATABASE"])
    with closing(db.cursor()) as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS districts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                region_index INTEGER NOT NULL,
                district_index INTEGER NOT NULL,
                region_name TEXT NOT NULL,
                district_name TEXT NOT NULL,
                full_name TEXT UNIQUE NOT NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS scores (
                district_id INTEGER NOT NULL,
                item_code TEXT NOT NULL,
                score INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (district_id, item_code),
                FOREIGN KEY (district_id) REFERENCES districts(id)
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS tonnage (
                district_id INTEGER PRIMARY KEY,
                amount REAL NOT NULL DEFAULT 0,
                FOREIGN KEY (district_id) REFERENCES districts(id)
            )
            """
        )

        cur.execute("SELECT COUNT(*) AS c FROM districts")
        if cur.fetchone()[0] == 0:
            for region_index, region_name in enumerate(REGIONS, start=1):
                for district_index, district_name in enumerate(DISTRICT_NAMES, start=1):
                    full_name = f"{district_name} {region_name}"
                    cur.execute(
                        """
                        INSERT INTO districts (region_index, district_index, region_name, district_name, full_name)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (region_index, district_index, region_name, district_name, full_name),
                    )

        cur.execute("SELECT id FROM districts")
        district_ids = [row[0] for row in cur.fetchall()]
        for district_id in district_ids:
            for item_code in ALL_ITEM_CODES:
                cur.execute(
                    "INSERT OR IGNORE INTO scores (district_id, item_code, score) VALUES (?, ?, 0)",
                    (district_id, item_code),
                )
            cur.execute(
                "INSERT OR IGNORE INTO tonnage (district_id, amount) VALUES (?, 0)",
                (district_id,),
            )

    db.commit()
    db.close()


def category_scores_for_district(score_map: Dict[str, int]) -> Dict[str, float]:
    output = {}
    for cat_key, cat in CATEGORIES.items():
        item_codes = [code for code, _ in cat["items"]]
        total = sum(score_map.get(code, 0) for code in item_codes)
        output[cat_key] = (total / (len(item_codes) * 5)) * 100
    return output


def calculate_district_metrics(district_row, score_map: Dict[str, int], tonnage_amount: float):
    cat_scores = category_scores_for_district(score_map)
    overall = (sum(score_map.get(code, 0) for code in ALL_ITEM_CODES) / MAX_SCORE) * 100
    return {
        "id": district_row["id"],
        "region_index": district_row["region_index"],
        "region_name": district_row["region_name"],
        "district_index": district_row["district_index"],
        "district_name": district_row["district_name"],
        "full_name": district_row["full_name"],
        "scores": score_map,
        "category_scores": cat_scores,
        "overall": overall,
        "tonnage": tonnage_amount,
    }


def get_all_district_metrics() -> List[dict]:
    db = get_db()
    districts = db.execute(
        """
        SELECT d.*, COALESCE(t.amount, 0) AS tonnage
        FROM districts d
        LEFT JOIN tonnage t ON t.district_id = d.id
        ORDER BY d.region_index, d.district_index
        """
    ).fetchall()

    score_rows = db.execute("SELECT district_id, item_code, score FROM scores").fetchall()
    score_map_by_district: Dict[int, Dict[str, int]] = {}
    for row in score_rows:
        score_map_by_district.setdefault(row["district_id"], {})[row["item_code"]] = row["score"]

    output = []
    for district in districts:
        score_map = score_map_by_district.get(district["id"], {})
        output.append(calculate_district_metrics(district, score_map, district["tonnage"]))
    return output


def region_summary(all_districts: List[dict], region_index: int):
    region_districts = [d for d in all_districts if d["region_index"] == region_index]
    region_districts_sorted = sorted(region_districts, key=lambda x: x["overall"], reverse=True)
    region_name = REGIONS[region_index - 1]

    category_avg = {
        cat: sum(d["category_scores"][cat] for d in region_districts) / len(region_districts)
        for cat in CATEGORY_ORDER
    }
    overall_avg = sum(d["overall"] for d in region_districts) / len(region_districts)

    return {
        "region_index": region_index,
        "region_name": region_name,
        "districts": region_districts_sorted,
        "category_avg": category_avg,
        "overall_avg": overall_avg,
        "total_tonnage": sum(d["tonnage"] for d in region_districts),
    }


def all_regions_summary(all_districts: List[dict]):
    summaries = [region_summary(all_districts, idx) for idx in range(1, len(REGIONS) + 1)]
    return sorted(summaries, key=lambda x: x["overall_avg"], reverse=True)


def to_two(value: float) -> float:
    return round(value, 2)


@app.context_processor
def inject_globals():
    return {
        "regions": list(enumerate(REGIONS, start=1)),
        "category_order": CATEGORY_ORDER,
        "categories": CATEGORIES,
    }


@app.route("/")
def index():
    all_districts = get_all_district_metrics()
    ranked = sorted(all_districts, key=lambda x: x["overall"], reverse=True)
    return render_template("index.html", ranked=ranked[:5])


@app.route("/data-entry")
def data_entry():
    districts = get_all_district_metrics()
    return render_template("data_entry.html", districts=districts)


@app.route("/district/<int:district_id>", methods=["GET", "POST"])
def district_form(district_id: int):
    db = get_db()
    district = db.execute("SELECT * FROM districts WHERE id = ?", (district_id,)).fetchone()
    if not district:
        return "ناحیه پیدا نشد", 404

    if request.method == "POST":
        errors = []
        updated_scores = {}
        for code in ALL_ITEM_CODES:
            raw = request.form.get(code, "0").strip()
            try:
                value = int(raw)
            except ValueError:
                errors.append("تمام امتیازها باید عدد صحیح بین ۰ تا ۵ باشند.")
                continue
            if value < 0 or value > 5:
                errors.append("تمام امتیازها باید بین ۰ تا ۵ باشند.")
                continue
            updated_scores[code] = value

        tonnage_raw = request.form.get("tonnage", "0").strip()
        try:
            tonnage_value = float(tonnage_raw)
            if tonnage_value < 0:
                errors.append("تناژ نمی‌تواند منفی باشد.")
        except ValueError:
            errors.append("تناژ باید عددی باشد.")
            tonnage_value = 0.0

        if errors:
            for err in sorted(set(errors)):
                flash(err, "error")
        else:
            for code, value in updated_scores.items():
                db.execute(
                    "UPDATE scores SET score = ? WHERE district_id = ? AND item_code = ?",
                    (value, district_id, code),
                )
            db.execute(
                "UPDATE tonnage SET amount = ? WHERE district_id = ?",
                (tonnage_value, district_id),
            )
            db.commit()
            flash("اطلاعات با موفقیت ذخیره شد.", "success")
            return redirect(url_for("district_form", district_id=district_id))

    score_rows = db.execute(
        "SELECT item_code, score FROM scores WHERE district_id = ?", (district_id,)
    ).fetchall()
    score_map = {r["item_code"]: r["score"] for r in score_rows}
    tonnage_row = db.execute("SELECT amount FROM tonnage WHERE district_id = ?", (district_id,)).fetchone()
    tonnage_value = tonnage_row["amount"] if tonnage_row else 0

    district_metric = calculate_district_metrics(district, score_map, tonnage_value)

    return render_template(
        "district_form.html",
        district=district,
        score_map=score_map,
        tonnage_value=tonnage_value,
        district_metric=district_metric,
    )


@app.route("/region/<int:region_index>")
def region_dashboard(region_index: int):
    if region_index < 1 or region_index > len(REGIONS):
        return "منطقه نامعتبر است", 404

    summary = region_summary(get_all_district_metrics(), region_index)

    labels = [d["district_name"] for d in summary["districts"]]
    datasets = [
        {
            "label": CATEGORIES[cat]["title"],
            "backgroundColor": CATEGORIES[cat]["color"],
            "data": [to_two(d["category_scores"][cat]) for d in summary["districts"]],
        }
        for cat in CATEGORY_ORDER
    ]
    overall_data = [to_two(d["overall"]) for d in summary["districts"]]

    return render_template(
        "region_dashboard.html",
        summary=summary,
        labels=labels,
        datasets=datasets,
        overall_data=overall_data,
    )


@app.route("/regions-comparison")
def regions_comparison():
    summaries = all_regions_summary(get_all_district_metrics())
    labels = [s["region_name"] for s in summaries]
    datasets = [
        {
            "label": CATEGORIES[cat]["title"],
            "backgroundColor": CATEGORIES[cat]["color"],
            "data": [to_two(s["category_avg"][cat]) for s in summaries],
        }
        for cat in CATEGORY_ORDER
    ]
    overall = [to_two(s["overall_avg"]) for s in summaries]
    return render_template(
        "regions_comparison.html",
        summaries=summaries,
        labels=labels,
        datasets=datasets,
        overall=overall,
    )


@app.route("/tonnage")
def tonnage_dashboard():
    all_districts = get_all_district_metrics()
    region_charts = []
    for region_index, region_name in enumerate(REGIONS, start=1):
        region_districts = sorted(
            [d for d in all_districts if d["region_index"] == region_index],
            key=lambda x: x["tonnage"],
            reverse=True,
        )
        region_charts.append(
            {
                "region_name": region_name,
                "labels": [d["district_name"] for d in region_districts],
                "values": [to_two(d["tonnage"]) for d in region_districts],
                "rows": region_districts,
            }
        )

    region_totals = sorted(
        [
            {
                "region_name": r["region_name"],
                "value": to_two(r["total_tonnage"]),
            }
            for r in all_regions_summary(all_districts)
        ],
        key=lambda x: x["value"],
        reverse=True,
    )

    return render_template(
        "tonnage_dashboard.html",
        region_charts=region_charts,
        region_totals=region_totals,
    )


@app.route("/overall-comparison")
def overall_comparison():
    all_districts = get_all_district_metrics()

    charts = [
        {
            "title": "رتبه‌بندی کلی نواحی بر اساس مجموع امتیاز عملکردی",
            "suffix": "%",
            "labels": [d["full_name"] for d in sorted(all_districts, key=lambda x: x["overall"], reverse=True)],
            "values": [to_two(d["overall"]) for d in sorted(all_districts, key=lambda x: x["overall"], reverse=True)],
            "color": "#4e79a7",
            "rows": sorted(all_districts, key=lambda x: x["overall"], reverse=True),
            "metric": "overall",
        }
    ]

    for cat in CATEGORY_ORDER:
        ranked = sorted(all_districts, key=lambda x: x["category_scores"][cat], reverse=True)
        charts.append(
            {
                "title": f"رتبه‌بندی کلی نواحی بر اساس {CATEGORIES[cat]['title']}",
                "suffix": "%",
                "labels": [d["full_name"] for d in ranked],
                "values": [to_two(d["category_scores"][cat]) for d in ranked],
                "color": CATEGORIES[cat]["color"],
                "rows": ranked,
                "metric": cat,
            }
        )

    ranked_tonnage = sorted(all_districts, key=lambda x: x["tonnage"], reverse=True)
    charts.append(
        {
            "title": "رتبه‌بندی کلی نواحی بر اساس تناژ آسفالت",
            "suffix": "تن",
            "labels": [d["full_name"] for d in ranked_tonnage],
            "values": [to_two(d["tonnage"]) for d in ranked_tonnage],
            "color": "#f28e2b",
            "rows": ranked_tonnage,
            "metric": "tonnage",
        }
    )

    return render_template("overall_comparison.html", charts=charts)


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5000, debug=False)
else:
    init_db()
