"""
LLM Benchmark — Comparative evaluation of LLM providers for the AI Receptionist.

Tests each LLM on:
  1. Time to First Token (TTFT)
  2. Total generation time
  3. Tokens per second
  4. Tool call accuracy (correct function selected)
  5. Response quality (coherent, concise, receptionist-appropriate)

Usage:
    python llm_benchmark.py
"""

import asyncio
import json
import os
import time

from dotenv import load_dotenv

load_dotenv()

# ─── Shared imports ──────────────────────────────────────────────────────────

try:
    import openai
except ImportError:
    raise SystemExit("pip install openai  — required for benchmarking")


# ─── Model definitions ──────────────────────────────────────────────────────

MODELS = [
    {
        "name": "Groq — llama-3.3-70b-versatile",
        "short": "groq-70b",
        "base_url": "https://api.groq.com/openai/v1",
        "api_key_env": "GROQ_API_KEY",
        "model": "llama-3.3-70b-versatile",
    },
    {
        "name": "Groq — llama-3.1-8b-instant",
        "short": "groq-8b",
        "base_url": "https://api.groq.com/openai/v1",
        "api_key_env": "GROQ_API_KEY",
        "model": "llama-3.1-8b-instant",
    },
    {
        "name": "OpenAI — gpt-4o-mini",
        "short": "oai-4o-mini",
        "base_url": "https://api.openai.com/v1",
        "api_key_env": "OPENAI_API_KEY",
        "model": "gpt-4o-mini",
    },
    {
        "name": "OpenAI — gpt-4.1-nano",
        "short": "oai-4.1-nano",
        "base_url": "https://api.openai.com/v1",
        "api_key_env": "OPENAI_API_KEY",
        "model": "gpt-4.1-nano",
    },
]

# ─── System prompt (same as bot.py) ─────────────────────────────────────────

SYSTEM_PROMPT = """\
You are the front-desk receptionist for Acme Corp. Your voice is warm, \
professional, and concise — like a real person answering the phone, not a menu system.

Match the caller's intent to one of the actions below. If their request maps to a \
tool, call the tool FIRST, then speak.

  Sales inquiry         → call transfer_to_sales()
  Support / issue       → call transfer_to_support()
  Billing / invoices    → call transfer_to_billing()
  Business hours        → call get_business_hours()
  Location / address    → call get_location()
  Support details       → call get_support_info()
  Department contacts   → call get_department_directory()
  Outage / status       → call check_service_status()
  Holiday schedule      → call get_holiday_schedule()

Keep responses to two or three sentences. Use natural contractions.
"""

