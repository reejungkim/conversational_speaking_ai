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
from supabase import create_client, Client 

#st.write("Debug: Found keys in secrets:", list(st.secrets.keys()))

# --- 1. PAGE CONFIGURATION (MUST BE FIRST) ---
st.set_page_config(
    page_title="AI Language Tutor",
    page_icon="🗣️",
    layout="wide"
)


# --- 2. CREDENTIALS FETCHING ---
def get_supabase_creds():
    """
    Fetches Supabase credentials from st.secrets.
    Streamlit automatically loads local values from .streamlit/secrets.toml
    and cloud values from the Streamlit Cloud dashboard.
    """
    try:
        # Check if the 'supabase' section exists in secrets
        if "supabase" in st.secrets:
            url = st.secrets["supabase"].get("url")
            key = st.secrets["supabase"].get("key")
            if url and key:
                return url, key
    except Exception:
        pass
    
    # Optional: Fallback to OS environment variables if needed
    return os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY")

# Initialize Supabase
SUPABASE_URL, SUPABASE_KEY = get_supabase_creds()

if not SUPABASE_URL or not SUPABASE_KEY:
    st.error("Missing Supabase Credentials! Ensure they are in .streamlit/secrets.toml (local) or App Settings (cloud).")
    st.stop()

supabase = Client(SUPABASE_URL, SUPABASE_KEY)


from user_auth import authenticate_user

# --- 2. LOGIN LOGIC ---
def check_login():
    """Returns True if the user has logged in."""
    if "password_correct" not in st.session_state:
        st.session_state.password_correct = False
        st.session_state.current_user = None

    if st.session_state.password_correct:
        return True

    def password_entered():
        """Checks whether a password entered by the user is correct."""
        username = st.session_state.get("username", "")
        password = st.session_state.get("password", "")
        
        # Try Supabase authentication first
        user = authenticate_user(supabase, username, password)
        
        if user:
            st.session_state.password_correct = True
            st.session_state.current_user = user
            # Clean up sensitive info from state
            if "password" in st.session_state:
                del st.session_state["password"]
            if "username" in st.session_state:
                del st.session_state["username"]
        else:
            # Fallback to secrets.toml for backward compatibility
            if "login" in st.secrets:
                if (
                    username in st.secrets["login"]["username"]
                    and password == st.secrets["login"]["password"]
                ):
                    st.session_state.password_correct = True
                    st.session_state.current_user = {
                        'username': username,
                        'full_name': username,
                        'is_admin': username == 'admin'
                    }
                    # Clean up sensitive info
                    if "password" in st.session_state:
                        del st.session_state["password"]
                    if "username" in st.session_state:
                        del st.session_state["username"]
                else:
                    st.session_state.password_correct = False
            else:
                st.session_state.password_correct = False

    # Display Login Form
    st.markdown("## 🔒 Please Log In")
    with st.form("credentials"):
        st.text_input("Username", key="username")
        st.text_input("Password", type="password", key="password")
        st.form_submit_button("Log in", on_click=password_entered)
    
    # Optional: Error message for failed attempts
    if "username" in st.session_state and not st.session_state.password_correct:
         st.error("😕 User not known or password incorrect")
    
    # Info message about admin panel
    st.info("👉 Admins: Access the user management panel by running `streamlit run admin_panel.py`")

    return False

# Execution Flow
if not check_login():
    st.stop()  # Stop here if not logged in

# --- 3. SETUP & CREDENTIALS ---
#APP_DIR = os.path.dirname(os.path.abspath(__file__))
# ENV_PATH = os.path.join(APP_DIR, '.env')
# load_dotenv(ENV_PATH)



def sanitize_json_string(s):
    if not isinstance(s, str): return s
    s = s.replace('\u00a0', ' ').replace('“', '"').replace('”', '"').replace("‘", "'").replace("’", "'")
    try:
        pattern = r'("private_key"\s*:\s*")([^"]+)(")'
        def escape_newlines(match):
            # Move the replacement logic to variables to avoid backslashes inside the f-string
            prefix = match.group(1)
            key_content = match.group(2).replace("\n", "\\n").replace("\r", "")
            suffix = match.group(3)
            return prefix + key_content + suffix
        s = re.sub(pattern, escape_newlines, s, flags=re.DOTALL)
    except Exception: pass
    return s.strip()

