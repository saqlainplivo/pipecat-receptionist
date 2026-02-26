"""
Project 2: Pipecat AI Receptionist - Railway Deployment Server

Production-ready FastAPI server with:
  - /health endpoint for Railway health checks
  - /answer endpoint for Plivo Answer URL
  - /ws WebSocket endpoint for audio streaming
  - /logs endpoint to view call logs

All configuration is via environment variables (no .env file needed in production).

Usage (local):
    pip install -r requirements.txt
    python server.py

Usage (Docker):
    docker build -t pipecat-bot .
    docker run -p 8000:8000 --env-file .env pipecat-bot
"""

import base64
import json
import os

import plivo
from dotenv import load_dotenv
from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import HTMLResponse, PlainTextResponse, JSONResponse
from loguru import logger
from starlette.websockets import WebSocketState

from db import init_db, get_connection

# Load .env for local development (no-op if file doesn't exist)
load_dotenv()

app = FastAPI(title="Acme Corp AI Receptionist")


@app.on_event("startup")
async def startup():
    logger.info("Starting Acme Corp AI Receptionist...")
    init_db()

    # Validate required API keys
    required_keys = {
        "GROQ_API_KEY": "LLM (Groq)",
        "DEEPGRAM_API_KEY": "STT + TTS (Deepgram)",
    }
    missing = [f"{name} ({desc})" for name, desc in required_keys.items() if not os.getenv(name)]
    if missing:
        logger.error(f"MISSING API KEYS: {', '.join(missing)} — bot will NOT respond to callers!")
    else:
        logger.info("All API keys present.")

    # Optional: OpenAI fallback for when Groq hits rate limits
    if os.getenv("OPENAI_API_KEY"):
        logger.info("OPENAI_API_KEY set — fallback LLM enabled (Groq 429 → OpenAI gpt-4o-mini)")
    else:
        logger.warning("OPENAI_API_KEY not set — no fallback if Groq is rate-limited")

    logger.info("Server ready.")


@app.get("/health")
async def health():
    """Health check endpoint for Railway monitoring."""
    return {
        "status": "healthy",
        "service": "acme-corp-receptionist",
        "version": "1.0.0",
    }


