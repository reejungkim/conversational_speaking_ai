"""
Conversation Router
Handles AI conversation interactions
"""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional, List
import re

from openai import OpenAI
import sys
sys.path.append('..')
from config import get_settings

router = APIRouter()
settings = get_settings()

# OpenAI client
openai_client = OpenAI(api_key=settings.openai_api_key)


# ==================== Pydantic Models ====================

class Message(BaseModel):
    """Chat message model"""
    role: str  # "user" or "assistant"
    content: str


class ConversationRequest(BaseModel):
    """Conversation request model"""
    message: str
    history: Optional[List[Message]] = []
    language: str = "English"  # "English" or "French"
    level: str = "Intermediate (B1-B2)"
    persona: str = "Friendly"
    topic: str = "General"


class ConversationResponse(BaseModel):
    """Conversation response model"""
    conversation: str
    correction: Optional[str] = None


# ==================== Conversation Endpoints ====================

@router.post("/send", response_model=ConversationResponse)
async def send_message(request: ConversationRequest):
    """
    Send a message to the AI tutor and receive a response
    """
    try:
        language_name = "French" if request.language == "French" else "English"
        
        sys_prompt = f"""You are an experienced {language_name} language tutor with a {request.persona.lower()} teaching style.

Your role:
- Help students practice {language_name} conversation on the topic of {request.topic}
- Adapt your language to {request.level} proficiency
- Keep responses natural and conversational (2-3 sentences)
- Provide grammar corrections when needed WITHOUT interrupting the conversation flow

CRITICAL: You MUST use this exact format for EVERY response:

<conversation>
[Your natural, conversational response here - NO corrections, NO grammar mentions, ONLY conversation]
</conversation>

<correction>
[ONLY if there was a grammar/vocabulary/spelling error, write it here. Otherwise leave empty]
[Format: "You said: '[incorrect phrase]' → Better: '[corrected phrase]' - [brief explanation]"]
</correction>

IMPORTANT RULES:
1. The <conversation> section should NEVER mention errors or corrections
2. The <conversation> section should flow naturally as if nothing was wrong
3. Keep the conversation going - ask follow-up questions, show interest
4. The <correction> section is COMPLETELY SEPARATE - only grammar fixes go there
5. If there are no errors, leave <correction> empty 
6. Do NOT mix conversation and correction - they are separate sections

Topic: {request.topic}
Level: {request.level}
Persona: {request.persona}
"""
        
        # Build messages for API
        messages = [{"role": "system", "content": sys_prompt}]
        
        # Add conversation history (last 6 turns)
        for msg in request.history[-6:]:
            messages.append({"role": msg.role, "content": msg.content})
        
        # Add current message
        messages.append({"role": "user", "content": request.message})
        
        # Call OpenAI
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages
        )
        
        full_response = response.choices[0].message.content.strip()
        
        # Parse the response
        conversation_match = re.search(r'<conversation>(.*?)</conversation>', full_response, re.DOTALL)
        correction_match = re.search(r'<correction>(.*?)</correction>', full_response, re.DOTALL)
        
        conversation = conversation_match.group(1).strip() if conversation_match else full_response
        correction = correction_match.group(1).strip() if correction_match else None
        
        # Clean up empty or placeholder corrections
        if correction and (len(correction) < 3 or correction.strip() in ['-', 'none', 'n/a', 'None', 'N/A']):
            correction = None
        
        return ConversationResponse(
            conversation=conversation,
            correction=correction
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Conversation error: {str(e)}"
        )


@router.get("/topics")
async def get_topics():
    """
    Get available conversation topics
    """
    return {
        "topics": [
            {"id": "general", "name": "General", "description": "General conversation practice"},
            {"id": "food", "name": "Food", "description": "Restaurant and food discussions"},
            {"id": "travel", "name": "Travel", "description": "Travel and tourism scenarios"},
            {"id": "work", "name": "Work", "description": "Professional and work-related topics"},
            {"id": "shopping", "name": "Shopping", "description": "Shopping and errands"},
            {"id": "interview", "name": "Job Interview", "description": "Practice job interviews"}
        ]
    }


@router.get("/personas")
async def get_personas():
    """
    Get available tutor personas
    """
    return {
        "personas": [
            {"id": "friendly", "name": "Friendly", "description": "Patient, supportive, celebrates your efforts"},
            {"id": "professional", "name": "Professional", "description": "Focused on accuracy, provides clear feedback"},
            {"id": "casual", "name": "Casual", "description": "Uses idioms, humor, and relatable examples"}
        ]
    }


@router.get("/levels")
async def get_levels():
    """
    Get available language levels
    """
    return {
        "levels": [
            {"id": "beginner", "name": "Beginner (A1-A2)", "description": "Simple vocabulary, short sentences"},
            {"id": "intermediate", "name": "Intermediate (B1-B2)", "description": "Broader vocabulary, complex sentences"},
            {"id": "advanced", "name": "Advanced (C1-C2)", "description": "Sophisticated language, nuanced discussions"}
        ]
    }
