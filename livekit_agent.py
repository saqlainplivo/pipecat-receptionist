"""
Project 6: LiveKit AI Receptionist - Railway Deployment Version

Full-featured AI receptionist using LiveKit Agents framework.
Deploy to Railway with its own Dockerfile.livekit.

Pipeline: Silero VAD -> Deepgram STT -> OpenAI GPT-4.1-mini -> ElevenLabs TTS

Usage (local):
    python livekit_agent.py download-files
    python livekit_agent.py dev

Usage (Railway):
    Deployed via Dockerfile.livekit, runs with: python livekit_agent.py start
"""

import os
import time

from dotenv import load_dotenv
from loguru import logger
from livekit import rtc
from livekit.agents import Agent, AgentSession, JobContext, RunContext, cli, WorkerOptions, function_tool
from livekit.plugins import silero, deepgram, openai, elevenlabs

from livekit_db import init_db, log_call

load_dotenv()

# Initialize database on import
init_db()

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

When you detect the caller's intent, use the log_caller_intent tool to record it."""


class Receptionist(Agent):
    def __init__(self) -> None:
        super().__init__(instructions=RECEPTIONIST_INSTRUCTIONS)
        self._call_start_time = time.time()
        self._transcript_parts: list[str] = []
        self._detected_intent = "unknown"
        self._caller_number = "unknown"

    @function_tool()
    async def get_business_hours(self, context: RunContext) -> str:
        """Get the current business hours for TechCorp Solutions."""
        logger.info("Tool called: get_business_hours")
        return (
            "TechCorp Solutions is open Monday through Friday, 9 AM to 6 PM Eastern Time. "
            "We are closed on weekends and major holidays."
        )

    @function_tool()
    async def get_office_location(self, context: RunContext) -> str:
        """Get the office location and address for TechCorp Solutions."""
        logger.info("Tool called: get_office_location")
        return (
            "TechCorp Solutions is located at 123 Innovation Drive, Suite 400, "
            "San Francisco, California 94105. We're in the Financial District, "
            "near the Embarcadero BART station."
        )

    @function_tool()
    async def get_faq_answer(self, context: RunContext, question: str) -> str:
        """Look up the answer to a frequently asked question.

        Args:
            question: The customer's question to look up in the FAQ database.
        """
        logger.info(f"Tool called: get_faq_answer(question={question})")

        faqs = {
            "pricing": (
                "Our pricing starts at 49 dollars per month for the Starter plan, "
                "149 dollars per month for Professional, and 399 dollars per month for Enterprise. "
                "We also offer custom pricing for large organizations."
            ),
            "trial": (
                "Yes, we offer a free 14-day trial of our Professional plan. "
                "No credit card required to start."
            ),
            "support": (
                "We offer email support for all plans, priority phone support for Professional plans, "
                "and dedicated account managers for Enterprise customers."
            ),
            "refund": (
                "We offer a 30-day money-back guarantee on all annual plans. "
                "Monthly plans can be cancelled at any time."
            ),
        }

        question_lower = question.lower()
        for keyword, answer in faqs.items():
            if keyword in question_lower:
                return answer

        return (
            "I don't have a specific FAQ answer for that question. "
            "I can connect you with a team member who can help, "
            "or you can email support at help@techcorp.com."
        )

    @function_tool()
    async def log_caller_intent(
        self, context: RunContext, intent: str, summary: str
    ) -> str:
        """Log the detected caller intent for call tracking purposes.

        Args:
            intent: The detected intent category (sales, support, faq, or other).
            summary: A brief summary of what the caller needs.
        """
        logger.info(f"Tool called: log_caller_intent(intent={intent}, summary={summary})")
        self._detected_intent = intent
        self._transcript_parts.append(f"[Intent: {intent}] {summary}")
        return f"Intent recorded as: {intent}. Continue helping the caller."

    @function_tool()
    async def transfer_to_department(
        self, context: RunContext, department: str, caller_name: str, reason: str
    ) -> str:
        """Transfer the caller to a specific department (simulated).

        Args:
            department: The department to transfer to (sales or support).
            caller_name: The caller's name if provided.
            reason: Brief reason for the transfer.
        """
        logger.info(f"Tool called: transfer_to_department({department}, {caller_name}, {reason})")
        self._transcript_parts.append(f"[Transfer: {department}] {caller_name} - {reason}")

        if department.lower() == "sales":
            return (
                "I've noted your interest and a sales representative will follow up with you "
                "within the next business day. Is there anything else I can help with?"
            )
        elif department.lower() == "support":
            return (
                "I've logged your support request and a technician will call you back "
                "within 2 hours during business hours. Is there anything else I can help with?"
            )
        else:
            return (
                f"I've forwarded your request to the {department} team. "
                "Someone will get back to you shortly. Is there anything else?"
            )


async def entrypoint(ctx: JobContext):
    """Agent entrypoint - called when a participant joins or a SIP call arrives."""
    await ctx.connect()

    # Detect if this is a SIP (phone) call
    caller_number = "browser-user"
    for participant in ctx.room.remote_participants.values():
        if participant.kind == rtc.ParticipantKind.PARTICIPANT_KIND_SIP:
            caller_number = participant.identity
            logger.info(f"SIP caller: {caller_number}")

    receptionist = Receptionist()
    receptionist._caller_number = caller_number

    session = AgentSession(
        vad=silero.VAD.load(),
        stt=deepgram.STT(),
        llm=openai.LLM(model="gpt-4.1-mini"),
        tts=elevenlabs.TTS(voice_id="21m00Tcm4TlvDq8ikWAM"),  # Rachel
    )

    # Log call when session ends
    @session.on("close")
    def on_session_close():
        duration = int(time.time() - receptionist._call_start_time)
        transcript = " | ".join(receptionist._transcript_parts) if receptionist._transcript_parts else "No transcript"
        log_call(
            caller_number=receptionist._caller_number,
            transcript=transcript,
            detected_intent=receptionist._detected_intent,
            duration=duration,
        )
        logger.info(f"Call ended. Duration: {duration}s, Intent: {receptionist._detected_intent}")

    await session.start(
        room=ctx.room,
        agent=receptionist,
    )

    await session.generate_reply(
        instructions=(
            "Greet the caller warmly. Say something like: "
            "'Hello! Thank you for calling TechCorp Solutions. "
            "My name is Rachel, your virtual receptionist. "
            "How can I help you today?'"
        )
    )


if __name__ == "__main__":
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            agent_name="receptionist",
        )
    )
