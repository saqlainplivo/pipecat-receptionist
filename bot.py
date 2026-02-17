"""
Project 2: AI Receptionist Bot for Acme Corp - Railway Deployment Version

Handles incoming calls with:
  - Greeting and intent detection
  - Function calling for business info and transfers
  - Transcript collection and call logging to Postgres
  - Interruption handling and conversation context
"""

import os
import time

from loguru import logger

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import LLMRunFrame, EndFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.runner.types import RunnerArguments
from pipecat.runner.utils import parse_telephony_websocket
from pipecat.serializers.plivo import PlivoFrameSerializer
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.services.elevenlabs.tts import ElevenLabsTTSService
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.transports.base_transport import BaseTransport
from pipecat.transports.websocket.fastapi import (
    FastAPIWebsocketParams,
    FastAPIWebsocketTransport,
)

from db import log_call

SYSTEM_PROMPT = """You are a friendly, natural-sounding receptionist for Acme Corp.

When someone calls:
1. Greet them warmly: "Hello, thank you for calling Acme Corp. How can I help you today?"
2. Listen carefully to their request.
3. If they want sales: Call transfer_to_sales, then say you're connecting them.
4. If they want support: Call transfer_to_support, ask them to briefly describe their issue.
5. If they ask about hours: Call get_business_hours and share the info conversationally.
6. If they ask about location: Call get_location and share the address naturally.
7. If unclear: Say "I'm sorry, I didn't quite catch that. Could you say that again?"

IMPORTANT CONVERSATION RULES:
- After helping with any request, always ask: "Is there anything else I can help you with?"
- If they say "no", "that's all", "thanks", "goodbye", etc., respond with:
  "Thank you for calling Acme Corp. Have a wonderful day! Goodbye."
- Remember what was discussed earlier in the call. If they ask a follow-up like
  "What about weekends?" after asking about hours, understand the context.
- Keep responses brief and conversational. Sound warm, not robotic.
- Your output will be converted to audio, so avoid special characters or formatting.
- If you can't understand what someone said, politely ask them to repeat."""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_business_hours",
            "description": "Get the business hours for Acme Corp",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_location",
            "description": "Get the office location/address of Acme Corp",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "transfer_to_sales",
            "description": "Transfer the caller to the sales team",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "transfer_to_support",
            "description": "Transfer the caller to the support team",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
]


class CallTracker:
    """Tracks call metadata for logging."""

    def __init__(self, caller_number: str):
        self.caller_number = caller_number
        self.transcript_parts: list[str] = []
        self.detected_intent = "unknown"
        self.start_time = time.time()
        self.stt_error_count = 0

    @property
    def duration(self) -> int:
        return int(time.time() - self.start_time)

    @property
    def transcript(self) -> str:
        return "\n".join(self.transcript_parts)

    def add_user_message(self, text: str):
        self.transcript_parts.append(f"Caller: {text}")

    def add_assistant_message(self, text: str):
        self.transcript_parts.append(f"Receptionist: {text}")

    def set_intent(self, intent: str):
        self.detected_intent = intent
        logger.info(f"Intent detected: {intent}")

    def save(self):
        log_call(self.caller_number, self.transcript, self.detected_intent, self.duration)


async def run_bot(transport: BaseTransport, handle_sigint: bool, caller_number: str):
    """Set up and run the enhanced AI receptionist pipeline."""

    call_tracker = CallTracker(caller_number)

    # Initialize AI services
    stt = DeepgramSTTService(api_key=os.getenv("DEEPGRAM_API_KEY"))

    llm = OpenAILLMService(
        api_key=os.getenv("OPENAI_API_KEY"),
        model="gpt-4.1-mini",
    )

    tts = ElevenLabsTTSService(
        api_key=os.getenv("ELEVENLABS_API_KEY"),
        voice_id="21m00Tcm4TlvDq8ikWAM",  # Rachel
    )

    # Register function handlers
    async def handle_get_business_hours(function_name, tool_call_id, args, llm, context, result_callback):
        call_tracker.set_intent("hours_inquiry")
        await result_callback(
            "Acme Corp is open Monday to Friday, 9 AM to 5 PM Pacific time. "
            "We are closed on weekends and major holidays."
        )

    async def handle_get_location(function_name, tool_call_id, args, llm, context, result_callback):
        call_tracker.set_intent("location_inquiry")
        await result_callback(
            "Acme Corp is located at 123 Main Street, San Francisco, California. "
            "We have free visitor parking available."
        )

    async def handle_transfer_to_sales(function_name, tool_call_id, args, llm, context, result_callback):
        call_tracker.set_intent("sales_transfer")
        logger.info(f"TRANSFER: Caller {caller_number} -> Sales")
        await result_callback("Connecting to the sales team now.")

    async def handle_transfer_to_support(function_name, tool_call_id, args, llm, context, result_callback):
        call_tracker.set_intent("support_transfer")
        logger.info(f"TRANSFER: Caller {caller_number} -> Support")
        await result_callback("Connecting to the support team now.")

    llm.register_function("get_business_hours", handle_get_business_hours)
    llm.register_function("get_location", handle_get_location)
    llm.register_function("transfer_to_sales", handle_transfer_to_sales)
    llm.register_function("transfer_to_support", handle_transfer_to_support)

    # Conversation context with tools
    context_messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    context = LLMContext(context_messages, tools=TOOLS)

    vad_analyzer = SileroVADAnalyzer()

    user_aggregator, assistant_aggregator = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(
            vad_analyzer=vad_analyzer,
        ),
    )

    # Build pipeline
    pipeline = Pipeline(
        [
            transport.input(),
            stt,
            user_aggregator,
            llm,
            tts,
            transport.output(),
            assistant_aggregator,
        ]
    )

    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            audio_in_sample_rate=8000,
            audio_out_sample_rate=8000,
            enable_metrics=True,
            enable_usage_metrics=True,
            allow_interruptions=True,
        ),
    )

    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport, client):
        logger.info(f"Call connected from {caller_number}")
        context_messages.append(
            {
                "role": "system",
                "content": "A caller just connected. Greet them warmly.",
            }
        )
        await task.queue_frames([LLMRunFrame()])

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, client):
        logger.info(f"Call disconnected from {caller_number} (duration: {call_tracker.duration}s)")
        call_tracker.save()
        await task.cancel()

    # Track user transcripts
    @stt.event_handler("on_transcript")
    async def on_transcript(processor, frame):
        if hasattr(frame, "text") and frame.text:
            text = frame.text.strip()
            if text:
                call_tracker.add_user_message(text)
                logger.info(f"Caller: {text}")

    runner = PipelineRunner(handle_sigint=handle_sigint)
    await runner.run(task)


async def bot(runner_args: RunnerArguments):
    """Main entry point for the receptionist bot."""

    transport_type, call_data = await parse_telephony_websocket(runner_args.websocket)
    logger.info(f"Transport: {transport_type}, Call data: {call_data}")

    body = runner_args.body or {}
    caller_number = body.get("from", "unknown")

    serializer = PlivoFrameSerializer(
        stream_id=call_data["stream_id"],
        call_id=call_data.get("call_id", ""),
        auth_id=os.getenv("PLIVO_AUTH_ID", ""),
        auth_token=os.getenv("PLIVO_AUTH_TOKEN", ""),
    )

    transport = FastAPIWebsocketTransport(
        websocket=runner_args.websocket,
        params=FastAPIWebsocketParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            add_wav_header=False,
            serializer=serializer,
        ),
    )

    await run_bot(transport, handle_sigint=runner_args.handle_sigint, caller_number=caller_number)
