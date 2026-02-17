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
from fastapi.responses import PlainTextResponse, JSONResponse
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
    logger.info("Server ready.")


@app.get("/health")
async def health():
    """Health check endpoint for Railway monitoring."""
    return {
        "status": "healthy",
        "service": "acme-corp-receptionist",
        "version": "1.0.0",
    }


@app.get("/")
async def root():
    """Root endpoint - basic service info."""
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


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8000"))
    logger.info(f"Starting Acme Corp AI Receptionist on port {port}")
    logger.info("Endpoints:")
    logger.info(f"  GET      /health - Health check")
    logger.info(f"  GET      /       - Service info")
    logger.info(f"  GET/POST /answer - Plivo Answer URL")
    logger.info(f"  WS       /ws     - WebSocket audio streaming")
    logger.info(f"  GET      /logs   - View call logs")

    uvicorn.run(app, host="0.0.0.0", port=port)
