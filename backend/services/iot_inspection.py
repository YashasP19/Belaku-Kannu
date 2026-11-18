"""
IoT "Run Inspection": run the existing ML models on a transformer's live readings
===================================================================================
Reuses ai_service.predict_daily_health(), the same four models the daily batch uses:

  Isolation Forest   anomaly detection            (15% of the blend)
  XGBoost            SAFE/WARNING/CRITICAL class. \\ 35% together: the more cautious
  Random Forest      SAFE/WARNING/CRITICAL class. // of the two counts
  Cox survival       remaining useful life        (50% of the blend)
  SHAP               which inputs drive the risk

Nothing here changes or retrains a model, and nothing here touches the threshold
alerts: those stay a separate, instant rule layer (services/iot_alerts.py).

How simulator readings are mapped to model inputs (shown to the user on the page):
  * voltage: the simulator's 230 V is a phase voltage. The models were built on the
    415 V line-to-line scale, so voltage_lv = voltage_v x sqrt(3). Without this every
    reading looks like a 45% under-voltage and the models flag even normal data.
  * load %: current / rated current, where rated current comes from the transformer's
    own kVA rating (same formula the models use).
  * rating and age come from the transformers table.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from statistics import mean
from typing import Any, Dict, List, Optional

from core.config import settings
from services.ai_service import ai_service
from services.iot_alerts import CRITICAL, Fault, evaluate_reading

SQRT3 = 1.732
WINDOW_READINGS = 30  # about the last minute at one reading every 2 s

BLEND_WEIGHTS = {"isolation_forest": 0.15, "classifier": 0.35, "cox": 0.50}

FEATURE_LABELS = {
    "temperature_c": "Oil temperature",
    "load_percentage": "Load (% of rating)",
    "voltage_lv": "LV voltage",
    "current_a": "Current",
    "ambient_temperature": "Ambient temperature",
    "age_years": "Transformer age",
    "rated_kva": "Rated capacity",
    "power_factor": "Power factor",
    "load_ratio": "Load ratio",
    "current_ratio": "Current vs rated current",
    "voltage_deviation": "Voltage deviation from 415 V",
    "temperature_rise": "Temperature rise over ambient",
    "stress_index": "Combined thermal-load stress",
}

# Which advice a risk driver maps to (feature -> group)
_GROUPS = {
    "temperature_c": "thermal", "temperature_rise": "thermal", "stress_index": "thermal",
    "load_percentage": "load", "load_ratio": "load", "current_ratio": "load", "current_a": "load",
    "voltage_lv": "voltage", "voltage_deviation": "voltage",
    "age_years": "age",
}
_GROUP_ADVICE = {
    "thermal": ("SOON", "Check oil level, cooling fins and ventilation; thermal-scan the tank and bushings."),
    "load": ("SOON", "Rebalance phases or feeders and shed non-essential load; plan a capacity upgrade if load stays high."),
    "voltage": ("SOON", "Check the supply voltage and the tap-changer setting."),
    "age": ("ROUTINE", "Plan an oil test (BDV) and a condition assessment, given the transformer's age."),
}
_PRIORITY_ORDER = {"URGENT": 0, "SOON": 1, "ROUTINE": 2}


@dataclass
class _Reading:
    """The four attributes ai_service.predict_daily_health() reads from each row."""
    temperature_c: float
    load_percentage: float
    voltage_lv: float
    current_a: float


def build_model_readings(rows, rated_kva: float) -> List[_Reading]:
    """Map raw IoT rows (voltage_v, current_a, temperature_c) to model inputs."""
    rated_current = (rated_kva * 1000.0) / (1.732 * settings.NOMINAL_VOLTAGE)
    out = []
    for r in rows:
        load_pct = min(max(r.current_a / rated_current * 100.0, 0.0), 200.0)
        out.append(_Reading(
            temperature_c=r.temperature_c,
            load_percentage=load_pct,
            voltage_lv=r.voltage_v * SQRT3,
            current_a=r.current_a,
        ))
    return out


def _model_cards(pred: Dict[str, Any]) -> List[Dict[str, Any]]:
    mp = pred["model_predictions"]
    xgb, rf = mp["xgboost"], mp["random_forest"]
    xgb_is_winner = xgb["anomaly_score"] >= rf["anomaly_score"]  # higher risk = more cautious

    def card(key, name, role, weight, in_blend=True, extra=None):
        m = mp[key]
        d = {
            "key": key, "name": name, "role": role,
            "verdict": m["risk_category"], "risk_score": round(float(m["anomaly_score"]), 1),
            "weight": weight, "in_blend": in_blend,
        }
        if extra:
            d.update(extra)
        return d

    return [
        card("isolation_forest", "Isolation Forest", "Is the behaviour abnormal?", BLEND_WEIGHTS["isolation_forest"]),
        card("xgboost", "XGBoost", "Classifies SAFE / WARNING / CRITICAL", BLEND_WEIGHTS["classifier"],
             in_blend=xgb_is_winner),
        card("random_forest", "Random Forest", "Classifies SAFE / WARNING / CRITICAL", BLEND_WEIGHTS["classifier"],
             in_blend=not xgb_is_winner),
        card("cox", "Cox survival", "How much life is left?", BLEND_WEIGHTS["cox"],
             extra={"expected_lifetime_days": pred.get("expected_lifetime_days")}),
    ]


def _drivers(pred: Dict[str, Any], top: int = 6) -> List[Dict[str, Any]]:
    shap = pred.get("xgb_shap_values") or pred.get("shap_values") or []
    ranked = sorted(shap, key=lambda s: abs(s["shap_value"]), reverse=True)[:top]
    return [{
        "feature": s["feature_name"],
        "label": FEATURE_LABELS.get(s["feature_name"], s["feature_name"]),
        "value": s["feature_value"],
        "impact": s["shap_value"],
        "direction": "raises risk" if s["shap_value"] > 0 else "lowers risk",
    } for s in ranked]


def build_recommendations(
    risk_category: str,
    health_score: float,
    drivers: List[Dict[str, Any]],
    faults: List[Fault],
    expected_lifetime_days: Optional[int],
) -> List[Dict[str, str]]:
    """Plain-language 'what can be done' list. Pure function: easy to test."""
    recs: List[Dict[str, str]] = []

    for f in faults:
        if f.severity == CRITICAL:
            recs.append({"priority": "URGENT", "action": f.recommended_action, "reason": f.message})

    if risk_category == "CRITICAL":
        recs.append({"priority": "URGENT",
                     "action": "Raise a priority maintenance ticket and schedule a crew visit.",
                     "reason": f"Predicted health score {health_score:.0f}/100 is in the critical range (below 45)."})
    elif risk_category == "WARNING":
        recs.append({"priority": "SOON",
                     "action": "Schedule an inspection in the next maintenance round (about a week).",
                     "reason": f"Predicted health score {health_score:.0f}/100 is in the warning range (45-75)."})

    # Driver-based advice only when something is actually wrong; a healthy transformer
    # with no alarms should not be told to "do something soon" about its top driver.
    needs_attention = risk_category != "HEALTHY" or any(f.severity == CRITICAL for f in faults)
    seen_groups = set()
    for d in drivers:
        if not needs_attention:
            break
        group = _GROUPS.get(d["feature"])
        if group and d["impact"] > 0 and group not in seen_groups and len(seen_groups) < 2:
            seen_groups.add(group)
            priority, action = _GROUP_ADVICE[group]
            recs.append({"priority": priority, "action": action,
                         "reason": f"{d['label']} is one of the top risk drivers."})

    if expected_lifetime_days is not None and expected_lifetime_days < 365:
        recs.append({"priority": "SOON",
                     "action": "Plan refurbishment or replacement.",
                     "reason": f"Estimated median remaining life is about {expected_lifetime_days} days."})

    if risk_category != "HEALTHY" or any(f.severity == CRITICAL for f in faults):
        recs.append({"priority": "SOON",
                     "action": "Upload a photo for the AI visual inspection to check for outside damage (leaks, rust, burn marks).",
                     "reason": "Sensors measure the inside; a photo confirms what is visible outside."})

    if not recs:
        recs.append({"priority": "ROUTINE",
                     "action": "No action needed. Keep monitoring.",
                     "reason": f"Health score {health_score:.0f}/100 and no protection alarms."})

    unique, seen = [], set()
    for r in recs:
        if r["action"] not in seen:
            seen.add(r["action"])
            unique.append(r)
    return sorted(unique, key=lambda r: _PRIORITY_ORDER[r["priority"]])


def _summary(risk_category: str, health_score: float, faults: List[Fault]) -> str:
    critical = [f for f in faults if f.severity == CRITICAL]
    if critical and risk_category == "HEALTHY":
        return ("A protection alarm is active, but the predictive models still rate the transformer healthy. "
                "That is expected: protection reacts to instant faults, while the models judge long-term "
                "degradation, so a short spike may not change their verdict yet.")
    if critical:
        return "A protection alarm is active and the predictive models also see elevated risk."
    if risk_category == "HEALTHY":
        return "No protection alarms and the predictive models rate the transformer healthy."
    return "No protection alarm right now, but the predictive models see elevated long-term risk."


def run_inspection(transformer, rows: List[Any], open_alert_count: int) -> Dict[str, Any]:
    """
    transformer: object with id, transformer_code, rated_kva, age_years
    rows: IoTTelemetry rows, newest first (at least one)
    Raises RuntimeError if the ML models are not available on the server.
    """
    rated_kva = float(transformer.rated_kva) if transformer.rated_kva is not None else settings.DEFAULT_RATED_KVA
    age_years = int(transformer.age_years) if transformer.age_years is not None else settings.DEFAULT_AGE_YEARS

    window = list(reversed(rows))  # oldest -> newest
    readings = build_model_readings(window, rated_kva)

    pred = ai_service.predict_daily_health(
        str(transformer.id), readings, calculate_shap=True, age_years=age_years, rated_kva=rated_kva
    )
    if pred.get("health_score") is None:
        raise RuntimeError("ML models are not loaded on the server (run scripts/train_production_models.py).")

    latest = rows[0]
    status, faults = evaluate_reading(latest.voltage_v, latest.current_a, latest.temperature_c)
    drivers = _drivers(pred)
    now = datetime.now(timezone.utc)

    notes = [
        "Simulator voltage is treated as a phase voltage and multiplied by √3 to match the 415 V line-to-line scale the models use.",
        f"Load % is the current divided by this transformer's rated current ({rated_kva:g} kVA).",
        "The models were trained on the project's generated dataset, so scores are for demonstration.",
    ]
    if transformer.rated_kva is None:
        notes.append(f"No rating on record: assumed {settings.DEFAULT_RATED_KVA:g} kVA.")
    if transformer.age_years is None:
        notes.append(f"No age on record: assumed {settings.DEFAULT_AGE_YEARS} years.")

    return {
        "transformer_id": transformer.id,
        "transformer_code": transformer.transformer_code,
        "run_at": now,
        "health_score": pred["health_score"],
        "risk_category": pred["risk_category"],
        "failure_probability": pred["failure_probability"],
        "expected_lifetime_days": pred["expected_lifetime_days"],
        "models": _model_cards(pred),
        "drivers": drivers,
        "protection": {
            "status": status,
            "open_alerts": open_alert_count,
            "faults": [{"fault_type": f.fault_type, "severity": f.severity, "message": f.message} for f in faults],
        },
        "summary": _summary(pred["risk_category"], pred["health_score"], faults),
        "recommendations": build_recommendations(
            pred["risk_category"], pred["health_score"], drivers, faults, pred["expected_lifetime_days"]
        ),
        "inputs": {
            "readings_used": len(rows),
            "window_seconds": round((rows[0].received_at - rows[-1].received_at).total_seconds(), 1),
            "data_age_seconds": round(max((now - rows[0].received_at).total_seconds(), 0.0), 1),
            "rated_kva": rated_kva,
            "age_years": age_years,
            "avg_voltage_v": round(mean(r.voltage_v for r in rows), 1),
            "avg_current_a": round(mean(r.current_a for r in rows), 1),
            "avg_temperature_c": round(mean(r.temperature_c for r in rows), 1),
            "avg_voltage_lv_mapped": round(mean(r.voltage_lv for r in readings), 1),
            "avg_load_pct_mapped": round(mean(r.load_percentage for r in readings), 1),
            "notes": notes,
        },
    }
