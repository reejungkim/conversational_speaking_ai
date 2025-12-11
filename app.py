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

# --- CRITICAL: DEBUG & SETUP CREDENTIALS ---
def setup_google_credentials():
    """
    Verbose setup to diagnose Streamlit Cloud secrets issues.
    Returns: True if successful, False otherwise.
    """
    st.sidebar.header("🔧 System Status")
    
    # 1. Check if we already have the Env Var (Local Dev)
    if os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
        if os.path.exists(os.environ["GOOGLE_APPLICATION_CREDENTIALS"]):
            st.sidebar.success("✅ Credentials found in Env (Local)")
            return True
            
    # 2. Check Streamlit Secrets
    raw_secret = None
    secret_source = "None"
    
    if hasattr(st, "secrets"):
        # Check specific key 'gemini_llm_api'
        if "gemini_llm_api" in st.secrets:
            raw_secret = st.secrets["gemini_llm_api"]
            secret_source = "st.secrets['gemini_llm_api']"
        # Check 'GOOGLE_APPLICATION_CREDENTIALS'
        elif "GOOGLE_APPLICATION_CREDENTIALS" in st.secrets:
            raw_secret = st.secrets["GOOGLE_APPLICATION_CREDENTIALS"]
            secret_source = "st.secrets['GOOGLE_APPLICATION_CREDENTIALS']"

    if not raw_secret:
        st.sidebar.error("❌ No Google Credentials found in Secrets.")
        return False

    # 3. Process the Secret
    try:
        json_content = None
        
        # If it's already a dict (TOML table)
        if isinstance(raw_secret, dict):
            # Convert to dict to be safe
            json_content = dict(raw_secret)
            
        # If it's a string (TOML string)
        elif isinstance(raw_secret, str):
            clean_str = raw_secret.strip()
            # Clean common copy-paste artifacts
            clean_str = clean_str.replace('\u00a0', ' ') 
            try:
                json_content = json.loads(clean_str)
            except json.JSONDecodeError as e:
                st.sidebar.error(f"❌ JSON Parse Error: {e}")
                st.sidebar.code(clean_str[:100] + "...", language="text") # Show start of string for debug
                return False
                
        if not json_content:
            st.sidebar.error("❌ Failed to process secret into JSON.")
            return False

        # 4. FIX PRIVATE KEY (Common Streamlit Issue)
        # Sometimes newlines get escaped as '\\n' literal characters
        if "private_key" in json_content:
            key = json_content["private_key"]
            if "\\n" in key:
                json_content["private_key"] = key.replace("\\n", "\n")
        
        # 5. Create Temp File
        with tempfile.NamedTemporaryFile(delete=False, suffix='.json', mode='w', encoding='utf-8') as tmp:
            json.dump(json_content, tmp)
            tmp_path = tmp.name
            
        # 6. Set Environment Variable
        os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = tmp_path
        st.sidebar.success(f"✅ Loaded from {secret_source}")
        return True

    except Exception as e:
        st.sidebar.error(f"❌ Unexpected Error: {e}")
        return False

# Run Setup Immediately
credentials_ok = setup_google_credentials()

# Get OpenAI Key
OPENAI_API_KEY = None
if hasattr(st, 'secrets') and 'openai_api_llm' in st.secrets:
    OPENAI_API_KEY = st.secrets['openai_api_llm']
elif hasattr(st, 'secrets') and 'OPENAI_API_KEY' in st.secrets:
    OPENAI_API_KEY = st.secrets['OPENAI_API_KEY']
else:
    OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')

# --- END CONFIGURATION ---

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

# Initialize clients
@st.cache_resource
def init_speech_client():
    if not credentials_ok: return None
    return speech.SpeechClient()

@st.cache_resource
def init_tts_client():
    if not credentials_ok: return None
    return texttospeech.TextToSpeechClient()

# Speech-to-Text function
def transcribe_audio(audio_content):
    if not credentials_ok:
        st.error("Google Cloud Credentials are missing.")
        return None
        
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
        st.error(f"Transcription Error: {str(e)}")
        return None

# GPT-4 function
def get_ai_response(user_input, conversation_history, persona, topic, level):
    if not OPENAI_API_KEY:
        st.error("OpenAI API Key is missing.")
        return "I can't respond right now."

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
    trimmed_history = conversation_history[-6:] if len(conversation_history) > 6 else conversation_history
    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(trimmed_history)
    messages.append({"role": "user", "content": user_input})

    try:
        client = OpenAI(api_key=str(OPENAI_API_KEY).strip())
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            temperature=0.7,
            max_tokens=300
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        st.error(f"OpenAI Error: {e}")
        return "Sorry, I encountered an error."

