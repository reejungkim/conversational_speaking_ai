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
import time

# --- 1. PAGE CONFIGURATION (MUST BE FIRST) ---
st.set_page_config(
    page_title="AI Language Tutor",
    page_icon="🗣️",
    layout="wide"
)

# --- 2. LOGIN LOGIC (NEW) ---
def check_login():
    """Returns True if the user had logged in."""
    if "password_correct" not in st.session_state:
        st.session_state.password_correct = False

    def password_entered():
        """Checks whether a password entered by the user is correct."""
        if (
            st.session_state["username"] in st.secrets["login"]["username"]
            and st.session_state["password"] == st.secrets["login"]["password"]
        ):
            st.session_state.password_correct = True
            # Delete password from session state for security
            del st.session_state["password"]
            del st.session_state["username"]
        else:
            st.session_state.password_correct = False

    if st.session_state.password_correct:
        return True

    # --- 🔒 NEW FORM LOGIC STARTS HERE ---
    st.markdown("## 🔒 Please Log In")
    
    with st.form("credentials"):
        st.text_input("Username", key="username")
        st.text_input("Password", type="password", key="password")
        
        # Using form_submit_button allows "Enter" key to trigger this too
        st.form_submit_button("Log in", on_click=password_entered)
    # -------------------------------------
    
    if "password_correct" in st.session_state and st.session_state.get("username"):
         st.error("😕 User not known or password incorrect")
         
    return False

# --- STOP EXECUTION IF NOT LOGGED IN ---
if not check_login():
    st.stop()

# --- 3. SETUP & CREDENTIALS ---
APP_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(APP_DIR, '.env')
load_dotenv(ENV_PATH)

def sanitize_json_string(s):
    """
    Aggressively cleans JSON strings.
    Specifically fixes 'Invalid control character' errors in private keys.
    """
    if not isinstance(s, str):
        return s
    
    # 1. Remove non-breaking spaces (common copy-paste artifact)
    s = s.replace('\u00a0', ' ')
    
    # 2. Fix Smart Quotes
    s = s.replace('“', '"').replace('”', '"').replace("‘", "'").replace("’", "'")
    
    # 3. CRITICAL FIX: Handle actual newlines inside the private_key string.
    try:
        pattern = r'("private_key"\s*:\s*")([^"]+)(")'
        def escape_newlines(match):
            key_label = match.group(1)
            content = match.group(2)
            end_quote = match.group(3)
            fixed_content = content.replace('\n', '\\n').replace('\r', '')
            return f'{key_label}{fixed_content}{end_quote}'
        s = re.sub(pattern, escape_newlines, s, flags=re.DOTALL)
    except Exception:
        pass

    return s.strip()

def find_google_credentials_in_secrets():
    """Scans secrets for Google Service Account credentials."""
    logs = []
    
    if hasattr(st, 'secrets'):
        if "type" in st.secrets and st.secrets["type"] == "service_account":
            return dict(st.secrets), "ROOT", logs

        keys_to_check = list(st.secrets.keys())
        # Filter out the login key so we don't scan it for google creds
        keys_to_check = [k for k in keys_to_check if k != "login"]
        logs.append(f"🔎 Scanning secret keys: {keys_to_check}")
        
        for key in keys_to_check:
            value = st.secrets[key]
            if isinstance(value, dict) or hasattr(value, "keys"):
                try:
                    d = dict(value)
                    if d.get("type") == "service_account":
                        return d, key, logs
                except: pass
            elif isinstance(value, str):
                cleaned = sanitize_json_string(value)
                if "service_account" in cleaned and "private_key" in cleaned:
                    logs.append(f"👀 Key '{key}' looks promising. parsing...")
                    try:
                        d = json.loads(cleaned, strict=False)
                        if isinstance(d, dict) and d.get("type") == "service_account":
                            return d, key, logs
                    except json.JSONDecodeError as e:
                        logs.append(f"❌ Key '{key}' JSON error: {str(e)}")
                        pass

    env_path = os.getenv('GOOGLE_APPLICATION_CREDENTIALS')
    if env_path and os.path.isfile(env_path):
        return env_path, "ENV_VAR", logs

    return None, None, logs

