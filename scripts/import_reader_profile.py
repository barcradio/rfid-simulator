"""Replace a scenario's arrival schedule with timestamp offsets from a reader CSV."""

import argparse
import csv
from datetime import datetime
import json
from pathlib import Path
import math


def import_profile(source: Path, destination: Path, noise_percent: float = 0) -> None:
    if not math.isfinite(noise_percent) or not 0 <= noise_percent <= 100:
        raise ValueError("noise_percent must be between 0 and 100")
    with source.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames is None or "Timestamp" not in reader.fieldnames:
            raise ValueError(f"{source}: missing Timestamp column")
        timestamps = []
        for line, row in enumerate(reader, start=2):
            try:
                timestamps.append(datetime.fromisoformat(row["Timestamp"]))
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{source}:{line}: invalid Timestamp") from exc
    if len(timestamps) < 2:
        raise ValueError(f"{source}: at least two arrivals are required")
    timestamps.sort()
    arrivals = [(stamp - timestamps[0]).total_seconds() for stamp in timestamps]
    if arrivals[-1] <= 0:
        raise ValueError(f"{source}: arrival timeline must have a positive duration")
    data = json.loads(destination.read_text(encoding="utf-8"))
    data.update(
        duration_seconds=arrivals[-1],
        runner_count=len(arrivals),
        bib_start=1,
        bib_end=len(arrivals),
        distribution={"type": "recorded", "arrivals_seconds": arrivals},
        noise={"percent": noise_percent},
    )
    destination.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"{destination.name}: {len(arrivals)} arrivals over {arrivals[-1]} seconds; noise {noise_percent}%")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Reader CSV with a Timestamp column")
    parser.add_argument("destination", type=Path, help="Existing scenario JSON to update")
    parser.add_argument("--noise-percent", type=float, default=0, help="Additive noise probability per runner (0-100)")
    args = parser.parse_args()
    import_profile(args.source, args.destination, args.noise_percent)
