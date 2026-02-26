# Day 6: Deploy Voice AI to Railway

Move from local development (ngrok) to 24/7 cloud deployment on Railway.

---

## Prerequisites

- Completed Day 4 (Pipecat + Plivo) and optionally Day 5 (LiveKit)
- `.env` file configured with all API keys
- Node.js/npm installed (for Railway CLI)

---

## Project 1: Set Up Railway Account and CLI

### 1.1 Create Railway Account

1. Go to https://railway.app
2. Click **Sign Up** → Sign up with GitHub

### 1.2 Install Railway CLI

```bash
npm install -g @railway/cli
```

### 1.3 Login

```bash
railway login
```

This opens a browser window. Authorize the CLI.

### 1.4 Verify

```bash
railway whoami
```

### 1.5 Run verification script

```bash
cd /Users/saqlain.p/Assignments/Week2/Day6
python verify_railway_setup.py
```

Expected output: both checks PASS (CLI Installed, Logged In).

---

## Project 2: Prepare Pipecat Bot for Railway

The deployment-ready files are already in this folder:

| File | Purpose |
|------|---------|
| `server.py` | FastAPI server with `/health`, `/answer`, `/ws`, `/logs` |
| `bot.py` | Pipecat AI receptionist pipeline |
| `db.py` | Vercel Postgres call logging |
| `Dockerfile` | Docker image for Railway |
| `requirements.txt` | All Python dependencies |

### 2.1 Review the key changes from Day 4

- `/health` endpoint added for Railway monitoring
- `RAILWAY_PUBLIC_DOMAIN` env var replaces ngrok URL
- Server binds to `0.0.0.0` and uses `PORT` env var
- All config via environment variables (no hardcoded paths)

### 2.2 Test locally with Docker (optional)

```bash
cd /Users/saqlain.p/Assignments/Week2/Day6

docker build -t pipecat-bot .
docker run -p 8000:8000 --env-file .env pipecat-bot
```

### 2.3 Test the health endpoint

```bash
curl http://localhost:8000/health
```

Expected: `{"status":"healthy","service":"acme-corp-receptionist","version":"1.0.0"}`

---

## Project 3: Deploy to Railway

### 3.1 Initialize Railway project

```bash
cd /Users/saqlain.p/Assignments/Week2/Day6

railway init
```

Choose a project name (e.g., `pipecat-receptionist`).

### 3.2 Link to the project

```bash
railway link
```

Select the project you just created.

### 3.3 Set environment variables

```bash
railway variables set OPENAI_API_KEY="your-key"
railway variables set DEEPGRAM_API_KEY="your-key"
railway variables set ELEVENLABS_API_KEY="your-key"
railway variables set PLIVO_AUTH_ID="your-id"
railway variables set PLIVO_AUTH_TOKEN="your-token"
railway variables set POSTGRES_URL="your-postgres-url"
```

Or set them all at once via the Railway dashboard:
Dashboard → your project → Variables tab.

### 3.4 Deploy

```bash
railway up
```

Wait for the build to complete. Railway auto-detects the Dockerfile.

### 3.5 Generate a public domain

```bash
railway domain
```

Or go to Railway dashboard → Settings → Generate Domain.

You'll get a URL like: https://pipecat-receptionist-production.up.railway.app

### 3.6 Verify the deployment

```bash
python verify_deployment.py https://your-app.up.railway.app
```

### 3.7 Check logs

```bash
railway logs
railway logs --tail
```

---

## Project 4: Update Plivo to Use Railway

### 4.1 Update Plivo automatically

```bash
cd /Users/saqlain.p/Assignments/Week2/Day6

python update_plivo.py https://pipecat-receptionist-production.up.railway.app
```

This sets your Plivo phone number's Answer URL to `https://your-app.up.railway.app/answer`.

### 4.2 Or update manually

1. Go to https://console.plivo.com/phone-numbers/
2. Click your number
3. Set **Answer URL** to: `https://your-app.up.railway.app/answer`
4. Set **Method** to: `POST`
5. Save

### 4.3 Verify Plivo config

```bash
python verify_plivo.py
```

