import speech_recognition as sr
import threading
import time
import json
import os
import re
import pyaudio
import math
import struct
import numpy as np
import collections
import transformers
from indic_transliteration import sanscript
from indic_transliteration.sanscript import transliterate
from . import config

# ─── Hinglish Polishing Pipeline ────────────────────────────────────────────
# Word-level fixes preferred over regex (no English-word collateral damage).
# Regex used only for genuine multi-character patterns (suffixes, nasals,
# hallucination artifacts).

# Whisper / Zero-STT prompt-leakage hallucinations to strip
_PROMPT_ARTIFACTS = [
    re.compile(re.escape(a), re.IGNORECASE) for a in [
        "it's cool", "it is cool", "mix karke likho", "ghar ja raha hoon",
        "thank you for watching", "subscribe to my channel",
        "please subscribe", "thanks for watching",
    ]
]

# Narrow regex patterns — never destructive to English/proper nouns
_REGEX_PATTERNS = [
    # Nasal endings: haim → hain, maim → main, nahim → nahin
    (re.compile(r'\bhaim\b', re.IGNORECASE), 'hain'),
    (re.compile(r'\bmaim\b', re.IGNORECASE), 'main'),
    (re.compile(r'\bnahim\b', re.IGNORECASE), 'nahin'),
    # Plural nasal collapse only after i/y (khirkiyam → khirkiyan).
    # Narrower than (\w+)am which would corrupt "exam", "spam", etc.
    (re.compile(r'(\w+[iy])am\b', re.IGNORECASE), r'\1an'),
    # Word-boundary merges (Aapaki → aap ki)
    (re.compile(r'\baapaki\b', re.IGNORECASE), 'aap ki'),
    (re.compile(r'\baapane\b', re.IGNORECASE), 'aap ne'),
    # NOTE: Schwa-syncope rules removed — the previous `(\w)X\b -> \1Y`
    # patterns captured only 1 char (the stem) and would corrupt non-verb
    # words like "galata" -> "glta" -> "glt". Specific verb-form fixes
    # (karata, bolata, banata, lakhata etc.) live in _PHONETIC_WORD_MAP.
    # Plural past correction
    (re.compile(r'\brahe\s+tha\b', re.IGNORECASE), 'rahe the'),
    (re.compile(r'\brahi\s+tha\b', re.IGNORECASE), 'rahi thi'),
    (re.compile(r'\bkar\s+rahe\s+tha\b', re.IGNORECASE), 'kar rahe the'),
    (re.compile(r'\bkar\s+rahi\s+tha\b', re.IGNORECASE), 'kar rahi thi'),
    # Hallucination char repetition: "aaaaa" -> "aa"
    (re.compile(r'(\S)\1{3,}'), r'\1\1'),
    # Repeated punctuation (dots handled separately to preserve "..." ellipsis)
    (re.compile(r'([!?,;:])\1+'), r'\1'),
    # 4+ dots collapse to 3-dot ellipsis
    (re.compile(r'\.{4,}'), '...'),
    # Exactly 2 dots are typos: collapse to single period
    (re.compile(r'(?<!\.)\.{2}(?!\.)'), '.'),
    # Multi-space normalization
    (re.compile(r' {2,}'), ' '),
]

# Word-level phonetic confusions: { wrong → right }
# Only entries that cannot collide with English / proper nouns.
_PHONETIC_WORD_MAP = {
    # ── Voice / aawaz family ────────────────────────────────────────────────
    'avaj': 'awaaz', 'awaj': 'awaaz', 'aawaj': 'awaaz', 'aavaj': 'awaaz',
    'evaj': 'awaaz', 'ebaj': 'awaaz', 'aubaj': 'awaaz', 'yavaj': 'awaaz',
    'aavad': 'awaaz', 'aabd': 'awaaz', 'yavaja': 'awaaz', 'yawaja': 'awaaz',
    # ITRANS-transliterated trailing-a variants (आवाज -> "avaja")
    'avaja': 'awaaz', 'awaja': 'awaaz', 'aawaja': 'awaaz', 'aavaja': 'awaaz',
    # ── Demonstratives (this/that/those) ────────────────────────────────────
    'isak': 'iska', 'isake': 'iske', 'asak': 'iska', 'asake': 'iske',
    'usake': 'uske', 'usamge': 'uske', 'unake': 'unke', 'unon': 'unhe',
    'yah': 'yeh', 'yahni': 'yani',
    # ── Filler / common words ───────────────────────────────────────────────
    'matalab': 'matlab', 'mathlab': 'matlab', 'matalaba': 'matlab',
    'mathlaba': 'matlab',
    'kebal': 'kabhi', 'kayee': 'kayi',
    # ── Use / istemal ───────────────────────────────────────────────────────
    'istemal': 'istemaal', 'sistemal': 'istemaal',
    # ── Very / much / many ──────────────────────────────────────────────────
    'bahuti': 'bahut', 'bahute': 'bahut', 'bahot': 'bahut', 'bohot': 'bahut',
    'jitana': 'jitna', 'jitan': 'jitna', 'jetna': 'jitna', 'jetan': 'jitna',
    'kitane': 'kitne',
    # ── People / log ────────────────────────────────────────────────────────
    'lokon': 'log', 'lokan': 'log',
    # ── Time / when ─────────────────────────────────────────────────────────
    'jabaka': 'jab', 'jabaki': 'jabki', 'takibi': 'taki',
    'abe': 'abhi', 'abi': 'abhi',
    # ── Better / behtar ─────────────────────────────────────────────────────
    'bhetar': 'behtar', 'bhetara': 'behtar', 'btar': 'behtar',
    'bahatar': 'behtar', 'bahatura': 'behtar',
    # ── tum / tumhara family ────────────────────────────────────────────────
    'tuma': 'tum', 'tomin': 'tum', 'tumin': 'tum',
    'tomara': 'tumhara', 'tomahara': 'tumhara', 'tamara': 'tumhara',
    'tamahara': 'tumhara', 'tomari': 'tumhari', 'tamari': 'tumhari',
    'tamar': 'tumhara', 'tamare': 'tumhare',
    'tamahem': 'tumhein', 'tumahem': 'tumhein', 'tumhem': 'tumhein',
    'tumhaim': 'tumhein',
    # ── Main / nahi / hoon ──────────────────────────────────────────────────
    'mahan': 'main', 'kucha': 'kuch', 'kuchh': 'kuch',
    # NOTE: 'hona' (होना = "to be") is itself a legit Hindi infinitive verb.
    # Do NOT map 'hona' -> 'hoon' — destroys "sahi hona chahiye" semantics.
    'sahar': 'sahi', 'sai': 'sahi', 'sehi': 'sahi',
    'kui': 'koi', 'koee': 'koi',
    'hun': 'hoon', 'mem': 'mein',
    # ── Verb infinitives (karan → karna, etc.) ──────────────────────────────
    'karan': 'karna', 'karana': 'karna', 'bolan': 'bolna', 'sunan': 'sunna',
    # ── chahiye variants ────────────────────────────────────────────────────
    'chayiye': 'chahiye', 'chayiya': 'chahiye', 'chahiya': 'chahiye',
    'chaiye': 'chahiye', 'chaiya': 'chahiye', 'chahie': 'chahiye',
    'chahiee': 'chahiye',
    # ── Bhai variants ───────────────────────────────────────────────────────
    'bahi': 'bhai', 'bhaee': 'bhai', 'bhaeee': 'bhai',
    # ── lekin / agar / aur ──────────────────────────────────────────────────
    'likin': 'lekin', 'ager': 'agar', 'aura': 'aur',
    # ── Galat / galati / gadbad ─────────────────────────────────────────────
    'gantiya': 'galatiya', 'galab': 'galat', 'galah': 'galat',
    'galate': 'galat', 'galabag': 'gadbad', 'galti': 'galati',
    'galtiyan': 'galatiyan', 'gadabag': 'gadbad',
    'garabari': 'gadbad', 'garabar': 'gadbad',
    # ── Please / fix / minor ────────────────────────────────────────────────
    'plist': 'please', 'plij': 'please', 'pliz': 'please',
    'phiks': 'fix', 'fiks': 'fix', 'mainar': 'minor',
    'mahanat': 'mehnat', 'tariph': 'tarif',
    # ── Problem / translate / mushkil / gussa ───────────────────────────────
    'probalam': 'problem', 'transalet': 'translation',
    'mushah': 'mushkil', 'mahalab': 'mushkil',
    'gussha': 'gussa', 'gusal': 'gussa',
    # ── Improvement ─────────────────────────────────────────────────────────
    'aainprog': 'improvement', 'ainprog': 'improvement',
    'inproement': 'improvement', 'inprovement': 'improvement',
    'inproovement': 'improvement',
    # ── Zarurat ─────────────────────────────────────────────────────────────
    'jaruaat': 'zarurat', 'jarubat': 'zarurat', 'jarrubat': 'zarurat',
    'jaruat': 'zarurat', 'zaruat': 'zarurat', 'jarurah': 'zarurat',
    'jarup': 'zarurat', 'zaruat': 'zarurat',
    # ── Achha ───────────────────────────────────────────────────────────────
    'achchha': 'achha', 'achchhi': 'achhi',
    # ── Result / sound / boosted ────────────────────────────────────────────
    'rijalat': 'result', 'rijalt': 'result', 'rijult': 'result',
    'busted': 'boosted', 'saund': 'sound',
    # ── Thoda / thik ────────────────────────────────────────────────────────
    'tora': 'thoda', 'thike': 'thik', 'tik': 'thik',
    # ── Zero-STT dropped vowels (verified narrow) ───────────────────────────
    'kiy': 'kiya', 'sakata': 'sakta', 'lagt': 'lagta',
    'nahar': 'nahin', 'pich': 'piche', 'pise': 'piche',
    'chald': 'chal', 'chalad': 'chal',
    # ── App-specific systematic errors ──────────────────────────────────────
    'palac': 'pehle', 'pahal': 'pehle', 'isali': 'isliye',
    'apa': 'aap', 'apak': 'aapka',
    'deka': 'dekha', 'vekhane': 'dekhne', 'dedate': 'dete',
    'jad': 'zyada', 'suriph': 'sirf', 'pravait': 'provide',
    'simg': 'singh', 'simk': 'singh', 'khirkiyom': 'khidkiyon',
    'gathiya': 'gatiya', 'gaari': 'galati', 'garii': 'galati',
    # ── v→w for unambiguous Hindi possessives ───────────────────────────────
    'vala': 'wala', 'vali': 'wali', 'vale': 'wale',
    # ── Common Devanagari → Roman drift ─────────────────────────────────────
    'dishtil': 'distil', 'dishdil': 'distil', 'disdil': 'distil',
    # ── Zero-STT ITRANS leftovers seen in production ─────────────────────────
    # tumhara family (transliteration adds 'a' after 'tumh')
    'tumahara': 'tumhara', 'tumahari': 'tumhari', 'tumahare': 'tumhare',
    'tumane': 'tumne', 'tumahem': 'tumhein',
    # kyun family (Hindi क्यों -> "kyom" via ITRANS)
    'kyom': 'kyun', 'kyomki': 'kyunki', 'kyon': 'kyun', 'kyonki': 'kyunki',
    # shayad
    'sayata': 'shayad', 'sayta': 'shayad', 'sayad': 'shayad',
    # chahta / chahti / chahte
    'chata': 'chahta', 'chati': 'chahti', 'chate': 'chahte',
    # samapt / khatam
    'samap': 'samapt', 'samapa': 'samapt', 'samaapa': 'samapt',
    # toh
    'tho': 'toh', 'thoh': 'toh',
    # hamesha
    'hamesa': 'hamesha', 'hames': 'hamesha', 'hamesh': 'hamesha',
    # iska/isliye/iske family — ITRANS adds 'a'
    'isaka': 'iska', 'isake': 'iske', 'isaki': 'iski',
    'isaliya': 'isliye', 'isaliye': 'isliye',
    # Verb infinitives (Zero-STT adds schwa)
    'dekhana': 'dekhna', 'dekhan': 'dekhna',
    'sikhana': 'sikhna', 'sikhan': 'sikhna',
    'samajhana': 'samajhna', 'samajhan': 'samajhna',
    'sunana': 'sunna',
    'lakhana': 'likhna', 'lakhna': 'likhna', 'lakhat': 'lagta',
    'lakhata': 'lagta', 'lakhta': 'lagta',
    # Verb present continuous (Zero-STT inserts schwa)
    'karata': 'karta', 'karati': 'karti', 'karate': 'karte',
    'bolata': 'bolta', 'bolati': 'bolti', 'bolate': 'bolte',
    'banata': 'banta', 'banati': 'banti', 'banate': 'bante',
    'rakhata': 'rakhta', 'rakhati': 'rakhti',
    'milata': 'milta', 'milati': 'milti', 'milate': 'milte',
    'jaata': 'jata', 'jaati': 'jati', 'jaate': 'jate',
    'aata': 'aata', 'aati': 'aati', 'aate': 'aate',
    'lagata': 'lagta', 'lagati': 'lagti', 'lagate': 'lagte',
    'galata': 'galat', 'ghalata': 'galat',
    'bahuta': 'bahut', 'bahute': 'bahut',
    'kama': 'kaam', 'kaama': 'kaam',
    # Other ITRANS artifacts
    'aba': 'ab',          # extra 'a' after ab
    'maimne': 'maine', 'mainne': 'maine',  # past-tense "I"
    'haine': 'hain',
    'yahim': 'yahin', 'wahim': 'wahin', 'jahim': 'jahin',
    # Anusvara left as 'm' after ITRANS conversion
    'men': 'mein',         # में -> "men" via preclean (NOT English "men")
    'meM': 'mein',         # uppercase M variant
    # Numbers / counters
    'eka': 'ek', 'doha': 'do', 'tina': 'teen',
    # Time / common drift
    'pahale': 'pehle', 'pahala': 'pehla', 'pahali': 'pehli',
    'rata': 'raat', 'din': 'din',
    'bota': 'bahut', 'bot': 'bahut',  # "बोत" misread of "बहुत"
    # Postposition Google variant
    'per': 'par',          # "per" used for "पर" in Google output
    # Common adjective drift
    'achchhe': 'achhe',
    # Saath family
    'sata': 'saath',       # ITRANS of "साथ"; also could be "सात" (7) but rare
    'sath': 'saath',
    # Poetic Hindi misreads
    'aphasan': 'afsana', 'aphasana': 'afsana',
    'aphasane': 'afsane',
    'racha': 'raat',       # "रात" misread as "राच"
    'rach': 'raat',
    'maim': 'main',
    'kyasa': 'kaisa', 'kyase': 'kaise', 'kyasi': 'kaisi',
    'paoge': 'paaoge', 'paaoge': 'paaoge',
    'phira': 'phir',
    # Whisper hallucination words seen in log
    'baddhiya': 'badhiya', 'baddhiyan': 'badhiya',
    'badhahi': 'badhiya', 'badhah': 'badhiya',
    # Honour / sound English drift cleanup
    'savamda': 'sound', 'savamd': 'sound',
}

