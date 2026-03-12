import argparse
from collections import Counter

from .utils import connect_db, load_yaml, resolve_path


def main() -> None:
    parser = argparse.ArgumentParser(description="POC data validation")
    parser.add_argument("--config", default="poc/config/poc.yaml")
    args = parser.parse_args()

    config = load_yaml(args.config)
    db_path = resolve_path(config.get("paths", {}).get("db_path", "data/metadata.db"))

    conn = connect_db(db_path)

    assets = conn.execute("SELECT COUNT(*) AS cnt FROM assets").fetchone()["cnt"]
    events = conn.execute("SELECT COUNT(*) AS cnt FROM events").fetchone()["cnt"]
    detections = conn.execute("SELECT COUNT(*) AS cnt FROM detections").fetchone()[
        "cnt"
    ]

    missing_assets = conn.execute(
        """
        SELECT COUNT(*) AS cnt
        FROM events e
        LEFT JOIN assets a ON e.asset_id = a.asset_id
        WHERE e.asset_id IS NOT NULL AND a.asset_id IS NULL
        """
    ).fetchone()["cnt"]

    event_types = conn.execute(
        "SELECT event_type FROM events WHERE event_type IS NOT NULL"
    ).fetchall()
    counts = Counter([row["event_type"] for row in event_types])

    print(f"assets: {assets}")
    print(f"events: {events}")
    print(f"detections: {detections}")
    print(f"events_missing_assets: {missing_assets}")
    if counts:
        top_types = ", ".join([f"{k}:{v}" for k, v in counts.most_common(5)])
        print(f"top_event_types: {top_types}")

    conn.close()


if __name__ == "__main__":
    main()

