"""Regression tests for the Hinglish text cleanup pipeline.

Guards against re-introduction of the catastrophic patterns we removed
(e.g. `(\\w{3,})re -> \1 rahe` which corrupted "before" -> "befo rahe").

Run with:  python -m pytest tests/test_hinglish_cleanup.py -v
       or: python tests/test_hinglish_cleanup.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.audio_engine import AudioEngine

clean = AudioEngine._clean_hinglish
post = AudioEngine._post_process_transcription


def check(label, raw, must_contain=None, must_not_contain=None):
    out = clean(raw)
    ok = True
    if must_contain and must_contain not in out:
        ok = False
    if must_not_contain and must_not_contain in out:
        ok = False
    status = "PASS" if ok else "FAIL"
    print(f"  [{status}] {label}")
    print(f"        raw:    {raw}")
    print(f"        clean:  {out}")
    if not ok:
        if must_contain:
            print(f"        expect: contains '{must_contain}'")
        if must_not_contain:
            print(f"        expect: NOT contain '{must_not_contain}'")
    return ok


def main():
    passed = 0
    total = 0

    print("=== English-word preservation (must NOT be corrupted) ===")
    cases = [
        ("English 'before' must not become 'befo rahe'",
         "before we start", "before", None),
        ("English 'more' must not become 'mo rahe'",
         "give me more time", "more", None),
        ("English 'store' must not become 'sto rahe'",
         "the store is closed", "store", None),
        ("English 'bad' must not become 'baat'",
         "this is bad", "bad", None),
        ("Person name 'Sam' must not become 'same'",
         "Sam is coming", "Sam", None),
        ("English 'full' (typed as 'full') must stay",
         "the cup is full", "full", None),
    ]
    for label, raw, must, mustnot in cases:
        total += 1
        if check(label, raw, must, mustnot):
            passed += 1

    print("\n=== Hinglish fixes that SHOULD happen ===")
    fixes = [
        ("haim -> hain", "ye sahi haim", "hain", "haim"),
        ("maim -> main", "maim ja raha hoon", "main", "maim"),
        ("nahim -> nahin", "nahim yaar", "nahin", "nahim"),
        ("kuchh -> kuch", "kuchh bhi karo", "kuch", "kuchh"),
        ("bahot -> bahut", "bahot accha hai", "bahut", "bahot"),
        ("achchha -> achha", "achchha laga", "achha", "achchha"),
        ("avaj -> awaaz", "meri avaj suni?", "awaaz", "avaj"),
        ("tamara -> tumhara", "tamara naam kya hai", "tumhara", "tamara"),
        ("chayiye -> chahiye", "mujhe yeh chayiye", "chahiye", "chayiye"),
        ("ager -> agar", "ager possible ho", "agar", "ager"),
        ("vala -> wala", "wo vala laao", "wala", None),
        # ── New Zero-STT fixes (from prod log analysis) ────────────────────
        ("galata -> galat (NOT 'glt')", "tum galata ho", "galat", "glt"),
        ("kyom -> kyun", "kyom karte ho", "kyun", "kyom"),
        ("kyomki -> kyunki", "kyomki ye sahi hai", "kyunki", "kyomki"),
        ("tumahari -> tumhari", "tumahari baat sahi hai", "tumhari", "tumahari"),
        ("sayata -> shayad", "sayata aaye", "shayad", "sayata"),
        ("hamesa -> hamesha", "hamesa late aate ho", "hamesha", "hamesa"),
        ("isaka -> iska", "isaka matlab", "iska", "isaka"),
        ("isaliya -> isliye", "isaliya nahi aaya", "isliye", "isaliya"),
        ("dekhana -> dekhna", "dekhana hai mujhe", "dekhna", "dekhana"),
        ("karata -> karta", "kya karata hai", "karta", "karata"),
        ("bolata -> bolta", "wo bolata hai", "bolta", "bolata"),
        ("lakhata -> lagta", "achha lakhata hai", "lagta", "lakhata"),
        ("mem -> mein", "ghar mem ja raha", "mein", " mem "),
        ("saba -> sab (trim)", "saba sahi", "sab", "saba"),
        ("tumane -> tumne", "tumane kaha tha", "tumne", "tumane"),
        ("paoge -> paaoge", "tum paoge", "paaoge", None),
        ("tho -> toh", "wo tho aaya", "toh", " tho "),
    ]
    for label, raw, must, mustnot in fixes:
        total += 1
        if check(label, raw, must, mustnot):
            passed += 1

    print("\n=== Devanagari pre-clean (chandra-O, anusvara) ===")
    deva_cases = [
        ("chandra-O 'सॉन्ड' should not leak", "सॉन्ड", None, "ॉ"),
        ("anusvara 'हैं' should become 'hain'", "हैं", "hain", None),
        ("Mixed: 'मैं ठीक हूँ'", "मैं ठीक हूँ", "main", None),
    ]
    for label, raw, must, mustnot in deva_cases:
        total += 1
        # Pipeline: transliterate -> clean
        translit = AudioEngine._transliterate_to_roman(raw)
        cleaned = AudioEngine._clean_hinglish(translit)
        ok = True
        if must and must not in cleaned:
            ok = False
        if mustnot and mustnot in cleaned:
            ok = False
        status = "PASS" if ok else "FAIL"
        print(f"  [{status}] {label}")
        print(f"        raw:    {raw}")
        print(f"        translit: {translit}")
        print(f"        clean:  {cleaned}")
        if ok:
            passed += 1

    print("\n=== Hallucination cleanup ===")
    hallu = [
        ("Repeated chars 'aaaaa' collapse to 'aa'",
         "haaaaaai", None, "aaaa"),
        ("Repeated punct '!!!' collapse to '!'",
         "wow!!!", "wow!", "!!!"),
    ]
    for label, raw, must, mustnot in hallu:
        total += 1
        if check(label, raw, must, mustnot):
            passed += 1

    print("\n=== Spoken commands ===")
    sc_cases = [
        ("'comma' -> ','",         "hello comma how are you",           ", how are you"),
        ("'full stop' -> '.'",     "this is a sentence full stop",      "This is a sentence."),
        ("'question mark' -> '?'", "kya tum aaoge question mark",       "Kya tum aaoge?"),
        ("'new line' -> newline",  "line one new line line two",        "Line one\nline two"),
        ("'period' -> '.'",        "end of sentence period",            "End of sentence."),
        ("'exclamation mark'",     "wow exclamation mark",              "Wow!"),
        ("Hindi 'purna viram'",    "mera naam ram hai purna viram",     "Mera naam ram hai."),
        ("Hindi 'alp viram'",      "main alp viram tu alp viram woh",   "Main, tu, woh"),
    ]
    for label, raw, expected_substr in sc_cases:
        total += 1
        out = post(raw)
        ok = expected_substr in out
        status = "PASS" if ok else "FAIL"
        print(f"  [{status}] {label}")
        print(f"        raw:  {raw}")
        print(f"        post: {out!r}")
        if ok:
            passed += 1

    print("\n=== Post-processing (capitalization + punctuation) ===")
    post_cases = [
        ("Question mark preserved", "kya tum aaoge?", "?"),
        ("Exclamation preserved", "wah kya baat hai!", "!"),
        ("Ellipsis preserved", "hmm well...", "..."),
        ("Auto-period added when missing", "ye sahi hai", "."),
        ("First letter capitalized", "namaste", "N"),
    ]
    for label, raw, must in post_cases:
        total += 1
        out = post(raw)
        ok = must in out
        status = "PASS" if ok else "FAIL"
        print(f"  [{status}] {label}")
        print(f"        raw:  {raw}")
        print(f"        post: {out}")
        if ok:
            passed += 1

    print("\n" + "=" * 50)
    print(f"Result: {passed}/{total} passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
