"""
Audio Router
Handles speech-to-text and text-to-speech processing
"""
from fastapi import APIRouter, HTTPException, UploadFile, File
from fastapi.responses import Response
from pydantic import BaseModel
from typing import Optional
import tempfile
import os
import json

from google.cloud import speech_v1p1beta1 as speech
from google.cloud import texttospeech
import sys
sys.path.append('..')
from config import get_settings

router = APIRouter()
settings = get_settings()


def setup_google_credentials():
    """Setup Google Cloud credentials from settings"""
    if settings.google_credentials_path and os.path.isfile(settings.google_credentials_path):
        os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = settings.google_credentials_path
    elif settings.google_credentials_json:
        # Write JSON credentials to temp file
        creds = json.loads(settings.google_credentials_json)
        if 'private_key' in creds:
            creds['private_key'] = creds['private_key'].replace('\\n', '\n')
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(creds, f)
            os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = f.name


# Setup credentials on module load
setup_google_credentials()

# Initialize clients (lazy loading)
_speech_client = None
_tts_client = None


def get_speech_client():
    global _speech_client
    if _speech_client is None:
        _speech_client = speech.SpeechClient()
    return _speech_client


def get_tts_client():
    global _tts_client
    if _tts_client is None:
        _tts_client = texttospeech.TextToSpeechClient()
    return _tts_client


# ==================== Pydantic Models ====================

class TranscribeRequest(BaseModel):
    """Transcription request metadata"""
    language_code: str = "en-US"


class TranscribeResponse(BaseModel):
    """Transcription response"""
    transcript: str
    confidence: Optional[float] = None


class SynthesizeRequest(BaseModel):
    """Text-to-speech request"""
    text: str
    language_code: str = "en-US"
    voice_name: str = "en-US-Journey-F"


# ==================== Audio Endpoints ====================

@router.post("/transcribe", response_model=TranscribeResponse)
async def transcribe_audio(
    file: UploadFile = File(...),
    language_code: str = "en-US"
):
    """
    Transcribe audio file to text using Google Cloud Speech-to-Text
    
    - Accepts WAV, WEBM, or MP3 audio files
    - Returns transcribed text with confidence score
    """
    try:
        # Read audio content
        audio_content = await file.read()
        
        if not audio_content:
            raise HTTPException(status_code=400, detail="Empty audio file")
        
        client = get_speech_client()
        
        # Create audio object
        audio = speech.RecognitionAudio(content=audio_content)
        
        # Configure recognition
        config = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=48000,
            language_code=language_code,
            enable_automatic_punctuation=True,
            model="default"
        )
        
        # Perform transcription
        response = client.recognize(config=config, audio=audio)
        
        if not response.results:
            return TranscribeResponse(transcript="", confidence=0.0)
        
        # Combine all transcripts
        transcript = " ".join([
            result.alternatives[0].transcript 
            for result in response.results
        ]).strip()
        
        # Get average confidence
        confidences = [
            result.alternatives[0].confidence 
            for result in response.results 
            if result.alternatives
        ]
        avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0
        
        return TranscribeResponse(
            transcript=transcript,
            confidence=avg_confidence
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Transcription error: {str(e)}"
        )


@router.post("/synthesize")
async def synthesize_speech(request: SynthesizeRequest):
    """
    Convert text to speech using Google Cloud Text-to-Speech
    
    - Returns MP3 audio file
    - Supports multiple voices and languages
    """
    try:
        client = get_tts_client()
        
        # Create synthesis input
        synthesis_input = texttospeech.SynthesisInput(text=request.text)
        
        # Configure voice
        voice = texttospeech.VoiceSelectionParams(
            language_code=request.language_code,
            name=request.voice_name
        )
        
        # Configure audio output
        audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.MP3
        )
        
        # Perform synthesis
        response = client.synthesize_speech(
            input=synthesis_input,
            voice=voice,
            audio_config=audio_config
        )
        
        return Response(
            content=response.audio_content,
            media_type="audio/mpeg",
            headers={
                "Content-Disposition": "attachment; filename=speech.mp3"
            }
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Speech synthesis error: {str(e)}"
        )


@router.get("/voices")
async def get_voices(language: str = "en"):
    """
    Get available voice options for a language
    """
    voices = {
        "en": [
            {"id": "en-US-Journey-F", "name": "Journey Female", "gender": "female"},
            {"id": "en-US-Journey-D", "name": "Journey Male", "gender": "male"},
            {"id": "en-US-Studio-O", "name": "Studio Female", "gender": "female"},
            {"id": "en-US-Studio-M", "name": "Studio Male", "gender": "male"},
            {"id": "en-US-Neural2-F", "name": "Neural2 Female", "gender": "female"},
            {"id": "en-US-Neural2-D", "name": "Neural2 Male", "gender": "male"}
        ],
        "fr": [
            {"id": "fr-FR-Neural2-A", "name": "Neural2 Female A", "gender": "female"},
            {"id": "fr-FR-Neural2-B", "name": "Neural2 Male B", "gender": "male"},
            {"id": "fr-FR-Neural2-C", "name": "Neural2 Female C", "gender": "female"},
            {"id": "fr-FR-Neural2-D", "name": "Neural2 Male D", "gender": "male"},
            {"id": "fr-FR-Standard-A", "name": "Standard Female A", "gender": "female"},
            {"id": "fr-FR-Standard-B", "name": "Standard Male B", "gender": "male"}
        ]
    }
    
    return {"voices": voices.get(language, voices["en"])}


@router.get("/languages")
async def get_supported_languages():
    """
    Get supported languages for speech recognition and synthesis
    """
    return {
        "languages": [
            {"code": "en-US", "name": "English (US)", "short": "en"},
            {"code": "en-GB", "name": "English (UK)", "short": "en"},
            {"code": "fr-FR", "name": "French", "short": "fr"}
        ]
    }