def setup_credentials():
    creds, source, logs = find_google_credentials_in_secrets()
    
    if creds:
        try:
            if isinstance(creds, str) and os.path.isfile(creds):
                os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = creds
                return True, logs, source
                
            if isinstance(creds, dict):
                if 'private_key' in creds:
                    creds['private_key'] = creds['private_key'].replace('\\n', '\n')
                
                with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False, encoding='utf-8') as f:
                    json.dump(creds, f)
                    temp_path = f.name
                
                os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = temp_path
                return True, logs, source
        except Exception as e:
            logs.append(f"❌ Error writing temp file: {str(e)}")
            
    return False, logs, None

# Run Setup
creds_ok, debug_logs, creds_source = setup_credentials()

# Find OpenAI Key
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if hasattr(st, "secrets") and not OPENAI_API_KEY:
    for key in ['openai_api_llm', 'OPENAI_API_KEY', 'openai_key']:
        if key in st.secrets:
            OPENAI_API_KEY = st.secrets[key]
            break
    if not OPENAI_API_KEY:
        for k, v in st.secrets.items():
            if "openai" in k.lower() and "login" not in k: # avoid confusing with login
                OPENAI_API_KEY = v
                break

# --- 4. APP LOGIC ---

if 'conversation_history' not in st.session_state:
    st.session_state.conversation_history = []
if 'messages' not in st.session_state:
    st.session_state.messages = []
if 'last_user_message' not in st.session_state:
    st.session_state.last_user_message = None
# TRACKING AUDIO STATE TO PREVENT LOOP
if 'last_audio_bytes' not in st.session_state:
    st.session_state.last_audio_bytes = None

@st.cache_resource
def init_speech_client():
    return speech.SpeechClient()

@st.cache_resource
def init_tts_client():
    return texttospeech.TextToSpeechClient()

def transcribe_audio(audio_content):
    try:
        client = init_speech_client()
        sample_rate = 16000
        try:
            with wave.open(io.BytesIO(audio_content), 'rb') as wav_file:
                sample_rate = wav_file.getframerate()
        except: pass

        audio = speech.RecognitionAudio(content=audio_content)
        config = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=sample_rate,
            language_code="en-US",
            enable_automatic_punctuation=True,
            model="default"
        )
        response = client.recognize(config=config, audio=audio)
        if not response.results: return None
        return " ".join([result.alternatives[0].transcript for result in response.results]).strip()
    except Exception as e:
        st.error(f"Transcription Error: {e}")
        return None

def get_ai_response(user_input, history, persona, topic, level):
    if not OPENAI_API_KEY:
        st.error("OpenAI Key Missing")
        return "Error: No API Key."
        
    client = OpenAI(api_key=str(OPENAI_API_KEY).strip())
    
    sys_prompt = f"Role: English Tutor ({persona})\nTopic: {topic}\nLevel: {level}\nGoal: Conversational practice. Keep replies short (2-4 sentences)."
    msgs = [{"role": "system", "content": sys_prompt}] + history[-6:] + [{"role": "user", "content": user_input}]

    try:
        response = client.chat.completions.create(model="gpt-4o-mini", messages=msgs)
        return response.choices[0].message.content.strip()
    except Exception as e:
        st.error(f"OpenAI Error: {e}")
        return "Sorry, I encountered an error."

def synthesize_speech(text, voice_name):
    try:
        client = init_tts_client()
        s_input = texttospeech.SynthesisInput(text=text)
        voice = texttospeech.VoiceSelectionParams(language_code="en-US", name=voice_name)
        audio_config = texttospeech.AudioConfig(audio_encoding=texttospeech.AudioEncoding.MP3)
        response = client.synthesize_speech(input=s_input, voice=voice, audio_config=audio_config)
        return response.audio_content
    except Exception as e:
        st.error(f"TTS Error: {e}")
        return None