TOOLS = [
    {"type": "function", "function": {"name": "get_business_hours", "description": "Get the business hours for Acme Corp", "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {"name": "get_location", "description": "Get the office location/address of Acme Corp", "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {"name": "transfer_to_sales", "description": "Transfer the caller to the sales team", "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {"name": "transfer_to_support", "description": "Transfer the caller to the support team", "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {"name": "transfer_to_billing", "description": "Transfer the caller to the billing and accounts department", "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {"name": "get_support_info", "description": "Get support contact details including email, ticket portal, and SLA information", "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {"name": "get_department_directory", "description": "Get the internal department directory with extensions and email contacts", "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {"name": "check_service_status", "description": "Check current system and service status for any outages or incidents", "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {"name": "get_holiday_schedule", "description": "Get the upcoming holiday schedule and office closures", "parameters": {"type": "object", "properties": {}, "required": []}}},
]

# ─── Test cases ──────────────────────────────────────────────────────────────

# (user_message, expected_tool_or_None, description)
TEST_CASES = [
    # Pure text responses (no tool)
    ("Hi, good morning!", None, "Greeting — no tool expected"),
    # Tool calls
    ("What are your business hours?", "get_business_hours", "Hours inquiry"),
    ("Where is your office?", "get_location", "Location inquiry"),
    ("I want to talk to someone about purchasing your product.", "transfer_to_sales", "Sales transfer"),
    ("My service is broken, I need help.", "transfer_to_support", "Support transfer"),
    ("I have a question about my invoice.", "transfer_to_billing", "Billing transfer"),
    ("How do I submit a support ticket?", "get_support_info", "Support info"),
    ("What's the extension for engineering?", "get_department_directory", "Directory lookup"),
    ("Is there an outage right now?", "check_service_status", "Status check"),
    ("When are you closed for the holidays?", "get_holiday_schedule", "Holiday schedule"),
    # Ambiguous / harder cases
    ("I have a problem with my bill.", "transfer_to_billing", "Ambiguous billing/support"),
    ("What are your hours and where are you located?", "get_business_hours", "Multi-intent (accept either)"),
]


# ─── Benchmark runner ────────────────────────────────────────────────────────

async def benchmark_streaming(client: openai.AsyncOpenAI, model: str, user_msg: str, use_tools: bool):
    """Run a single streaming request and measure latency."""
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
    ]

    kwargs = {
        "model": model,
        "messages": messages,
        "stream": True,
        "max_tokens": 256,
    }
    if use_tools:
        kwargs["tools"] = TOOLS
        kwargs["tool_choice"] = "auto"

    ttft = None
    full_text = ""
    tool_calls_raw = {}
    token_count = 0

    t_start = time.perf_counter()
    try:
        stream = await client.chat.completions.create(**kwargs)
        async for chunk in stream:
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta is None:
                continue

            # First content token
            if ttft is None and (delta.content or delta.tool_calls):
                ttft = (time.perf_counter() - t_start) * 1000

            if delta.content:
                full_text += delta.content
                token_count += 1

            if delta.tool_calls:
                for tc in delta.tool_calls:
                    idx = tc.index
                    if idx not in tool_calls_raw:
                        tool_calls_raw[idx] = {"name": "", "arguments": ""}
                    if tc.function.name:
                        tool_calls_raw[idx]["name"] += tc.function.name
                    if tc.function.arguments:
                        tool_calls_raw[idx]["arguments"] += tc.function.arguments
                        token_count += 1

    except Exception as e:
        return {
            "error": str(e),
            "ttft_ms": None,
            "total_ms": (time.perf_counter() - t_start) * 1000,
            "tokens": 0,
            "tok_per_sec": 0,
            "text": "",
            "tool_called": None,
        }

    t_total = (time.perf_counter() - t_start) * 1000
    tok_per_sec = (token_count / (t_total / 1000)) if t_total > 0 and token_count > 0 else 0

    tool_called = None
    if tool_calls_raw:
        first_tc = tool_calls_raw[min(tool_calls_raw.keys())]
        tool_called = first_tc["name"]

    return {
        "error": None,
        "ttft_ms": round(ttft, 1) if ttft else None,
        "total_ms": round(t_total, 1),
        "tokens": token_count,
        "tok_per_sec": round(tok_per_sec, 1),
        "text": full_text[:120],
        "tool_called": tool_called,
    }


async def run_model_benchmark(model_cfg: dict, iterations: int = 3):
    """Run all test cases against a single model."""
    api_key = os.getenv(model_cfg["api_key_env"])
    if not api_key:
        print(f"  SKIP — {model_cfg['api_key_env']} not set")
        return None

    client = openai.AsyncOpenAI(
        api_key=api_key,
        base_url=model_cfg["base_url"],
        timeout=30.0,
    )

    results = []
    for user_msg, expected_tool, desc in TEST_CASES:
        use_tools = expected_tool is not None
        iteration_results = []

        for i in range(iterations):
            r = await benchmark_streaming(client, model_cfg["model"], user_msg, use_tools)
            iteration_results.append(r)
            # Small delay to avoid rate limits
            await asyncio.sleep(1.0)  # delay between iterations (Groq rate limits)

        # Aggregate across iterations
        successful = [r for r in iteration_results if r["error"] is None]
        if not successful:
            results.append({
                "desc": desc,
                "expected_tool": expected_tool,
                "error": iteration_results[0]["error"],
                "avg_ttft_ms": None,
                "avg_total_ms": None,
                "avg_tok_per_sec": None,
                "tool_accuracy": 0,
                "sample_text": "",
            })
            continue

        avg_ttft = sum(r["ttft_ms"] for r in successful if r["ttft_ms"]) / max(1, len([r for r in successful if r["ttft_ms"]]))
        avg_total = sum(r["total_ms"] for r in successful) / len(successful)
        avg_tps = sum(r["tok_per_sec"] for r in successful) / len(successful)

        # Tool accuracy: how many times did it call the correct tool?
        if expected_tool:
            correct = sum(1 for r in successful if r["tool_called"] == expected_tool)
            tool_acc = correct / len(successful)
        else:
            # For no-tool cases, success = no tool called
            correct = sum(1 for r in successful if r["tool_called"] is None)
            tool_acc = correct / len(successful)

        results.append({
            "desc": desc,
            "expected_tool": expected_tool,
            "error": None,
            "avg_ttft_ms": round(avg_ttft, 1),
            "avg_total_ms": round(avg_total, 1),
            "avg_tok_per_sec": round(avg_tps, 1),
            "tool_accuracy": round(tool_acc * 100),
            "sample_text": successful[0]["text"],
            "sample_tool": successful[0]["tool_called"],
        })

    return results


def print_separator():
    print("─" * 100)


def print_model_results(model_name: str, results: list[dict]):
    print(f"\n{'═' * 100}")
    print(f"  {model_name}")
    print(f"{'═' * 100}")
    print(f"{'Test':<35} {'TTFT':>8} {'Total':>8} {'tok/s':>8} {'Tool Acc':>9}  {'Tool Called':<25}")
    print_separator()

    ttft_vals = []
    total_vals = []
    tps_vals = []
    tool_accs = []

    for r in results:
        if r["error"]:
            print(f"{r['desc']:<35} {'ERROR':>8}  {r['error'][:50]}")
            continue

        ttft_str = f"{r['avg_ttft_ms']}ms" if r['avg_ttft_ms'] else "N/A"
        total_str = f"{r['avg_total_ms']}ms"
        tps_str = f"{r['avg_tok_per_sec']}"
        acc_str = f"{r['tool_accuracy']}%"
        tool_str = r.get("sample_tool", "") or "(none)"

        print(f"{r['desc']:<35} {ttft_str:>8} {total_str:>8} {tps_str:>8} {acc_str:>9}  {tool_str:<25}")

        if r['avg_ttft_ms']:
            ttft_vals.append(r['avg_ttft_ms'])
        total_vals.append(r['avg_total_ms'])
        tps_vals.append(r['avg_tok_per_sec'])
        if r['expected_tool'] is not None:
            tool_accs.append(r['tool_accuracy'])

    print_separator()
    avg_ttft = sum(ttft_vals) / len(ttft_vals) if ttft_vals else 0
    avg_total = sum(total_vals) / len(total_vals) if total_vals else 0
    avg_tps = sum(tps_vals) / len(tps_vals) if tps_vals else 0
    avg_tool = sum(tool_accs) / len(tool_accs) if tool_accs else 0
    print(f"{'AVERAGE':<35} {avg_ttft:>7.0f}ms {avg_total:>7.0f}ms {avg_tps:>8.1f} {avg_tool:>8.0f}%")


async def main():
    print("╔══════════════════════════════════════════════════════════════════╗")
    print("║       LLM BENCHMARK — AI Receptionist Tool Calling              ║")
    print("║       Testing TTFT, throughput, and tool routing accuracy        ║")
    print(f"║       {len(TEST_CASES)} test cases × 3 iterations per model{' ' * 24}║")
    print("╚══════════════════════════════════════════════════════════════════╝")

    all_results = {}

    for model_cfg in MODELS:
        print(f"\n>>> Testing: {model_cfg['name']}...")
        results = await run_model_benchmark(model_cfg, iterations=3)
        if results is None:
            continue
        all_results[model_cfg["short"]] = results
        print_model_results(model_cfg["name"], results)

    # ─── Cross-model comparison summary ──────────────────────────────────
    if len(all_results) > 1:
        print(f"\n{'═' * 100}")
        print("  CROSS-MODEL COMPARISON")
        print(f"{'═' * 100}")
        print(f"{'Model':<30} {'Avg TTFT':>10} {'Avg Total':>10} {'Avg tok/s':>10} {'Tool Acc':>10}")
        print_separator()

        for short, results in all_results.items():
            valid = [r for r in results if r["error"] is None]
            ttft_vals = [r["avg_ttft_ms"] for r in valid if r["avg_ttft_ms"]]
            total_vals = [r["avg_total_ms"] for r in valid]
            tps_vals = [r["avg_tok_per_sec"] for r in valid]
            tool_accs = [r["tool_accuracy"] for r in valid if r["expected_tool"] is not None]

            avg_ttft = sum(ttft_vals) / len(ttft_vals) if ttft_vals else 0
            avg_total = sum(total_vals) / len(total_vals) if total_vals else 0
            avg_tps = sum(tps_vals) / len(tps_vals) if tps_vals else 0
            avg_tool = sum(tool_accs) / len(tool_accs) if tool_accs else 0

            print(f"{short:<30} {avg_ttft:>9.0f}ms {avg_total:>9.0f}ms {avg_tps:>10.1f} {avg_tool:>9.0f}%")

    # Save raw results to JSON
    output_path = os.path.join(os.path.dirname(__file__), "benchmark_results.json")
    with open(output_path, "w") as f:
        json.dump(all_results, f, indent=2)
    print(f"\nRaw results saved to: {output_path}")


if __name__ == "__main__":
    asyncio.run(main())
