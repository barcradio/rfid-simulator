import pytest
from fastapi.testclient import TestClient

from fx90_simulator.main import create_app


@pytest.mark.integration
def test_control_panel_and_status() -> None:
    with TestClient(create_app()) as client:
        panel = client.get("/test/")
        status = client.get("/test/status")

    assert panel.status_code == 200
    assert "RFID Interface Test Harness" in panel.text
    assert status.status_code == 200
    assert status.json()["config"]["runner_count"] == 400


@pytest.mark.integration
def test_control_api_rejects_invalid_settings() -> None:
    with TestClient(create_app()) as client:
        response = client.put("/test/config", json={"noise_percent": 101})

    assert response.status_code == 400


@pytest.mark.integration
def test_scenario_api_rejects_malformed_payload() -> None:
    with TestClient(create_app()) as client:
        response = client.put("/test/scenario", json={
            "name": "Invalid",
            "duration_seconds": 10,
            "runner_count": 1,
            "distribution": None,
            "burst": None,
            "noise": {"percent": 0},
            "random_seed": 1,
        })

    assert response.status_code == 400


@pytest.mark.integration
@pytest.mark.parametrize("name,count,duration,noise_percent", [
    ("Start Line", 341, 621.1, 2),
    ("Finish Line", 253, 65681.0, 25),
    ("Aid2", 310, 13022.414, 25),
])
def test_recorded_scenarios_are_available_and_selectable(name, count, duration, noise_percent) -> None:
    with TestClient(create_app()) as client:
        listed = client.get("/test/scenarios")
        assert listed.status_code == 200
        profile = next(item for item in listed.json()["scenarios"] if item["name"] == name)
        assert profile["distribution"]["type"] == "recorded"
        assert len(profile["distribution"]["arrivals_seconds"]) == count
        assert profile["distribution"]["arrivals_seconds"][0] == 0
        assert profile["distribution"]["arrivals_seconds"][-1] == duration
        response = client.put("/test/scenario", json={"name": name, "time_scale": 600})
        assert response.status_code == 200
        selected = response.json()["scenario"]
        assert selected["runner_count"] == count
        assert selected["duration_seconds"] == duration
        assert selected["time_scale"] == 600
        assert selected["distribution"] == profile["distribution"]
        assert selected["noise"] == {"percent": noise_percent}
