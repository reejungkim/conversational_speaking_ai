import streamlit as st
import openai
from openai import OpenAI
from google.cloud import speech_v1p1beta1 as speech
from google.cloud import texttospeech
import os
import io
import base64
from datetime import datetime
import tempfile
import dotenv


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

# Configuration
dotenv.load_dotenv('/Users/reejungkim/Documents/Git/working-in-progress/.env')
GOOGLE_CREDENTIALS_PATH = os.getenv('gemini_llm_api')
OPENAI_API_KEY = os.getenv('openai_api_llm')

# Initialize clients
@st.cache_resource
def init_speech_client():
    """Initialize Google Speech-to-Text client"""
    return speech.SpeechClient()

@st.cache_resource
def init_tts_client():
    """Initialize Google Text-to-Speech client"""
    return texttospeech.TextToSpeechClient()

def init_openai_client():
    """Initialize OpenAI client"""
    openai.api_key = OPENAI_API_KEY

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
        
        audio = speech.RecognitionAudio(content=audio_content)
        config = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.WEBM_OPUS,
            sample_rate_hertz=48000,
            language_code="en-US",
            enable_automatic_punctuation=True,
            model="default"
        )
        
        response = client.recognize(config=config, audio=audio)
        
        if not response.results:
            return None
        
        transcript = ""
        for result in response.results:
            transcript += result.alternatives[0].transcript
        
        return transcript.strip()
    
    except Exception as e:
        st.error(f"Transcription error: {str(e)}")
        return None

    # GPT-4 function
def get_ai_response(user_input, conversation_history, persona, topic, level):

    system_prompt = f"""
    You are {persona}, an AI English speaking partner.
    Your topic is "{topic}". You are helping the user practice {level}-level English conversation.
    - Always reply naturally and contextually to the user's latest message.
    - Do NOT repeat or rephrase your own previous messages.
    - Do NOT generate both sides of a conversation.
    - Respond as if in a friendly dialogue, short and engaging.
    """

    # Keep only the last few turns to avoid infinite recursion
    trimmed_history = conversation_history[-6:] if len(conversation_history) > 6 else conversation_history

    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(trimmed_history)
    messages.append({"role": "user", "content": user_input})

    client = OpenAI(api_key=OPENAI_API_KEY)

    # 🧠 Debug log of what is being sent
    st.write("🔍 DEBUG: Messages sent to OpenAI:")
    for i, msg in enumerate(messages):
        st.write(f"Message {i}: {msg['role']} → {msg['content'][:200]}")

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            temperature=0.7,
        )

        ai_message = response.choices[0].message.content.strip()

    except Exception as e:
        st.error(f"❌ OpenAI API error: {e}")
        ai_message = "Sorry, there was a problem generating a response."

    return ai_message



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
        st.error(f"Text-to-speech error: {str(e)}")
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
            <audio autoplay>
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
            ["Beginner (A1-A2)", "Intermediate (B1-B2)", "Advanced (C1-C2)"]
        )
        
        # Tutor Persona
        persona = st.selectbox(
            "Tutor Personality",
            ["Friendly & Encouraging", "Professional & Direct", "Casual & Fun"]
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
            ]
        )
        
        # Voice Selection
        voice_options = {
            "Female Voice 1": "en-US-Neural2-F",
            "Female Voice 2": "en-US-Neural2-C",
            "Male Voice 1": "en-US-Neural2-D",
            "Male Voice 2": "en-US-Neural2-A"
        }
        # voice_selection = st.selectbox("AI Voice", list(voice_options.keys()))
        # selected_voice = voice_options[voice_selection]
        voice_keys = list(voice_options.keys())
        voice_selection = st.selectbox("AI Voice", voice_keys, index=0)
        if isinstance(voice_selection, int): 
            # fallback safeguard
            voice_selection = voice_keys[voice_selection]
        selected_voice = voice_options[voice_selection]

        
        st.markdown("---")
        
        # Reset conversation
        if st.button("🔄 Reset Conversation", use_container_width=True):
            st.session_state.conversation_history = []
            st.session_state.messages = []
            st.rerun()
        
        st.markdown("---")
        st.markdown("### 📊 Session Info")
        st.metric("Conversation Turns", len(st.session_state.messages) // 2)
    
    # Check if API keys are configured
    if not OPENAI_API_KEY:
        st.error("⚠️ OpenAI API key not found. Please set the OPENAI_API_KEY environment variable.")
        st.stop()
    
    if not GOOGLE_CREDENTIALS_PATH:
        st.error("⚠️ Google Cloud credentials not found. Please set the GOOGLE_APPLICATION_CREDENTIALS environment variable.")
        st.stop()
    
    # Main conversation area
    st.markdown("### 💬 Conversation")
    
    # Display conversation history
    chat_container = st.container()
    with chat_container:
        for message in st.session_state.messages:
            role = message["role"]
            content = message["content"]
            timestamp = message.get("timestamp", "")
            
            if role == "user":
                st.markdown(f"""
                <div style='background-color: #e3f2fd; padding: 15px; border-radius: 10px; margin: 10px 0;'>
                    <strong>🙋 You</strong> <span style='color: #666; font-size: 0.8em;'>{timestamp}</span><br>
                    {content}
                </div>
                """, unsafe_allow_html=True)
            else:
                st.markdown(f"""
                <div style='background-color: #f5f5f5; padding: 15px; border-radius: 10px; margin: 10px 0;'>
                    <strong>🤖 AI Tutor</strong> <span style='color: #666; font-size: 0.8em;'>{timestamp}</span><br>
                    {content}
                </div>
                """, unsafe_allow_html=True)
    
    # Audio input section
    st.markdown("---")
    st.markdown("### 🎤 Your Turn to Speak")
    
    col1, col2 = st.columns([3, 1])
    
    with col1:
        # Audio recorder
        audio_file = st.file_uploader(
            "Record or upload your audio",
            type=["wav", "mp3", "webm", "ogg", "m4a"],
            help="Click to record audio or upload an audio file"
        )
    
    with col2:
        process_button = st.button("🚀 Send", use_container_width=True, type="primary")
    
    # Text input as alternative
    text_input = st.text_input(
        "Or type your message here (if voice isn't working)",
        placeholder="Type your message and press Enter..."
    )
    
    # Process audio or text input
    # Initialize input flag
    if "last_user_message" not in st.session_state:
        st.session_state.last_user_message = None

    # Detect new input
    new_message = None

    # Process audio if uploaded and button pressed
    if process_button and audio_file:
        with st.spinner("🎧 Transcribing your speech..."):
            audio_bytes = audio_file.read()
            new_message = transcribe_audio(audio_bytes)
            if not new_message:
                st.warning("Could not transcribe audio. Please try again or use text input.")

    # Process text input (only if new and not empty)
    elif text_input and text_input.strip() and text_input != st.session_state.last_user_message:
        new_message = text_input.strip()

    # Handle AI interaction if there is a new message
    if new_message:
        st.session_state.last_user_message = new_message  # remember last input
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

        # Add AI response
        st.session_state.messages.append({
            "role": "assistant",
            "content": ai_response,
            "timestamp": ai_timestamp
        })

        # Optional: play AI audio
        audio_content = synthesize_speech(ai_response, voice_name=selected_voice)
        autoplay_audio(audio_content)

    
    # Instructions
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

if __name__ == "__main__":
    main()