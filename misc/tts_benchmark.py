"""
TTS Benchmark — Comparative evaluation of TTS providers for the AI Receptionist.

Tests each TTS on:
  1. Time to First Audio (TTFA)
  2. Total generation time
  3. Audio size (bytes)
  4. Streaming support

Usage:
    python3 tts_benchmark.py
"""

import asyncio
import json
import os
import time

import aiohttp
from dotenv import load_dotenv

load_dotenv()

# ─── Test sentences ──────────────────────────────────────────────────────────

TEST_SENTENCES = [
    "Hello, thank you for calling Acme Corp. How can I help you today?",
    "We're open Monday through Friday, nine to five Pacific time.",
    "Let me connect you with our sales team right away.",
    "I'm sorry, I didn't quite catch that. Could you say that one more time?",
    "Our office is located at 123 Main Street in San Francisco, California. We have free visitor parking available.",
    "Thank you for calling Acme Corp. Have a wonderful day! Goodbye.",
]

# ─── Provider configs ────────────────────────────────────────────────────────

PROVIDERS = []

# Voice.ai
if os.getenv("VOICEAI_API_KEY"):
    PROVIDERS.append({
        "name": "Voice.ai (ulaw_8000)",
        "short": "voiceai",
        "type": "http_stream",
        "url": "https://dev.voice.ai/api/v1/tts/speech/stream",
        "headers": {
            "Authorization": f"Bearer {os.getenv('VOICEAI_API_KEY')}",
            "Content-Type": "application/json",
        },
        "body_fn": lambda text: {
            "text": text,
            "audio_format": "ulaw_8000",
            "language": "en",
            "model": "voiceai-tts-v1-latest",
        },
    })

# Deepgram Aura
if os.getenv("DEEPGRAM_API_KEY"):
    PROVIDERS.append({
        "name": "Deepgram Aura (linear16, 8kHz)",
        "short": "deepgram",
        "type": "http_stream",
        "url": "https://api.deepgram.com/v1/speak?model=aura-asteria-en&encoding=linear16&container=none&sample_rate=8000",
        "headers": {
            "Authorization": f"Token {os.getenv('DEEPGRAM_API_KEY')}",
            "Content-Type": "application/json",
        },
        "body_fn": lambda text: {"text": text},
    })

# ElevenLabs
if os.getenv("ELEVENLABS_API_KEY"):
    PROVIDERS.append({
        "name": "ElevenLabs (eleven_flash_v2_5)",
        "short": "elevenlabs",
        "type": "http_stream",
        "url": "https://api.elevenlabs.io/v1/text-to-speech/21m00Tcm4TlvDq8ikWAM/stream",
        "headers": {
            "xi-api-key": os.getenv("ELEVENLABS_API_KEY"),
            "Content-Type": "application/json",
        },
        "body_fn": lambda text: {
            "text": text,
            "model_id": "eleven_flash_v2_5",
            "output_format": "ulaw_8000",
        },
    })

# OpenAI TTS
if os.getenv("OPENAI_API_KEY"):
    PROVIDERS.append({
        "name": "OpenAI TTS (alloy)",
        "short": "openai",
        "type": "http_stream",
        "url": "https://api.openai.com/v1/audio/speech",
        "headers": {
            "Authorization": f"Bearer {os.getenv('OPENAI_API_KEY')}",
            "Content-Type": "application/json",
        },
        "body_fn": lambda text: {
            "model": "tts-1",
            "voice": "alloy",
            "input": text,
            "response_format": "pcm",
        },
    })


# ─── Benchmark runner ────────────────────────────────────────────────────────

async def benchmark_single(session: aiohttp.ClientSession, provider: dict, text: str):
    """Run a single TTS request and measure timing."""
    body = provider["body_fn"](text)

    t0 = time.perf_counter()
    ttfa = None
    total_bytes = 0

    try:
        async with session.post(
            provider["url"],
            headers=provider["headers"],
            json=body,
        ) as resp:
            if resp.status != 200:
                error = await resp.text()
                return {"error": f"HTTP {resp.status}: {error[:100]}", "ttfa_ms": None, "total_ms": None, "bytes": 0}

            async for chunk in resp.content.iter_chunked(1024):
                if chunk:
                    if ttfa is None:
                        ttfa = (time.perf_counter() - t0) * 1000
                    total_bytes += len(chunk)

    except Exception as e:
        return {"error": str(e)[:100], "ttfa_ms": None, "total_ms": None, "bytes": 0}

    total_ms = (time.perf_counter() - t0) * 1000
    return {
        "error": None,
        "ttfa_ms": round(ttfa, 1) if ttfa else None,
        "total_ms": round(total_ms, 1),
        "bytes": total_bytes,
    }


