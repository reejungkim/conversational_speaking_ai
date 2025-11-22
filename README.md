# 🗣️ AI Language Tutor

An interactive English conversation practice application powered by AI. Practice speaking English with an AI-powered tutor that responds with both text and speech, adapting to your language level and preferred conversation style.

## ✨ Features

- **🎤 Voice Input**: Record your speech using the microphone, automatically transcribed using Google Cloud Speech-to-Text
- **⌨️ Text Input**: Type your messages as an alternative input method
- **🤖 AI-Powered Responses**: Get natural, contextual responses from OpenAI GPT-4o mini
- **🔊 Text-to-Speech**: Listen to AI responses with natural-sounding voices using Google Cloud Text-to-Speech
- **🎯 Customizable Settings**:
  - Language level selection (Beginner, Intermediate, Advanced)
  - Tutor personality (Friendly & Encouraging, Professional & Direct, Casual & Fun)
  - Conversation topics (General, Restaurant, Job Interview, Travel, Small Talk, Shopping)
  - Voice selection (Multiple male and female voices)
- **💬 Conversation History**: View your conversation history with timestamps
- **🔄 Session Management**: Reset conversations and track conversation turns

## 🛠️ Technologies Used

- **Streamlit**: Web application framework
- **OpenAI GPT-4o mini**: AI conversation model
- **Google Cloud Speech-to-Text**: Audio transcription
- **Google Cloud Text-to-Speech**: Speech synthesis
- **streamlit-mic-recorder**: Microphone recording component

## 📋 Prerequisites

- Python 3.7+
- OpenAI API key
- Google Cloud account with:
  - Speech-to-Text API enabled
  - Text-to-Speech API enabled
  - Service account credentials (JSON file)

## 🔧 Installation

1. **Clone the repository**:
```bash
git clone <repository-url>
cd conversational_speaking_ai
```

2. **Install dependencies**:
```bash
pip install streamlit openai google-cloud-speech google-cloud-texttospeech python-dotenv streamlit-mic-recorder
```

3. **Set up environment variables**:
   
   Create a `.env` file in your project directory (or update the path in `app.py` line 16) with:
```env
openai_api_llm=your_openai_api_key_here
gemini_llm_api=/path/to/your/google-credentials.json
```

   Alternatively, you can set `GOOGLE_APPLICATION_CREDENTIALS` environment variable directly.

## ⚙️ Configuration

### Option 1: Environment Variables (Recommended)

Set the following in your `.env` file:
- `openai_api_llm`: Your OpenAI API key
- `gemini_llm_api`: Path to your Google Cloud service account JSON file, or the raw JSON content

### Option 2: In-App Configuration

You can also configure Google Cloud credentials directly in the app:
1. Open the sidebar
2. Expand "Google Cloud Credentials"
3. Choose "Path" or "JSON" input type
4. Enter your credentials and click "Save credentials"

## 🚀 Usage

1. **Start the application**:
```bash
streamlit run app.py
```

2. **Configure your preferences** in the sidebar:
   - Select your language level
   - Choose a tutor personality
   - Pick a conversation topic
   - Select an AI voice

3. **Start conversing**:
   - **Voice mode**: Click "🎙️ Start recording", speak your message, then click "⏹️ Stop" to automatically send
   - **Text mode**: Type your message in the text box and press Enter

4. **Listen to responses**: The AI tutor will respond with both text and speech (auto-played)

5. **Reset conversation**: Click "🔄 Reset Conversation" in the sidebar to start fresh

## 📝 How It Works

1. **Input Processing**:
   - Voice input is recorded and sent to Google Cloud Speech-to-Text for transcription
   - Text input is processed directly

2. **AI Response Generation**:
   - Your message is sent to OpenAI GPT-4o mini with conversation context
   - The AI generates a response tailored to your level, persona, and topic

3. **Speech Synthesis**:
   - The AI response is converted to speech using Google Cloud Text-to-Speech
   - Audio is auto-played in the browser

4. **Context Management**:
   - The last 6 conversation turns are maintained for context
   - Conversation history is displayed with timestamps

## 🔑 API Keys Required

- **OpenAI API Key**: Required for GPT-4o mini responses
- **Google Cloud Service Account**: Required for Speech-to-Text and Text-to-Speech services

## 🎯 Conversation Topics

- General Conversation
- Restaurant & Ordering Food
- Job Interview Practice
- Travel & Tourism
- Everyday Small Talk
- Shopping & Errands

## 🎭 Tutor Personalities

- **Friendly & Encouraging**: Patient, supportive, celebrates your efforts
- **Professional & Direct**: Focused on accuracy, provides clear feedback
- **Casual & Fun**: Uses idioms, humor, and relatable examples

## 🎤 Voice Options

- Female Voice 1 (en-US-Neural2-F)
- Female Voice 2 (en-US-Neural2-C)
- Male Voice 1 (en-US-Neural2-D)
- Male Voice 2 (en-US-Neural2-A)

## ⚠️ Troubleshooting

- **"OpenAI API key not found"**: Make sure `openai_api_llm` is set in your `.env` file
- **"Google Cloud credentials not found"**: Set up credentials via the sidebar or environment variables
- **Audio transcription fails**: Check your Google Cloud Speech-to-Text API is enabled and credentials are valid
- **Text input doesn't clear**: This is handled automatically on the next rerun after sending a message

## 📄 License

[Add your license here]

## 🤝 Contributing

[Add contribution guidelines here]
