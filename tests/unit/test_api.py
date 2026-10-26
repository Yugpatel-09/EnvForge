"""Unit and integration tests for EnvForge Control Plane API."""

from fastapi.testclient import TestClient

from apps.api.main import app

client = TestClient(app)


def test_api_health():
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json()["status"] == "healthy"


def test_list_environments():
    res = client.get("/v1/environments")
    assert res.status_code == 200
    envs = res.json()
    assert len(envs) >= 1
    sre = envs[0]
    assert sre["id"] == "sre.incident-response"
    assert sre["distinct_fault_mechanisms"] == 10
    assert "read_logs" in sre["tools"]


def test_environment_suites():
    res = client.get("/v1/environments/sre.incident-response/suites")
    assert res.status_code == 200
    data = res.json()
    suite_ids = [s["id"] for s in data["suites"]]
    assert "smoke" in suite_ids
    assert "standard" in suite_ids
    assert "adversarial" in suite_ids


def test_agent_registration_and_evaluation_workflow():
    # 1. Register an agent
    agent_res = client.post(
        "/v1/agents",
        json={"name": "ReferenceGoldenAgent-v1", "adapter": "reference_solver"},
    )
    assert agent_res.status_code == 200
    agent = agent_res.json()
    agent_id = agent["id"]

    # 2. Test agent connection
    test_conn_res = client.post(f"/v1/agents/{agent_id}/test-connection")
    assert test_conn_res.status_code == 200
    assert test_conn_res.json()["status"] == "healthy"

    # 3. Trigger evaluation batch
    eval_res = client.post(
        "/v1/evaluations",
        json={
            "name": "CI Release Gate Test",
            "environment_id": "sre.incident-response",
            "suite": "smoke",
            "tier": "easy",
            "agent_id": agent_id,
            "episodes_count": 2,
            "base_seed": 500,
        },
    )
    assert eval_res.status_code == 200
    eval_id = eval_res.json()["id"]

    # 4. Fetch evaluation status
    eval_get = client.get(f"/v1/evaluations/{eval_id}")
    assert eval_get.status_code == 200
    assert eval_get.json()["total_episodes"] == 2

    # 5. Fetch episodes
    episodes_res = client.get(f"/v1/evaluations/{eval_id}/episodes")
    assert episodes_res.status_code == 200
    episodes = episodes_res.json()
    assert len(episodes) == 2

    ep_id = episodes[0]["id"]

    # 6. Fetch trajectory
    traj_res = client.get(f"/v1/episodes/{ep_id}/trajectory")
    assert traj_res.status_code == 200
    traj = traj_res.json()
    assert len(traj["action_history"]) > 0

    # 7. Fetch verification
    verif_res = client.get(f"/v1/episodes/{ep_id}/verification")
    assert verif_res.status_code == 200
    assert verif_res.json()["success"] is True

    # 8. Export report
    report_res = client.get(f"/v1/reports/{eval_id}/export")
    assert report_res.status_code == 200
    report = report_res.json()
    assert report["provenance"]["platform"] == "EnvForge"
    assert report["metrics"]["critical_safety_failures"] == 0
