import streamlit as st
import openai
from openai import OpenAI
from google.cloud import speech_v1p1beta1 as speech
from google.cloud import texttospeech
import os
import base64
from datetime import datetime
from dotenv import load_dotenv 
import io
import wave
from streamlit_mic_recorder import mic_recorder
import tempfile
import json

# Get the directory where app.py is located
APP_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(APP_DIR, '.env')

# Load environment variables from .env file (for local development)
load_dotenv(ENV_PATH)

# --- Configuration & Credential Handling ---

def get_secret_or_env(keys):
    """
    Retrieve secret or env var without forcing string conversion immediately.
    This preserves Dict objects from Streamlit secrets (TOML tables).
    """
    # 1. Try Streamlit secrets
    try:
        if hasattr(st, 'secrets'):
            for key in keys:
                if key in st.secrets:
                    return st.secrets[key]
    except Exception:
        pass
    
    # 2. Try Environment variables
    for key in keys:
        val = os.getenv(key)
        if val:
            return val
            
    return None

# Fetch raw configuration
raw_google_creds = get_secret_or_env(['gemini_llm_api', 'GOOGLE_APPLICATION_CREDENTIALS', 'GOOGLE_CREDENTIALS'])
OPENAI_API_KEY = get_secret_or_env(['openai_api_llm', 'OPENAI_API_KEY', 'OPENAI_KEY'])

# Ensure OpenAI Key is a string if found
if OPENAI_API_KEY:
    OPENAI_API_KEY = str(OPENAI_API_KEY).strip()

# Process Google Credentials
# Goal: Ensure os.environ['GOOGLE_APPLICATION_CREDENTIALS'] points to a valid JSON file
if raw_google_creds:
    try:
        # Case 1: Streamlit Secrets parsed it as a Dict (TOML table)
        if isinstance(raw_google_creds, dict):
            # Create a temp file with valid JSON (double quotes)
            # json.dumps() ensures valid JSON format
            with tempfile.NamedTemporaryFile(delete=False, suffix='.json', mode='w', encoding='utf-8') as tmp:
                json.dump(raw_google_creds, tmp)
                tmp_path = tmp.name
            
            os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = tmp_path

        # Case 2: It is a String (File Path or JSON String)
        elif isinstance(raw_google_creds, str):
            stripped = raw_google_creds.strip()
            
            # Check if it looks like an API Key (starts with AIza...) -> Invalid for Service Account
            if stripped.startswith('AIza') or (len(stripped) < 100 and not stripped.startswith('{') and not os.path.isfile(stripped)):
                 # Invalid: Looks like an API key, not a service account
                if 'GOOGLE_APPLICATION_CREDENTIALS' in os.environ:
                    del os.environ['GOOGLE_APPLICATION_CREDENTIALS']

            # Check if it is a JSON string
            elif stripped.startswith('{') and stripped.endswith('}'):
                try:
                    # Validate JSON and normalize
                    json_obj = json.loads(stripped)
                    
                    if json_obj.get('type') == 'service_account':
                        with tempfile.NamedTemporaryFile(delete=False, suffix='.json', mode='w', encoding='utf-8') as tmp:
                            json.dump(json_obj, tmp)
                            tmp_path = tmp.name
                        os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = tmp_path
                except json.JSONDecodeError:
                    # Invalid JSON string
                    pass

            # Check if it is a valid File Path
            elif os.path.isfile(stripped):
                # Validate content
                try:
                    with open(stripped, 'r') as f:
                        data = json.load(f)
                        if data.get('type') == 'service_account':
                            os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = stripped
                except Exception:
                    pass

    except Exception as e:
        # Fallback: Clear env var if processing failed
        if 'GOOGLE_APPLICATION_CREDENTIALS' in os.environ:
            del os.environ['GOOGLE_APPLICATION_CREDENTIALS']

# --- End Configuration ---

# Page configuration
st.set_page_config(
    page_title="AI Language Tutor",
    page_icon="🗣️",
    layout="wide"
)

# Initialize session state
if 'conversation_history' not in st.session_state:
    st.session_state.conversation_history = []
if 'messages' not in st.session_state:
    st.session_state.messages = []
if 'last_user_message' not in st.session_state:
    st.session_state.last_user_message = None
if 'last_audio_file' not in st.session_state:
    st.session_state.last_audio_file = None