def find_google_credentials_in_secrets():
    logs = []
    if hasattr(st, 'secrets'):
        # 1. Check a dedicated [google] section (Recommended)
        if "google" in st.secrets:
            g_creds = st.secrets["google"]
            if isinstance(g_creds, (dict, st.runtime.secrets.AttrDict)) and g_creds.get("type") == "service_account":
                return dict(g_creds), "SECTION_GOOGLE", logs
        
        # 2. Check the ROOT level (Original logic)
        if "type" in st.secrets and st.secrets["type"] == "service_account":
            return dict(st.secrets), "ROOT", logs
            
        # 3. Check for any nested dict that looks like a service account
        keys_to_check = [k for k in list(st.secrets.keys()) if k not in ["login", "supabase", "google"]]
        for key in keys_to_check:
            value = st.secrets[key]
            if isinstance(value, (dict, st.runtime.secrets.AttrDict)):
                try:
                    d = dict(value)
                    if d.get("type") == "service_account": 
                        return d, key, logs
                except Exception: pass

    # 4. Fallback to Environment Variable
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
                # More robust private key handling for Streamlit Cloud
                if 'private_key' in creds:
                    pk = creds['private_key']
                    # Replace literal \n with actual newlines
                    pk = pk.replace('\\n', '\n')
                    # Also handle if it's already correct
                    if '\\n' not in pk and '\n' not in pk:
                        # If no newlines at all, might need to add them
                        pk = pk.replace('-----BEGIN PRIVATE KEY-----', '-----BEGIN PRIVATE KEY-----\n')
                        pk = pk.replace('-----END PRIVATE KEY-----', '\n-----END PRIVATE KEY-----')
                    creds['private_key'] = pk
                
                with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False, encoding='utf-8') as f:
                    json.dump(creds, f)
                    temp_path = f.name
                os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = temp_path
                return True, logs, source
        except Exception as e: 
            logs.append(f"❌ Error: {str(e)}")
            import traceback
            logs.append(f"Traceback: {traceback.format_exc()}")
    return False, logs, None

creds_ok, debug_logs, creds_source = setup_credentials() 

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if hasattr(st, "secrets") and not OPENAI_API_KEY:
    for key in ['openai_api_llm', 'OPENAI_API_KEY', 'openai_key']:
        if key in st.secrets:
            OPENAI_API_KEY = st.secrets[key]
            break

# --- 4. APP LOGIC ---

if 'conversation_history' not in st.session_state: st.session_state.conversation_history = []
if 'messages' not in st.session_state: st.session_state.messages = []
if 'last_user_message' not in st.session_state: st.session_state.last_user_message = None
if 'last_audio_bytes' not in st.session_state: st.session_state.last_audio_bytes = None
# NEW: Flag to hold audio for the next run
if 'audio_to_play' not in st.session_state: st.session_state.audio_to_play = None

@st.cache_resource
def init_speech_client(): return speech.SpeechClient()

@st.cache_resource
def init_tts_client(): return texttospeech.TextToSpeechClient()

def transcribe_audio(audio_content, language_code="en-US"):
    try:
        client = init_speech_client()
        audio = speech.RecognitionAudio(content=audio_content)
        config = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=48000,
            language_code=language_code,
            enable_automatic_punctuation=True,
            model="default"
        )
        
        response = client.recognize(config=config, audio=audio)
        
        if not response.results:
            return None
            
        transcript = " ".join([result.alternatives[0].transcript for result in response.results]).strip()
        return transcript
    except Exception as e:
        st.error(f"Transcription Error: {e}")
        import traceback
        st.error(f"Traceback: {traceback.format_exc()}")
        return None