FRONTEND_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Acme Corp AI Receptionist</title>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    background: #f5f7fa; color: #1a1a2e; min-height: 100vh;
    display: flex; flex-direction: column; align-items: center; justify-content: center;
    padding: 1.5rem;
  }
  .container { max-width: 440px; width: 100%; }
  h1 { font-size: 1.6rem; text-align: center; margin-bottom: .25rem; }
  .subtitle { text-align: center; color: #555; margin-bottom: 2rem; font-size: .95rem; }
  .card {
    background: #fff; border-radius: 12px; padding: 2rem;
    box-shadow: 0 2px 12px rgba(0,0,0,.08);
  }
  .card h2 { font-size: 1.1rem; margin-bottom: 1.25rem; }
  label { display: block; font-size: .85rem; font-weight: 600; margin-bottom: .35rem; color: #333; }
  .phone-row { display: flex; gap: .5rem; margin-bottom: 1.25rem; }
  select, input {
    border: 1px solid #d0d5dd; border-radius: 8px; padding: .6rem .75rem;
    font-size: .95rem; outline: none; transition: border-color .15s;
  }
  select:focus, input:focus { border-color: #4f46e5; }
  select { width: 120px; flex-shrink: 0; background: #fff; }
  input { flex: 1; min-width: 0; }
  button {
    width: 100%; padding: .7rem; border: none; border-radius: 8px;
    background: #4f46e5; color: #fff; font-size: 1rem; font-weight: 600;
    cursor: pointer; transition: background .15s; display: flex;
    align-items: center; justify-content: center; gap: .5rem;
  }
  button:hover { background: #4338ca; }
  button:disabled { background: #a5b4fc; cursor: not-allowed; }
  .spinner {
    width: 18px; height: 18px; border: 2.5px solid rgba(255,255,255,.3);
    border-top-color: #fff; border-radius: 50%;
    animation: spin .6s linear infinite; display: none;
  }
  button.loading .spinner { display: inline-block; }
  button.loading .btn-text { display: none; }
  @keyframes spin { to { transform: rotate(360deg); } }
  .banner {
    margin-top: 1rem; padding: .75rem 1rem; border-radius: 8px;
    font-size: .9rem; display: none;
  }
  .banner.success { display: block; background: #ecfdf5; color: #065f46; border: 1px solid #a7f3d0; }
  .banner.error { display: block; background: #fef2f2; color: #991b1b; border: 1px solid #fecaca; }
  .footer { text-align: center; margin-top: 2rem; font-size: .8rem; color: #888; }
</style>
</head>
<body>
<div class="container">
  <h1>Acme Corp AI Receptionist</h1>
  <p class="subtitle">Enter a phone number below and our AI receptionist will call you.</p>

  <div class="card">
    <h2>Place a Call</h2>
    <label for="code">Country code</label>
    <div class="phone-row">
      <select id="code">
        <option value="+91" selected>+91 India</option>
        <option value="+1">+1 US/CA</option>
        <option value="+44">+44 UK</option>
        <option value="+61">+61 Australia</option>
        <option value="+49">+49 Germany</option>
        <option value="+33">+33 France</option>
        <option value="+81">+81 Japan</option>
        <option value="+86">+86 China</option>
        <option value="+971">+971 UAE</option>
        <option value="+65">+65 Singapore</option>
        <option value="+55">+55 Brazil</option>
        <option value="+27">+27 South Africa</option>
        <option value="+82">+82 South Korea</option>
        <option value="+39">+39 Italy</option>
        <option value="+34">+34 Spain</option>
        <option value="+7">+7 Russia</option>
        <option value="+62">+62 Indonesia</option>
        <option value="+60">+60 Malaysia</option>
        <option value="+966">+966 Saudi Arabia</option>
        <option value="+234">+234 Nigeria</option>
      </select>
      <input type="tel" id="phone" placeholder="Phone number" autocomplete="tel">
    </div>
    <button id="callBtn" type="button">
      <span class="btn-text">Place Call</span>
      <span class="spinner"></span>
    </button>
    <div id="banner" class="banner"></div>
  </div>

  <p class="footer">Powered by Pipecat &bull; Groq &bull; Deepgram &bull; Plivo</p>
</div>
<script>
(function() {
  const btn = document.getElementById('callBtn');
  const banner = document.getElementById('banner');
  const phoneInput = document.getElementById('phone');
  const codeSelect = document.getElementById('code');

  btn.addEventListener('click', async function() {
    const number = phoneInput.value.replace(/[^\\d]/g, '');
    if (!number) { showBanner('Please enter a phone number.', 'error'); return; }

    const to = codeSelect.value + number;
    btn.classList.add('loading');
    btn.disabled = true;
    banner.className = 'banner';

    try {
      const res = await fetch('/call', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ to: to })
      });
      const data = await res.json();
      if (res.ok) {
        showBanner('Call initiated! You should receive a call shortly.', 'success');
      } else {
        showBanner(data.error || 'Something went wrong.', 'error');
      }
    } catch (e) {
      showBanner('Network error. Please try again.', 'error');
    } finally {
      btn.classList.remove('loading');
      btn.disabled = false;
    }
  });

  function showBanner(msg, type) {
    banner.textContent = msg;
    banner.className = 'banner ' + type;
  }
})();
</script>
</body>
</html>
"""


@app.get("/")
async def root():
    """Serve the frontend UI."""
    return HTMLResponse(content=FRONTEND_HTML)


@app.get("/api")
async def api_info():
    """API info endpoint — programmatic access to service metadata."""
    return {
        "status": "ok",
        "service": "acme-corp-receptionist",
        "endpoints": {
            "/health": "Health check",
            "/answer": "Plivo Answer URL (POST)",
            "/call": "Outbound call (POST)",
            "/ws": "WebSocket audio streaming",
            "/logs": "View recent call logs",
        },
    }


@app.post("/call")
async def call(request: Request):
    """Initiate an outbound call to the given phone number."""
    body = await request.json()
    to_number = body.get("to")
    if not to_number:
        return JSONResponse({"error": "Missing 'to' field"}, status_code=400)

    auth_id = os.getenv("PLIVO_AUTH_ID")
    auth_token = os.getenv("PLIVO_AUTH_TOKEN")
    from_number = os.getenv("PLIVO_PHONE_NUMBER")
    railway_domain = os.getenv("RAILWAY_PUBLIC_DOMAIN")

    if not all([auth_id, auth_token, from_number]):
        return JSONResponse(
            {"error": "Plivo credentials not configured"},
            status_code=500,
        )

    answer_url = f"https://{railway_domain}/answer" if railway_domain else "http://localhost:8000/answer"

    client = plivo.RestClient(auth_id, auth_token)
    try:
        response = client.calls.create(
            from_=from_number,
            to_=to_number,
            answer_url=answer_url,
            answer_method="POST",
        )
        logger.info(f"Outbound call initiated to {to_number}, UUID: {response.request_uuid}")
        return {"status": "call_initiated", "request_uuid": response.request_uuid}
    except plivo.exceptions.PlivoRestError as e:
        logger.error(f"Plivo API error: {e}")
        return JSONResponse({"error": str(e)}, status_code=502)


@app.api_route("/answer", methods=["GET", "POST"])
async def answer(request: Request):
    """Plivo Answer URL - returns XML to stream audio via WebSocket."""
    params = dict(request.query_params)
    if request.method == "POST":
        form = await request.form()
        params.update(form)

    call_uuid = params.get("CallUUID", "unknown")
    caller = params.get("From", "unknown")
    callee = params.get("To", "unknown")

    logger.info(f"Incoming call: {caller} -> {callee} (UUID: {call_uuid})")

    # Build WebSocket URL from the request host (works with Railway's domain)
    host = request.headers.get("host", "localhost:8000")
    scheme = "wss" if request.url.scheme == "https" else "ws"

    # Railway provides HTTPS by default, so always use wss
    railway_url = os.getenv("RAILWAY_PUBLIC_DOMAIN")
    if railway_url:
        ws_url = f"wss://{railway_url}"
    else:
        ws_url = f"{scheme}://{host}"

    body_data = {"from": caller, "to": callee, "call_uuid": call_uuid}
    body_b64 = base64.b64encode(json.dumps(body_data).encode()).decode()
    ws_endpoint = f"{ws_url}/ws?body={body_b64}"

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Stream bidirectional="true" keepCallAlive="true" contentType="audio/x-mulaw;rate=8000">
        {ws_endpoint}
    </Stream>
</Response>"""

    return PlainTextResponse(content=xml, media_type="application/xml")


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for Plivo audio streaming."""
    await websocket.accept()

    body = None
    if "body" in websocket.query_params:
        try:
            body_b64 = websocket.query_params["body"]
            body = json.loads(base64.b64decode(body_b64).decode())
            logger.info(f"Call metadata: {body}")
        except Exception as e:
            logger.warning(f"Failed to decode body: {e}")

    try:
        from bot import bot
        from pipecat.runner.types import WebSocketRunnerArguments

        runner_args = WebSocketRunnerArguments(
            websocket=websocket,
            body=body,
        )
        await bot(runner_args)

    except Exception as e:
        logger.error(f"Bot error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if websocket.client_state != WebSocketState.DISCONNECTED:
            await websocket.close()


@app.get("/logs")
async def get_logs():
    """View recent call logs from the database."""
    conn = get_connection()
    if not conn:
        return JSONResponse(
            {"error": "Database not configured"},
            status_code=503,
        )

    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, caller_number, transcript, detected_intent, duration, created_at
            FROM receptionist_call_logs
            ORDER BY created_at DESC
            LIMIT 20
        """)
        rows = cur.fetchall()
        cur.close()

        logs = []
        for row in rows:
            logs.append({
                "id": row[0],
                "caller_number": row[1],
                "transcript": row[2],
                "detected_intent": row[3],
                "duration_seconds": row[4],
                "timestamp": row[5].isoformat() if row[5] else None,
            })

        return {"logs": logs, "count": len(logs)}

    except Exception as e:
        logger.error(f"Failed to fetch logs: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)
    finally:
        conn.close()


@app.get("/metrics")
async def get_metrics():
    """View per-turn latency metrics from recent calls."""
    conn = get_connection()
    if not conn:
        return JSONResponse({"error": "Database not configured"}, status_code=503)

    try:
        cur = conn.cursor()
        # Per-turn metrics from the dedicated table
        cur.execute("""
            SELECT
                m.call_log_id,
                c.caller_number,
                c.created_at,
                c.duration,
                m.turn_number,
                m.t0_t1_ms,
                m.t1_t2_ms,
                m.t0_t2_ms,
                m.target_met
            FROM call_latency_metrics m
            JOIN receptionist_call_logs c ON c.id = m.call_log_id
            ORDER BY m.call_log_id DESC, m.turn_number ASC
            LIMIT 200
        """)
        rows = cur.fetchall()

        # Aggregate by call
        calls = {}
        for row in rows:
            call_id = row[0]
            if call_id not in calls:
                calls[call_id] = {
                    "call_id": call_id,
                    "caller": row[1],
                    "timestamp": row[2].isoformat() if row[2] else None,
                    "duration_s": row[3],
                    "turns": [],
                }
            calls[call_id]["turns"].append({
                "turn": row[4],
                "t0_t1_ms": row[5],
                "t1_t2_ms": row[6],
                "t0_t2_ms": row[7],
                "target_met": row[8],
            })

        # Compute aggregates
        all_t0_t2 = [row[7] for row in rows if row[7] is not None]
        summary = {}
        if all_t0_t2:
            sorted_vals = sorted(all_t0_t2)
            summary = {
                "total_turns": len(all_t0_t2),
                "total_calls": len(calls),
                "avg_t0_t2_ms": round(sum(all_t0_t2) / len(all_t0_t2)),
                "p50_t0_t2_ms": sorted_vals[len(sorted_vals) // 2],
                "p95_t0_t2_ms": sorted_vals[int(len(sorted_vals) * 0.95)],
                "max_t0_t2_ms": max(all_t0_t2),
                "min_t0_t2_ms": min(all_t0_t2),
                "target_pass_rate": round(sum(1 for v in all_t0_t2 if v < 1500) / len(all_t0_t2) * 100),
            }

        cur.close()
        return {"summary": summary, "calls": list(calls.values())}

    except Exception as e:
        logger.error(f"Failed to fetch metrics: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)
    finally:
        conn.close()


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8000"))
    logger.info(f"Starting Acme Corp AI Receptionist on port {port}")
    logger.info("Endpoints:")
    logger.info(f"  GET      /health  - Health check")
    logger.info(f"  GET      /        - Frontend UI")
    logger.info(f"  GET      /api     - Service info (JSON)")
    logger.info(f"  GET/POST /answer  - Plivo Answer URL")
    logger.info(f"  WS       /ws      - WebSocket audio streaming")
    logger.info(f"  GET      /logs    - View call logs")
    logger.info(f"  GET      /metrics - View latency metrics")

    uvicorn.run(app, host="0.0.0.0", port=port)
