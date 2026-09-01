from __future__ import annotations

import csv
import gzip
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW_SITE = ROOT / "data" / "emsx" / "raw" / "8.csv.gz"
RAW_METADATA = ROOT / "data" / "emsx" / "raw" / "metadata.csv"
OUTPUT = ROOT / "data" / "emsx" / "processed" / "emsx_site8_core_upload.csv"


def number(value: str | None) -> float:
    if value is None or value == "":
        return 0.0
    return float(value)


def load_metadata(site_id: str) -> dict[str, str]:
    with RAW_METADATA.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row["site_id"] == site_id:
                return row
    raise SystemExit(f"metadata missing for site {site_id}")


def score_day(rows: list[dict[str, str]]) -> float:
    rows = rows[:96]
    load = sum(max(0.0, number(row["actual_consumption"])) for row in rows)
    pv = sum(max(0.0, number(row["actual_pv"])) for row in rows)
    load_error = sum(
        abs(number(row["load_00"]) - number(row["actual_consumption"])) for row in rows
    )
    pv_error = sum(abs(number(row["pv_00"]) - number(row["actual_pv"])) for row in rows)
    peak = max(max(0.0, number(row["actual_consumption"])) for row in rows)
    return load + pv * 0.8 + load_error * 1.2 + pv_error * 1.2 + peak * 6


def main() -> None:
    days: dict[str, list[dict[str, str]]] = defaultdict(list)
    with gzip.open(RAW_SITE, "rt", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter=";")
        for row in reader:
            day = datetime.fromisoformat(row["timestamp"]).date().isoformat()
            days[day].append(row)
    complete_days = {day: rows for day, rows in days.items() if len(rows) >= 96}
    if not complete_days:
        raise SystemExit("no complete 96-point day found")
    selected_day = max(complete_days, key=lambda day: score_day(complete_days[day]))
    rows = sorted(complete_days[selected_day], key=lambda row: row["timestamp"])[:96]
    site_id = rows[0]["site_id"]
    metadata = load_metadata(site_id)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    keep_fields = [
        "timestamp",
        "site_id",
        "actual_consumption",
        "actual_pv",
        "load_00",
        "pv_00",
        "battery_capacity_kwh",
        "battery_power_kwh_per_interval",
        "charge_efficiency",
        "discharge_efficiency",
        "battery_soc",
    ]
    with OUTPUT.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=keep_fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "timestamp": row["timestamp"],
                    "site_id": site_id,
                    "actual_consumption": row["actual_consumption"],
                    "actual_pv": row["actual_pv"],
                    "load_00": row["load_00"],
                    "pv_00": row["pv_00"],
                    "battery_capacity_kwh": metadata["capacity"],
                    "battery_power_kwh_per_interval": metadata["power"],
                    "charge_efficiency": metadata["charge_efficiency"],
                    "discharge_efficiency": metadata["discharge_efficiency"],
                    "battery_soc": "62",
                }
            )
    print(f"selected_day={selected_day}")
    print(f"rows={len(rows)}")
    print(f"output={OUTPUT}")


if __name__ == "__main__":
    main()