def get_ai_response(user_input, history, persona, topic, level, language="English"):
    if not OPENAI_API_KEY: return "Error: No API Key."
    client = OpenAI(api_key=str(OPENAI_API_KEY).strip())
    language_name = "French" if language == "French" else "English"
    sys_prompt = f"""Role: {language_name} Tutor ({persona})
Topic: {topic}
Level: {level}
Your Goal:
1. Maintain a natural conversation.
2. Concise (2-3 sentences).
3. Adjust vocabulary to {level}.

You are an experienced {language_name} language tutor specializing in conversational fluency and grammar correction tailored to varying proficiency levels. I seek your expertise to design a dynamic tutoring prompt that facilitates natural, concise dialogues while adapting vocabulary complexity appropriately.

Please ensure the prompt includes:

- Role Specification: Define the tutor's persona clearly to align responses with the learner's needs.

- Topic and Level Customization: Integrate subject matter and proficiency level to tailor vocabulary and complexity.

- Conversational Goals: Emphasize maintaining natural flow, limiting responses to 2-3 sentences for conciseness.

- Error Correction Protocol: Upon detecting grammar mistakes, provide the corrected response first, followed by a distinct "💡 Correction:" note explaining the error.

- Engagement Strategy: Conclude each response with a relevant follow-up question to encourage learner interaction.

- Message Structure: Incorporate system-level instructions combined with recent conversational history and the current user input to maintain context.

Leverage your advanced understanding of language pedagogy and AI prompt engineering to refine this framework, ensuring it maximizes learner engagement and language acquisition efficacy."""
    msgs = [{"role": "system", "content": sys_prompt}] + history[-6:] + [{"role": "user", "content": user_input}]
    try:
        response = client.chat.completions.create(model="gpt-4o-mini", messages=msgs)
        return response.choices[0].message.content.strip()
    except Exception as e: return "Sorry, I encountered an error."

def synthesize_speech(text, voice_name, language_code="en-US"):
    try:
        client = init_tts_client()
        s_input = texttospeech.SynthesisInput(text=text)
        # Use the voice selected in sidebar
        voice = texttospeech.VoiceSelectionParams(language_code=language_code, name=voice_name)
        audio_config = texttospeech.AudioConfig(audio_encoding=texttospeech.AudioEncoding.MP3)
        response = client.synthesize_speech(input=s_input, voice=voice, audio_config=audio_config)
        return response.audio_content
    except Exception as e:
        st.error(f"TTS Error: {e}")
        return None

def autoplay_audio(audio_content):
    """
    Plays audio immediately using an invisible HTML player.
    """
    if audio_content:
        b64 = base64.b64encode(audio_content).decode()
        md = f"""
            <audio autoplay="true">
            <source src="data:audio/mp3;base64,{b64}" type="audio/mp3">
            </audio>
            """
        st.markdown(md, unsafe_allow_html=True)