Confirms your number points to Railway (not ngrok).

### 4.4 Test with a phone call

1. Call your Plivo number
2. Talk to the AI receptionist
3. Watch logs in real time:

```bash
railway logs --tail
```

---

## Project 5: Verify Database Logging

### 5.1 Make a few test calls

Call your Plivo number 2-3 times and interact with the receptionist.

### 5.2 Verify logs in the database

```bash
cd /Users/saqlain.p/Assignments/Week2/Day6

python verify_db.py
```

This checks both `receptionist_call_logs` and `livekit_receptionist_call_logs` tables.

### 5.3 Check via Vercel dashboard

1. Go to Vercel Dashboard → Storage → Postgres
2. Click the **Data** tab
3. Select `receptionist_call_logs` table
4. Verify each call has:
   - Caller number
   - Transcript
   - Detected intent
   - Duration

---

## Project 6: Deploy LiveKit Agent to Railway (Optional)

Only if you built the LiveKit version on Day 5.

### 6.1 Create a separate Railway project

```bash
cd /Users/saqlain.p/Assignments/Week2/Day6

railway init
```

Name it something like `livekit-receptionist`.

### 6.2 Link and set variables

```bash
railway link

railway variables set LIVEKIT_API_KEY="your-key"
railway variables set LIVEKIT_API_SECRET="your-secret"
railway variables set LIVEKIT_URL="wss://your-project.livekit.cloud"
railway variables set OPENAI_API_KEY="your-key"
railway variables set DEEPGRAM_API_KEY="your-key"
railway variables set ELEVENLABS_API_KEY="your-key"
railway variables set POSTGRES_URL="your-postgres-url"
```

### 6.3 Deploy with the LiveKit Dockerfile

```bash
railway up --dockerfile Dockerfile.livekit
```

### 6.4 Test

- Call via phone (if SIP trunk from Day 5 is set up)
- Or test via browser at https://agents-playground.livekit.io/

### 6.5 Check logs

```bash
railway logs --tail
```

---

## End of Day 6 Checklist

- [ ] Understand why Railway is needed (vs Vercel — Railway supports long-running processes + WebSockets)
- [ ] Railway account created
- [ ] Railway CLI installed and working (`railway whoami`)
- [ ] Pipecat bot deployed to Railway
- [ ] Plivo pointing to Railway URL (not ngrok!)
- [ ] Phone calls working 24/7
- [ ] Call logs saved to Vercel Postgres
- [ ] No local processes needed — everything in cloud
- [ ] (Optional) LiveKit agent also deployed to Railway

---

## Quick Reference

| Command | What it does |
|---------|-------------|
| `railway login` | Authenticate CLI |
| `railway whoami` | Check logged-in user |
| `railway init` | Create new project |
| `railway link` | Link directory to project |
| `railway variables set KEY="val"` | Set env variable |
| `railway up` | Deploy current directory |
| `railway domain` | Generate public URL |
| `railway logs` | View deployment logs |
| `railway logs --tail` | Stream logs in real time |
| `railway status` | Check deployment status |
| `railway down` | Take down deployment |

---

## File Reference

| File | Project | Purpose |
|------|---------|---------|
| `verify_railway_setup.py` | 1 | Verify CLI install and login |
| `server.py` | 2 | FastAPI server (health, answer, ws, logs) |
| `bot.py` | 2 | Pipecat receptionist pipeline |
| `db.py` | 2 | Postgres call logging |
| `Dockerfile` | 2 | Docker image for Pipecat bot |
| `deploy.sh` | 3 | Interactive deployment helper |
| `verify_deployment.py` | 3 | Check Railway endpoints |
| `update_plivo.py` | 4 | Set Plivo Answer URL to Railway |
| `verify_plivo.py` | 4 | Confirm Plivo configuration |
| `verify_db.py` | 5 | Query and validate call logs |
| `livekit_agent.py` | 6 | LiveKit receptionist agent |
| `livekit_db.py` | 6 | LiveKit DB logging (separate table) |
| `Dockerfile.livekit` | 6 | Docker image for LiveKit agent |
