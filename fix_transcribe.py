def transcribe_audio(audio_content, language_code="en-US"):
    try:
        # Debug: Log audio size
        st.write(f"Debug: Audio size: {len(audio_content)} bytes")
        
        client = init_speech_client()
        audio = speech.RecognitionAudio(content=audio_content)
        config = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=48000,
            language_code=language_code,
            enable_automatic_punctuation=True,
            model="default"
        )
        
        st.write("Debug: Sending to Google Speech API...")
        response = client.recognize(config=config, audio=audio)
        st.write(f"Debug: Response received. Results count: {len(response.results) if response.results else 0}")
        
        if not response.results:
            st.write("Debug: No results from Google Speech API")
            return None
            
        transcript = " ".join([result.alternatives[0].transcript for result in response.results]).strip()
        st.write(f"Debug: Transcript: '{transcript}'")
        return transcript
    except Exception as e:
        st.error(f"Transcription Error: {e}")
        import traceback
        st.error(f"Traceback: {traceback.format_exc()}")
        return None