# Spoken-command patterns — convert "comma"/"full stop"/"new line" etc. to
# their actual punctuation/formatting. Longer phrases first so "exclamation
# mark" wins over a bare "exclamation".
_SPOKEN_COMMAND_PATTERNS = [
    # English — multi-word phrases first
    (re.compile(r'\bnew\s+paragraph\b', re.IGNORECASE),    '\n\n'),
    (re.compile(r'\bnew\s+line\b', re.IGNORECASE),         '\n'),
    (re.compile(r'\bnext\s+line\b', re.IGNORECASE),        '\n'),
    (re.compile(r'\bfull\s+stop\b', re.IGNORECASE),        '.'),
    (re.compile(r'\bquestion\s+mark\b', re.IGNORECASE),    '?'),
    (re.compile(r'\bexclamation\s+(?:mark|point)\b', re.IGNORECASE), '!'),
    (re.compile(r'\bsemi[\s-]?colon\b', re.IGNORECASE),    ';'),
    (re.compile(r'\bopen\s+quote[s]?\b', re.IGNORECASE),   '"'),
    (re.compile(r'\bclose\s+quote[s]?\b', re.IGNORECASE),  '"'),
    (re.compile(r'\bend\s+quote\b', re.IGNORECASE),        '"'),
    (re.compile(r'\bopen\s+(?:bracket|parenthesis)\b', re.IGNORECASE),  '('),
    (re.compile(r'\bclose\s+(?:bracket|parenthesis)\b', re.IGNORECASE), ')'),
    (re.compile(r'\bopen\s+square\b', re.IGNORECASE),      '['),
    (re.compile(r'\bclose\s+square\b', re.IGNORECASE),     ']'),
    # English — single words
    (re.compile(r'\bcomma\b', re.IGNORECASE),              ','),
    (re.compile(r'\bperiod\b', re.IGNORECASE),             '.'),
    (re.compile(r'\bcolon\b', re.IGNORECASE),              ':'),
    (re.compile(r'\bhyphen\b', re.IGNORECASE),             '-'),
    (re.compile(r'\bdash\b', re.IGNORECASE),               '-'),
    (re.compile(r'\bslash\b', re.IGNORECASE),              '/'),
    (re.compile(r'\bbackslash\b', re.IGNORECASE),          '\\\\'),
    (re.compile(r'\bunderscore\b', re.IGNORECASE),         '_'),
    (re.compile(r'\bat\s+sign\b', re.IGNORECASE),          '@'),
    (re.compile(r'\bhashtag\b', re.IGNORECASE),            '#'),
    # Hinglish / Hindi
    (re.compile(r'\bnaya\s+paragraph\b', re.IGNORECASE),   '\n\n'),
    (re.compile(r'\bnayi\s+line\b', re.IGNORECASE),        '\n'),
    (re.compile(r'\bagli\s+line\b', re.IGNORECASE),        '\n'),
    (re.compile(r'\bpurna\s+viram\b', re.IGNORECASE),      '.'),
    (re.compile(r'\balp\s+viram\b', re.IGNORECASE),        ','),
    (re.compile(r'\bprashn\s+chinh\b', re.IGNORECASE),     '?'),
    (re.compile(r'\bvismayadhi[bm]odhak\b', re.IGNORECASE), '!'),
]