if 'google_credentials_set' not in st.session_state:
    st.session_state.google_credentials_set = bool(os.environ.get('GOOGLE_APPLICATION_CREDENTIALS'))


# Validate Google credentials
def validate_google_credentials():
    """
    Validate that Google credentials are properly configured
    Returns: (is_valid, error_message)
    """
    creds_path = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS')
    
    if not creds_path:
        return False, "Google credentials not configured. Please set GOOGLE_APPLICATION_CREDENTIALS."
    
    # Check if file exists
    if not os.path.isfile(creds_path):
        return False, f"Credentials file not found: {creds_path}"
    
    # Validate it's a service account JSON
    try:
        with open(creds_path, 'r') as f:
            creds_data = json.load(f)
            if creds_data.get('type') != 'service_account':
                return False, "The credentials file is not a service account JSON. Please use a Service Account JSON file, not an API key."
            if not creds_data.get('private_key'):
                return False, "The service account JSON is missing required fields. Please download a new key from Google Cloud Console."
    except json.JSONDecodeError:
        return False, "The credentials file is not valid JSON. Please check the file format."
    except Exception as e:
        return False, f"Error reading credentials file: {str(e)}"
    
    return True, None

# Initialize clients
@st.cache_resource
def init_speech_client():
    """Initialize Google Speech-to-Text client"""
    try:
        return speech.SpeechClient()
    except Exception as e:
        error_str = str(e).lower()
        if any(phrase in error_str for phrase in [
            "could not automatically determine credentials",
            "your default credentials were not found",
            "invalid credentials"
        ]):
            st.error("❌ **Failed to initialize Speech-to-Text client.**\n\n"
                    "This usually means your credentials are not properly configured.\n\n"
                    "**Please check:**\n"
                    "1. Your `.env` file contains: `GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json`\n"
                    "2. The file path is correct and the file exists\n"
                    "3. The file is a valid Service Account JSON (not an API key)\n"
                    "4. Speech-to-Text API is enabled in your Google Cloud project")
        raise

@st.cache_resource
def init_tts_client():
    """Initialize Google Text-to-Speech client"""
    try:
        return texttospeech.TextToSpeechClient()
    except Exception as e:
        error_str = str(e).lower()
        if any(phrase in error_str for phrase in [
            "could not automatically determine credentials",
            "your default credentials were not found",
            "invalid credentials"
        ]):
            st.error("❌ **Failed to initialize Text-to-Speech client.**\n\n"
                    "This usually means your credentials are not properly configured.\n\n"
                    "**Please check:**\n"
                    "1. Your `.env` file contains: `GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json`\n"
                    "2. The file path is correct and the file exists\n"
                    "3. The file is a valid Service Account JSON (not an API key)\n"
                    "4. Text-to-Speech API is enabled in your Google Cloud project")
        raise