# Text-to-Speech function
def synthesize_speech(text, voice_name="en-US-Neural2-F"):
    if not credentials_ok: return None
    try:
        client = init_tts_client()
        synthesis_input = texttospeech.SynthesisInput(text=text)
        voice = texttospeech.VoiceSelectionParams(language_code="en-US", name=voice_name)
        audio_config = texttospeech.AudioConfig(audio_encoding=texttospeech.AudioEncoding.MP3)
        response = client.synthesize_speech(input=synthesis_input, voice=voice, audio_config=audio_config)
        return response.audio_content
    except Exception as e:
        st.error(f"TTS Error: {str(e)}")
        return None

# Audio player helper
def autoplay_audio(audio_content):
    if audio_content:
        b64 = base64.b64encode(audio_content).decode()
        audio_html = f"""<audio autoplay style="width: 100%;"><source src="data:audio/mp3;base64,{b64}" type="audio/mp3"></audio>"""
        st.markdown(audio_html, unsafe_allow_html=True)

# Main UI
def main():
    st.title("🗣️ AI Language Tutor")
    
    if not credentials_ok:
        st.error("⚠️ **System Error: Google Cloud Credentials not loaded.**")
        st.info("Check the 'System Status' in the sidebar for details.")
        st.stop()
        
    if not OPENAI_API_KEY:
        st.error("⚠️ **System Error: OpenAI API Key not loaded.**")
        st.stop()

    # Sidebar for configuration
    with st.sidebar:
        st.header("⚙️ Preferences")
        level = st.selectbox("Language Level", ["Beginner (A1-A2)", "Intermediate (B1-B2)", "Advanced (C1-C2)"], key="language_level")
        persona = st.selectbox("Tutor Personality", ["Friendly & Encouraging", "Professional & Direct", "Casual & Fun"], key="tutor_persona")
        topic = st.selectbox("Topic", ["General Conversation", "Restaurant & Ordering", "Job Interview", "Travel", "Small Talk"], key="conversation_topic")
        voice_selection = st.selectbox("AI Voice", ["Female 1", "Female 2", "Male 1", "Male 2"], key="voice_selection")
        
        voice_map = {
            "Female 1": "en-US-Neural2-F", "Female 2": "en-US-Neural2-C",
            "Male 1": "en-US-Neural2-D", "Male 2": "en-US-Neural2-A"
        }
        selected_voice = voice_map[voice_selection]
        
        if st.button("🔄 Reset Chat", use_container_width=True):
            st.session_state.conversation_history = []
            st.session_state.messages = []
            st.session_state.last_user_message = None
            st.rerun()

    # Chat UI
    chat_container = st.container()
    with chat_container:
        if not st.session_state.messages:
            st.info("👋 **Welcome!** Select your topic and start speaking/typing.")
        
        for message in st.session_state.messages:
            role = message["role"]
            content = message["content"]
            if role == "user":
                st.markdown(f"<div style='background-color: #e3f2fd; padding: 10px; border-radius: 10px; margin: 5px 0;'><strong>You:</strong> {content}</div>", unsafe_allow_html=True)
            else:
                st.markdown(f"<div style='background-color: #f5f5f5; padding: 10px; border-radius: 10px; margin: 5px 0;'><strong>Tutor:</strong> {content}</div>", unsafe_allow_html=True)

    # Inputs
    st.markdown("---")
    col1, col2 = st.columns([1, 4])
    with col1:
        audio_data = mic_recorder(start_prompt="🎤 Speak", stop_prompt="⏹️ Stop", key="mic")
    with col2:
        text_input = st.text_input("Or type here:", key="text_in")

    # Processing Logic
    user_msg = None
    if audio_data and audio_data['bytes']:
        with st.spinner("Transcribing..."):
            user_msg = transcribe_audio(audio_data['bytes'])
    elif text_input and text_input != st.session_state.last_user_message:
        user_msg = text_input

    if user_msg:
        st.session_state.last_user_message = user_msg
        st.session_state.messages.append({"role": "user", "content": user_msg})
        st.session_state.conversation_history.append({"role": "user", "content": user_msg})
        
        with st.spinner("Thinking..."):
            ai_resp = get_ai_response(user_msg, st.session_state.conversation_history, persona, topic, level)
            
        st.session_state.messages.append({"role": "assistant", "content": ai_resp})
        st.session_state.conversation_history.append({"role": "assistant", "content": ai_resp})
        
        with st.spinner("Speaking..."):
            audio = synthesize_speech(ai_resp, selected_voice)
            if audio: autoplay_audio(audio)
        
        st.rerun()

if __name__ == "__main__":
    main()