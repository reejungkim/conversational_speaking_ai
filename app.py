import streamlit as st
import openai
from openai import OpenAI
from google.cloud import speech_v1p1beta1 as speech
from google.cloud import texttospeech
import os
import base64
from datetime import datetime
import dotenv

# Load environment variables
dotenv.load_dotenv('/Users/reejungkim/Documents/Git/working-in-progress/.env')
# Configuration
GOOGLE_CREDENTIALS_PATH = os.getenv('gemini_llm_api')
OPENAI_API_KEY = os.getenv('openai_api_llm')

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
        
        audio = speech.RecognitionAudio(content=audio_content)
        config = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=16000,
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
        client = OpenAI(api_key=OPENAI_API_KEY)
        
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            temperature=0.7,
            max_tokens=300
        )

        ai_message = response.choices[0].message.content.strip()
        st.write(f"✅ AI Response received: {ai_message[:100]}...")
        return ai_message

    except Exception as e:
        error_msg = f"❌ OpenAI API error: {str(e)}"
        st.error(error_msg)
        st.write(f"Error details: {str(e)}")
        return "Sorry, I encountered an issue. Could you please try again?"


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
        st.error("⚠️ OpenAI API key not found. Please set OPENAI_API_KEY in your .env file.")
        st.stop()
    
    if not GOOGLE_CREDENTIALS_PATH:
        st.error("⚠️ Google Cloud credentials not found. Please set GOOGLE_APPLICATION_CREDENTIALS in your .env file.")
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
            help="Click to record audio or upload an audio file",
            key="audio_upload"
        )
    
    with col2:
        process_button = st.button("🚀 Send", use_container_width=True, type="primary")
    
    # Text input as alternative
    text_input = st.text_input(
        "Or type your message here (if voice isn't working)",
        placeholder="Type your message and press Enter...",
        key="text_input"
    )
    
    # Process audio or text input
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