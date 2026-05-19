import pyaudio
p = pyaudio.PyAudio()
for i in range(p.get_device_count()):
    info = p.get_device_info_by_index(i)
    print("[{}]: {} | Rate: {} | Channels: {}".format(i, info['name'], info['defaultSampleRate'], info['maxInputChannels']))
p.terminate()