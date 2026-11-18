# Wokwi ESP32 → Belaku Kannu live monitoring

```
Wokwi ESP32 → WiFi → HTTPS POST → ngrok → FastAPI → PostgreSQL → Next.js dashboard (polls every 3 s)
```

Threshold alerts are separate from the ML health score. They never read or write each other.
The thresholds are demonstration values, **not certified BESCOM protection limits**.

## One-time setup

```bash
# 1. Create the two new tables (additive; touches no existing table)
cd backend && source .venv/bin/activate     # or: .venv/bin/python -m alembic ...
alembic upgrade head                        # applies d4e5f6a7b8c9

# 2. Device key: already generated in backend/.env as DEVICE_API_KEY (git-ignored).
grep DEVICE_API_KEY backend/.env            # copy this value into the sketch
```

On Render, add `DEVICE_API_KEY` in the dashboard (declared in `render.yaml`, value not in git).

## Every demo

```bash
# Terminal 1: backend            # Terminal 2: frontend        # Terminal 3: tunnel
cd backend                       cd frontend                   ngrok http 8000
.venv/bin/python -m uvicorn main:app --port 8000   npm run dev
```

1. First time only: `ngrok config add-authtoken <your token>`.
2. Copy the `https://….ngrok-free.app` URL ngrok prints.
3. In Wokwi, open `iot/wokwi/sketch.ino` and set `API_BASE_URL`, `DEVICE_API_KEY` and `TRANSFORMER_ID`
   (use the `transformer_code` of a real row in your `transformers` table).
4. Start the simulation, then open http://localhost:3000/dashboard. The **Live IoT Monitoring** and
   **Emergency Alerts** panels are at the top.

If you deploy the backend to Render, use its URL as `API_BASE_URL` and skip ngrok.

## Test without Wokwi

```bash
KEY=$(grep DEVICE_API_KEY backend/.env | cut -d= -f2); URL=http://localhost:8000/api/v1/telemetry; TX=<transformer_code>
post() { curl -s -X POST $URL -H "X-Device-Key: $KEY" -H "Content-Type: application/json" \
  -d "{\"transformer_id\":\"$TX\",\"voltage_v\":$1,\"current_a\":$2,\"temperature_c\":$3}"; echo; }
post 230 40 40   # SAFE
post 230 90 40   # CRITICAL, overload alert
post 230 40 75   # CRITICAL, over-temperature (overload alert resolves)
post 180 40 40   # CRITICAL, under-voltage
post 230 40 40   # recovery: alerts resolve
```

Automated tests: `pytest tests/test_iot_thresholds.py` (always runs). The database tests run only when you
point them at a scratch PostgreSQL: `IOT_TEST_DATABASE_URL=postgresql://… pytest tests/test_iot_api.py`.

## Behaviour

| Reading | Warning | Critical (raises an alert) |
|---|---|---|
| Voltage | 200–210 V or 250–260 V | < 200 V or > 260 V |
| Current | > 65 A | > 80 A |
| Temperature | > 65 °C | > 70 °C |

- One open alert per transformer and fault type, enforced by a partial unique index. An ongoing fault does not re-alert every 2 s.
- When the fault is no longer critical, its alert is resolved. The same fault later raises a new alert.
- Warnings colour the status amber but do not create alerts.
- The backend recomputes the status itself. The status sent by the device is stored for comparison only.
- A device counts as online if its last reading is ≤ 10 s old, delayed up to 60 s, offline after that.

## API (all under `/api/v1`)

| Method | Path | Notes |
|---|---|---|
| POST | `/telemetry` | Device → backend. Needs the `X-Device-Key` header. 401 wrong key, 503 key not configured, 404 unknown transformer, 422 bad data |
| GET | `/telemetry/latest` | Newest reading per transformer (last 24 h) with connection state |
| GET | `/telemetry/history?transformer_id=` | Recent readings, newest first |
| GET | `/iot-alerts?scope=active\|resolved\|all` | Alerts |
| POST | `/iot-alerts/{id}/acknowledge` | Marks an open alert as seen |
| POST | `/iot-inspection` | Runs the 4 ML models + SHAP on the latest ~30 readings; returns scores, drivers, recommended actions |
| POST | `/iot-inspection/ticket` | Raises a maintenance ticket from an inspection (one open ticket per transformer + priority) |

## AI Analytics page (Run Inspection)

Dashboard → **Latest IoT Monitoring** → **View full** opens `/ml-analytics`. **Run Inspection** runs Isolation
Forest, XGBoost, Random Forest and Cox (plus SHAP) from `ai_service.predict_daily_health()` on that transformer's
latest readings, next to the instant protection alarms. The old model benchmark page moved to `/ml-analytics/performance`.

How readings map to model inputs: the simulator's 230 V is read as a phase voltage and multiplied by √3 (the models
use a 415 V line-to-line scale; without this every reading looks like a 45% under-voltage), and load % is the current
divided by the rated current of the transformer's own kVA rating. How strongly the models react depends on that rating:
a 25 kVA transformer reacts clearly to overload or heat, while a 100 kVA or 250 kVA one barely moves for a single spike.
The models treat oil temperature below roughly 85 °C as normal, and the Wokwi DHT22 tops out at 80 °C, so heat alone
will not turn them critical (the 70 °C protection alarm still fires).

## Files changed or added

Backend: `models/iot.py`, `models/__init__.py`, `alembic/versions/d4e5f6a7b8c9_…py`, `schemas/iot.py`,
`services/iot_alerts.py`, `services/iot_inspection.py`, `api/endpoints/iot.py`, `api/api.py`, `core/config.py`, `tests/test_iot_*.py`.
Frontend: `components/widgets/LiveIoTPanel.tsx` (new), `app/ml-analytics/page.tsx` (replaced; old page now `app/ml-analytics/performance/page.tsx`), `lib/api.ts` (functions added), `app/dashboard/page.tsx` (4 lines).
Config: `.env.example`, `render.yaml`. Device: `iot/wokwi/sketch.ino`, `iot/wokwi/libraries.txt`.

## Notes

- Readings arrive every 2 s (about 43,000 rows a day). Plan a cleanup job if you leave it running for weeks.
- The API currently has authentication bypassed for the dashboard (demo mode). The device endpoint is key-protected independently of that.
