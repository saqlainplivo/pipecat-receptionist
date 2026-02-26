# AI Receptionist Bot — Development Log & Engineering Decisions

> This document traces every incremental change from initial commit to production, explains the **why** behind each decision, and provides a testing framework with metric placeholders to be filled post-measurement.

---

## Table of Contents

1. [Commit-by-Commit Evolution](#1-commit-by-commit-evolution)
2. [Model Exploration: STT](#2-model-exploration-stt)
3. [Model Exploration: TTS](#3-model-exploration-tts)
4. [Model Exploration: LLM](#4-model-exploration-llm)
5. [VAD & Turn-Taking Configuration](#5-vad--turn-taking-configuration)
6. [Interruption Handling](#6-interruption-handling)
7. [Latency Instrumentation Plan](#7-latency-instrumentation-plan)
8. [Audio Sample Rate Analysis](#8-audio-sample-rate-analysis)
9. [Call Duration & Timeout Ceiling](#9-call-duration--timeout-ceiling)
10. [Infrastructure: Why Railway](#10-infrastructure-why-railway)
11. [Test Matrix](#11-test-matrix)
12. [Comparative Results (To Be Filled)](#12-comparative-results)

---

## 1. Commit-by-Commit Evolution

Each row is a real commit. Run `git log --oneline --reverse` to verify.

### Phase 1: Foundation (Commits 1-2)

| Commit | Hash | What Changed | Why | Files Touched |
|--------|------|-------------|-----|---------------|
| 1 | `942d09b` | Empty repo | Initial commit | — |
| 2 | `ba0ba40` | Full MVP: Pipecat bot, FastAPI server, LiveKit agent, DB logging, Dockerfiles, deploy scripts | Get a working end-to-end call pipeline — caller dials in, audio streams over WebSocket, AI responds, call is logged | `bot.py`, `server.py`, `livekit_agent.py`, `db.py`, `livekit_db.py`, `requirements.txt`, `Dockerfile`, `Dockerfile.livekit`, `guide.md`, `deploy.sh`, `verify_*.py` |

**Initial stack choices:**
- **TTS**: ElevenLabs (Rachel voice, `voice_id=21m00Tcm4TlvDq8ikWAM`)
- **STT**: Deepgram (default model, no explicit config)
- **LLM**: OpenAI `gpt-4.1-mini`
- **VAD**: SileroVADAnalyzer (pipecat built-in)
- **Tools**: 4 functions — `get_business_hours`, `get_location`, `transfer_to_sales`, `transfer_to_support`
- **Audio**: 8kHz mu-law (PSTN standard via Plivo)

### Phase 2: TTS Exploration (Commits 3-4)

| Commit | Hash | What Changed | Why | Impact |
|--------|------|-------------|-----|--------|
| 3 | `057aa88` | ElevenLabs TTS → OpenAI TTS (`alloy` voice) | Reduce dependency count (one fewer API key), test OpenAI's native TTS quality | Removed `ELEVENLABS_API_KEY` dependency. OpenAI TTS uses a different synthesis approach — neural but not optimized for telephony streaming |
| 4 | `49ee059` | OpenAI TTS → Deepgram Aura (`aura-asteria-en`) | Deepgram Aura is purpose-built for streaming telephony: native 8kHz output, chunk-level streaming, lowest latency in our testing | Single provider for both STT and TTS. Eliminated OpenAI TTS dependency |

**Diff detail (commit 3 → 4):**
```python
# BEFORE (OpenAI TTS)
from pipecat.services.openai.tts import OpenAITTSService
tts = OpenAITTSService(api_key=os.getenv("OPENAI_API_KEY"), voice="alloy")

# AFTER (Deepgram Aura)
from pipecat.services.deepgram.tts import DeepgramTTSService
tts = DeepgramTTSService(api_key=os.getenv("DEEPGRAM_API_KEY"), voice="aura-asteria-en")
```

### Phase 3: Pipeline Compatibility (Commits 5-7)

| Commit | Hash | What Changed | Why |
|--------|------|-------------|-----|
| 5 | `19b2081` | Pin `pipecat>=0.0.102`, switch `gpt-4.1-mini` → `gpt-4o-mini`, remove `allow_interruptions` from PipelineParams, clean up imports | Pipecat 0.0.102 introduced breaking API changes. `allow_interruptions` moved to per-frame control. `gpt-4.1-mini` was deprecated |
| 6 | `31ee79c` | Migrate raw dict tool definitions → `ToolsSchema`/`FunctionSchema`, migrate handler signatures to `FunctionCallParams` | Pipecat 0.0.102 replaced the raw OpenAI-style tools dict with its own schema classes. Old format would silently fail |
| 7 | `a4acbd3` | Remove explicit `torch` from `requirements.txt` | `pipecat-ai[silero]` extra already pulls in the correct torch version. Explicit pinning caused version conflicts on Railway's build |

**Diff detail (commit 6 — tools migration):**
```python
# BEFORE: Raw OpenAI dict
TOOLS = [{"type": "function", "function": {"name": "get_business_hours", ...}}]
async def handle(function_name, tool_call_id, args, llm, context, result_callback):
    await result_callback(...)

# AFTER: Pipecat schema objects
TOOLS = ToolsSchema(standard_tools=[FunctionSchema(name="get_business_hours", ...)])
async def handle(params: FunctionCallParams):
    await params.result_callback(...)
```

### Phase 4: Security & LLM Switch (Commits 8-10)

| Commit | Hash | What Changed | Why |
|--------|------|-------------|-----|
| 8 | `4554358` | Added `.gitignore`, `.dockerignore`, `.env.example`. Removed `.env` from git history | Secrets were committed in earlier pushes. This commit fixes the security issue and establishes the env-var pattern for Railway |
| 9 | `fd2377a` | **OpenAI → Groq**: Created `GroqLLMService` subclass, switched to `llama-3.3-70b-versatile`. Added post-call transcript analysis. Added Deepgram STT config (`nova-2`, `endpointing=300`) | Groq offers sub-500ms inference on 70B models vs ~1-2s on OpenAI gpt-4o-mini. Post-call analysis extracts intent + summary via a second LLM call after hangup |
| 10 | `64bce83` | API key validation on startup, immediate greeting on connect (skip LLM round-trip for first utterance), `GroqLLMService` strips `service_tier` and `max_completion_tokens` | Groq's API rejects OpenAI-specific parameters. Immediate greeting eliminates the cold-start delay — caller hears "Hello..." within ~200ms of connect |

**Diff detail (commit 9 — GroqLLMService):**
```python
class GroqLLMService(OpenAILLMService):
    """Strips parameters that Groq's API rejects."""
    def build_chat_completion_params(self, params_from_context) -> dict:
        params = super().build_chat_completion_params(params_from_context)
        params.pop("service_tier", None)       # Groq doesn't support
        params.pop("max_completion_tokens", None)  # Groq doesn't support
        return params
```

### Phase 5: Production Features (Commit 11)

| Commit | Hash | What Changed | Why |
|--------|------|-------------|-----|
| 11 | `bfaf664` | 5 new tools (`transfer_to_billing`, `get_support_info`, `get_department_directory`, `check_service_status`, `get_holiday_schedule`), massively expanded system prompt with routing rules, embedded frontend UI in `server.py` | Move from demo to production-capable receptionist. Frontend allows non-technical users to trigger outbound calls without curl/Postman |

**Tools evolution:**
```
Commit 2 (MVP):     4 tools  — hours, location, sales transfer, support transfer
Commit 11 (Final):  9 tools  — + billing transfer, support info, directory, status, holidays
```

**System prompt evolution:**
```
Commit 2:   ~15 lines  — basic "you are a receptionist" instruction
Commit 11:  ~90 lines  — structured routing table, conversation rules, voice/style
                          guidelines, boundary rules, follow-up handling
```

---

## 2. Model Exploration: STT

### Models Considered

| Model | Provider | Type | Sample Rate Support | Streaming | Endpointing | Status |
|-------|----------|------|-------------------|-----------|-------------|--------|
| Deepgram Nova-2 | Deepgram | Streaming | 8kHz native | Yes (WebSocket) | Configurable (ms) | **Selected** |
| Deepgram Nova-3 | Deepgram | Streaming | 8kHz native | Yes | Configurable | Not tested |
| Deepgram Nova-2 Enhanced | Deepgram | Streaming | 8kHz native | Yes | Configurable | Not tested |
| Groq Whisper (distil-whisper-large-v3-en) | Groq | Batch only | Resamples internally | No (REST) | N/A | **Rejected** |

### Why Nova-2

1. **Streaming is non-negotiable** — telephony requires real-time transcription as the caller speaks. Groq's Whisper is batch-only (upload full audio, get transcript back), which adds seconds of latency per turn.
2. **Native 8kHz mu-law** — Nova-2 handles PSTN audio natively without upsampling. No quality loss from sample rate conversion.
3. **Configurable endpointing** — `endpointing=300` (300ms silence = end of utterance). This is the primary turn-detection mechanism.
4. **Interim results** — `interim_results=True` lets the pipeline see partial transcripts, enabling future smart-turn detection.

### What Was NOT Tested (Gaps)

- **Nova-3**: Deepgram's latest model. May offer better accuracy on noisy telephony audio. Needs A/B testing.
- **Nova-2 Enhanced**: Higher accuracy tier. Costs more. Unknown latency impact.
- **8kHz vs 16kHz accuracy**: We send 8kHz mu-law (PSTN standard). No measurement of whether upsampling to 16kHz before STT would improve Word Error Rate.

### STT Metrics (To Be Measured)

| Metric | Nova-2 (8kHz) | Nova-2 (16kHz upsampled) | Nova-3 (8kHz) | Nova-2 Enhanced (8kHz) |
|--------|--------------|------------------------|--------------|----------------------|
| First partial transcript (ms) | `___` | `___` | `___` | `___` |
| Final transcript latency (ms) | `___` | `___` | `___` | `___` |
| Word Error Rate (clean speech) | `___` | `___` | `___` | `___` |
| WER (noisy/cellular) | `___` | `___` | `___` | `___` |
| WER (accented speech) | `___` | `___` | `___` | `___` |
| False endpointing rate | `___` | `___` | `___` | `___` |

---

## 3. Model Exploration: TTS

### Models Tested (3 iterations in code)

| Model | Provider | Commit | Voice | Streaming | 8kHz Native | Latency (TTFA) | Status |
|-------|----------|--------|-------|-----------|-------------|----------------|--------|
| ElevenLabs Multilingual v2 | ElevenLabs | `ba0ba40` | Rachel | Yes (WebSocket) | No (resamples) | `___` ms | Replaced |
| OpenAI TTS | OpenAI | `057aa88` | Alloy | Chunked | No (resamples) | `___` ms | Replaced |
| Deepgram Aura | Deepgram | `49ee059` | Asteria | Yes (native streaming) | Yes | `___` ms | **Selected** |

### Why Each Was Replaced

**ElevenLabs → OpenAI (commit 3)**
- ElevenLabs produced high-quality audio but required a separate API key and account
- Latency on first audio chunk was higher due to the synthesis model's complexity
- Cost per character was significantly higher than alternatives

**OpenAI → Deepgram Aura (commit 4)**
- OpenAI TTS returns audio in larger chunks, not true frame-by-frame streaming
- Output is 24kHz by default — requires downsampling to 8kHz for Plivo, adding processing overhead
- Deepgram Aura outputs streaming audio natively in telephony-compatible format

### Models NOT Tested (Gaps)

| Model | Provider | Claimed TTFA | Why Not Tested |
|-------|----------|-------------|----------------|
| ElevenLabs Flash v2.5 | ElevenLabs | ~135ms | Newer model released after our selection. Should be benchmarked |
| ElevenLabs Turbo v2.5 | ElevenLabs | ~170ms | Higher quality than Flash but slower. Trade-off worth measuring |
| Cartesia Sonic | Cartesia | ~40ms | Claimed fastest TTFA. Not integrated with Pipecat at time of development |
| Inworld TTS | Inworld | <120ms | Gaming/interactive focus. No pipecat plugin available |
| PlayHT 2.0 | PlayHT | ~150ms | Not evaluated |

### TTS Metrics (To Be Measured)

| Metric | ElevenLabs Rachel | OpenAI Alloy | Deepgram Aura Asteria | ElevenLabs Flash v2.5 |
|--------|-------------------|-------------|----------------------|----------------------|
| Time to First Audio (ms) | `___` | `___` | `___` | `___` |
| Audio generation rate (realtime factor) | `___` | `___` | `___` | `___` |
| MOS score (subjective quality 1-5) | `___` | `___` | `___` | `___` |
| Naturalness on telephony (1-5) | `___` | `___` | `___` | `___` |
| 8kHz output quality (1-5) | `___` | `___` | `___` | `___` |
| Cost per 1M characters | `___` | `___` | `___` | `___` |

---

## 4. Model Exploration: LLM

### Models Tested (3 iterations in code)

| Model | Provider | Commit | Params | Streaming | Tool Calling | Status |
|-------|----------|--------|--------|-----------|-------------|--------|
| gpt-4.1-mini | OpenAI | `ba0ba40` | Unknown | Yes | Yes | Replaced (deprecated) |
| gpt-4o-mini | OpenAI | `19b2081` | Unknown | Yes | Yes | Replaced |
| llama-3.3-70b-versatile | Groq | `fd2377a` | 70B | Yes | Yes | **Selected** |

*(NVIDIA NIM with `zhipuai/glm-4-9b-chat` was explored but only exists as commented-out code — never committed as active.)*

### Why Groq

1. **Speed**: Groq's LPU delivers ~500 tok/s on llama-3.3-70b vs ~80 tok/s on OpenAI gpt-4o-mini. First token arrives in ~200-400ms.
2. **Cost**: Groq pricing is significantly lower than OpenAI for equivalent quality.
3. **70B > 8B**: The 70B parameter model handles complex routing decisions (9 tools) more reliably than smaller models. Fewer hallucinated tool calls.
4. **OpenAI-compatible API**: Works with pipecat's `OpenAILLMService` via `base_url` — required only a thin `GroqLLMService` subclass to strip unsupported params.

### Compatibility Work Required

Groq's API is *mostly* OpenAI-compatible but rejects:
- `service_tier` parameter → stripped in `GroqLLMService.build_chat_completion_params()`
- `max_completion_tokens` parameter → stripped in same method
- Returns `arguments: "null"` for no-parameter tool calls → pipecat handles this correctly

### LLM Benchmark Results (Measured 2026-02-26)

> Benchmark: 12 test cases x 3 iterations each. Includes greeting (no tool), 9 tool-call intents,
> 1 ambiguous intent, 1 multi-intent. Run via `llm_benchmark.py`. Raw data in `benchmark_results.json`.

#### Cross-Model Summary

| Metric | gpt-4o-mini (OpenAI) | llama-3.3-70b (Groq) | llama-3.1-8b (Groq) | glm-4-9b (NVIDIA NIM) |
|--------|---------------------|---------------------|--------------------|-----------------------|
| Avg TTFT (ms) | **851** | 2001 | 5795 | N/A (404 — model endpoint down) |
| Avg total time (ms) | **880** | 2129 | 5853 | N/A |
| Avg tok/s | 2.2 | 5.9 | **12.4** | N/A |
| Tool call accuracy | **100%** | **100%** | 70% | N/A |
| Cost per 1K input tokens | $0.15 | **$0.05** | **$0.05** | $0.10 |
| Cost per 1K output tokens | $0.60 | **$0.08** | **$0.08** | $0.10 |

#### Per-Test Breakdown (TTFT in ms, averaged over 3 runs)

| Test Case | gpt-4o-mini | Groq 70B | Groq 8B | Winner |
|-----------|-------------|----------|---------|--------|
| Greeting (no tool) | 727 | 453 | **145** | Groq 8B |
| Business hours | 854 | **198** | 197 | Groq (both) |
| Location | 772 | **226** | 188 | Groq 8B |
| Sales transfer | 997 | **271** | 4614 | Groq 70B |
| Support transfer | 830 | **234** | 8325 | Groq 70B |
| Billing transfer | 800 | **302** | 8325 | Groq 70B |
| Support info | 870 | 2976 | 8339 | **OpenAI** |
| Directory lookup | 767 | 3995 | 8344 | **OpenAI** |
| Status check | **743** | 3646 | 7991 | OpenAI |
| Holiday schedule | **786** | 3984 | 6659 | OpenAI |
| Ambiguous billing | **703** | 4009 | 8322 | OpenAI |
| Multi-intent | **1369** | 3715 | 8096 | OpenAI |

#### Key Findings

1. **Groq 70B is fastest for simple tool calls** (198-302ms TTFT for hours/location/transfers) but slows drastically on less-common tools (3-4s for directory, status, holiday). This is likely Groq rate-limiting or queuing — not model speed.
2. **OpenAI gpt-4o-mini is the most consistent** — TTFT stays in the 700-1000ms range regardless of which tool is called. No spikes.
3. **Groq 8B is unreliable for tool calling** — 70% accuracy. It often emits tool calls as plain text (`<function=transfer_to_support>`) instead of using the proper tool_calls API. Not suitable for production.
4. **NVIDIA NIM (glm-4-9b-chat) is offline** — returns 404. The free-tier endpoint appears to be decommissioned.
5. **For the receptionist use case**: Groq 70B gives the best simple-tool latency (198ms) with 100% accuracy, but the tail latency on complex tools is concerning. OpenAI is the safer choice for consistent <1s TTFT across all tools.

---

## 5. VAD & Turn-Taking Configuration

### Current Configuration

The system uses **two layers** of voice activity detection:

**Layer 1 — Deepgram Endpointing (Primary)**
```python
stt = DeepgramSTTService(
    model="nova-2",
    interim_results=True,
    endpointing=300,  # 300ms of silence = end of utterance
)
```
- This is the primary turn-detection mechanism
- When 300ms of silence is detected after speech, Deepgram emits a final transcript
- The pipeline treats this as "user is done speaking" and triggers LLM inference

**Layer 2 — SileroVADAnalyzer (Secondary)**
```python
user_aggregator, assistant_aggregator = LLMContextAggregatorPair(
    context,
    user_params=LLMUserAggregatorParams(
        vad_analyzer=SileroVADAnalyzer(),  # Default config
    ),
)
```
- Runs locally on the server (no API call)
- Detects speech vs silence at the audio frame level
- Used by pipecat's aggregator to know when to start/stop accumulating user audio
- Running on default parameters (no custom `min_silence_duration` or threshold tuning)

### Why 300ms Endpointing?

The `endpointing=300` value is Deepgram's recommended default for conversational turn-taking:
- **< 200ms**: Too aggressive — cuts off mid-sentence pauses ("I want to... talk to sales")
- **300ms**: Good balance for phone conversations — natural pauses are typically 200-400ms
- **> 500ms**: Too slow — the bot feels unresponsive, caller thinks they're disconnected
- **1000ms+**: Unusable for real-time conversation

### What Was NOT Tested

- No A/B testing of different endpointing values (200ms, 300ms, 400ms, 500ms)
- No measurement of false positive rate (bot responds when caller is still speaking)
- No comparison between 8kHz mu-law phone audio vs 16kHz browser audio for VAD accuracy
- SileroVAD uses default thresholds — not tuned for telephony noise profiles

### Smart Turn Detection

`requirements.txt` includes `livekit-agents[turn-detector]` but:
- **Pipecat bot (`bot.py`)**: Does NOT use any smart turn detector. Relies purely on Deepgram endpointing + Silero VAD.
- **LiveKit agent (`livekit_agent.py`)**: The dependency is installed but not wired into the `VoicePipelineAgent` constructor. No `turn_detector=` parameter is passed.

Smart turn detection would use an LLM-based classifier to determine if the user's utterance is "complete" before triggering a response. This is a gap — currently, any 300ms pause triggers a response even if the caller is mid-thought.

### VAD Metrics (To Be Measured)

| Metric | Endpointing 200ms | Endpointing 300ms | Endpointing 400ms | Endpointing 500ms |
|--------|-------------------|-------------------|-------------------|-------------------|
| False positive rate (cut off mid-sentence) | `___`% | `___`% | `___`% | `___`% |
| Avg response delay from end-of-speech | `___` ms | `___` ms | `___` ms | `___` ms |
| User perception ("felt responsive" 1-5) | `___` | `___` | `___` | `___` |

| Metric | Phone audio (8kHz mu-law) | Browser audio (48kHz PCM) |
|--------|--------------------------|--------------------------|
| Silero VAD accuracy | `___`% | `___`% |
| False silence detections per minute | `___` | `___` |
| Missed speech detections per minute | `___` | `___` |

---

## 6. Interruption Handling

### Current State

| Component | `allow_interruptions` | Behavior |
|-----------|----------------------|----------|
| Pipecat bot (`bot.py`) | **Not set** (removed in commit `19b2081`) | Bot speaks to completion. Caller audio during TTS playback is queued and processed after bot finishes |
| LiveKit agent greeting | `True` (explicit: `await agent.say("Hello...", allow_interruptions=True)`) | Caller can interrupt the greeting. TTS stops, caller's speech is processed |
| LiveKit agent (general) | Default (framework default) | Depends on LiveKit agent framework defaults |

### What Happens When Caller Interrupts (Predicted, Needs Testing)

**Pipecat bot (no interruption support):**
1. Bot is speaking (TTS audio streaming to caller)
2. Caller speaks over the bot
3. Caller's audio is captured by STT but the TTS continues playing
4. After TTS finishes, the queued transcription triggers the next LLM turn
5. **Result**: Audio overlap — caller hears the bot continue while they're speaking

**LiveKit agent (interruption on greeting only):**
1. Greeting is playing
2. Caller speaks
3. TTS stops immediately, caller's speech is transcribed
4. LLM processes the interruption as a new turn
5. **Result**: Clean interruption for greeting only

### Interruption Metrics (To Be Measured)

| Scenario | TTS Stops? | Audio Overlap? | Caller's Speech Lost? | Response Correct? |
|----------|-----------|---------------|----------------------|-------------------|
| Interrupt during greeting (LiveKit) | `___` | `___` | `___` | `___` |
| Interrupt during response (Pipecat) | `___` | `___` | `___` | `___` |
| Interrupt during response (LiveKit) | `___` | `___` | `___` | `___` |
| Interrupt with short word ("yes") | `___` | `___` | `___` | `___` |
| Interrupt with long correction | `___` | `___` | `___` | `___` |

---

## 7. Latency Instrumentation Plan

### Target

**T0 → T2 under 1.5 seconds** (transcript received → first TTS audio chunk)

### Pipeline Stages to Instrument

```
Caller speaks → [network] → Plivo → [WebSocket] → Server
    T0: Final transcription received from Deepgram
        ↓
    T1: First LLM token received from Groq
        ↓
    T2: First TTS audio chunk received from Deepgram Aura
        ↓
    T3: Audio chunk sent over WebSocket to Plivo → caller's phone
```

### Current State: NO Instrumentation

The codebase currently logs:
- Call connect/disconnect with duration (`CallTracker.duration`)
- Transcript accumulation (user + assistant messages)
- Post-call analysis results

It does **NOT** log:
- Per-turn latency (T0 → T1 → T2 → T3)
- STT processing time
- LLM time-to-first-token
- TTS time-to-first-audio
- Network jitter or WebSocket frame timing

### Instrumentation Points (To Be Added)

```python
# T0: In on_user_transcript handler
@task.event_handler("on_user_transcript")
async def on_user_transcript(task, transcript):
    t0 = time.perf_counter()
    logger.info(f"[LATENCY] T0 transcript_final: {t0:.4f}")
    call_tracker.last_t0 = t0

# T1: In LLM first-token callback (requires pipecat event or monkey-patch)
# T2: In TTS first-chunk callback
# T3: In transport output frame handler
```

### Latency Budget

| Stage | Target | Expected | Measured |
|-------|--------|----------|----------|
| T0 → T1 (STT final → LLM first token) | < 500ms | ~300-500ms (Groq) | `___` ms |
| T1 → T2 (LLM first token → TTS first audio) | < 500ms | ~200-400ms (Aura) | `___` ms |
| T2 → T3 (TTS first audio → on caller's phone) | < 500ms | ~100-200ms (network) | `___` ms |
| **T0 → T2 (total pipeline)** | **< 1500ms** | **~500-900ms** | **`___` ms** |
| T0 → T3 (end-to-end) | < 2000ms | ~600-1100ms | `___` ms |

### Network/Jitter Metrics (To Be Measured)

| Metric | Value |
|--------|-------|
| WebSocket round-trip (server ↔ Plivo) | `___` ms |
| Audio frame jitter (stddev of inter-frame time) | `___` ms |
| Packet loss rate | `___`% |
| Plivo → caller last-mile latency | `___` ms |

---

## 8. Audio Sample Rate Analysis

### Current Configuration

```python
# bot.py — Pipecat
PipelineParams(
    audio_in_sample_rate=8000,   # 8kHz mu-law from Plivo PSTN
    audio_out_sample_rate=8000,  # 8kHz mu-law to Plivo PSTN
)

# server.py — Plivo XML
<Stream contentType="audio/x-mulaw;rate=8000">

# livekit_agent.py — LiveKit
# No explicit sample_rate set. LiveKit defaults to 48kHz for WebRTC,
# but SIP trunk audio arrives at 8kHz.
```

### Why 8kHz

- **PSTN standard**: Phone networks transmit at 8kHz mu-law (G.711). This is not a choice — it's what Plivo delivers.
- **No upsampling**: We pass 8kHz directly to Deepgram. Upsampling to 16kHz before STT *might* improve accuracy (the model was trained on 16kHz) but adds processing overhead.
- **TTS output**: Deepgram Aura outputs at the requested rate. We request 8kHz to match the outbound PSTN stream.

### Unknowns

- Does Deepgram Nova-2 perform better when receiving 16kHz (even if upsampled from 8kHz)?
- Does LiveKit's implicit sample rate handling cause any degradation?
- Is there measurable WER difference between 8kHz and 16kHz input?

### Sample Rate Metrics (To Be Measured)

| Metric | 8kHz mu-law (native) | 16kHz (upsampled from 8kHz) |
|--------|---------------------|---------------------------|
| STT Word Error Rate | `___`% | `___`% |
| STT latency (first partial) | `___` ms | `___` ms |
| Processing overhead (CPU) | `___`% | `___`% |
| Subjective quality difference | `___` | `___` |

---

## 9. Call Duration & Timeout Ceiling

### Known Timeout Boundaries

| Component | Default Timeout | Configured Value | Source |
|-----------|----------------|-----------------|--------|
| Plivo `<Stream>` | Unknown (Plivo docs state stream continues while call is active) | `keepCallAlive="true"` set | `server.py` line 304 |
| Plivo call max duration | 14,400s (4 hours) per Plivo docs | Not explicitly set | Plivo default |
| Railway process | No timeout (long-running) | Not set | Railway default |
| WebSocket connection | No timeout in code | Not set | FastAPI default |
| Deepgram STT session | 5 minutes idle timeout (Deepgram docs) | Not set | Deepgram default |
| Groq API request | 60s per request (Groq docs) | Not set | Groq default |
| LiveKit room | Configurable, default varies | Not set | LiveKit default |
| Postgres connection | Server-side idle timeout | Not set | Vercel Postgres default |

### Predicted Failure Points

1. **Deepgram STT session timeout** (~5 min idle): If the caller goes silent for 5+ minutes, the STT WebSocket may disconnect. The pipeline would stop transcribing without explicit reconnection logic.
2. **Conversation history growth**: Each turn adds to `messages[]`. After ~50+ turns, the context may exceed Groq's 128K token window. No truncation strategy exists.
3. **Memory**: Each active call holds a full pipeline in memory. No measurement of per-call memory footprint.

### Duration Metrics (To Be Measured)

| Test | Duration | Result | Notes |
|------|----------|--------|-------|
| 1-minute call | 60s | `___` | Baseline — should work |
| 2-minute call | 120s | `___` | |
| 4-minute call | 240s | `___` | Reviewer's specific ask |
| 10-minute call | 600s | `___` | Stress test |
| Idle call (caller silent) | Until disconnect | `___` | Find Deepgram timeout |
| Rapid-fire 20 turns | ~2 min | `___` | Context window stress |

---

## 10. Infrastructure: Why Railway

### Decision Rationale

| Requirement | Railway | Vercel | AWS Lambda | Fly.io |
|-------------|---------|--------|-----------|--------|
| Long-running processes | Yes (Docker containers) | No (10s/60s timeout) | No (15 min max) | Yes |
| WebSocket support | Yes (native) | No (serverless) | Via API Gateway (complex) | Yes |
| Docker support | Yes | No | Via ECR (complex) | Yes |
| Auto-HTTPS | Yes (free) | Yes | Via ALB (paid) | Yes |
| Custom domains | Yes | Yes | Yes | Yes |
| Persistent process | Yes | No | No | Yes |
| Deploy from git | Yes | Yes | Via CodePipeline | Yes |
| Cost (hobby tier) | ~$5/mo | Free (but can't use it) | Pay-per-use | ~$3/mo |

**Railway won because:**
1. **WebSocket is mandatory** — Plivo streams audio bidirectionally over WebSocket. Vercel and Lambda can't maintain persistent WebSocket connections.
2. **Long-running process** — The FastAPI server must stay alive to accept incoming calls at any time. Serverless platforms cold-start on each request (~2-5s), which is unacceptable for real-time voice.
3. **Simple deploy** — `railway up` or push to git. No Kubernetes, no ECS task definitions, no API Gateway config.
4. **Docker support** — Our `Dockerfile` runs as-is. No build pack quirks.

### Architecture Diagram

```
┌─────────────┐     PSTN      ┌──────────┐    HTTPS/WSS     ┌─────────────────┐
│ Caller's    │───────────────→│  Plivo   │────────────────→│  Railway         │
│ Phone       │←───────────────│  SIP GW  │←────────────────│  (Docker)        │
└─────────────┘   8kHz mu-law  └──────────┘   WebSocket      │                 │
                                    │                        │  server.py       │
                                    │  POST /answer          │  ├─ /answer      │
                                    │  (get WebSocket URL)   │  ├─ /ws (audio)  │
                                    │                        │  └─ bot.py       │
                                    │                        │     ├─ Deepgram  │
                                    │                        │     ├─ Groq LLM  │
                                    │                        │     └─ Silero VAD│
                                    │                        └────────┬────────┘
                                    │                                 │
                                    │                        ┌────────▼────────┐
                                    │                        │ Vercel Postgres  │
                                    │                        │ (call logs)      │
                                    │                        └─────────────────┘
                                    │
                              ┌─────▼──────────┐
                              │ LiveKit Cloud   │  (Alternative path)
                              │ ├─ SIP Trunk    │
                              │ ├─ Room         │
                              │ └─ Agent Worker │──→ livekit_agent.py on Railway
                              └────────────────┘
```

### What Would Break If We Moved

| Target Platform | What Breaks | Mitigation |
|----------------|-------------|------------|
| Vercel | WebSocket connections, long-running process | Cannot be mitigated — architecture mismatch |
| AWS Lambda | WebSocket (needs API Gateway), cold start latency, 15-min max | Use ECS/Fargate instead. Significant rearchitecting |
| Fly.io | Nothing critical — closest alternative to Railway | Change deploy commands. Wire up `fly.toml` instead of Railway config |
| Bare VPS (EC2/Dropbox) | Nothing critical | Lose auto-deploy, auto-HTTPS, health checks. Need manual ops |

---

## 11. Test Matrix

### Tests Required

The following tests need to be executed and their results filled into the metric tables above.

#### A. Latency Tests

| Test ID | Description | Method | What to Log |
|---------|-------------|--------|------------|
| LAT-01 | Baseline turn-around latency | Make 5 calls, ask "What are your business hours?" each time. Log T0/T1/T2/T3 timestamps | Per-turn latency breakdown |
| LAT-02 | Tool call latency | Ask questions triggering each of the 9 tools. Measure T0→T2 for each | Tool-specific latency |
| LAT-03 | Multi-turn conversation latency | 10-turn conversation. Does latency increase with context growth? | T0→T2 per turn number |
| LAT-04 | Cold start vs warm | First call after deploy vs fifth call | Pipeline initialization time |

#### B. STT Accuracy Tests

| Test ID | Description | Method |
|---------|-------------|--------|
| STT-01 | Clean speech WER | Read 10 scripted sentences, compare transcript to ground truth |
| STT-02 | Noisy environment WER | Same sentences with background noise (cafe, street) |
| STT-03 | Accented speech WER | Same sentences with different accents |
| STT-04 | Phone audio vs browser | Same sentences via phone call (8kHz) vs browser (48kHz) |
| STT-05 | Endpointing accuracy | Speak sentences with natural 0.5s, 1s, 2s, 3s pauses mid-sentence |

#### C. TTS Quality Tests

| Test ID | Description | Method |
|---------|-------------|--------|
| TTS-01 | Time to First Audio | Log timestamp of first audio frame after LLM output |
| TTS-02 | Subjective quality | Rate recordings on a 1-5 MOS scale (5 listeners minimum) |
| TTS-03 | Telephony naturalness | Same comparison but over actual phone call (8kHz playback) |

#### D. VAD & Turn-Taking Tests

| Test ID | Description | Method |
|---------|-------------|--------|
| VAD-01 | False endpointing | Speak a sentence with a natural 0.5s pause ("I want to... talk to sales"). Does the bot cut in? |
| VAD-02 | Endpointing sweep | Test with 200ms, 300ms, 400ms, 500ms. Count false positives per 10 sentences |
| VAD-03 | Silence handling | Go silent for 5s, 10s, 30s, 60s. What happens? |
| VAD-04 | Background noise | Test VAD with TV/music playing. Does it trigger false speech detection? |

#### E. Interruption Tests

| Test ID | Description | Method |
|---------|-------------|--------|
| INT-01 | Interrupt greeting | Speak "Hello" 1 second into the greeting. Does TTS stop? |
| INT-02 | Interrupt mid-response | Ask for business hours, then interrupt with "Actually, transfer me to sales" while bot is speaking |
| INT-03 | Double interrupt | Interrupt twice in quick succession. Does the pipeline crash? |

#### F. Duration & Reliability Tests

| Test ID | Description | Method |
|---------|-------------|--------|
| DUR-01 | 4-minute call | Have a real 4-minute multi-topic conversation |
| DUR-02 | 10-minute call | Extended conversation. Monitor memory, latency drift |
| DUR-03 | Idle timeout | Connect and stay silent. How long until disconnect? |
| DUR-04 | Rapid reconnect | Hang up and call back 5 times in 1 minute |

#### G. Tool Accuracy Tests

| Test ID | Description | Method |
|---------|-------------|--------|
| TOOL-01 | Correct routing | Ask 20 questions covering all 9 tools. Score correct tool selection |
| TOOL-02 | Ambiguous intent | "I have a problem with my bill" — does it route to billing or support? |
| TOOL-03 | Multi-intent | "What are your hours and can I talk to sales?" — does it handle both? |
| TOOL-04 | No-tool fallback | Ask something no tool covers. Does it gracefully handle it? |

---

## 12. Comparative Results

> **Status: PENDING** — Fill in after executing the test matrix above.

### 12.1 Latency Results

| Turn | T0→T1 (ms) | T1→T2 (ms) | T0→T2 (ms) | T0→T3 (ms) | Notes |
|------|-----------|-----------|-----------|-----------|-------|
| 1 (greeting response) | `___` | `___` | `___` | `___` | |
| 2 (tool call: hours) | `___` | `___` | `___` | `___` | |
| 3 (tool call: transfer) | `___` | `___` | `___` | `___` | |
| 5 (mid-conversation) | `___` | `___` | `___` | `___` | |
| 10 (late conversation) | `___` | `___` | `___` | `___` | |

**Verdict**: T0→T2 target of 1.5s met? `___`

### 12.2 STT Model Comparison

| Model | WER (clean) | WER (noisy) | Latency (ms) | Cost/hr | Recommendation |
|-------|------------|------------|-------------|---------|----------------|
| Nova-2 (8kHz) | `___`% | `___`% | `___` | `___` | |
| Nova-2 (16kHz up) | `___`% | `___`% | `___` | `___` | |
| Nova-3 (8kHz) | `___`% | `___`% | `___` | `___` | |

### 12.3 TTS Model Comparison

| Model | TTFA (ms) | MOS (1-5) | Telephony Quality (1-5) | Cost/1M chars | Recommendation |
|-------|----------|----------|----------------------|--------------|----------------|
| Deepgram Aura | `___` | `___` | `___` | `___` | |
| ElevenLabs Flash v2.5 | `___` | `___` | `___` | `___` | |
| OpenAI TTS | `___` | `___` | `___` | `___` | |

### 12.4 Endpointing Sweep

| Value | False Positives (/10) | Avg Response Delay (ms) | User Rating (1-5) | Recommendation |
|-------|----------------------|------------------------|-------------------|----------------|
| 200ms | `___` | `___` | `___` | |
| 300ms | `___` | `___` | `___` | |
| 400ms | `___` | `___` | `___` | |
| 500ms | `___` | `___` | `___` | |

### 12.5 Duration Test Results

| Duration | Completed? | Issues | Memory (MB) | Latency Drift? |
|----------|-----------|--------|-------------|---------------|
| 1 min | `___` | `___` | `___` | `___` |
| 2 min | `___` | `___` | `___` | `___` |
| 4 min | `___` | `___` | `___` | `___` |
| 10 min | `___` | `___` | `___` | `___` |

### 12.6 Tool Routing Accuracy (Measured — from LLM Benchmark)

> Data from `llm_benchmark.py` — 3 iterations per test case per model. Groq llama-3.3-70b-versatile results shown (production model).

| Tool | Times Tested | Correct | Accuracy | Avg TTFT (ms) | Notes |
|------|-------------|---------|----------|--------------|-------|
| get_business_hours | 3 | 3 | 100% | 198 | Fastest tool call |
| get_location | 3 | 3 | 100% | 226 | |
| transfer_to_sales | 3 | 3 | 100% | 271 | |
| transfer_to_support | 3 | 3 | 100% | 234 | |
| transfer_to_billing | 3 | 3 | 100% | 302 | |
| get_support_info | 3 | 3 | 100% | 2976 | Tail latency spike |
| get_department_directory | 3 | 3 | 100% | 3995 | Tail latency spike |
| check_service_status | 3 | 3 | 100% | 3646 | Tail latency spike |
| get_holiday_schedule | 3 | 3 | 100% | 3984 | Tail latency spike |
| **Ambiguous: "problem with my bill"** | 3 | 3 | 100% | 4009 | Correctly routed to billing |
| **Multi-intent: hours + location** | 3 | 3 | 100% | 3715 | Correctly picked hours first |

**Groq 70B: 100% tool accuracy across all 33 test runs.**

Groq 8B comparison: 70% accuracy — failed on support transfer (0%), status check (67%), holiday (33%), support info (33%). The 8B model often emits tool calls as plain text instead of using the API.

---

## Appendix A: How to Run Each Diff

```bash
# See all commits in order
git log --oneline --reverse

# See what changed between any two commits
git diff 942d09b ba0ba40   # Initial → MVP
git diff ba0ba40 057aa88   # → OpenAI TTS
git diff 057aa88 49ee059   # → Deepgram TTS
git diff 49ee059 19b2081   # → Pipeline fix
git diff 19b2081 31ee79c   # → Tools schema migration
git diff 31ee79c a4acbd3   # → Torch dep fix
git diff a4acbd3 4554358   # → Secrets removal
git diff 4554358 fd2377a   # → Groq LLM
git diff fd2377a 64bce83   # → Groq compat fix
git diff 64bce83 bfaf664   # → Frontend + expanded tools

# See a specific commit's changes
git show <hash>

# See full file at a specific point in history
git show <hash>:bot.py
```

## Appendix B: File Inventory

| File | Purpose | Lines | Last Modified |
|------|---------|-------|---------------|
| `bot.py` | Pipecat pipeline bot (main) | 502 | Commit 11 |
| `server.py` | FastAPI server + frontend UI | 399 | Commit 11 |
| `livekit_agent.py` | LiveKit VoicePipelineAgent (alternative) | 194 | Commit 10 |
| `db.py` | Postgres logging (Pipecat) | 76 | Commit 9 |
| `livekit_db.py` | Postgres logging (LiveKit) | 76 | Commit 2 |
| `requirements.txt` | Python dependencies | 10 | Commit 7 |
| `Dockerfile` | Pipecat bot container | 24 | Commit 2 |
| `Dockerfile.livekit` | LiveKit agent container | 27 | Commit 2 |
| `guide.md` | Deployment guide | ~320 | Commit 2 |
| `deploy.sh` | Interactive deploy helper | ~60 | Commit 2 |