def main():
    st.title("🗣️ AI Language Tutor")

    if 'text_input_key' not in st.session_state:
        st.session_state.text_input_key = "initial_text_input"
    
    if not creds_ok or not OPENAI_API_KEY:
        st.error("Credentials missing. Check logs.")
                # Temporary Debugging Lines
        st.write(f"DEBUG: creds_ok status: {creds_ok}")
        st.write(f"DEBUG: OpenAI Key found: {bool(OPENAI_API_KEY)}")
        st.stop()

    # --- Sidebar ---
    with st.sidebar:
        st.header("Settings")
        
        # Welcome message
        if st.session_state.get('current_user'):
            user = st.session_state.current_user
            st.markdown(f"**Welcome, {user.get('full_name') or user.get('username')}!**")
            if user.get('is_admin'):
                st.caption("🔑 Admin")
            st.markdown("---")
        
        language = st.selectbox("Language", ["English", "French"])
        level = st.selectbox("Level", ["Beginner (A1-A2)", "Intermediate (B1-B2)", "Advanced (C1-C2)"])
        persona = st.selectbox("Persona", ["Friendly", "Professional", "Casual"])
        topic = st.selectbox("Topic", ["General", "Food", "Travel", "Work"])
        # Voice names from Google Cloud TTS - update based on language selection
        if language == "English":
            voice = st.selectbox("Voice", ["en-US-Journey-F", "en-US-Journey-D", "en-US-Studio-O", "en-US-Studio-M"])
        else:  # French
            voice = st.selectbox("Voice", ["fr-FR-Neural2-A", "fr-FR-Neural2-B", "fr-FR-Neural2-C", "fr-FR-Neural2-D", "fr-FR-Standard-A", "fr-FR-Standard-B", "fr-FR-Standard-C", "fr-FR-Standard-D", "fr-FR-Standard-E"])
        
        st.markdown("---")
        if st.button("Reset Chat"):
            st.session_state.messages = []
            st.session_state.conversation_history = []
            st.session_state.last_audio_bytes = None
            st.session_state.audio_to_play = None
            st.session_state.text_input_key = "reset_text_input"
            st.rerun()
        if st.button("Logout", type="primary"):
            st.session_state.password_correct = False
            st.rerun()

    # --- Chat History ---
    for msg in st.session_state.messages:
        bg = "#e3f2fd" if msg["role"] == "user" else "#f5f5f5"
        st.markdown(f"<div style='background:{bg};padding:10px;border-radius:10px;margin:5px 0; color: black'><b>{msg['role'].title()}:</b> {msg['content']}</div>", unsafe_allow_html=True)

    # --- Audio Playback Logic ---
    # We check if there is audio waiting to be played from the previous run
    if st.session_state.audio_to_play:
        autoplay_audio(st.session_state.audio_to_play)
        st.session_state.audio_to_play = None  # Clear it so it plays only once

    # --- Input Area ---
    st.markdown("---")
    c1, c2 = st.columns([1, 4])
    with c1: audio = mic_recorder(start_prompt="🎙️", stop_prompt="⏹️", key="mic")
    with c2: text = st.text_input("Type...", key=st.session_state.text_input_key)

    user_msg = None
    msg_source = None
    
    # 1. Handle Audio Input
    if audio and audio.get('bytes'):
        if audio['bytes'] != st.session_state.last_audio_bytes:
            st.session_state.last_audio_bytes = audio['bytes']
            with st.spinner("Transcribing..."):
                language_code = "fr-FR" if language == "French" else "en-US"
                user_msg = transcribe_audio(audio['bytes'], language_code)
                msg_source = 'audio'
                # Debug: Show what was transcribed
                if user_msg:
                    st.info(f"🎤 Transcribed: {user_msg}")
                else:
                    st.warning("⚠️ No speech detected. Please try again.")
                    user_msg = None
                
    # 2. Handle Text Input
    elif text and text != st.session_state.last_user_message:
        user_msg = text
        msg_source = 'text'

    # 3. Process Message
    if user_msg:
        st.session_state.last_user_message = user_msg
        st.session_state.messages.append({"role": "user", "content": user_msg})
        st.session_state.conversation_history.append({"role": "user", "content": user_msg})
        
        with st.spinner("Thinking..."):
            # Get text response
            reply = get_ai_response(user_msg, st.session_state.conversation_history, persona, topic, level, language)
            st.session_state.messages.append({"role": "assistant", "content": reply})
            st.session_state.conversation_history.append({"role": "assistant", "content": reply})

            # Get audio response using the sidebar voice setting
            language_code = "fr-FR" if language == "French" else "en-US"
            audio_bytes = synthesize_speech(reply, voice, language_code)
            
            # SAVE AUDIO TO STATE TO PLAY ON NEXT RELOAD
            if audio_bytes:
                st.session_state.audio_to_play = audio_bytes

        # Reset text input if needed
        if msg_source == 'text':
            current_key = st.session_state.text_input_key
            st.session_state.text_input_key = f"text_input_{time.time()}"
            if current_key in st.session_state:
                del st.session_state[current_key]
            
        st.rerun()

if __name__ == "__main__":
    main()