# Speech-to-Text function
def transcribe_audio(audio_content):
    """
    Transcribe audio using Google Cloud Speech-to-Text
    
    Args:
        audio_content: Audio file content in bytes
    
    Returns:
        str: Transcribed text
    """
    try:
        client = init_speech_client()
        # Try to detect WAV sample rate from bytes; fall back to 16000Hz
        detected_sample_rate = 16000
        try:
            with wave.open(io.BytesIO(audio_content), 'rb') as wav_file:
                detected_sample_rate = wav_file.getframerate()
        except Exception:
            pass

        audio = speech.RecognitionAudio(content=audio_content)
        config = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=detected_sample_rate,
            language_code="en-US",
            enable_automatic_punctuation=True,
            model="default"
        )
        
        response = client.recognize(config=config, audio=audio)
        
        if not response.results:
            return None
        
        transcript = ""
        for result in response.results:
            if result.alternatives:
                transcript += result.alternatives[0].transcript + " "
        
        return transcript.strip() if transcript else None
    
    except Exception as e:
        error_str = str(e)
        error_lower = error_str.lower()
        
        # Check for credential-related errors - Google Cloud raises specific errors for API keys vs service accounts
        if any(phrase in error_lower for phrase in [
            "could not automatically determine credentials",
            "your default credentials were not found",
            "invalid credentials",
            "invalid authentication credentials",
            "authentication failed",
            "was not found",
            "file" in error_lower and "not found" in error_lower,
            "api key" in error_lower,
            "service account" in error_lower and "not found" in error_lower
        ]):
            # This usually means an API key was used instead of a service account JSON file
            st.error("❌ **Invalid Google Cloud credentials detected.**\n\n"
                    "The error suggests you're using an **API key** instead of a **Service Account JSON file**.\n\n"
                    "**Google Cloud Speech-to-Text requires:**\n"
                    "- A Service Account JSON file (not an API key)\n\n"
                    "**To fix:**\n"
                    "1. Go to Google Cloud Console → IAM & Admin → Service Accounts\n"
                    "2. Create or select a service account\n"
                    "3. Create a key (JSON format) and download it\n"
                    "4. Update your `.env` file or Streamlit Secrets:\n"
                    "   - **Option A (file path):** `GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json`\n"
                    "   - **Option B (JSON content):** Paste the entire JSON content as a single line\n"
                    "5. Make sure Speech-to-Text API is enabled for your project\n\n"
                    f"**Error details:** {error_str[:200]}")
        elif "authentication" in error_lower or "credentials" in error_lower:
            st.error(f"❌ **Authentication error:** {error_str}\n\n"
                    "Please check your Google Cloud Service Account credentials.\n\n"
                    "**Common issues:**\n"
                    "- The service account JSON file path is incorrect\n"
                    "- The service account doesn't have Speech-to-Text API permissions\n"
                    "- The JSON file is corrupted or incomplete")
        else:
            st.error(f"❌ Transcription error: {error_str}\n\n"
                    "**Troubleshooting:**\n"
                    "- Check that Speech-to-Text API is enabled in your Google Cloud project\n"
                    "- Verify your service account has the 'Cloud Speech Client' role\n"
                    "- Ensure your audio format is supported (WAV, LINEAR16)")
        return None

# GPT-4 function
def get_ai_response(user_input, conversation_history, persona, topic, level):
    """
    Generate AI tutor response using OpenAI GPT-4o mini
    """
    
    # Map persona to system prompt
    persona_prompts = {
        "Friendly & Encouraging": f"You are a friendly and encouraging English conversation partner. Be patient, supportive, and celebrate the user's efforts. Keep responses natural and conversational (2-4 sentences).",
        "Professional & Direct": f"You are a professional English tutor focused on accuracy. Provide clear feedback and corrections when needed. Keep responses educational but friendly. Keep responses conversational (2-4 sentences).",
        "Casual & Fun": f"You are a casual and fun English conversation partner. Use idioms, humor, and relatable examples. Keep the conversation light and engaging. Keep responses conversational (2-4 sentences)."
    }
    
    system_prompt = f"""
You are an English conversation partner with the following characteristics:
- Personality: {persona_prompts.get(persona, persona_prompts['Friendly & Encouraging'])}
- Current topic: {topic}
- User's level: {level}

Instructions:
1. Reply naturally to the user's message
2. Stay on topic unless the user changes it
3. Use vocabulary appropriate for their level
4. Keep responses conversational and engaging
5. Do NOT repeat your own previous messages
6. Do NOT generate both sides of the conversation
7. Do NOT ask multiple questions at once (max 1 question per response)
"""

    # Keep only the last 6 turns to maintain context without bloat
    trimmed_history = conversation_history[-6:] if len(conversation_history) > 6 else conversation_history

    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(trimmed_history)
    messages.append({"role": "user", "content": user_input})

    try:
        # Check if API key is available
        if not OPENAI_API_KEY:
            error_msg = "❌ OpenAI API key is missing. Please set OPENAI_API_KEY in your .env file or environment."
            st.error(error_msg)
            return "Sorry, I encountered an issue. Could you please try again?"
        
        # Clean and validate API key
        api_key = str(OPENAI_API_KEY).strip()
        if not api_key or len(api_key) < 10:
            error_msg = "❌ OpenAI API key appears to be invalid or too short."
            st.error(error_msg)
            return "Sorry, I encountered an issue. Could you please try again?"
        
        # Initialize client with only the api_key parameter
        client = OpenAI(api_key=api_key)
        
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            temperature=0.7,
            max_tokens=300
        )

        if not response.choices or not response.choices[0].message:
            error_msg = "❌ OpenAI API returned an empty response."
            st.error(error_msg)
            return "Sorry, I encountered an issue. Could you please try again?"

        ai_message = response.choices[0].message.content.strip()
        if not ai_message:
            error_msg = "❌ OpenAI API returned empty content."
            st.error(error_msg)
            return "Sorry, I encountered an issue. Could you please try again?"
            
        st.write(f"✅ AI Response received: {ai_message[:100]}...")
        return ai_message

    except Exception as e:
        error_type = type(e).__name__
        error_str = str(e)
        
        # Check for specific error types
        if "authentication" in error_str.lower() or "api key" in error_str.lower() or "invalid" in error_str.lower():
            error_msg = f"❌ OpenAI Authentication Error: Invalid API key. Please check your OPENAI_API_KEY.\n\nError: {error_str}"
            st.error(error_msg)
            st.exception(e)
            return "Sorry, I encountered an authentication issue. Please check your API key."
        elif "rate limit" in error_str.lower() or "too many" in error_str.lower():
            error_msg = f"❌ OpenAI Rate Limit Error: Too many requests. Please wait a moment and try again.\n\nError: {error_str}"
            st.error(error_msg)
            st.exception(e)
            return "Sorry, I'm receiving too many requests. Please wait a moment and try again."
        else:
            error_msg = f"❌ OpenAI API Error ({error_type}): {error_str}"
            st.error(error_msg)
            st.exception(e)
            return f"Sorry, I encountered an issue: {error_str[:100]}. Could you please try again?"


