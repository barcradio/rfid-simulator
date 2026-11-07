import asyncio
import csv
from datetime import datetime
import random
from pathlib import Path

import pytest

from fx90_simulator.simulator.reader import Reader
from fx90_simulator.simulator.scenario import ScenarioConfig, ScenarioScheduler
from fx90_simulator.simulator.scenario_loader import ScenarioLoader
from fx90_simulator.simulator.tag_generator import TagGenerator


SCENARIOS = Path(__file__).parents[1] / "src" / "fx90_simulator" / "scenarios"


@pytest.mark.unit
def test_builtin_scenarios_load() -> None:
    scenarios = ScenarioLoader(SCENARIOS).list()

    assert [scenario.name for scenario in scenarios] == ["Aid2", "Finish Line", "Short Burst", "Start Line"]
    assert all(scenario.runner_count > 0 for scenario in scenarios)


@pytest.mark.unit
def test_start_line_schedule_is_deterministic_and_bounded() -> None:
    scenario = ScenarioLoader(SCENARIOS).get("Start Line")
    first = ScenarioScheduler(scenario).arrivals
    second = ScenarioScheduler(scenario).arrivals

    assert first == second
    assert len(first) == 341
    assert first == sorted(first)
    assert min(first) >= 0
    assert max(first) <= scenario.duration_seconds


@pytest.mark.unit
def test_burst_never_exceeds_configured_maximum() -> None:
    scenario = ScenarioLoader(SCENARIOS).get("Start Line")
    scheduler = ScenarioScheduler(scenario)

    index = 0
    total = 0
    while index < len(scheduler.arrivals):
        count, start = scheduler.next_burst(index)
        assert 0 < count <= scenario.burst.max_size
        assert start == scheduler.arrivals[index]
        total += count
        index += count

    assert total == scenario.runner_count


@pytest.mark.unit
def test_burst_duration_matches_scheduled_arrivals() -> None:
    scenario = ScenarioLoader(SCENARIOS).get("Start Line")
    scheduler = ScenarioScheduler(scenario)

    index = 0
    while index < len(scheduler.arrivals):
        count, start = scheduler.next_burst(index)
        burst_arrivals = scheduler.arrivals[index:index + count]
        assert burst_arrivals[-1] - start <= scenario.burst.max_duration_seconds + 1e-9
        index += count


RECORDED_PROFILES = [
    ("Start Line", "StartLine.csv", 341, 621.1, 2),
    ("Finish Line", "FinishLine.csv", 253, 65681.0, 25),
    ("Aid2", "Aid2.csv", 310, 13022.414, 25),
]


@pytest.mark.unit
@pytest.mark.parametrize("name,filename,count,duration,noise_percent", RECORDED_PROFILES)
def test_recorded_profile_properties(name, filename, count, duration, noise_percent) -> None:
    scenario = ScenarioLoader(SCENARIOS).get(name)
    arrivals = ScenarioScheduler(scenario).arrivals
    assert scenario.runner_count == count
    assert scenario.duration_seconds == duration
    assert scenario.noise.percent == noise_percent
    assert len(arrivals) == count
    assert arrivals == sorted(arrivals)
    assert arrivals[0] == 0
    assert arrivals[-1] == duration
    assert ScenarioConfig.from_dict(scenario.to_dict()) == scenario


@pytest.mark.unit
@pytest.mark.parametrize("name,filename,count,duration,noise_percent", RECORDED_PROFILES)
def test_recorded_profiles_match_every_csv_arrival(name, filename, count, duration, noise_percent) -> None:
    source = SCENARIOS.parents[2] / "rfidreader_data" / filename
    if not source.exists():
        pytest.skip(f"archived recording not available: {source}")
    with source.open(newline="", encoding="utf-8-sig") as stream:
        timestamps = sorted(datetime.fromisoformat(row["Timestamp"]) for row in csv.DictReader(stream))
    expected = [(stamp - timestamps[0]).total_seconds() for stamp in timestamps]
    scenario = ScenarioLoader(SCENARIOS).get(name)
    assert ScenarioScheduler(scenario).arrivals == expected