# Common Hindi/Hinglish words that should ALWAYS be lowercase mid-sentence.
# Google's en-IN ASR randomly Title-Cases words mid-sentence ("Sab Sahi Hai" etc.).
# After the first word, any title-cased entry from this set gets lowercased.
# Kept conservative — only words that are NEVER proper nouns.
_HINDI_LOWERCASE_MIDWORDS = frozenset([
    # Pronouns / possessives
    'main', 'mein', 'tum', 'aap', 'hum', 'woh', 'yeh', 'ye', 'wo',
    'mera', 'meri', 'mere', 'tera', 'teri', 'tere',
    'aapka', 'aapki', 'aapke', 'tumhara', 'tumhari', 'tumhare',
    'hamara', 'hamari', 'hamare', 'unka', 'unki', 'unke',
    'uska', 'uski', 'uske', 'iska', 'iski', 'iske',
    'mujhe', 'tujhe', 'usse', 'usko', 'mujhko', 'tumko',
    # Verbs (be / do / go / come / say)
    'hai', 'hain', 'tha', 'thi', 'the', 'hoon', 'ho', 'hoga', 'honga',
    'hona', 'hota', 'hoti', 'hote', 'hua', 'huye', 'huyi',
    'kar', 'karo', 'karna', 'karta', 'karte', 'karti',
    'kara', 'kari', 'kiya', 'kiye', 'ja', 'jao', 'jana', 'gaya', 'gayi',
    'aa', 'aao', 'aana', 'aaya', 'aayi', 'aate', 'aati',
    'le', 'lo', 'liya', 'de', 'do', 'diya', 'dete', 'deti',
    'bol', 'bolo', 'bola', 'boli', 'bole',
    'rakh', 'rakha', 'rakhi', 'rakhe',
    'mil', 'mila', 'mili', 'mile', 'milta', 'milti',
    'samajh', 'samjho', 'samjha', 'samajhi',
    # Continuous (raha/rahi/rahe)
    'raha', 'rahi', 'rahe', 'rahega', 'rahegi',
    # Common particles / postpositions / conjunctions
    'aur', 'ya', 'agar', 'lekin', 'magar', 'kyunki', 'kyuki',
    'jab', 'tab', 'kab', 'jaha', 'waha', 'kaha', 'yaha',
    'phir', 'fir', 'ab', 'abhi', 'kabhi', 'hamesha', 'humesha',
    'se', 'ko', 'me', 'mein', 'par', 'pe', 'tak', 'bina',
    'liye', 'isliye', 'kyun', 'kyon',
    'bhi', 'hi', 'na', 'nahin', 'nahi', 'mat',
    'jo', 'jiska', 'jiska', 'jise', 'wo', 'usko',
    # Adjectives / quantifiers / common
    'sab', 'kuch', 'koi', 'kai', 'thoda', 'zyada', 'bahut', 'kam',
    'sahi', 'galat', 'achha', 'accha', 'acchi', 'acche',
    'naya', 'purana', 'bada', 'chhota', 'lamba', 'chhoti',
    'pyara', 'sundar', 'badhiya', 'gandhi',
    # Common nouns (low risk of being a proper noun)
    'baat', 'kaam', 'samay', 'din', 'raat', 'subah', 'shaam',
    'ghar', 'aaj', 'kal', 'parso', 'hafta', 'mahina', 'saal',
    'naam', 'jagah', 'cheez', 'paani', 'khana', 'kapda', 'kapde',
    'matlab', 'taraf', 'tarah', 'awaaz', 'awaz', 'aawaz',
    'dikkat', 'pareshani', 'mushkil', 'asaan', 'mushkilen',
    # Sunai/dikhai etc.
    'sunai', 'dikhai', 'sunna', 'sun', 'suno', 'suna',
    'dekhna', 'dekh', 'dekho', 'dekha',
    # Quantity / answer
    'haan', 'haa', 'na', 'nahin', 'nahi', 'shayad', 'jarur',
])

# Words that legitimately end in 'a' — never strip trailing 'a' from these.
# Entries that do NOT end in 'a' would be no-ops (the stripper checks
# `low.endswith('a')` first) and have been omitted.
_TRAILING_A_WHITELIST = frozenset([
    # ── Hindi pronouns / possessives ────────────────────────────────────────
    'aapka', 'apna', 'hamara', 'mera', 'tera', 'tumhara', 'unka', 'uska',
    'iska', 'inka', 'jinka', 'kinka',  # demonstratives ending in -a
    'kya', 'kaha', 'jaha', 'waha', 'yaha',
    # Hindi infinitives ending in 'a' (-na/-aa forms)
    'hona', 'lana', 'paana', 'dena', 'lena', 'rona', 'kona',
    'jeena', 'marna', 'rakhna', 'samjhna',
    # ── Demonstrative adjectives (kaisa/waisa family) ──────────────────────
    'aisa', 'jaisa', 'kaisa', 'waisa', 'kaunsa', 'itna', 'jitna', 'utna',
    # ── Future tense verbs (-ega) ──────────────────────────────────────────
    'aayega', 'hoga', 'jaega', 'jayega', 'karega', 'milega', 'rahega', 'lagega',
    # ── Past/perfect verb forms ────────────────────────────────────────────
    'aaya', 'gaya', 'hua', 'tha', 'piya', 'gaaya',
    'banaaya', 'banaya', 'dekha', 'sikha', 'paya', 'paaya',
    'kiya', 'liya', 'diya', 'likha', 'pakda', 'padha', 'pita', 'mata',
    'bhuja', 'roya', 'maara', 'haara', 'jeeta',
    'bhaga', 'bhaagi', 'bhaage', 'jaga', 'jaagi', 'jaage',
    # ── Modal / capability verbs (sakta/sakti/sakte) ───────────────────────
    'sakta', 'sakti', 'sakte', 'pata', 'paata', 'paati',
    'rakhta', 'rakhti', 'rakhte',
    # ── Song / poetic Hindi words ─────────────────────────────────────────
    'divana', 'diwana', 'deewana', 'parwana', 'tarana', 'afsana', 'dastana',
    'jadu', 'sapna', 'apna', 'rasta', 'kahani', 'rishta',
    # ── Continuous tense (raha/rahi) ───────────────────────────────────────
    'raha', 'rahi',
    # ── Infinitive verbs (-na) ─────────────────────────────────────────────
    'aana', 'bolna', 'bhulna', 'chalna', 'chhupna', 'dena',
    'jana', 'jeena', 'jhukna', 'kahna', 'kahana', 'karna', 'khana',
    'khelna', 'lena', 'likhna', 'pakdna', 'pakadna', 'pina',
    'sikhana', 'sona', 'sunna', 'samajna', 'samajhna', 'utarna',
    'dekhna', 'sikhna',
    # ── Common adjectives ──────────────────────────────────────────────────
    'accha', 'acchha', 'achcha', 'achha', 'badhiya', 'bada', 'chhota',
    'gora', 'kaala', 'kala', 'kaccha', 'meetha', 'meeta', 'mota',
    'naya', 'neela', 'peela', 'puraana', 'purana', 'seedha', 'thanda',
    'thoda', 'thora', 'safa', 'kacha', 'pakka',
    # ── Common nouns ───────────────────────────────────────────────────────
    'bachcha', 'bhasha', 'bharosa', 'chacha', 'dada', 'baniya',
    'data', 'desha', 'dikha', 'duniya', 'ganga',
    'hawa', 'kapda', 'khaata', 'macha', 'masala', 'rasta', 'roja',
    'sapna', 'suna', 'yamuna', 'zyada', 'maja', 'maza',
    'paani', 'pasinda', 'pasanda', 'rishta', 'shadi',
    'beta', 'beti', 'pita', 'mata', 'mama',
    'pata', 'paka', 'jaata',  # know/info, ripe, going (data/sata moved to dict)
    # ── Verbs (past 3p) ────────────────────────────────────────────────────
    'baitha', 'bana', 'bola', 'bula', 'chala', 'gira',
    'jaga', 'jaaga', 'khaya', 'khada', 'lauta',
    'mila', 'mara', 'rakha', 'roka', 'rota', 'soya', 'utha',
    # ── English-origin words used in Hinglish (end in 'a') ─────────────────
    'agenda', 'alpha', 'area', 'beta', 'camera', 'cinema', 'delta',
    'drama', 'extra', 'idea', 'india', 'media', 'mocha', 'opera',
    'panda', 'pasta', 'pizza', 'plaza', 'soda', 'tea', 'visa',
    'vista', 'yoga', 'yatra',
])

# Legacy alias — _clean_hinglish now does everything.
# These are kept so that downstream code referring to them does not break,
# but they no longer drive behavior.
_HINGLISH_CLEANUP_PATTERNS = _REGEX_PATTERNS
_ARTIFACT_PATTERNS = _PROMPT_ARTIFACTS
_HINGLISH_FIX_PATTERNS = []  # Legacy stub; behavior moved into _PHONETIC_WORD_MAP.


def _detect_device():
    """
    Advanced Hardware Detection for Bolo:
    Detects CUDA, checks VRAM, and sets optimal quantization.
    """
    try:
        import torch
        if torch.cuda.is_available():
            gpu_name = torch.cuda.get_device_name(0)
            vram_total = torch.cuda.get_device_properties(0).total_memory / 1024**3
            print(f"[Hardware] CUDA detected: {gpu_name} ({vram_total:.1f}GB VRAM)")
            # int8_float16: store weights as int8 (VRAM efficient), compute in float16 (fast GPU)
            return "cuda", "int8_float16"
    except ImportError:
        pass

    # Fallback check via nvidia-smi
    try:
        import subprocess
        res = subprocess.run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"], 
                           capture_output=True, text=True, timeout=2)
        if res.returncode == 0 and res.stdout.strip():
            print(f"[Hardware] NVIDIA GPU found ({res.stdout.strip()}) but CUDA torch not available.")
    except:
        pass

    print("[Hardware] Using CPU Mode (int8 quantization).")
    return "cpu", "int8"

