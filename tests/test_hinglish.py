import sys
import os
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 1. Check transformers
try:
    import transformers
    print(f"[OK] transformers {transformers.__version__} is available")
except ImportError as e:
    print(f"[FAIL] transformers: {e}")

# 2. Test transliteration
from src.audio_engine import AudioEngine

print("\n--- Transliteration Tests ---")
tests = [
    ("क्या मेरी आवाज़ सुनाई दे रही है",  "kya meri awaaz sunai de rahi hai"),
    ("नहीं यार, यह काम नहीं कर रहा",      "nahi yaar, yeh kaam nahi kar raha"),
    ("मुझे Hinglish में चाहिए",            "mujhe Hinglish mein chahiye"),
    ("अभी सही से काम कर रहा है",          "abhi sahi se kaam kar raha hai"),
    ("मैं बोल रहा हूं",                    "main bol raha hoon"),
    ("आज बहुत गर्मी है यार",              "aaj bahut garmi hai yaar"),
]

all_ok = True
for deva, expected_hint in tests:
    result = AudioEngine._transliterate_to_roman(deva)
    has_deva = any('\u0900' <= c <= '\u097F' for c in result)
    status = "FAIL (Deva leftover)" if has_deva else "OK"
    if has_deva:
        all_ok = False
    print(f"  [{status}]")
    print(f"    Input:    {deva}")
    print(f"    Output:   {result}")
    print(f"    Expected: ~{expected_hint}")
    print()

print("=" * 50)
print(f"All Devanagari cleared: {all_ok}")