@pytest.mark.unit
@pytest.mark.parametrize("arrivals,match", [
    ([], "one arrival per runner"),
    ([0], "one arrival per runner"),
    ([1, 0], "sorted"),
    ([-1, 1], "within scenario duration"),
    ([0, 11], "within scenario duration"),
    ([0, float("nan")], "finite"),
    ([0, float("inf")], "finite"),
    (None, "must be an array"),
    ("0,1", "must be an array"),
])
def test_recorded_profile_rejects_invalid_arrivals(arrivals, match) -> None:
    data = ScenarioLoader(SCENARIOS).get("Short Burst").to_dict()
    data.update(runner_count=2, duration_seconds=10)
    data["distribution"] = {"type": "recorded", "arrivals_seconds": arrivals}
    with pytest.raises(ValueError, match=match):
        ScenarioConfig.from_dict(data)


@pytest.mark.unit
def test_recorded_profile_preserves_simultaneous_arrivals_and_copies_schedule() -> None:
    data = ScenarioLoader(SCENARIOS).get("Short Burst").to_dict()
    data.update(runner_count=3, duration_seconds=10)
    data["distribution"] = {"type": "recorded", "arrivals_seconds": [0, 0, 10]}
    scenario = ScenarioConfig.from_dict(data)
    scheduler = ScenarioScheduler(scenario)
    assert scheduler.arrivals == [0, 0, 10]
    scheduler.arrivals.pop()
    assert scenario.distribution.arrivals_seconds == [0, 0, 10]


@pytest.mark.unit
@pytest.mark.parametrize("distribution", ["truncated-normal", "log-normal"])
def test_synthetic_distributions_remain_deterministic_and_bounded(distribution) -> None:
    data = ScenarioLoader(SCENARIOS).get("Short Burst").to_dict()
    data["distribution"]["type"] = distribution
    scenario = ScenarioConfig.from_dict(data)
    arrivals = ScenarioScheduler(scenario).arrivals
    assert arrivals == ScenarioScheduler(scenario).arrivals
    assert len(arrivals) == scenario.runner_count
    assert arrivals == sorted(arrivals)
    assert all(0 <= value <= scenario.duration_seconds for value in arrivals)


@pytest.mark.unit
def test_scenario_validation_rejects_invalid_bib_range() -> None:
    with pytest.raises(ValueError, match="runner_count exceeds"):
        ScenarioConfig.from_dict({
            "name": "Invalid",
            "version": 1,
            "type": "custom",
            "duration_seconds": 10,
            "runner_count": 2,
            "bib_start": 1,
            "bib_end": 1,
            "distribution": {
                "type": "truncated-normal",
                "center_seconds": 5,
                "spread_seconds": 1,
            },
            "burst": {"max_size": 1, "max_duration_seconds": 0.1},
            "noise": {"percent": 0},
            "random_seed": 1,
        })


@pytest.mark.unit
def test_scenario_validation_rejects_unseeded_or_infeasible_distribution() -> None:
    base = {
        "name": "Invalid",
        "version": 1,
        "type": "custom",
        "duration_seconds": 10,
        "runner_count": 1,
        "bib_start": 1,
        "bib_end": 1,
        "distribution": {"type": "truncated-normal", "center_seconds": 5, "spread_seconds": 1},
        "burst": {"max_size": 1, "max_duration_seconds": 0.1},
        "noise": {"percent": 0},
    }
    with pytest.raises(ValueError, match="random_seed"):
        ScenarioConfig.from_dict(base)
    base["random_seed"] = 1
    base["distribution"] = {"type": "truncated-normal", "center_seconds": 1e12, "spread_seconds": 1}
    with pytest.raises(ValueError, match="negligible probability"):
        ScenarioConfig.from_dict(base)