# Text-to-Speech function
def synthesize_speech(text, voice_name="en-US-Neural2-F"):
    """
    Convert text to speech using Google Cloud Text-to-Speech
    
    Args:
        text: Text to convert to speech
        voice_name: Voice to use for synthesis
    
    Returns:
        bytes: Audio content in MP3 format
    """
    try:
        client = init_tts_client()
        
        synthesis_input = texttospeech.SynthesisInput(text=text)
        
        voice = texttospeech.VoiceSelectionParams(
            language_code="en-US",
            name=voice_name
        )
        
        audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.MP3,
            speaking_rate=1.0,
            pitch=0.0
        )
        
        response = client.synthesize_speech(
            input=synthesis_input,
            voice=voice,
            audio_config=audio_config
        )
        
        return response.audio_content
    
    except Exception as e:
        st.error(f"❌ Text-to-speech error: {str(e)}")
        return None

# Audio player helper
def autoplay_audio(audio_content):
    """
    Auto-play audio in Streamlit
    
    Args:
        audio_content: Audio bytes to play
    """
    if audio_content:
        b64 = base64.b64encode(audio_content).decode()
        audio_html = f"""
            <audio autoplay style="width: 100%;">
                <source src="data:audio/mp3;base64,{b64}" type="audio/mp3">
            </audio>
        """
        st.markdown(audio_html, unsafe_allow_html=True)

