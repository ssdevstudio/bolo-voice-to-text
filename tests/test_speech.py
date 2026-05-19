import speech_recognition as sr

print("Testing Google Speech API with speech_recognition library...")

r = sr.Recognizer()

print("\nSpeak something for 5 seconds... (Say 'Hello World' or something)")
try:
    with sr.Microphone() as source:
        print("Listening... (Speak now)")
        audio = r.listen(source, timeout=5, phrase_time_limit=5)
        print("Got audio: {} bytes".format(len(audio.get_wav_data())))
        print("Sample rate: {}, Width: {}".format(audio.sample_rate, audio.sample_width))
        
        print("Sending to Google...")
        text = r.recognize_google(audio, language="en-IN")
        print("Transcription: {}".format(text))
except Exception as e:
    print("Error: {}: {}".format(type(e).__name__, e))