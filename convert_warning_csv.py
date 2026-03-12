import csv
from pathlib import Path
from typing import Optional


def pick_basename(value: str) -> Optional[str]:
    if not value:
        return None
    items = [x.strip() for x in value.split(",") if x.strip()]
    if not items:
        return None
    first = items[0]
    return first.split("/")[-1]


def main() -> None:
    root = Path(__file__).resolve().parent
    src = root / "告警明细表.csv"
    dst = root / "data" / "structured" / "alarms_warning.csv"
    dst.parent.mkdir(parents=True, exist_ok=True)

    if not src.exists():
        raise SystemExit(f"source CSV not found: {src}")

    with src.open("r", encoding="utf-8") as f_in, dst.open(
        "w", encoding="utf-8", newline=""
    ) as f_out:
        reader = csv.DictReader(f_in)
        orig_fields = reader.fieldnames or []
        extra_fields = [
            "event_type",
            "alarm_level",
            "alarm_source",
            "lat",
            "lon",
            "region",
            "file_name",
        ]
        fieldnames = orig_fields + [f for f in extra_fields if f not in orig_fields]
        writer = csv.DictWriter(f_out, fieldnames=fieldnames)
        writer.writeheader()

        for row in reader:
            new_row = dict(row)

            wt_name = (row.get("warning_type_name") or "").strip()
            alarm_body = (row.get("alarm_body") or "").strip()
            new_row["event_type"] = wt_name or alarm_body or None

            new_row["lat"] = row.get("latitude")
            new_row["lon"] = row.get("longitude")

            level = (row.get("emergency_level") or "").strip()
            if not level:
                level = (row.get("importance_level") or "").strip()
            new_row["alarm_level"] = level or None

            src_name = (row.get("warning_source_name") or "").strip()
            if not src_name:
                ws = (row.get("warning_source") or "").strip()
                mapping = {"1": "AI告警", "2": "人工上报", "3": "一键告警"}
                src_name = mapping.get(ws, "")
            new_row["alarm_source"] = src_name or None

            parts = [
                row.get("province_name"),
                row.get("city_name"),
                row.get("county_name"),
                row.get("town_name"),
                row.get("grid_name"),
            ]
            parts = [p for p in parts if p not in (None, "")]
            new_row["region"] = ">".join(parts) if parts else None

            name = pick_basename(row.get("file_img_url_icon") or "")
            if not name:
                name = pick_basename(row.get("file_img_url_src") or "")
            if not name:
                name = pick_basename(row.get("video_url") or "")
            new_row["file_name"] = name

            writer.writerow(new_row)

    print(f"Wrote {dst}")


if __name__ == "__main__":
    main()