def autoplay_audio(audio_content):
    if audio_content:
        b64 = base64.b64encode(audio_content).decode()
        st.markdown(f'<audio autoplay style="width: 100%;"><source src="data:audio/mp3;base64,{b64}" type="audio/mp3"></audio>', unsafe_allow_html=True)

def main():
    st.title("🗣️ AI Language Tutor")

    # Initialize a dynamic key for the text input
    if 'text_input_key' not in st.session_state:
        st.session_state.text_input_key = "initial_text_input"
    
    # Debugger
    with st.expander("🔧 Connection Debugger", expanded=not creds_ok or not OPENAI_API_KEY):
        if creds_ok: st.success(f"✅ Google Creds: {creds_source}")
        else: st.error("❌ Google Creds Missing")
        if OPENAI_API_KEY: st.success("✅ OpenAI Key Found")
        else: st.error("❌ OpenAI Key Missing")
        for log in debug_logs:
            if "❌" in log: st.markdown(f"**{log}**")
            else: st.text(log)
            
    if not creds_ok or not OPENAI_API_KEY: st.stop()

    # Sidebar
    with st.sidebar:
        st.header("Settings")
        level = st.selectbox("Level", ["Beginner (A1-A2)", "Intermediate (B1-B2)", "Advanced (C1-C2)"])
        persona = st.selectbox("Persona", ["Friendly", "Professional", "Casual"])
        topic = st.selectbox("Topic", ["General", "Food", "Travel", "Work"])
        voice = st.selectbox("Voice", ["en-US-Neural2-F", "en-US-Neural2-D"])
        
        st.markdown("---")
        if st.button("Reset Chat"):
            st.session_state.messages = []
            st.session_state.conversation_history = []
            st.session_state.last_audio_bytes = None
            st.session_state.text_input_key = "reset_text_input"
            st.rerun()
            
        if st.button("Logout", type="primary"):
            st.session_state.password_correct = False
            st.rerun()

    # Chat
    for msg in st.session_state.messages:
        bg = "#e3f2fd" if msg["role"] == "user" else "#f5f5f5"
        st.markdown(f"<div style='background:{bg};padding:10px;border-radius:10px;margin:5px 0; color: black'><b>{msg['role'].title()}:</b> {msg['content']}</div>", unsafe_allow_html=True)

    # Input
    st.markdown("---")
    c1, c2 = st.columns([1, 4])
    with c1: audio = mic_recorder(start_prompt="🎙️", stop_prompt="⏹️", key="mic")
    with c2: text = st.text_input("Type...", key=st.session_state.text_input_key)

    user_msg = None
    msg_source = None
    
    if audio and audio.get('bytes'):
        if audio['bytes'] == st.session_state.last_audio_bytes:
            pass
        else:
            st.session_state.last_audio_bytes = audio['bytes']
            with st.spinner("Transcribing..."):
                user_msg = transcribe_audio(audio['bytes'])
                if user_msg:
                    msg_source = 'audio'
                
    elif text and text != st.session_state.last_user_message:
        user_msg = text
        msg_source = 'text'

    if user_msg:
        st.session_state.last_user_message = user_msg
        st.session_state.messages.append({"role": "user", "content": user_msg})
        st.session_state.conversation_history.append({"role": "user", "content": user_msg})
        
        with st.spinner("Thinking..."):
            reply = get_ai_response(user_msg, st.session_state.conversation_history, persona, topic, level)
            st.session_state.messages.append({"role": "assistant", "content": reply})
            st.session_state.conversation_history.append({"role": "assistant", "content": reply})
            
            sound = synthesize_speech(reply, voice)
            if sound: autoplay_audio(sound)

        if msg_source == 'text':
            current_key = st.session_state.text_input_key
            st.session_state.text_input_key = f"text_input_{time.time()}"
            if current_key in st.session_state:
                del st.session_state[current_key]
            
        st.rerun()

if __name__ == "__main__":
    main()