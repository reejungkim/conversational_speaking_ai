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
import re

# --- 1. PAGE CONFIGURATION (MUST BE FIRST) ---
st.set_page_config(
    page_title="AI Language Tutor",
    page_icon="🗣️",
    layout="wide"
)

# --- 2. SETUP & CREDENTIALS ---
# Get the directory where app.py is located
APP_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(APP_DIR, '.env')

# Load environment variables from .env file (for local development)
load_dotenv(ENV_PATH)

def sanitize_json_string(s):
    """Attempt to clean up common copy-paste errors in JSON strings."""
    if not isinstance(s, str):
        return s
    # Remove non-breaking spaces
    s = s.replace('\u00a0', ' ')
    # Replace smart quotes with standard quotes
    s = s.replace('“', '"').replace('”', '"').replace("‘", "'").replace("’", "'")
    return s.strip()

def find_google_credentials_in_secrets():
    """
    Scans ALL Streamlit secrets to find anything that looks like a Google Service Account.
    Returns: (found_dict, source_key_name, status_logs)
    """
    logs = []
    
    # 1. Check if the secrets file ITSELF is the JSON (Root level)
    if hasattr(st, 'secrets'):
        # Check if root has 'type': 'service_account'
        if "type" in st.secrets and st.secrets["type"] == "service_account":
            logs.append("✅ Found service account fields at root of secrets.")
            return dict(st.secrets), "ROOT", logs

        # 2. Iterate through every top-level key
        keys_to_check = list(st.secrets.keys())
        logs.append(f"🔎 Scanning secret keys: {keys_to_check}")
        
        for key in keys_to_check:
            value = st.secrets[key]
            
            # CASE A: Value is a Dictionary (TOML Table)
            if isinstance(value, dict) or hasattr(value, "keys"):
                # Convert to standard dict to be safe
                try:
                    d = dict(value)
                    if d.get("type") == "service_account" and d.get("private_key"):
                        logs.append(f"✅ Found valid Service Account Dict under key: '{key}'")
                        return d, key, logs
                except Exception:
                    pass
            
            # CASE B: Value is a String (TOML String / JSON String)
            elif isinstance(value, str):
                cleaned = sanitize_json_string(value)
                # Heuristic: does it contain key phrases?
                if "service_account" in cleaned and "private_key" in cleaned:
                    logs.append(f"👀 Key '{key}' looks like a Service Account string. Attempting parse...")
                    try:
                        d = json.loads(cleaned)
                        if isinstance(d, dict) and d.get("type") == "service_account":
                            logs.append(f"✅ Successfully parsed JSON string under key: '{key}'")
                            return d, key, logs
                    except json.JSONDecodeError as e:
                        logs.append(f"❌ Key '{key}' looks right but failed JSON parsing: {str(e)}")
                        logs.append(f"   Snippet: {cleaned[:50]}...")

    # 3. Check Environment Variables (Last Resort)
    env_path = os.getenv('GOOGLE_APPLICATION_CREDENTIALS')
    if env_path:
        logs.append(f"found GOOGLE_APPLICATION_CREDENTIALS env var: {env_path}")
        if os.path.isfile(env_path):
             return env_path, "ENV_VAR", logs
        else:
             logs.append("❌ Env var exists but file not found.")

    return None, None, logs

def setup_credentials():
    """Runs the setup and returns log info for the debugger."""
    creds, source, logs = find_google_credentials_in_secrets()
    
    if creds:
        try:
            # If we found a path (from env var), verify it
            if isinstance(creds, str) and os.path.isfile(creds):
                os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = creds
                return True, logs, source
                
            # If we found a dict, write to temp file
            if isinstance(creds, dict):
                # Dump to JSON string
                json_content = json.dumps(creds)
                
                # Create temp file
                with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False, encoding='utf-8') as f:
                    f.write(json_content)
                    f.flush()
                    temp_path = f.name
                
                os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = temp_path
                logs.append(f"💾 Written credentials to temp file: {temp_path}")
                return True, logs, source
        except Exception as e:
            logs.append(f"❌ Error writing temp file: {str(e)}")
            return False, logs, None
            
    return False, logs, None

# Run Setup (After page config)
creds_ok, debug_logs, creds_source = setup_credentials()

# Get OpenAI Key
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if hasattr(st, "secrets") and not OPENAI_API_KEY:
    if "OPENAI_API_KEY" in st.secrets:
        OPENAI_API_KEY = st.secrets["OPENAI_API_KEY"]
    else:
        # Try finding openai key case-insensitively
        for k, v in st.secrets.items():
            if "openai" in k.lower() and "key" in k.lower():
                OPENAI_API_KEY = v
                break

# --- 3. APP LOGIC ---

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
    return speech.SpeechClient()

@st.cache_resource
def init_tts_client():
    return texttospeech.TextToSpeechClient()

# Speech-to-Text function
def transcribe_audio(audio_content):
    try:
        client = init_speech_client()
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
        if not response.results: return None
        transcript = "".join([result.alternatives[0].transcript + " " for result in response.results])
        return transcript.strip()
    except Exception as e:
        st.error(f"Transcription Error: {e}")
        return None

