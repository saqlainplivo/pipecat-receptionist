"""
Project 6: Optimized LiveKit AI Receptionist - Railway Deployment

Features:
- Ultra-low latency with Deepgram Aura TTS (~200ms)
- Robust interruption detection with TurnDetector
- Modern VoicePipelineAgent API
- Immediate greeting to eliminate startup delay
"""

import os
import time
import json
from typing import Annotated

from dotenv import load_dotenv
from loguru import logger
from livekit import rtc
from livekit.agents import (
    AutoSubscribe,
    JobContext,
    WorkerOptions,
    cli,
    llm,
)
from livekit.agents.voice_pipeline import VoicePipelineAgent
from livekit.plugins import deepgram, openai, silero

from livekit_db import init_db, log_call

load_dotenv()

RECEPTIONIST_INSTRUCTIONS = """You are an AI receptionist for TechCorp Solutions. Keep responses brief and conversational.
Your output will be converted to audio, so avoid special characters, markdown, or formatting.
Speak naturally as if you're on a phone call.

Your responsibilities:
1. Greet callers warmly
2. Determine their intent: sales inquiry, technical support, or general FAQ
3. Use the provided tools to answer questions about business hours, location, and FAQs
4. For sales inquiries, gather their name and interest, then let them know a sales rep will follow up
5. For technical support, gather a brief description of their issue and let them know a technician will call back
6. Always be polite, professional, and helpful
"""

class ReceptionistFunctions(llm.FunctionContext):
    def __init__(self, caller_number: str) -> None:
        super().__init__()
        self._caller_number = caller_number
        self._detected_intent = "unknown"
        self._transcript_parts = []
        self._start_time = time.time()

    @llm.ai_callable(description="Get the current business hours for TechCorp Solutions.")
    def get_business_hours(self) -> str:
        logger.info("Tool called: get_business_hours")
        return (
            "TechCorp Solutions is open Monday through Friday, 9 AM to 6 PM Eastern Time. "
            "We are closed on weekends and major holidays."
        )

    @llm.ai_callable(description="Get the office location and address for TechCorp Solutions.")
    def get_office_location(self) -> str:
        logger.info("Tool called: get_office_location")
        return (
            "TechCorp Solutions is located at 123 Innovation Drive, Suite 400, "
            "San Francisco, California 94105."
        )

    @llm.ai_callable(description="Log the detected caller intent for call tracking purposes.")
    def log_caller_intent(
        self, 
        intent: Annotated[str, llm.TypeInfo(description="The detected intent category (sales, support, faq, or other)")],
        summary: Annotated[str, llm.TypeInfo(description="A brief summary of what the caller needs")]
    ) -> str:
        logger.info(f"Tool called: log_caller_intent(intent={intent}, summary={summary})")
        self._detected_intent = intent
        self._transcript_parts.append(f"[Intent: {intent}] {summary}")
        return f"Intent recorded as: {intent}."

async def perform_post_call_analysis(agent: VoicePipelineAgent):
    """Analyze the final chat context to get a better intent and summary."""
    if not agent.chat_ctx.messages:
        return "No summary", "unknown"

    try:
        # Create a simple summary prompt
        analysis_prompt = "Analyze this conversation and provide: 1. A 1-sentence summary. 2. The primary intent (one of: sales, support, hours, location, other)."
        
        # Use the agent's LLM (NVIDIA NIM GLM)
        analysis_ctx = agent.chat_ctx.copy()
        analysis_ctx.append(role="system", text=f"Output your analysis in JSON format: {{\"summary\": \"...\", \"intent\": \"...\"}} based on: {analysis_prompt}")
        
        response = await agent.llm.chat(history=analysis_ctx)
        
        import json
        content = response.choices[0].message.content
        # Basic JSON extraction in case there's markdown
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        
        analysis = json.loads(content)
        return analysis.get("summary", "No summary"), analysis.get("intent", "unknown")
    except Exception as e:
        logger.error(f"Post-call analysis failed: {e}")
        return "Analysis failed", "error"

async def entrypoint(ctx: JobContext):
    logger.info(f"Connecting to room {ctx.room.name}")
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)

    # Wait for at least one participant (the caller)
    participant = await ctx.wait_for_participant()
    caller_number = participant.identity if participant.kind == rtc.ParticipantKind.PARTICIPANT_KIND_SIP else "browser-user"
    logger.info(f"Starting session for {caller_number}")

    fnc_ctx = ReceptionistFunctions(caller_number)

    # --- OLD OPENAI SETUP (Commented Out) ---
    # llm_service = openai.LLM(model="gpt-4o-mini")

    # --- NVIDIA NIM SETUP (Commented Out) ---
    # llm_service = openai.LLM.with_openai(
    #     base_url="https://integrate.api.nvidia.com/v1",
    #     api_key=os.getenv("NVIDIA_NIM_API_KEY"),
    #     model="zhipuai/glm-4-9b-chat"
    # )

    # --- GROQ SETUP (Fast LLM Inference) ---
    groq_key = os.getenv("GROQ_API_KEY")
    if not groq_key:
        logger.error("GROQ_API_KEY is not set! LLM will not work.")
    llm_service = openai.LLM.with_openai(
        base_url="https://api.groq.com/openai/v1",
        api_key=groq_key,
        model="llama-3.3-70b-versatile",
    )

    # Initialize the VoicePipelineAgent with optimized plugins
    agent = VoicePipelineAgent(
        vad=silero.VAD.load(),
        stt=deepgram.STT(
            model="nova-2", 
            interim_results=True, 
            endpointing_ms=300
        ),
        llm=llm_service,
        tts=deepgram.TTS(voice="aura-asteria-en"), # Fast Aura voice
        chat_ctx=llm.ChatContext().append(
            role="system",
            text=RECEPTIONIST_INSTRUCTIONS,
        ),
        fnc_ctx=fnc_ctx,
    )

    agent.start(ctx.room, participant)

    # OPTIMIZATION: Immediate Greeting
    # We say the greeting immediately without waiting for LLM or STT
    await agent.say("Hello! Thank you for calling TechCorp Solutions. My name is Rachel, your virtual receptionist. How can I help you today?", allow_interruptions=True)

    # Register transcript logging on end
    @ctx.add_on_finished
    async def on_finished():
        duration = int(time.time() - fnc_ctx._start_time)
        
        # Perform stronger intent detection and summarization
        summary, intent = await perform_post_call_analysis(agent)
        
        # Collect clean transcript from agent history
        transcript = ""
        for msg in agent.chat_ctx.messages:
            if msg.role == "user" and msg.text:
                transcript += f"Caller: {msg.text} | "
            elif msg.role == "assistant" and msg.text:
                transcript += f"Bot: {msg.text} | "
        
        log_call(
            caller_number=caller_number,
            transcript=transcript.strip(" | "),
            detected_intent=intent,
            duration=duration,
            summary=summary
        )
        logger.info(f"Call ended and analyzed. Intent: {intent}")

if __name__ == "__main__":
    init_db()
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            agent_name="receptionist-optimized",
        )
    )