# Main UI
def main():
    st.title("🗣️ AI Language Tutor")
    st.markdown("Practice speaking English with an AI-powered conversation partner!")
    
    # Sidebar for configuration
    with st.sidebar:
        st.header("⚙️ Configuration")
        
        # Language Level
        level = st.selectbox(
            "Your Language Level",
            ["Beginner (A1-A2)", "Intermediate (B1-B2)", "Advanced (C1-C2)"],
            key="language_level"
        )
        
        # Tutor Persona
        persona = st.selectbox(
            "Tutor Personality",
            ["Friendly & Encouraging", "Professional & Direct", "Casual & Fun"],
            key="tutor_persona"
        )
        
        # Conversation Topic
        topic = st.selectbox(
            "Conversation Topic",
            [
                "General Conversation",
                "Restaurant & Ordering Food",
                "Job Interview Practice",
                "Travel & Tourism",
                "Everyday Small Talk",
                "Shopping & Errands"
            ],
            key="conversation_topic"
        )
        
        # Voice Selection
        voice_options = {
            "Female Voice 1": "en-US-Neural2-F",
            "Female Voice 2": "en-US-Neural2-C",
            "Male Voice 1": "en-US-Neural2-D",
            "Male Voice 2": "en-US-Neural2-A"
        }
        voice_selection = st.selectbox(
            "AI Voice",
            list(voice_options.keys()),
            key="voice_selection"
        )
        selected_voice = voice_options[voice_selection]

        # Google Credentials status
        with st.expander("Google Cloud Credentials"):
            # Credentials are already processed in the header
            creds_path = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS')
            
            if creds_path and os.path.exists(creds_path):
                # Validate credentials
                is_valid, error_msg = validate_google_credentials()
                
                if not is_valid:
                    st.error("⚠️ **Invalid credentials detected!**")
                    st.warning(f"{error_msg}\n\n"
                              "**Common issues:**\n"
                              "- Using an API key instead of a Service Account JSON file\n"
                              "- Incorrect file path\n"
                              "- Invalid or corrupted JSON file\n\n"
                              "**Solution:** Download a new Service Account JSON key from Google Cloud Console:\n"
                              "1. IAM & Admin → Service Accounts\n"
                              "2. Select service account → Keys → Add Key → JSON\n"
                              "3. Update your `.env` file with the file path")
                else:
                    st.success(f"✅ Google credentials loaded")
                    st.caption("Service Account JSON Active")
            else:
                st.warning("⚠️ Google credentials not found")
                st.info("💡 **For Streamlit Cloud:** Add to Secrets: `gemini_llm_api` or `GOOGLE_APPLICATION_CREDENTIALS`")
                st.info("💡 **For local:** Add to `.env` file: `GOOGLE_APPLICATION_CREDENTIALS=path/to/credentials.json`")
                st.info("⚠️ **Important:** Use a Service Account JSON file, NOT an API key!")
        
        st.markdown("---")
        
        # Reset conversation
        if st.button("🔄 Reset Conversation", use_container_width=True):
            st.session_state.conversation_history = []
            st.session_state.messages = []
            st.session_state.last_user_message = None
            st.session_state.last_audio_file = None
            st.rerun()
        
        st.markdown("---")
        st.markdown("### 📊 Session Info")
        st.metric("Conversation Turns", len(st.session_state.messages) // 2)
    
    # Check if API keys are configured
    if not OPENAI_API_KEY:
        error_msg = "⚠️ OpenAI API key not found.\n\n"
        error_msg += "**For Streamlit Cloud:**\n"
        error_msg += "1. Go to your app settings on Streamlit Cloud\n"
        error_msg += "2. Navigate to 'Secrets' section\n"
        error_msg += "3. Add: `openai_api_llm = \"your-api-key\"` or `OPENAI_API_KEY = \"your-api-key\"`\n\n"
        error_msg += "**For local development:**\n"
        error_msg += f"Add to your `.env` file: `OPENAI_API_KEY=your-api-key`\n"
        st.error(error_msg)
        st.stop()
    
    # Validate Google credentials
    if not os.environ.get('GOOGLE_APPLICATION_CREDENTIALS'):
        error_msg = "⚠️ Google Cloud credentials not found.\n\n"
        error_msg += "**Important:** Google Cloud Speech-to-Text requires a **Service Account JSON file**, not an API key.\n\n"
        error_msg += "**For Streamlit Cloud:**\n"
        error_msg += "1. Go to your app settings on Streamlit Cloud\n"
        error_msg += "2. Navigate to 'Secrets' section\n"
        error_msg += "3. Add: `gemini_llm_api = \"...\"` (Service Account JSON)\n\n"
        error_msg += "**For local development:**\n"
        error_msg += f"Add to your `.env` file: `GOOGLE_APPLICATION_CREDENTIALS=path/to/service-account.json`\n"
        st.error(error_msg)
        st.stop()
    else:
        # Validate the credentials are correct
        is_valid, error_msg = validate_google_credentials()
        if not is_valid:
            st.error(f"⚠️ **Invalid Google Cloud credentials:**\n\n{error_msg}\n\n"
                    "**To fix:**\n"
                    "1. Make sure you're using a **Service Account JSON file**, not an API key\n"
                    "2. Download a new Service Account key from Google Cloud Console:\n"
                    "   - Go to IAM & Admin → Service Accounts\n"
                    "   - Select your service account → Keys → Add Key → JSON\n"
                    "3. Update your `.env` file with the correct path:\n"
                    f"   `GOOGLE_APPLICATION_CREDENTIALS=/full/path/to/service-account.json`\n"
                    "4. Make sure Speech-to-Text and Text-to-Speech APIs are enabled")
            st.stop()
    
    # Main conversation area
    st.markdown("### 💬 Conversation")
    
    # Display conversation history
    chat_container = st.container()
    with chat_container:
        if len(st.session_state.messages) == 0:
            st.info("""
            👋 **Welcome! Here's how to get started:**
            
            1. Configure your preferences in the sidebar (language level, tutor personality, topic)
            2. Click the audio uploader and record your voice, or upload an audio file
            3. Click "Send" to submit your audio
            4. Alternatively, type your message in the text box below
            5. The AI tutor will respond with both text and speech!
            
            **Tips:**
            - Speak clearly and at a normal pace
            - If audio doesn't work, use the text input as a backup
            - Don't worry about mistakes - the tutor is here to help!
            """)
        else:
            for message in st.session_state.messages:
                role = message["role"]
                content = message["content"]
                timestamp = message.get("timestamp", "")
                
                if role == "user":
                    st.markdown(f"""
                    <div style='background-color: #e3f2fd; padding: 15px; border-radius: 10px; margin: 10px 0; color: #000000;'>
                        <strong>🙋 You</strong> <span style='color: #666; font-size: 0.8em;'>{timestamp}</span><br>
                        {content}
                    </div>
                    """, unsafe_allow_html=True)
                else:
                    st.markdown(f"""
                    <div style='background-color: #f5f5f5; padding: 15px; border-radius: 10px; margin: 10px 0; color: #000000;'>
                        <strong>🤖 AI Tutor</strong> <span style='color: #666; font-size: 0.8em;'>{timestamp}</span><br>
                        {content}
                    </div>
                    """, unsafe_allow_html=True)
    
    # Audio input section
    st.markdown("---")
    st.markdown("### 🎤 Your Turn to Speak")
    
    # Microphone recorder (records to WAV), auto-process on stop
    st.markdown("Click to start recording, speak, then stop to send.")
    audio_data = mic_recorder(
        start_prompt="🎙️ Start recording",
        stop_prompt="⏹️ Stop",
        key="mic_recorder"
    )
    
    # Reset the text input on the next run if flagged
    if st.session_state.get("reset_text_input"):
        st.session_state["text_input"] = ""
        st.session_state["reset_text_input"] = False

    # Text input as alternative
    text_input = st.text_input(
        "Or type your message here (if voice isn't working)",
        placeholder="Type your message and press Enter...",
        key="text_input"
    )
    
    # Process audio or text input
    new_message = None

    # Process mic audio automatically when available
    if audio_data and isinstance(audio_data, dict) and audio_data.get('bytes'):
        with st.spinner("🎧 Transcribing your speech..."):
            audio_bytes = audio_data['bytes']
            new_message = transcribe_audio(audio_bytes)
            if not new_message:
                st.warning("Could not transcribe audio. Please try again or use text input.")

    # Process text input (only if new and not empty)
    elif text_input and text_input.strip() and text_input != st.session_state.last_user_message:
        new_message = text_input.strip()
        # Flag to clear the text input on the next run
        st.session_state.reset_text_input = True

    # Handle AI interaction if there is a new message
    if new_message:
        st.session_state.last_user_message = new_message
        timestamp = datetime.now().strftime("%H:%M:%S")

        # Add user message
        st.session_state.messages.append({
            "role": "user",
            "content": new_message,
            "timestamp": timestamp
        })
        st.session_state.conversation_history.append({
            "role": "user",
            "content": new_message
        })

        # Get AI response
        with st.spinner("🤔 AI is thinking..."):
            ai_response = get_ai_response(
                new_message,
                st.session_state.conversation_history,
                persona,
                topic,
                level
            )

        ai_timestamp = datetime.now().strftime("%H:%M:%S")

        # Add AI response to session state
        st.session_state.messages.append({
            "role": "assistant",
            "content": ai_response,
            "timestamp": ai_timestamp
        })
        
        # Add to conversation history for context
        st.session_state.conversation_history.append({
            "role": "assistant",
            "content": ai_response
        })

        # Generate and play speech
        with st.spinner("🔊 Generating speech..."):
            audio_content = synthesize_speech(ai_response, voice_name=selected_voice)
            if audio_content:
                autoplay_audio(audio_content)

        # Rerun to refresh the UI and clear inputs
        st.rerun()

if __name__ == "__main__":
    main()