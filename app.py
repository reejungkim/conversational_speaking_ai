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

# Get the directory where app.py is located
APP_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(APP_DIR, '.env')

# Load environment variables from .env file (for local development)
# This will be ignored on Streamlit Cloud where secrets are used instead
load_dotenv(ENV_PATH)

# Configuration: Check Streamlit secrets first (for Streamlit Cloud), then fall back to environment variables (for local)
def get_config_value(secret_keys, env_keys):
    """
    Get configuration value from Streamlit secrets (Cloud) or environment variables (local)
    
    Args:
        secret_keys: Single key or list of keys to look up in st.secrets
        env_keys: List of environment variable names to try
    
    Returns:
        Configuration value or None
    """
    # Normalize secret_keys to a list
    if isinstance(secret_keys, str):
        secret_keys = [secret_keys]
    
    # Try Streamlit secrets first (for Streamlit Cloud)
    try:
        if hasattr(st, 'secrets'):
            for secret_key in secret_keys:
                if secret_key in st.secrets:
                    value = st.secrets[secret_key]
                    if value:
                        value = str(value).strip()
                        if value:
                            return value
    except Exception:
        pass
    
    # Fall back to environment variables (for local development)
    for env_key in env_keys:
        value = os.getenv(env_key)
        if value:
            value = value.strip()
            if value:
                return value
    return None

# Get configuration values
GOOGLE_CREDENTIALS_PATH = get_config_value(
    ['gemini_llm_api', 'GOOGLE_APPLICATION_CREDENTIALS', 'GOOGLE_CREDENTIALS'],
    ['gemini_llm_api', 'GOOGLE_APPLICATION_CREDENTIALS', 'GOOGLE_CREDENTIALS']
)

OPENAI_API_KEY = get_config_value(
    ['openai_api_llm', 'OPENAI_API_KEY', 'OPENAI_KEY'],
    ['openai_api_llm', 'OPENAI_API_KEY', 'OPENAI_KEY']
)

# Ensure Google ADC env var is exported for client libraries using either a file path or raw JSON
if GOOGLE_CREDENTIALS_PATH:
    try:
        # If it's a valid file path, use it directly
        if os.path.isfile(GOOGLE_CREDENTIALS_PATH):
            os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = GOOGLE_CREDENTIALS_PATH
        else:
            # If it looks like JSON content, write to a temp file and point ADC to it
            stripped = GOOGLE_CREDENTIALS_PATH.strip()
            if stripped.startswith('{') and stripped.endswith('}'):
                tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.json')
                tmp.write(stripped.encode('utf-8'))
                tmp.flush()
                os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = tmp.name
                tmp.close()
    except Exception:
        pass

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



# Initialize clients
@st.cache_resource
def init_speech_client():
    """Initialize Google Speech-to-Text client"""
    return speech.SpeechClient()

@st.cache_resource
def init_tts_client():
    """Initialize Google Text-to-Speech client"""
    return texttospeech.TextToSpeechClient()

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
        st.error(f"❌ Transcription error: {str(e)}")
        return None

# GPT-4 function
def get_ai_response(user_input, conversation_history, persona, topic, level):
    """
    Generate AI tutor response using OpenAI GPT-4o mini
    
    Args:
        user_input: User's message
        conversation_history: List of previous messages
        persona: Tutor personality
        topic: Conversation topic
        level: User's language level
    
    Returns:
        str: AI response
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
        # Ensure we're not passing any unexpected arguments
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
            # Check if credentials are loaded (from secrets or env)
            creds_source = None
            creds_value = None
            
            # Check Streamlit secrets first
            try:
                if hasattr(st, 'secrets'):
                    for key in ['gemini_llm_api', 'GOOGLE_APPLICATION_CREDENTIALS', 'GOOGLE_CREDENTIALS']:
                        if key in st.secrets:
                            creds_source = "Streamlit Secrets"
                            creds_value = str(st.secrets[key])
                            break
            except Exception:
                pass
            
            # Check environment variables
            if not creds_value and os.environ.get('GOOGLE_APPLICATION_CREDENTIALS'):
                creds_source = ".env file"
                creds_value = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS')
            
            if creds_value:
                st.success(f"✅ Google credentials loaded from {creds_source}")
                # Only show partial path for security
                if len(creds_value) > 50:
                    st.info(f"Using: ...{creds_value[-30:]}")
                else:
                    st.info(f"Using: {creds_value}")
            else:
                st.warning("⚠️ Google credentials not found")
                st.info("💡 **For Streamlit Cloud:** Add to Secrets: `gemini_llm_api` or `GOOGLE_APPLICATION_CREDENTIALS`")
                st.info("💡 **For local:** Add to `.env` file: `GOOGLE_APPLICATION_CREDENTIALS=path/to/credentials.json`")
                # st.markdown("---")
                # st.write("**Manual override (optional):**")
                # mode = st.radio("Input type", ["Path", "JSON"], horizontal=True, key="adc_mode")
                # if mode == "Path":
                #     cred_path = st.text_input("Service account JSON path", value="", key="adc_path")
                # else:
                #     cred_json = st.text_area("Service account JSON (raw)", value="", height=150, key="adc_json")
                # if st.button("Save credentials", use_container_width=True, key="adc_save_btn"):
                #     try:
                #         if mode == "Path" and cred_path:
                #             if os.path.isfile(cred_path):
                #                 os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = cred_path
                #                 st.session_state.google_credentials_set = True
                #                 st.success("Google credentials saved (path).")
                #             else:
                #                 st.error("Path not found. Please check the file path.")
                #         elif mode == "JSON" and cred_json:
                #             stripped = cred_json.strip()
                #             if stripped.startswith('{') and stripped.endswith('}'):
                #                 tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.json')
                #                 tmp.write(stripped.encode('utf-8'))
                #                 tmp.flush()
                #                 os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = tmp.name
                #                 st.session_state.google_credentials_set = True
                #                 tmp.close()
                #                 st.success("Google credentials saved (JSON).")
                #             else:
                #                 st.error("Invalid JSON content.")
                #         else:
                #             st.warning("Please provide credentials in the selected format.")
                #     except Exception as e:
                #         st.error(f"Failed to save credentials: {e}")
        
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
    
    if not (os.environ.get('GOOGLE_APPLICATION_CREDENTIALS') or st.session_state.get('google_credentials_set')):
        error_msg = "⚠️ Google Cloud credentials not found.\n\n"
        error_msg += "**For Streamlit Cloud:**\n"
        error_msg += "1. Go to your app settings on Streamlit Cloud\n"
        error_msg += "2. Navigate to 'Secrets' section\n"
        error_msg += "3. Add: `gemini_llm_api = \"path/to/credentials.json\"` or paste JSON directly\n\n"
        error_msg += "**For local development:**\n"
        error_msg += f"Add to your `.env` file: `GOOGLE_APPLICATION_CREDENTIALS=path/to/credentials.json`\n"
        st.error(error_msg)
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