@pytest.mark.unit
def test_tag_generator_seed_controls_random_order_and_noise() -> None:
    first = TagGenerator(1, 500, 500, "random", rng=random.Random(12345))
    second = TagGenerator(1, 500, 500, "random", rng=random.Random(12345))

    assert first.race_tags() == second.race_tags()
    assert first.noise_tags == second.noise_tags


@pytest.mark.unit
def test_scenario_noise_is_additive_and_does_not_consume_runner_tags() -> None:
    scenario = ScenarioLoader(SCENARIOS).get("Short Burst")
    rng = random.Random(scenario.random_seed)
    generator = TagGenerator(scenario.bib_start, scenario.bib_end, scenario.runner_count, "random", rng=rng)
    remaining = generator.race_tags()
    runner_tags = []
    noise_tags = []

    for _ in range(scenario.runner_count):
        if rng.random() < scenario.noise.percent / 100:
            noise_tags.append(generator.next_noise_tag())
        runner_tags.append(generator.next_runner_tag(remaining, True))

    assert len(runner_tags) == scenario.runner_count
    assert len(set(runner_tags)) == scenario.runner_count
    assert not remaining
    assert len(noise_tags) > 0
    assert set(noise_tags).isdisjoint(runner_tags)


@pytest.mark.asyncio
@pytest.mark.unit
@pytest.mark.parametrize("name", ["Start Line", "Finish Line", "Aid2"])
@pytest.mark.parametrize("time_scale", [1, 600])
async def test_reader_emits_recorded_timeline_with_time_scaling(monkeypatch, name, time_scale) -> None:
    reader = Reader()
    scenario = ScenarioLoader(SCENARIOS).get(name)
    scenario.time_scale = time_scale
    reader.set_scenario(scenario)
    reader.radio_active = True
    elapsed = 0.0
    emitted = []
    noise_times = []
    original_emit = reader._emit_tag

    async def sleep(delay: float) -> None:
        nonlocal elapsed
        elapsed += delay

    async def emit(generator, tag_id, is_noise, delay_ms) -> None:
        (noise_times if is_noise else emitted).append(elapsed)
        await original_emit(generator, tag_id, is_noise, delay_ms)

    monkeypatch.setattr(reader, "_emit_tag", emit)
    monkeypatch.setattr("fx90_simulator.simulator.reader.asyncio.sleep", sleep)
    await reader._generate_scenario()

    assert reader.test_status()["last_error"] == ""
    assert reader._good_tags_sent == scenario.runner_count
    assert 0 < reader._noise_tags_sent <= scenario.runner_count
    assert reader._noise_tags_sent == len(noise_times)
    assert all(value in emitted for value in noise_times)
    assert reader._tags_sent == scenario.runner_count + len(noise_times)
    assert emitted == pytest.approx([value / time_scale for value in scenario.distribution.arrivals_seconds])
    assert elapsed == pytest.approx(scenario.duration_seconds / time_scale)


@pytest.mark.asyncio
@pytest.mark.unit
async def test_reader_scenario_uses_scenario_bibs_and_additive_noise() -> None:
    reader = Reader()
    reader.set_scenario(ScenarioConfig.from_dict({
        "name": "Reader Test",
        "version": 1,
        "type": "custom",
        "duration_seconds": 0.01,
        "runner_count": 3,
        "bib_start": 700,
        "bib_end": 702,
        "distribution": {"type": "truncated-normal", "center_seconds": 0.001, "spread_seconds": 0.0001},
        "burst": {"max_size": 3, "max_duration_seconds": 0.1},
        "noise": {"percent": 100},
        "random_seed": 7,
    }))
    reader.test_config.tag_order = "sequential"
    await reader.start_scenario()
    for _ in range(100):
        if not reader.radio_active:
            break
        await asyncio.sleep(0.001)
    await reader.stop()

    assert reader._good_tags_sent == 3
    assert reader._noise_tags_sent == 3