class AudioEngine:
    """
    Core audio engine for Bolo voice-to-text application.

    Responsibilities:
        - Microphone stream management (PyAudio)
        - Audio recording with pre-roll buffer
        - Speech-to-text via Google Speech API or Whisper AI
        - Audio preprocessing (HPF, VAD, normalization, gain)
        - Hinglish transcription support with post-processing

    Thread Safety:
        - Uses threading.Lock for shared state (is_recording, audio_frames)
        - Background listener thread for volume metering and pre-roll buffer
        - File locking for history writes

    Configuration:
        - Audio parameters from config.py (SAMPLE_RATE, CHUNK_SIZE, etc.)
        - Transcription settings (engine, language, model)
        - Audio preprocessing (VAD_THRESHOLD, DIGITAL_GAIN, etc.)
    """
    def __init__(self):
        self.recognizer = sr.Recognizer()
        self.is_recording = False
        self._lock = threading.Lock()
        self.audio_frames = []

        self.p = None
        self.format = pyaudio.paInt16
        self.channels = config.CHANNELS
        self.rate = config.SAMPLE_RATE
        self.chunk_size = config.CHUNK_SIZE
        self.sample_width = 2
        
        self.current_volume = 0
        self._stop_event = threading.Event()
        self._record_thread = None

        self._whisper_model = None
        self._zero_stt_model = None
        self._device, self._compute_type = _detect_device()
        print(f"[Audio] Device: {self._device}, Compute: {self._compute_type}")

        # Pre-roll circular buffer (spec-compliant: 0.5s)
        self.pre_roll_buffer = collections.deque(
            maxlen=int(self.rate / self.chunk_size * config.PRE_ROLL_SECONDS)
        )
        self._stop_engine_event = threading.Event()
        self._bg_listener_thread = None

        self._adjust_noise()
        self._init_audio()
        self._start_bg_listener()

    def _init_audio(self):
        try:
            self.kill_stream()
            self.p = pyaudio.PyAudio()
            # Verify stream support
            self._initialize_stream()
            print(f"[Audio] Engine ready at {self.rate}Hz Mono")
        except Exception as e:
            print(f"[Audio] Engine Init Error: {e}")

    def _initialize_stream(self):
        """Initialize audio stream with error handling and auto-recovery."""
        try:
            self.stream = self.p.open(
                format=self.format,
                channels=self.channels,
                rate=self.rate,
                input=True,
                frames_per_buffer=self.chunk_size,
                start=True
            )
            print(f"[Audio] Stream initialized successfully")
        except Exception as e:
            print(f"[Audio] Failed to initialize stream: {e}")
            self.stream = None
            # Try to recover: reinitialize PyAudio if stream init fails
            try:
                print("[Audio] Attempting stream recovery...")
                if self.p:
                    self.p.terminate()
                self.p = pyaudio.PyAudio()
                self.stream = self.p.open(
                    format=self.format,
                    channels=self.channels,
                    rate=self.rate,
                    input=True,
                    frames_per_buffer=self.chunk_size,
                    start=True
                )
                print("[Audio] Stream recovered successfully")
            except Exception as e2:
                print(f"[Audio] Stream recovery failed: {e2}")
                raise RuntimeError(f"Cannot initialize audio stream: {e2}")

    def _adjust_noise(self):
        try:
            print("Calibrating microphone...")
            with sr.Microphone(sample_rate=self.rate) as source:
                self.recognizer.adjust_for_ambient_noise(source, duration=0.8)
            print(f"Calibration complete. Energy threshold: {self.recognizer.energy_threshold}")
        except Exception as e:
            print(f"[Audio] Noise calibration error: {e}")

    def _start_bg_listener(self):
        if self._bg_listener_thread is None or not self._bg_listener_thread.is_alive():
            self._stop_engine_event.clear()
            self._bg_listener_thread = threading.Thread(target=self._bg_listener_loop, daemon=True)
            self._bg_listener_thread.start()

    def _bg_listener_loop(self):
        """Always running background thread to fill pre-roll buffer and show volume."""
        while not self._stop_engine_event.is_set():
            if not self.is_recording:
                try:
                    if self.stream is None or not self.stream.is_active():
                        time.sleep(0.1)
                        continue
                        
                    data = self.stream.read(self.chunk_size, exception_on_overflow=False)
                    if data:
                        with self._lock:
                            # Double-check under lock to prevent TOCTOU race with start_recording()
                            if not self.is_recording:
                                self.pre_roll_buffer.append(data)
                            # Update volume for UI meters (always update, even during recording)
                            count = len(data) // 2
                            if count > 0:
                                shorts = struct.unpack("%dh" % count, data)
                                sum_squares = sum(s * s for s in shorts)
                                self.current_volume = math.sqrt(sum_squares / count)
                except Exception:
                    time.sleep(0.1)
            else:
                # When recording, the record_loop handles it, but we still want to 
                # keep the pre_roll buffer somewhat fresh or just wait.
                time.sleep(0.1)

    # ------------------------------------------------------------------
    #  Whisper Helpers
    # ------------------------------------------------------------------
    def _get_whisper_model(self):
        if self._whisper_model is None:
            model_size = config.WHISPER_MODEL
            print(f"[Audio] Loading Whisper model '{model_size}'...")
            try:
                from faster_whisper import WhisperModel
                self._whisper_model = WhisperModel(
                    model_size,
                    device=self._device,
                    compute_type=self._compute_type,
                )
                print(f"[Audio] Whisper model '{model_size}' loaded ({self._device}).")
            except Exception as e:
                print(f"[Audio] Failed to load Whisper: {e}")
                raise
        return self._whisper_model

    def _ensure_zero_stt_model(self, progress_cb=None):
        """Ensure shunyalabs/zero-stt-hinglish is available as a CTranslate2 model.

        Steps:
            1. Use existing converted model if model.bin already on disk.
            2. Otherwise pull weights from HuggingFace Hub into HF cache
               (auto-download — no manual huggingface-cli needed).
            3. Convert HF model → CTranslate2 quantized model for faster-whisper.

        progress_cb: optional callable(stage: str) for UI feedback.
        """
        model_path = config.ZERO_STT_MODEL_PATH
        if os.path.exists(os.path.join(model_path, "model.bin")):
            print("[Audio] zero-stt model present, using cached conversion.")
            return model_path

        # 1. Make sure raw HF weights are downloaded
        cache_path = self._get_hf_cache_path()
        if not cache_path or not os.path.exists(os.path.join(cache_path, "model.safetensors")):
            if progress_cb:
                progress_cb(0, "Downloading zero-stt-hinglish from HuggingFace Hub...")
            print(f"[Audio] Downloading {config.ZERO_STT_MODEL_ID} from HuggingFace Hub...")
            try:
                from huggingface_hub import snapshot_download
                cache_path = snapshot_download(
                    repo_id=config.ZERO_STT_MODEL_ID,
                    allow_patterns=["*.json", "*.txt", "*.safetensors", "tokenizer*", "preprocessor*"],
                )
                print(f"[Audio] Downloaded zero-stt to: {cache_path}")
            except Exception as e:
                raise RuntimeError(f"Failed to download {config.ZERO_STT_MODEL_ID}: {e}")

        # 2. Convert HF → CTranslate2 for faster-whisper compatibility
        if progress_cb:
            progress_cb(0, "Converting model for fast inference (one-time)...")
        try:
            from ctranslate2.converters import TransformersConverter
            converter = TransformersConverter(
                model_name_or_path=cache_path,
                low_cpu_mem_usage=True,
            )
            converter.convert(
                output_dir=model_path,
                force=True,
                quantization=self._compute_type,
            )
            print(f"[Audio] zero-stt converted to {model_path}")
        except Exception as e:
            raise RuntimeError(f"CTranslate2 conversion failed: {e}")

        return model_path

    def _get_hf_cache_path(self):
        """Return the resolved local path of shunyalabs/zero-stt-hinglish in HF cache."""
        try:
            import os
            cache_dir = os.path.join(os.path.expanduser("~"), ".cache", "huggingface", "hub")
            snapshots_dir = os.path.join(
                cache_dir, "models--shunyalabs--zero-stt-hinglish", "snapshots"
            )
            if not os.path.isdir(snapshots_dir):
                return None
            for rev in os.listdir(snapshots_dir):
                rev_path = os.path.join(snapshots_dir, rev)
                if os.path.isdir(rev_path) and os.path.exists(
                    os.path.join(rev_path, "model.safetensors")
                ):
                    return rev_path
        except Exception as e:
            print(f"[Audio] HF cache path lookup failed: {e}")
        return None

    def _get_zero_stt_model(self):
        """Lazy-load the zero-stt model. Each call may retry — no permanent
        failure cache (network/disk issues can heal between attempts).
        """
        if self._zero_stt_model is not None:
            return self._zero_stt_model
        model_path = self._ensure_zero_stt_model()
        print("[Audio] Loading zero-stt-hinglish model...")
        try:
            from faster_whisper import WhisperModel
            self._zero_stt_model = WhisperModel(
                model_path,
                device=self._device,
                compute_type=self._compute_type,
            )
            print("[Audio] zero-stt-hinglish model loaded.")
            return self._zero_stt_model
        except Exception as e:
            self._zero_stt_model = None
            raise RuntimeError(f"Failed to load zero-stt: {e}")

    def download_zero_stt_now(self, progress_cb=None):
        """Trigger zero-stt download + conversion explicitly (used by GUI).

        progress_cb(mb, status_text) is invoked from a poller thread during
        the HF download phase; the CTranslate2 conversion phase reports only
        the stage label (no per-MB progress).
        """
        stop = threading.Event()
        poller = None
        if progress_cb:
            poller = threading.Thread(
                target=self._poll_download_progress,
                args=(self._hf_cache_root(), stop, progress_cb, "Zero-STT-Hinglish"),
                daemon=True,
            )
            poller.start()
        try:
            self._ensure_zero_stt_model(progress_cb=progress_cb)
            return True
        except Exception as e:
            print(f"[Audio] zero-stt download failed: {e}")
            return False
        finally:
            stop.set()
            if poller:
                poller.join(timeout=2.0)

    def _transcribe_zero_stt(self, raw_data):
        audio_np = self._preprocess_audio(raw_data, self.rate, for_whisper=True)
        model = self._get_zero_stt_model()

        print("[Audio] Zero-STT: transcribing in Hindi...")
        segs, _ = model.transcribe(
            audio_np,
            beam_size=5,
            best_of=3,
            language="hi",
            task="transcribe",
            temperature=0.0,
            no_speech_threshold=config.NO_SPEECH_THRESHOLD,
            log_prob_threshold=config.LOG_PROB_THRESHOLD,
            condition_on_previous_text=False,
            compression_ratio_threshold=2.4,
            repetition_penalty=1.15,
            vad_filter=True,
            vad_parameters=dict(
                min_speech_duration_ms=250,
                min_silence_duration_ms=500,
                speech_pad_ms=400,
            ),
        )
        hindi_text = " ".join([s.text.strip() for s in segs]).strip()

        if not hindi_text:
            return ""

        print(f"[Audio] Zero-STT Hindi output: {hindi_text}")

        # Transliterate Devanagari → Roman, then apply Hinglish polisher
        text = self._transliterate_to_roman(hindi_text)
        print(f"[Audio] Transliterated: {text}")
        text = AudioEngine._clean_hinglish(text)
        return text

    @staticmethod
    def _clean_hinglish(text):
        """Polish Roman Hinglish text: strip prompt artifacts, normalize spelling,
        fix conjugation suffixes, drop stray trailing vowels from ASR output.

        Pipeline (no destructive English-word collateral):
            1. Strip Whisper / Zero-STT prompt-leak hallucinations
            2. Apply curated regex patterns (nasal, plural, schwa, char repeats)
            3. Word-level: dict lookup → verb-suffix heuristics → trailing-vowel
        """
        if not text:
            return text

        # 1. Strip prompt-leak artifacts
        for pattern in _PROMPT_ARTIFACTS:
            text = pattern.sub('', text)

        # 2. Curated regex pass
        for pattern, replacement in _REGEX_PATTERNS:
            text = pattern.sub(replacement, text)

        # 3. Word-level cleanup. Preserve original word/case unless a fix applies
        # (so proper nouns like "Sam", "Delhi" survive untouched).
        out = []
        for raw in text.split():
            if not raw:
                continue
            # Peel trailing punctuation so dict matching works on bare word
            m = re.match(r'^(.*?)([.,!?;:]+)?$', raw)
            word = m.group(1) if m else raw
            punct = (m.group(2) if m else '') or ''
            low = word.lower()

            # 3a. Direct phonetic dictionary hit
            fixed = _PHONETIC_WORD_MAP.get(low)
            if fixed is not None:
                out.append(fixed + punct)
                continue

            # 3b. Verb-suffix heuristics — only rewrite if pattern matches.
            # NOTE: `at -> ta` removed; was corrupting nouns like dikkat,
            # adalat, haqeeqat, jaroorat, imarat, etc. Verb stems that need
            # this fix (karat, bolat) are in _PHONETIC_WORD_MAP.
            rewritten = None
            if low.endswith('ane') and len(low) > 4:
                rewritten = low[:-3] + 'ne'      # khadagane -> khadne
            elif low.endswith('ate') and len(low) > 4:
                rewritten = low[:-3] + 'te'      # karate -> karte
            elif low.endswith('ati') and len(low) > 4:
                rewritten = low[:-3] + 'ti'      # karati -> karti
            elif low.endswith('eg') and len(low) > 3:
                rewritten = low[:-2] + 'ega'     # kareg -> karega

            # 3c. Trailing-vowel cleanup (Zero-STT drops/adds short final 'a'/'ah')
            # Only the OUTER whitelist check matters — if `low` is a legit word
            # ending in 'a' (raha, jaisa, etc.), don't touch it. The trimmed form
            # being valid is fine: "saba" -> "sab" is the desired behavior.
            if rewritten is None and len(low) > 3 and low not in _TRAILING_A_WHITELIST:
                if low.endswith('ah'):
                    rewritten = low[:-1]
                elif low.endswith('a'):
                    trimmed = low[:-1]
                    if len(trimmed) >= 3:
                        rewritten = trimmed

            # 3d. Cascade lookup: trimmed form may itself be a dict key
            # (e.g. "matalaba" -> trim -> "matalab" -> dict -> "matlab")
            if rewritten is not None:
                cascade = _PHONETIC_WORD_MAP.get(rewritten)
                if cascade is not None:
                    rewritten = cascade

            # If no rewrite triggered, keep the ORIGINAL word (case preserved)
            out.append((rewritten if rewritten is not None else word) + punct)
        return ' '.join(out).strip()


    def reload_zero_stt_model(self):
        self._zero_stt_model = None
        print("[Audio] zero-stt model will be reloaded on next use.")

    @staticmethod
    def _resample_audio(audio_np, orig_rate, target_rate):
        """Resample using linear interpolation (good enough for speech)."""
        if orig_rate == target_rate:
            return audio_np
        duration = len(audio_np) / orig_rate
        target_length = int(duration * target_rate)
        indices = np.linspace(0, len(audio_np) - 1, target_length)
        return np.interp(indices, np.arange(len(audio_np)), audio_np)

    @staticmethod
    def _high_pass_filter(data, cutoff=100, fs=16000):
        """First-order IIR high-pass filter.

        Recurrence:  y[n] = alpha * (y[n-1] + x[n] - x[n-1])
            alpha = RC / (RC + dt),  RC = 1 / (2*pi*cutoff),  dt = 1/fs

        Uses scipy.signal.lfilter for a vectorized C-level pass that gives the
        true IIR response (the previous numpy-cumsum implementation produced a
        different — and incorrect — transfer function).
        """
        if len(data) < 2:
            return data
        rc = 1.0 / (2.0 * np.pi * cutoff)
        dt = 1.0 / fs
        alpha = rc / (rc + dt)
        try:
            from scipy.signal import lfilter
            # Transfer function: H(z) = alpha (1 - z^-1) / (1 - alpha z^-1)
            b = np.array([alpha, -alpha], dtype=np.float32)
            a = np.array([1.0, -alpha], dtype=np.float32)
            return lfilter(b, a, data).astype(np.float32)
        except ImportError:
            # Fallback: pure-numpy IIR using a Python loop. Slow but correct.
            y = np.empty_like(data)
            y[0] = data[0]
            for n in range(1, len(data)):
                y[n] = alpha * (y[n - 1] + data[n] - data[n - 1])
            return y

    @staticmethod
    def _trim_silence(audio_np, threshold=None, frame_length=512):
        # Use configurable VAD_THRESHOLD from config
        if threshold is None:
            threshold = config.VAD_THRESHOLD
        if len(audio_np) < frame_length:
            return audio_np
        n_frames = (len(audio_np) - frame_length + 1) // frame_length
        if n_frames <= 0:
            return audio_np
        truncated = audio_np[:n_frames * frame_length]
        frames_rms = np.sqrt(np.mean(truncated.reshape(n_frames, frame_length) ** 2, axis=1))
        above = frames_rms > threshold
        if not np.any(above):
            return audio_np
        # Find first frame above threshold
        first_active = np.argmax(above)
        # Find last frame above threshold
        last_active = len(above) - 1 - np.argmax(above[::-1])
        # Keep more context to preserve beginning and end of speech
        # 5 frames before speech starts (~160ms), 6 frames after it ends (~192ms)
        start_idx = max(0, first_active - 5) * frame_length
        end_idx = min(len(audio_np), (last_active + 7) * frame_length)
        return audio_np[start_idx:end_idx]

    def _preprocess_audio(self, raw_data, sample_rate, for_whisper=False):
        """Audio preprocessing pipeline:

            1. int16 → float32 normalize
            2. Resample to 16 kHz if needed
            3. 100 Hz HPF (remove fan/hum)
            4. RMS-target normalize (consistent loudness across recordings)
            5. Optional digital gain
            6. VAD silence trim
            7. Soft clip + symmetric silence padding
        """
        audio = np.frombuffer(raw_data, dtype=np.int16).astype(np.float32) / 32768.0

        if sample_rate != 16000:
            audio = self._resample_audio(audio, sample_rate, 16000)

        # 1. HPF — remove low-frequency hum/fan noise
        audio = self._high_pass_filter(audio, cutoff=config.HPF_CUTOFF, fs=16000)

        # 2. RMS normalize to target loudness (single source of truth for level)
        rms = float(np.sqrt(np.mean(audio ** 2)))
        if rms > 1e-3:
            audio = audio * (config.NORMALIZATION_RMS / rms)

        # 3. Apply user-configurable digital gain (post-normalize)
        if config.DIGITAL_GAIN != 1.0:
            audio = audio * config.DIGITAL_GAIN

        # 4. VAD trim on normalized signal
        audio = self._trim_silence(audio, threshold=config.VAD_THRESHOLD * 1.2)

        # 5. Soft-clip to prevent hard distortion if gain pushed peaks > 1.0
        audio = np.tanh(audio * 0.95)

        # 6. Symmetric silence padding (gives ASR context at edges)
        pad_len = int(16000 * (config.SILENCE_PADDING_MS / 1000.0))
        if pad_len > 0:
            padding = np.zeros(pad_len, dtype=np.float32)
            audio = np.concatenate([padding, audio, padding])

        if for_whisper:
            # Dynamic window: pad to nearest power-of-2, min 3s (was fixed 30s)
            min_samples = 3 * 16000
            padded_len = max(min_samples, len(audio))
            # Round up to nearest power of 2 for faster FFT
            target_samples = 1 << (padded_len - 1).bit_length()
            if len(audio) > target_samples:
                audio = audio[:target_samples]
            else:
                audio = np.pad(audio, (0, target_samples - len(audio)), 'constant')
            return audio
        else:
            # int16 bytes for speech_recognition.AudioData
            audio_int16 = np.clip(audio * 32767, -32768, 32767).astype(np.int16)
            return audio_int16.tobytes()

    # ------------------------------------------------------------------
    #  Recording
    # ------------------------------------------------------------------
    def start_recording(self):
        print("[Audio] start_recording() called")
        with self._lock:
            if self.is_recording:
                print("[Audio] Already recording, ignoring")
                return

            print("[Audio] Setting up recording state...")
            self._stop_event.clear()
            self.is_recording = True

            # Start with the pre-roll buffer to catch the beginning of the speech
            # CRITICAL: Must acquire lock to prevent race with bg_listener_loop
            self.audio_frames = list(self.pre_roll_buffer)
            print(f"[Audio] Pre-roll buffer has {len(self.pre_roll_buffer)} frames")
            # We don't clear pre_roll_buffer here, we'll just stop adding to it in bg_listener

            if self.p is None:
                print("[Audio] Initializing audio (PyAudio is None)")
                self._init_audio()
            else:
                print("[Audio] PyAudio already initialized")

            # Stream is kept active by background listener (start=True in _initialize_stream)
            # Only need recovery if stream is None or unexpectedly inactive
            if self.stream is None or not self.stream.is_active():
                print("[Audio] Stream needs initialization/recovery")
                if self.stream:
                    try:
                        self.stream.close()
                    except:
                        pass
                self._initialize_stream()

            if not self.stream or not self.stream.is_active():
                print("[Audio] CRITICAL: Stream failed to start")
                self.is_recording = False
                return

            print("[Audio] Stream active and ready")

            print("[Audio] Starting record thread...")
            self._record_thread = threading.Thread(target=self._record_loop, daemon=True)
            self._record_thread.start()
            print("[Audio] Record thread started")

    def _record_loop(self):
        """Stream read loop. Holds lock briefly to snapshot stream ref so
        kill_stream() can't null it under us between is_active() and read().
        """
        print("[Audio] _record_loop() started")
        frame_count = 0
        expected_bytes = self.chunk_size * self.sample_width
        while self.is_recording and not self._stop_event.is_set():
            # Snapshot stream under lock — kill_stream() may null self.stream
            with self._lock:
                stream = self.stream
                if stream is None:
                    break
            try:
                if not stream.is_active():
                    print(f"[Audio] Stream not active, exiting loop ({frame_count} frames)")
                    break
                data = stream.read(self.chunk_size, exception_on_overflow=False)
                if not data or len(data) < expected_bytes:
                    print(f"[Audio] Incomplete frame: {len(data) if data else 0}/{expected_bytes} bytes")
                    continue
                self.audio_frames.append(data)
                frame_count += 1
                count = len(data) // 2
                if count > 0:
                    shorts = struct.unpack(f"{count}h", data)
                    sum_squares = sum(s * s for s in shorts)
                    self.current_volume = math.sqrt(sum_squares / count)
            except OSError as e:
                # Stream closed mid-read; expected during shutdown
                print(f"[Audio] Stream OSError during read: {e}")
                break
            except Exception as e:
                print(f"[Audio] Recording error: {e}")
                break
        print(f"[Audio] _record_loop() ended ({frame_count} frames)")
        self.current_volume = 0

    def stop_recording(self, language=config.DEFAULT_LANGUAGE):
        print(f"[Audio] stop_recording() called (language={language})")
        # 1. Post-roll: Wait for 0.5s before actually stopping the capture
        # This ensures the ending words are not cut off.
        time.sleep(config.POST_ROLL_SECONDS)

        with self._lock:
            self.is_recording = False
            self._stop_event.set()

        if self._record_thread:
            print("[Audio] Waiting for record thread to finish...")
            self._record_thread.join(timeout=2.0)
            self._record_thread = None

        # Stream stays active for background listener (continuous pre-roll)

        print(f"[Audio] Audio frames captured: {len(self.audio_frames)}")
        if not self.audio_frames:
            print("[Audio] No audio frames captured.")
            return ""

        return self._process_audio(language)

    # ------------------------------------------------------------------
    #  Processing
    # ------------------------------------------------------------------
    def _process_audio(self, language):
        print(f"[Audio] _process_audio() called")
        raw_data = b"".join(self.audio_frames)
        self.audio_frames = []

        if not raw_data:
            print("[Audio] Raw audio data is empty.")
            return ""
        print(f"[Audio] Processing {len(raw_data)} bytes of audio data")

        total_duration = len(raw_data) / (self.rate * self.sample_width)
        print(f"[Audio] Captured {total_duration:.2f}s of audio ({len(raw_data)} bytes)")

        if total_duration < 1.0:
            print("[Audio] Audio too short (<1s), skipping transcription to avoid gibberish.")
            return ""

        engine = getattr(config, 'TRANSCRIPTION_ENGINE', 'google')
        is_hinglish = language == 'xx-HI'
        # For Hinglish, Google's en-IN handles code-switching naturally and outputs Roman
        google_lang = 'en-IN' if is_hinglish else language

        if engine == 'google':
            text = self._transcribe_google(raw_data, google_lang, skip_history=(is_hinglish))
            if is_hinglish and text:
                text = AudioEngine._clean_hinglish(text)
                self.log_history(text, 'xx-HI')
            return text

        if engine == 'whisper':
            if is_hinglish:
                # 1. Primary: Zero-STT (most optimized for Hinglish)
                try:
                    print("[Audio] Mode: Local (Zero-STT) -> Hinglish Pipeline")
                    text = self._transcribe_zero_stt(raw_data)
                    if text and len(text.strip()) > 1:
                        text = AudioEngine._clean_hinglish(text)
                        text = AudioEngine._post_process_transcription(text)
                        self.log_history(text, 'xx-HI')
                        return text
                    print("[Audio] Zero-STT returned empty/short output. Trying fallback...")
                except Exception as e:
                    print(f"[Audio] Zero-STT Error: {e}. Falling back to Whisper Large-v3-Turbo.")

                # 2. Secondary: Whisper Large-v3-Turbo (Hindi → Romanized)
                try:
                    print("[Audio] Mode: Local (Whisper Fallback) -> Hinglish Pipeline")
                    text = self._transcribe_whisper_hinglish_fallback(raw_data)
                    if text and len(text.strip()) > 1:
                        text = AudioEngine._clean_hinglish(text)
                        text = AudioEngine._post_process_transcription(text)
                        self.log_history(text, 'xx-HI')
                        return text
                    print("[Audio] Whisper Fallback returned empty/short output. Trying Google Cloud.")
                except Exception as e:
                    print(f"[Audio] Whisper Fallback Error: {e}. Falling back to Google Cloud.")

                # 3. Tertiary: Google Cloud (en-IN handles code-switching well)
                print("[Audio] Mode: Cloud (Google en-IN)")
                text = self._transcribe_google(raw_data, 'en-IN', skip_history=True)
                if text:
                    text = AudioEngine._clean_hinglish(text)
                    self.log_history(text, 'xx-HI')
                return text

            try:
                text = self._transcribe_whisper(raw_data, language)
                return AudioEngine._post_process_transcription(text)
            except Exception as e:
                print(f"[Audio] Whisper failed ({e}), falling back to Google...")
                return self._transcribe_google(raw_data, google_lang)

        return self._transcribe_google(raw_data, google_lang)

    @staticmethod
    def _apply_spoken_commands(text):
        """Replace spoken punctuation/formatting commands with their symbols.

        Supports English and a few common Hindi phrases. Examples:
            "Hello comma how are you" -> "Hello, how are you"
            "End of line full stop"   -> "End of line."
            "Naya paragraph"          -> "\\n\\n"

        Order matters — longer phrases first so "exclamation mark" beats
        "exclamation". Runs space normalization after substitution to
        clean up artifacts like " ." or " ,".
        """
        if not text:
            return text
        for pattern, replacement in _SPOKEN_COMMAND_PATTERNS:
            text = pattern.sub(replacement, text)
        # Tighten spacing around punctuation: " ." -> ".", " ," -> ","
        # (Excludes newlines so "word\nword" stays intact.)
        text = re.sub(r'[^\S\n]+([.,!?;:])', r'\1', text)
        # Ensure exactly one space after punctuation when followed by a
        # non-space, non-punct character. Doesn't touch consecutive punct
        # like "..." (ellipsis) or "?!".
        text = re.sub(r'([.,!?;:])(?=[^\s.,!?;:])', r'\1 ', text)
        # Trim spaces around newlines: "word \n word" -> "word\nword"
        text = re.sub(r'[^\S\n]*\n[^\S\n]*', '\n', text)
        # Collapse triple+ newlines
        text = re.sub(r'\n{3,}', '\n\n', text)
        return text

    @staticmethod
    def _post_process_transcription(text):
        """Professional finish: dedup punctuation, normalize spaces,
        capitalize first letter, append terminal punctuation if missing.

        Terminal punctuation respects '?', '!', '.', ':', ';' and ellipsis.
        Auto-punctuation and capitalization can be disabled via config.
        """
        if not text:
            return ""
        text = text.strip()

        # Spoken commands BEFORE other cleanup so "full stop" -> "." then "."
        # gets the terminal-punct check below.
        if config.SPOKEN_COMMANDS:
            text = AudioEngine._apply_spoken_commands(text)

        # Collapse runs of repeated terminators (!!! -> !, ??? -> ?)
        # Dots handled specially so "..." ellipsis survives.
        text = re.sub(r'([!?,;:])\1+', r'\1', text)
        text = re.sub(r'\.{4,}', '...', text)
        text = re.sub(r'(?<!\.)\.{2}(?!\.)', '.', text)
        # Multi-space normalize (preserve newlines from "new line"/"new paragraph")
        text = re.sub(r'[^\S\n]+', ' ', text)

        # Lowercase Hindi common words that Google randomly Title-Cases
        # mid-sentence. Only affects positions AFTER the first word; first
        # word will get capitalized below.
        words = text.split(' ')
        if len(words) > 1:
            for i in range(1, len(words)):
                w = words[i]
                # Strip trailing punct for lookup
                m = re.match(r'^(\w+)([.,!?;:]*)$', w)
                if not m:
                    continue
                bare, punct = m.group(1), m.group(2)
                # Only retitle if it's currently Title-Case (1 upper + rest lower)
                # AND the lowercase form is a known Hindi stopword.
                if bare[:1].isupper() and bare[1:] == bare[1:].lower():
                    if bare.lower() in _HINDI_LOWERCASE_MIDWORDS:
                        words[i] = bare.lower() + punct
            text = ' '.join(words)

        if config.CAPITALIZE_FIRST and text:
            text = text[0].upper() + text[1:] if len(text) > 1 else text.upper()

        if config.AUTO_PUNCTUATION and text:
            # Don't append "." if already terminated (covers ellipsis "..." too)
            if text[-1] not in '.!?:;':
                text += '.'
        return text

    @staticmethod
    def _fix_hinglish_spelling(text):
        """Legacy alias — _clean_hinglish now does everything in one pass.

        Kept for any external callers; safe to call after _clean_hinglish.
        """
        return AudioEngine._clean_hinglish(text)

    def _transcribe_whisper_hinglish_fallback(self, raw_data):
        """
        Hinglish fallback using forced Hindi transcription + Romanization.
        Uses large-v3-turbo when zero-stt is unavailable or fails.
        """
        audio_np = self._preprocess_audio(raw_data, self.rate, for_whisper=True)

        model = self._get_whisper_model()
        print("[Audio] Whisper Hinglish (Fallback): transcribing...")
        segs, info = model.transcribe(
            audio_np,
            language="hi",
            task="transcribe",
            beam_size=5,
            best_of=3,
            temperature=0.0,
            compression_ratio_threshold=2.4,
            no_speech_threshold=config.NO_SPEECH_THRESHOLD,
            log_prob_threshold=config.LOG_PROB_THRESHOLD,
            condition_on_previous_text=False,
            repetition_penalty=1.15,
            vad_filter=True,
            vad_parameters=dict(min_speech_duration_ms=200, speech_pad_ms=400)
        )

        # Combine segments (Whisper outputs Devanagari when lang='hi')
        hindi_text = " ".join([s.text.strip() for s in segs]).strip()
        if not hindi_text:
            return ""

        # Transliterate Devanagari → Roman, then polish for Hinglish
        text = self._transliterate_to_roman(hindi_text)
        text = AudioEngine._clean_hinglish(text)

        print(f"[Audio] Whisper Hinglish (Romanized): {text}")
        return text

    def _transcribe_whisper_raw(self, raw_data, language=None, hinglish_prompt=False):
        audio_np = self._preprocess_audio(raw_data, self.rate, for_whisper=True)

        if len(audio_np) < int(16000 * 0.3):
            print("[Audio] Audio too short after preprocessing.")
            return ""

        model = self._get_whisper_model()
        lang_code = language.split('-')[0] if language else None

        print(f"[Audio] Transcribing with Whisper ({lang_code or 'auto'})...")
        kwargs = dict(
            audio=audio_np,
            language=lang_code,
            task="transcribe",
            beam_size=2,  # Fast CPU inference (was 5)
            best_of=1,
            temperature=0.0,
            vad_filter=True,
        )
        if hinglish_prompt:
            kwargs['initial_prompt'] = (
                "Acha, toh main abhi Hindi aur English mix karke bol raha hoon, "
                "please isse Roman script mein likho."
            )
        segments, info = model.transcribe(**kwargs)

        text = " ".join([segment.text.strip() for segment in segments]).strip()
        return self._filter_whisper_hallucinations(text)

    def _transcribe_whisper(self, raw_data, language):
        text = self._transcribe_whisper_raw(raw_data, language)

        if text:
            print(f"[Audio] Whisper Result: {text}")
            self.log_history(text, language)
        else:
            print("[Audio] No speech detected by Whisper.")
        return text

    # ------------------------------------------------------------------
    #  Whisper Hallucination Filtering
    # ------------------------------------------------------------------
    def _filter_whisper_hallucinations(self, text):
        """
        Cleans up common Whisper hallucinations and ensures Devanagari text
        is converted to Roman Hinglish using the transliteration logic.
        """
        if not text:
            return text
        has_devanagari = any('\u0900' <= c <= '\u097F' for c in text)
        has_arabic = any('\u0600' <= c <= '\u06FF' or '\u0750' <= c <= '\u077F' for c in text)

        if not has_devanagari and not has_arabic:
            # Already Roman — return as-is (preserves English words in Hinglish)
            return text

        if has_arabic:
            text = AudioEngine._strip_arabic_to_latin(text)

        if has_devanagari:
            text = self._transliterate_to_roman(text)
            text = text.lower().strip()

        return AudioEngine._fix_hinglish_spelling(text)

    @staticmethod
    def _strip_arabic_to_latin(text):
        mapping = {
            'ا': 'a', 'ب': 'b', 'پ': 'p', 'ت': 't', 'ٹ': 't', 'ث': 's',
            'ج': 'j', 'چ': 'ch', 'ح': 'h', 'خ': 'kh', 'د': 'd', 'ڈ': 'd',
            'ذ': 'z', 'ر': 'r', 'ڑ': 'r', 'ز': 'z', 'ژ': 'zh', 'س': 's',
            'ش': 'sh', 'ص': 's', 'ض': 'z', 'ط': 't', 'ظ': 'z', 'ع': 'a',
            'غ': 'gh', 'ف': 'f', 'ق': 'q', 'ک': 'k', 'گ': 'g', 'ل': 'l',
            'م': 'm', 'ن': 'n', 'ں': 'n', 'و': 'w', 'ہ': 'h', 'ھ': 'h',
            'ء': '', 'ی': 'y', 'ے': 'e', 'ئ': 'y', 'ؤ': 'w',
            'ً': 'an', 'ٌ': 'un', 'ٍ': 'in', 'َ': 'a', 'ُ': 'u', 'ِ': 'i',
            'ّ': '', 'ْ': '', 'ٰ': 'a',
            'آ': 'aa', 'إ': 'i', 'أ': 'a',
        }
        result = []
        for char in text:
            if '\u0600' <= char <= '\u06FF' or '\u0750' <= char <= '\u077F':
                result.append(mapping.get(char, ''))
            else:
                result.append(char)
        return ''.join(result)

    def _transcribe_google(self, raw_data, language, skip_history=False):
        processed_data = self._preprocess_audio(raw_data, self.rate, for_whisper=False)
        audio = sr.AudioData(processed_data, 16000, self.sample_width)

        print(f"[Audio] Transcribing with Google ({language})...")
        try:
            # CRITICAL: Add timeout to prevent indefinite freezes
            # Google API can hang on slow networks without timeout
            import threading
            result = [None]  # Use list to avoid nonlocal issues
            error = [None]
            
            def transcribe_with_timeout():
                try:
                    result[0] = self.recognizer.recognize_google(audio, language=language, show_all=False)
                except sr.UnknownValueError:
                    error[0] = "unknown"
                except sr.RequestError as e:
                    error[0] = str(e)
                except Exception as e:
                    error[0] = f"timeout: {e}"
            
            thread = threading.Thread(target=transcribe_with_timeout)
            thread.daemon = True
            thread.start()
            thread.join(timeout=30.0)  # 30-second timeout
            
            if thread.is_alive():
                print("[Audio] Google transcription timeout (30s) - network too slow")
                return ""
            
            if error[0]:
                if error[0] == "unknown":
                    print("[Audio] Google could not understand audio.")
                else:
                    print(f"[Audio] Google request failed: {error[0]}")
                return ""
            
            text = result[0] if result[0] else ""
        except Exception as e:
            print(f"[Audio] Google transcription error: {e}")
            return ""

        if text:
            print(f"[Audio] Raw Google result: {text}")
            logged_lang = language
            if language == 'hi-IN':
                text = self._transliterate_to_roman(text)
                print(f"[Audio] Transliterated: {text}")
                logged_lang = 'xx-HI'
            text = self._post_process_transcription(text)
            if not skip_history:
                self.log_history(text, logged_lang)
        else:
            print("[Audio] No speech detected.")
        return text


    def log_history(self, text, lang):
        """Append a transcription entry to history.json atomically.

        Uses config.atomic_json_* under per-path RLock — safe for concurrent
        callers (GUI clear vs audio thread append).
        """
        entry = {
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "text": text,
            "lang": lang,
        }
        history_path = config._get_history_path()
        with config._lock_for(history_path):
            history = config.atomic_json_read(history_path, default=[])
            if not isinstance(history, list):
                history = []
            history.append(entry)
            if len(history) > config.MAX_HISTORY:
                history = history[-config.MAX_HISTORY:]
            if config.atomic_json_write(history_path, history):
                print(f"[Audio] History updated ({len(history)} entries)")

    def reload_whisper_model(self):
        self._whisper_model = None
        print("[Audio] Whisper model will be reloaded on next use.")

    def download_model_now(self, progress_cb=None):
        """Download Whisper model. progress_cb(mb_downloaded, status_text) is
        called from a poller thread roughly every 500ms during download.
        """
        model_size = config.WHISPER_MODEL
        print(f"[Audio] Downloading Whisper model '{model_size}'...")

        # Start a disk-poller that watches the HF cache dir size growing
        stop = threading.Event()
        poller = None
        if progress_cb:
            poller = threading.Thread(
                target=self._poll_download_progress,
                args=(self._hf_cache_root(), stop, progress_cb, f"Whisper {model_size}"),
                daemon=True,
            )
            poller.start()

        try:
            from faster_whisper import WhisperModel
            self._whisper_model = WhisperModel(
                model_size,
                device=self._device,
                compute_type=self._compute_type,
            )
            print(f"[Audio] Whisper model '{model_size}' downloaded and loaded.")
            return True
        except Exception as e:
            print(f"[Audio] Failed to download: {e}")
            self._whisper_model = None
            return False
        finally:
            stop.set()
            if poller:
                poller.join(timeout=2.0)

    @staticmethod
    def _hf_cache_root():
        """Root of the HuggingFace Hub cache (where snapshots land)."""
        return os.path.join(os.path.expanduser("~"), ".cache", "huggingface", "hub")

    @staticmethod
    def _dir_size_mb(path):
        """Total size of a directory tree in MB. Safe for missing dirs."""
        if not os.path.isdir(path):
            return 0.0
        total = 0
        for root, _, files in os.walk(path):
            for name in files:
                try:
                    total += os.path.getsize(os.path.join(root, name))
                except OSError:
                    pass
        return total / (1024 * 1024)

    @staticmethod
    def _poll_download_progress(watch_dir, stop_event, callback, label):
        """Periodically report download progress by polling directory size."""
        baseline = AudioEngine._dir_size_mb(watch_dir)
        while not stop_event.is_set():
            current = AudioEngine._dir_size_mb(watch_dir)
            delta = current - baseline
            if delta > 0:
                callback(delta, f"{label}: {delta:.1f} MB downloaded...")
            stop_event.wait(0.5)

    def kill_stream(self):
        """Gracefully shut down audio stream with verification and retry."""
        self._stop_engine_event.set()
        try:
            # Wait for background listener to stop
            if self._bg_listener_thread:
                self._bg_listener_thread.join(timeout=2.0)
                if self._bg_listener_thread.is_alive():
                    print("[Audio] Background listener did not stop cleanly")

            # Stop and close stream with retry logic
            max_retries = 3
            for attempt in range(max_retries):
                if not hasattr(self, 'stream') or self.stream is None:
                    break
                try:
                    if self.stream.is_active():
                        try:
                            self.stream.stop_stream()
                        except Exception:
                            pass
                    self.stream.close()
                    self.stream = None
                    print(f"[Audio] Stream closed successfully (attempt {attempt + 1})")
                    break
                except AttributeError:
                    # stream doesn't exist yet
                    break
                except Exception as e:
                    print(f"[Audio] Error closing stream (attempt {attempt + 1}/{max_retries}): {e}")
                    if attempt == max_retries - 1:
                        print("[Audio] Failed to close stream after max retries, forcing None")
                        self.stream = None
                    else:
                        time.sleep(0.1)

            # Terminate PyAudio instance with retry
            for attempt in range(max_retries):
                if not hasattr(self, 'p') or self.p is None:
                    break
                try:
                    self.p.terminate()
                    self.p = None
                    print(f"[Audio] PyAudio terminated successfully (attempt {attempt + 1})")
                    break
                except AttributeError:
                    # p doesn't exist yet
                    break
                except Exception as e:
                    print(f"[Audio] Error terminating PyAudio (attempt {attempt + 1}/{max_retries}): {e}")
                    if attempt == max_retries - 1:
                        print("[Audio] Failed to terminate PyAudio after max retries")
                        self.p = None
                    else:
                        time.sleep(0.1)

            print("[Audio] Stream shutdown complete")
        except Exception as e:
            print(f"[Audio] Unexpected error in kill_stream: {e}")

    def reconnect_mic(self):
        """Surgically re-initializes audio capture without restarting the app."""
        print("[Audio] Attempting mic reconnection...")
        try:
            self.kill_stream()
            self._stop_engine_event.clear()
            self._init_audio()
            self._start_bg_listener()
            return True
        except Exception as e:
            print(f"[Audio] Reconnection failed: {e}")
            return False

    def check_health(self):
        """Health check for the background listener."""
        if self._bg_listener_thread and not self._bg_listener_thread.is_alive():
            print("[Audio] Background listener died. Restarting...")
            self._start_bg_listener()
            return False
        return True


    # Pre-clean map for Devanagari marks ITRANS doesn't render cleanly.
    # Applied before transliterate() to prevent raw Devanagari leakage
    # (e.g. "सॉन्ड" -> "saॉnda" without preclean).
    _DEVA_PRECLEAN = {
        'ॅ': 'ा',  # chandra-E sign  -> aa-matra
        'ॉ': 'ो',  # chandra-O sign  -> o-matra
        'ॲ': 'a',       # candra-A letter -> latin 'a'
        'ँ': 'n',       # chandrabindu    -> n
        'ं': 'n',       # anusvara        -> n
        '़': '',        # nukta — drop, ITRANS handles base char
    }
    _DEVA_PRECLEAN_TABLE = str.maketrans(_DEVA_PRECLEAN)

    @staticmethod
    def _transliterate_to_roman(text):
        """Devanagari (Hindi script) -> natural Hinglish Roman via ITRANS.

        Pre-cleans Devanagari marks (chandra vowels, anusvara, nukta) that
        ITRANS doesn't handle, so they don't leak into the Roman output.
        Strips ITRANS dot-prefixed retroflex/nasal markers.
        """
        if not any('\u0900' <= char <= '\u097f' for char in text):
            return text

        try:
            # Pre-clean Devanagari marks ITRANS doesn't handle
            pre = text.translate(AudioEngine._DEVA_PRECLEAN_TABLE)
            res = transliterate(pre, sanscript.DEVANAGARI, sanscript.ITRANS)
            res = res.lower()
            # Strip ITRANS dot-prefixed markers (.d, .n, .t etc.)
            res = re.sub(r'\.([a-zA-Z]+)', r'\1', res)
            # Strip svarita (^), tilde (~), grave (`)
            res = re.sub(r'[\^~`]', '', res)
            # Last-ditch: drop any Devanagari that survived
            res = re.sub(r'[\u0900-\u097f]', '', res)
            return res
        except Exception as e:
            print(f"[Audio] Transliteration error: {e}")
            return text

def is_whisper_model_downloaded(model_size):
    """Check if a given Whisper model is already cached locally."""
    try:
        from faster_whisper.utils import download_model
        download_model(model_size, local_files_only=True)
        return True
    except Exception:
        return False


def is_zero_stt_downloaded():
    """Check if zero-stt-hinglish model is already converted locally."""
    return os.path.exists(os.path.join(config.ZERO_STT_MODEL_PATH, "model.bin"))
