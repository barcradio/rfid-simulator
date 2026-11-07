import json
from pathlib import Path
import runpy

import pytest

from fx90_simulator.simulator.scenario import ScenarioConfig, ScenarioScheduler


ROOT = Path(__file__).parents[1]
import_profile = runpy.run_path(str(ROOT / "scripts" / "import_reader_profile.py"))["import_profile"]


@pytest.mark.unit
@pytest.mark.parametrize("noise_percent", [0, 2.05, 24.84])
def test_import_sorts_timestamps_preserves_precision_and_handles_midnight(tmp_path, noise_percent) -> None:
    source = tmp_path / "reader.csv"
    source.write_text(
        "Bib,Timestamp\n"
        "3,2026-09-26 00:00:01.123\n"
        "1,2026-09-25 23:59:59.000\n"
        "2,2026-09-25 23:59:59.000\n",
        encoding="utf-8-sig",
    )
    destination = tmp_path / "scenario.json"
    original = json.loads((ROOT / "src" / "fx90_simulator" / "scenarios" / "short-burst.json").read_text())
    destination.write_text(json.dumps(original), encoding="utf-8")

    import_profile(source, destination, noise_percent)

    scenario = ScenarioConfig.from_dict(json.loads(destination.read_text()))
    assert ScenarioScheduler(scenario).arrivals == [0, 0, 2.123]
    assert scenario.duration_seconds == 2.123
    assert scenario.runner_count == 3
    assert (scenario.bib_start, scenario.bib_end) == (1, 3)
    assert scenario.noise.percent == noise_percent
    assert scenario.name == original["name"]
    assert scenario.burst.max_size == original["burst"]["max_size"]
    assert scenario.random_seed == original["random_seed"]


@pytest.mark.unit
@pytest.mark.parametrize("content,match", [
    ("Bib,Time\n1,invalid\n", "missing Timestamp column"),
    ("Bib,Timestamp\n1,invalid\n", "invalid Timestamp"),
    ("Bib,Timestamp\n", "at least two arrivals"),
    ("Bib,Timestamp\n1,2026-09-25 06:00:00\n2,2026-09-25 06:00:00\n", "positive duration"),
])
def test_invalid_import_leaves_existing_profile_unchanged(tmp_path, content, match) -> None:
    source = tmp_path / "reader.csv"
    source.write_text(content, encoding="utf-8")
    destination = tmp_path / "scenario.json"
    destination.write_text('{"name": "Unchanged"}', encoding="utf-8")

    with pytest.raises(ValueError, match=match):
        import_profile(source, destination)

    assert destination.read_text() == '{"name": "Unchanged"}'


@pytest.mark.unit
@pytest.mark.parametrize("noise_percent", [-1, 101, float("nan"), float("inf")])
def test_import_rejects_invalid_noise_before_writing(tmp_path, noise_percent) -> None:
    destination = tmp_path / "scenario.json"
    destination.write_text('{"name": "Unchanged"}', encoding="utf-8")
    with pytest.raises(ValueError, match="noise_percent"):
        import_profile(tmp_path / "unused.csv", destination, noise_percent)
    assert destination.read_text() == '{"name": "Unchanged"}'