async def benchmark_provider(provider: dict, iterations: int = 3):
    """Run all test sentences against a single provider."""
    results = []
    async with aiohttp.ClientSession() as session:
        for text in TEST_SENTENCES:
            sentence_results = []
            for _ in range(iterations):
                r = await benchmark_single(session, provider, text)
                sentence_results.append(r)
                await asyncio.sleep(0.2)  # Rate limit courtesy

            successful = [r for r in sentence_results if r["error"] is None]
            if not successful:
                results.append({
                    "text": text[:50],
                    "error": sentence_results[0]["error"],
                    "avg_ttfa_ms": None,
                    "avg_total_ms": None,
                    "avg_bytes": 0,
                })
                continue

            results.append({
                "text": text[:50],
                "error": None,
                "avg_ttfa_ms": round(sum(r["ttfa_ms"] for r in successful if r["ttfa_ms"]) / len(successful), 1),
                "avg_total_ms": round(sum(r["total_ms"] for r in successful) / len(successful), 1),
                "avg_bytes": round(sum(r["bytes"] for r in successful) / len(successful)),
            })

    return results


def print_separator():
    print("-" * 105)


def print_provider_results(name: str, results: list[dict]):
    print(f"\n{'=' * 105}")
    print(f"  {name}")
    print(f"{'=' * 105}")
    print(f"{'Sentence':<52} {'TTFA':>8} {'Total':>8} {'Bytes':>8}  {'Status':<10}")
    print_separator()

    ttfa_vals = []
    total_vals = []

    for r in results:
        if r["error"]:
            print(f"{r['text']:<52} {'ERROR':>8}  {r['error'][:40]}")
            continue

        print(f"{r['text']:<52} {r['avg_ttfa_ms']:>7.0f}ms {r['avg_total_ms']:>7.0f}ms {r['avg_bytes']:>7}B  OK")
        if r["avg_ttfa_ms"]:
            ttfa_vals.append(r["avg_ttfa_ms"])
        total_vals.append(r["avg_total_ms"])

    print_separator()
    if ttfa_vals:
        avg_ttfa = sum(ttfa_vals) / len(ttfa_vals)
        avg_total = sum(total_vals) / len(total_vals)
        print(f"{'AVERAGE':<52} {avg_ttfa:>7.0f}ms {avg_total:>7.0f}ms")


async def main():
    print("+" + "=" * 68 + "+")
    print("|       TTS BENCHMARK — AI Receptionist Audio Synthesis             |")
    print(f"|       {len(TEST_SENTENCES)} sentences x 3 iterations per provider" + " " * 22 + "|")
    print(f"|       {len(PROVIDERS)} providers configured" + " " * 40 + "|")
    print("+" + "=" * 68 + "+")

    all_results = {}
    for provider in PROVIDERS:
        print(f"\n>>> Testing: {provider['name']}...")
        results = await benchmark_provider(provider)
        all_results[provider["short"]] = results
        print_provider_results(provider["name"], results)

    # Cross-provider comparison
    if len(all_results) > 1:
        print(f"\n{'=' * 105}")
        print("  CROSS-PROVIDER COMPARISON")
        print(f"{'=' * 105}")
        print(f"{'Provider':<35} {'Avg TTFA':>10} {'Avg Total':>10} {'Avg Bytes':>10}")
        print_separator()

        for short in all_results:
            valid = [r for r in all_results[short] if r["error"] is None]
            ttfa = [r["avg_ttfa_ms"] for r in valid if r["avg_ttfa_ms"]]
            total = [r["avg_total_ms"] for r in valid]
            byt = [r["avg_bytes"] for r in valid]

            avg_ttfa = sum(ttfa) / len(ttfa) if ttfa else 0
            avg_total = sum(total) / len(total) if total else 0
            avg_bytes = sum(byt) / len(byt) if byt else 0

            print(f"{short:<35} {avg_ttfa:>9.0f}ms {avg_total:>9.0f}ms {avg_bytes:>9.0f}B")

    # Save raw results
    output_path = os.path.join(os.path.dirname(__file__), "tts_benchmark_results.json")
    with open(output_path, "w") as f:
        json.dump(all_results, f, indent=2)
    print(f"\nRaw results saved to: {output_path}")


if __name__ == "__main__":
    asyncio.run(main())