# GPT-4 function
def get_ai_response(user_input, conversation_history, persona, topic, level):
    if not OPENAI_API_KEY:
        st.error("OpenAI API Key missing.")
        return "Error: No API Key."
        
    client = OpenAI(api_key=str(OPENAI_API_KEY).strip())
    
    persona_prompts = {
        "Friendly & Encouraging": f"You are a friendly and encouraging English conversation partner. Be patient, supportive. Keep responses natural (2-4 sentences).",
        "Professional & Direct": f"You are a professional English tutor. Provide clear feedback. Keep responses educational (2-4 sentences).",
        "Casual & Fun": f"You are a casual and fun English conversation partner. Use idioms/humor. Keep it light (2-4 sentences)."
    }
    
    system_prompt = f"Role: {persona_prompts.get(persona)}\nTopic: {topic}\nLevel: {level}\nInstructions: Reply naturally, stay on topic, don't repeat yourself."

    trimmed_history = conversation_history[-6:]
    messages = [{"role": "system", "content": system_prompt}] + trimmed_history + [{"role": "user", "content": user_input}]

    try:
        response = client.chat.completions.create(model="gpt-4o-mini", messages=messages, temperature=0.7)
        return response.choices[0].message.content.strip()
    except Exception as e:
        st.error(f"OpenAI Error: {e}")
        return "Sorry, I encountered an error."

# Text-to-Speech function
def synthesize_speech(text, voice_name):
    try:
        client = init_tts_client()
        synthesis_input = texttospeech.SynthesisInput(text=text)
        voice = texttospeech.VoiceSelectionParams(language_code="en-US", name=voice_name)
        audio_config = texttospeech.AudioConfig(audio_encoding=texttospeech.AudioEncoding.MP3)
        response = client.synthesize_speech(input=synthesis_input, voice=voice, audio_config=audio_config)
        return response.audio_content
    except Exception as e:
        st.error(f"TTS Error: {e}")
        return None

def autoplay_audio(audio_content):
    if audio_content:
        b64 = base64.b64encode(audio_content).decode()
        st.markdown(f'<audio autoplay style="width: 100%;"><source src="data:audio/mp3;base64,{b64}" type="audio/mp3"></audio>', unsafe_allow_html=True)

# Main UI
def main():
    st.title("🗣️ AI Language Tutor")
    
    # --- DEBUGGER SECTION ---
    with st.expander("🔧 Connection Debugger (Open if issues persist)", expanded=not creds_ok):
        st.write("### Credential Status")
        if creds_ok:
            st.success(f"✅ Google Credentials Loaded Successfully from: **{creds_source}**")
        else:
            st.error("❌ Google Credentials NOT Found.")
            
        st.write("### Diagnostics Logs")
        for log in debug_logs:
            if "❌" in log:
                st.markdown(f"**{log}**") # Bold errors
            else:
                st.text(log)
                
        st.write("### OpenAI Key Status")
        if OPENAI_API_KEY:
            st.success(f"✅ OpenAI Key detected (Starts with: {str(OPENAI_API_KEY)[:5]}...)")
        else:
            st.error("❌ OpenAI Key NOT found.")
    # ------------------------
    
    # Stop if critical errors
    if not creds_ok or not OPENAI_API_KEY:
        st.warning("Please check the Debugger above to fix your credentials before continuing.")
        st.stop()

    # Sidebar
    with st.sidebar:
        st.header("⚙️ Settings")
        level = st.selectbox("Level", ["Beginner (A1-A2)", "Intermediate (B1-B2)", "Advanced (C1-C2)"])
        persona = st.selectbox("Persona", ["Friendly & Encouraging", "Professional & Direct", "Casual & Fun"])
        topic = st.selectbox("Topic", ["General Chat", "Food & Ordering", "Travel", "Job Interview"])
        voice_options = {"Female 1": "en-US-Neural2-F", "Male 1": "en-US-Neural2-D"}
        voice_selection = st.selectbox("Voice", list(voice_options.keys()))
        
        if st.button("🔄 Reset"):
            st.session_state.messages = []
            st.session_state.conversation_history = []
            st.rerun()

    # Chat Area
    for msg in st.session_state.messages:
        role_style = "background-color: #e3f2fd;" if msg["role"] == "user" else "background-color: #f5f5f5;"
        st.markdown(f"<div style='{role_style} padding: 10px; border-radius: 10px; margin: 5px 0;'><strong>{msg['role'].title()}:</strong> {msg['content']}</div>", unsafe_allow_html=True)

    # Inputs
    st.markdown("---")
    c1, c2 = st.columns([1, 4])
    with c1:
        audio_data = mic_recorder(start_prompt="🎙️ Record", stop_prompt="⏹️ Stop", key="mic")
    with c2:
        text_input = st.text_input("Type message...", key="txt_in")

    # Handling Inputs
    user_msg = None
    if audio_data and isinstance(audio_data, dict) and audio_data.get('bytes'):
        with st.spinner("Transcribing..."):
            user_msg = transcribe_audio(audio_data['bytes'])
    elif text_input and text_input != st.session_state.last_user_message:
        user_msg = text_input

    if user_msg:
        st.session_state.last_user_message = user_msg
        st.session_state.messages.append({"role": "user", "content": user_msg})
        st.session_state.conversation_history.append({"role": "user", "content": user_msg})
        
        with st.spinner("AI Thinking..."):
            ai_reply = get_ai_response(user_msg, st.session_state.conversation_history, persona, topic, level)
            st.session_state.messages.append({"role": "assistant", "content": ai_reply})
            st.session_state.conversation_history.append({"role": "assistant", "content": ai_reply})
            
            # Auto play audio
            audio = synthesize_speech(ai_reply, voice_options[voice_selection])
            if audio: autoplay_audio(audio)
            
        st.rerun()

if __name__ == "__main__":
    main()