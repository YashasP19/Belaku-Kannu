"""
Integration tests for the IoT telemetry + emergency-alert pipeline.

These run against a REAL PostgreSQL and are OPT-IN: set IOT_TEST_DATABASE_URL, e.g.

    IOT_TEST_DATABASE_URL=postgresql://user:pass@localhost:5432/scratch_db \
        pytest tests/test_iot_api.py

Everything happens inside a throw-away schema that is dropped afterwards, so it is
safe to point at any database you can create schemas in. The real migration
(d4e5f6a7b8c9) is what creates the IoT tables, so the migration is tested too.
"""
import importlib.util
import os
import pathlib
import uuid

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from core.config import settings
from core.database import get_db
from main import app

TEST_URL = os.getenv("IOT_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not TEST_URL, reason="set IOT_TEST_DATABASE_URL to run IoT integration tests")

DEVICE_KEY = "test-device-key"
HEADERS = {"X-Device-Key": DEVICE_KEY}
TX_CODE = "TRF_TEST_001"


def _load_migration():
    path = (pathlib.Path(__file__).resolve().parent.parent
            / "alembic" / "versions" / "d4e5f6a7b8c9_add_iot_telemetry_and_alerts.py")
    spec = importlib.util.spec_from_file_location("iot_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def engine():
    schema = f"iot_test_{uuid.uuid4().hex[:8]}"
    admin = create_engine(TEST_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text(f'CREATE SCHEMA "{schema}"'))
    eng = create_engine(TEST_URL, connect_args={"options": f"-csearch_path={schema}"})
    with eng.begin() as conn:
        # Minimal stand-in for the real transformers table (the real one needs PostGIS).
        conn.execute(text(
            "CREATE TABLE transformers (id uuid PRIMARY KEY, transformer_code varchar(64) UNIQUE NOT NULL)"
        ))
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            _load_migration().upgrade()
    yield eng
    eng.dispose()
    with admin.connect() as c:
        c.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
    admin.dispose()


@pytest.fixture()
def tx_id(engine):
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE iot_alerts, iot_telemetry, transformers CASCADE"))
        tid = uuid.uuid4()
        conn.execute(text("INSERT INTO transformers (id, transformer_code) VALUES (:i, :c)"),
                     {"i": tid, "c": TX_CODE})
    return tid


@pytest.fixture()
def client(engine, monkeypatch):
    Session = sessionmaker(bind=engine, autoflush=False)

    def _get_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    monkeypatch.setattr(settings, "DEVICE_API_KEY", DEVICE_KEY)
    app.dependency_overrides[get_db] = _get_db
    yield TestClient(app)  # no `with`: skip startup (ML cache + batch thread)
    app.dependency_overrides.clear()


def post(client, v, a, t, tid=TX_CODE, **extra):
    body = {"transformer_id": tid, "voltage_v": v, "current_a": a, "temperature_c": t, **extra}
    return client.post("/api/v1/telemetry", json=body, headers=HEADERS)


def count(engine, sql):
    with engine.connect() as c:
        return c.execute(text(sql)).scalar()


# ─── Authentication and validation ────────────────────────────────────────────
def test_device_key_required(client, tx_id):
    body = {"transformer_id": TX_CODE, "voltage_v": 230, "current_a": 40, "temperature_c": 40}
    assert client.post("/api/v1/telemetry", json=body).status_code == 401
    assert client.post("/api/v1/telemetry", json=body, headers={"X-Device-Key": "wrong"}).status_code == 401


def test_ingestion_disabled_when_key_not_configured(client, tx_id, monkeypatch):
    monkeypatch.setattr(settings, "DEVICE_API_KEY", "")
    assert post(client, 230, 40, 40).status_code == 503


def test_unknown_transformer_is_404(client, tx_id, engine):
    r = post(client, 230, 40, 40, tid="NO_SUCH_TRANSFORMER")
    assert r.status_code == 404
    assert count(engine, "SELECT count(*) FROM iot_telemetry") == 0


@pytest.mark.parametrize("bad", [
    {"voltage_v": -5}, {"voltage_v": 5000}, {"current_a": -1}, {"temperature_c": 900},
    {"voltage_v": "abc"}, {"status": "EXPLODING"}, {"transformer_id": "  "},
])
def test_invalid_payload_is_422_and_not_stored(client, tx_id, engine, bad):
    body = {"transformer_id": TX_CODE, "voltage_v": 230, "current_a": 40, "temperature_c": 40, **bad}
    assert client.post("/api/v1/telemetry", json=body, headers=HEADERS).status_code == 422
    assert count(engine, "SELECT count(*) FROM iot_telemetry") == 0


def test_transformer_can_be_referenced_by_uuid(client, tx_id):
    r = post(client, 230, 40, 40, tid=str(tx_id))
    assert r.status_code == 201
    assert r.json()["transformer_code"] == TX_CODE


# ─── The five scenarios from the brief ───────────────────────────────────────
def test_scenario_normal_is_safe_and_stored(client, tx_id, engine):
    r = post(client, 230, 40, 40)
    assert r.status_code == 201
    assert r.json()["status"] == "SAFE"
    assert r.json()["alerts_opened"] == []
    assert count(engine, "SELECT count(*) FROM iot_telemetry") == 1
    assert count(engine, "SELECT count(*) FROM iot_alerts") == 0


def test_scenario_overload_raises_one_alert_no_duplicates(client, tx_id, engine):
    first = post(client, 230, 90, 40).json()
    assert first["status"] == "CRITICAL"
    assert [a["fault_type"] for a in first["alerts_opened"]] == ["OVERLOAD_CURRENT"]
    for _ in range(5):  # the ongoing fault keeps arriving every 2 s
        again = post(client, 230, 92, 40).json()
        assert again["alerts_opened"] == []
    assert count(engine, "SELECT count(*) FROM iot_telemetry") == 6
    assert count(engine, "SELECT count(*) FROM iot_alerts") == 1

    alert = client.get("/api/v1/iot-alerts?scope=active").json()[0]
    assert alert["transformer_code"] == TX_CODE
    assert alert["fault_type"] == "OVERLOAD_CURRENT"
    assert alert["severity"] == "CRITICAL"
    assert alert["actual_value"] == 90 and alert["threshold_value"] == 80 and alert["unit"] == "A"
    assert alert["recommended_action"] and alert["triggered_at"]


def test_scenario_high_temperature(client, tx_id):
    r = post(client, 230, 40, 75).json()
    assert r["status"] == "CRITICAL"
    assert [a["fault_type"] for a in r["alerts_opened"]] == ["OVER_TEMPERATURE"]


def test_scenario_low_voltage(client, tx_id):
    r = post(client, 180, 40, 40).json()
    assert r["status"] == "CRITICAL"
    assert [a["fault_type"] for a in r["alerts_opened"]] == ["UNDERVOLTAGE"]


def test_scenario_recovery_resolves_then_refault_raises_new_alert(client, tx_id, engine):
    post(client, 230, 90, 40)
    rec = post(client, 230, 40, 40).json()
    assert rec["status"] == "SAFE"
    assert [a["fault_type"] for a in rec["alerts_resolved"]] == ["OVERLOAD_CURRENT"]
    assert client.get("/api/v1/iot-alerts?scope=active").json() == []

    again = post(client, 230, 95, 40).json()  # the fault occurs again
    assert [a["fault_type"] for a in again["alerts_opened"]] == ["OVERLOAD_CURRENT"]
    history = client.get("/api/v1/iot-alerts?scope=all").json()
    assert len(history) == 2
    assert sorted(a["status"] for a in history) == ["ACTIVE", "RESOLVED"]
    assert count(engine, "SELECT count(*) FROM iot_alerts WHERE resolved_at IS NULL") == 1


# ─── Other behaviour ──────────────────────────────────────────────────────────
def test_warning_colours_status_but_raises_no_alert(client, tx_id, engine):
    r = post(client, 230, 70, 40).json()  # 70 A: above 65 (warning), below 80 (critical)
    assert r["status"] == "WARNING"
    assert r["alerts_opened"] == []
    assert count(engine, "SELECT count(*) FROM iot_alerts") == 0


def test_backend_status_ignores_device_reported_status(client, tx_id, engine):
    r = post(client, 230, 90, 40, status="SAFE").json()  # device lies / is out of date
    assert r["status"] == "CRITICAL"
    row = engine.connect().execute(text("SELECT status, device_status FROM iot_telemetry")).one()
    assert (row.status, row.device_status) == ("CRITICAL", "SAFE")


def test_multiple_simultaneous_faults_get_separate_alerts(client, tx_id):
    r = post(client, 180, 90, 75).json()
    assert {a["fault_type"] for a in r["alerts_opened"]} == {"UNDERVOLTAGE", "OVERLOAD_CURRENT", "OVER_TEMPERATURE"}
    # fixing one fault resolves only that alert
    r2 = post(client, 230, 90, 75).json()
    assert [a["fault_type"] for a in r2["alerts_resolved"]] == ["UNDERVOLTAGE"]
    assert len(client.get("/api/v1/iot-alerts?scope=active").json()) == 2


def test_acknowledge_keeps_alert_open_and_deduplicated(client, tx_id):
    post(client, 230, 90, 40)
    alert = client.get("/api/v1/iot-alerts?scope=active").json()[0]
    ack = client.post(f"/api/v1/iot-alerts/{alert['id']}/acknowledge")
    assert ack.status_code == 200
    assert ack.json()["status"] == "ACKNOWLEDGED" and ack.json()["acknowledged_at"]

    assert post(client, 230, 91, 40).json()["alerts_opened"] == []  # still no duplicate
    assert len(client.get("/api/v1/iot-alerts?scope=active").json()) == 1

    post(client, 230, 40, 40)  # recovery
    resolved = client.get("/api/v1/iot-alerts?scope=resolved").json()
    assert len(resolved) == 1 and resolved[0]["status"] == "RESOLVED"
    assert client.post(f"/api/v1/iot-alerts/{alert['id']}/acknowledge").status_code == 409
    assert client.post(f"/api/v1/iot-alerts/{uuid.uuid4()}/acknowledge").status_code == 404


def test_latest_and_history_endpoints(client, tx_id):
    post(client, 231, 41, 41)
    post(client, 232, 42, 42, timestamp="2026-11-18T10:00:00Z")
    latest = client.get("/api/v1/telemetry/latest").json()
    assert len(latest) == 1
    assert latest[0]["voltage_v"] == 232 and latest[0]["transformer_code"] == TX_CODE
    assert latest[0]["connection"] == "ONLINE" and latest[0]["age_seconds"] < 10
    assert latest[0]["device_timestamp"].startswith("2026-11-18T10:00:00")
    hist = client.get(f"/api/v1/telemetry/history?transformer_id={TX_CODE}").json()
    assert [h["voltage_v"] for h in hist] == [232, 231]  # newest first
    assert client.get("/api/v1/telemetry/history?transformer_id=nope").status_code == 404


def test_latest_connection_goes_stale_and_offline(client, tx_id, engine):
    post(client, 230, 40, 40)
    with engine.begin() as c:
        c.execute(text("UPDATE iot_telemetry SET received_at = now() - interval '30 seconds'"))
    assert client.get("/api/v1/telemetry/latest").json()[0]["connection"] == "STALE"
    with engine.begin() as c:
        c.execute(text("UPDATE iot_telemetry SET received_at = now() - interval '5 minutes'"))
    assert client.get("/api/v1/telemetry/latest").json()[0]["connection"] == "OFFLINE"


def test_partial_unique_index_blocks_second_open_alert_at_db_level(engine, tx_id):
    sql = text("""INSERT INTO iot_alerts (id, transformer_id, fault_type, severity, actual_value,
                  threshold_value, unit, message, recommended_action, status, triggered_at)
                  VALUES (:id, :t, 'OVERLOAD_CURRENT', 'CRITICAL', 90, 80, 'A', 'm', 'a', 'ACTIVE', now())""")
    with engine.begin() as c:
        c.execute(sql, {"id": uuid.uuid4(), "t": tx_id})
    with pytest.raises(Exception) as exc:
        with engine.begin() as c:
            c.execute(sql, {"id": uuid.uuid4(), "t": tx_id})
    assert "uq_iot_alerts_open_fault" in str(exc.value)
    # once resolved, the same fault may open again
    with engine.begin() as c:
        c.execute(text("UPDATE iot_alerts SET resolved_at = now(), status = 'RESOLVED'"))
        c.execute(sql, {"id": uuid.uuid4(), "t": tx_id})
