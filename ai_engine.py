import json
import os
from google import genai
from google.genai import types
from pydantic import BaseModel, Field
from dotenv import load_dotenv

load_dotenv()

# Validate API key at startup so misconfiguration is caught immediately
_api_key = os.getenv("GEMINI_API_KEY")
assert _api_key, (
    "GEMINI_API_KEY is not set. "
    "Add it to your .env file: GEMINI_API_KEY=your_key_here"
)

client = genai.Client()


class TicketAnalysis(BaseModel):
    summary: str = Field(
        description="A brief one-sentence summary of the support ticket"
    )
    category: str = Field(
        description=(
            "A single category name for the ticket. "
            "Must be one of: IT, HR, Finance, Engineering, Account, General"
        )
    )
    # NOTE: priority is intentionally excluded here.
    # The user-selected priority from the submission form is used instead,
    # so the AI does not silently override it.


def analyze_ticket(title: str, description: str) -> dict:
    prompt = f"""
Analyze this support ticket and return a JSON response.

Title:
{title}

Description:
{description}
"""
    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=TicketAnalysis,
            ),
        )
        return json.loads(response.text)
    except Exception as e:
        print("Gemini API Error in analyze_ticket:", e)
        return {
            "summary": "Unable to generate summary",
            "category": "General",
        }


def get_team(department: str) -> str:
    mapping = {
        "IT":          "Infrastructure Team",
        "HR":          "HR Operations",
        "Finance":     "Finance Support",
        "Engineering": "Engineering Support",
        "Marketing":   "Marketing Team",
        "Operations":  "Operations Team",
    }
    return mapping.get(department, "General Support")


def chatbot_response(user_message: str, tickets: list) -> str:
    prompt = f"""
You are SmartDesk AI, a professional assistant for an enterprise ticketing system.

Answer the user's question using the ticket data below.
If the question is not about tickets, respond helpfully and professionally.
Keep answers short, clear, and professional.

USER QUESTION:
{user_message}

TICKETS DATABASE:
{json.dumps(tickets, indent=2)}
"""
    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
        )
        return response.text
    except Exception as e:
        print("Gemini API Error in chatbot_response:", e)
        return "I'm sorry, I am currently unable to process your request."


# ---------------------------------------------------------------------------
# Smart Support Chat
# ---------------------------------------------------------------------------

class SupportResponse(BaseModel):
    reply: str = Field(
        description="Your helpful response to the user's problem. Be clear, step-by-step if needed."
    )
    resolved: bool = Field(
        description="True if the problem is likely solved by your reply. False if it needs escalation or more help."
    )
    should_raise_ticket: bool = Field(
        description="True if the issue cannot be resolved through chat and needs a support ticket to be created."
    )
    suggested_title: str = Field(
        description="A short ticket title summarising the issue. Always provide this even if not raising a ticket."
    )
    suggested_department: str = Field(
        description="Best department for this issue: Engineering, HR, IT, Finance, Operations, or Marketing."
    )
    suggested_priority: str = Field(
        description="Suggested priority: Low, Medium, High, or Critical."
    )


def smart_support_response(conversation_history: list, user_message: str) -> dict:
    """
    conversation_history: list of {"role": "user"|"assistant", "content": str}
    Returns a dict matching SupportResponse fields.
    """
    history_text = "\n".join(
        f"{m['role'].upper()}: {m['content']}"
        for m in conversation_history
    )

    prompt = f"""
You are SmartDesk AI, a smart IT/HR/enterprise support assistant.

Your job:
1. Try your best to solve the user's problem directly through conversation.
2. Give clear, actionable steps. Ask clarifying questions if needed.
3. If after trying you still cannot resolve it (hardware issue, needs human intervention,
   account access, payroll, physical fix, etc.), set should_raise_ticket = true.
4. If the user explicitly asks to raise/create/submit a ticket, set should_raise_ticket = true.
5. If your reply likely solves the problem, set resolved = true.

CONVERSATION SO FAR:
{history_text}

LATEST USER MESSAGE:
{user_message}

Always fill in suggested_title, suggested_department, and suggested_priority
based on the conversation — even if not raising a ticket yet.
"""
    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=SupportResponse,
            ),
        )
        return json.loads(response.text)
    except Exception as e:
        print("Gemini API Error in smart_support_response:", e)
        return {
            "reply": "I'm sorry, I'm having trouble processing that right now. Please try again.",
            "resolved": False,
            "should_raise_ticket": False,
            "suggested_title": user_message[:80],
            "suggested_department": "IT",
            "suggested_priority": "Medium",
        }