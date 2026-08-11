"""Multilingual lexicons for question detection and speaker cues.

All entries exist in romanized form and, where Whisper commonly emits it,
Devanagari, because Whisper output script varies run to run on code-mixed
Marathi and Hindi speech. Matching is done on lowercased text with word
boundaries, see app.pipeline.metrics.

NEGATIVE_FILTERS lists phrases that contain a question word but are used as
verbal punctuation in this register of classroom speech. A bare "theek hai"
or "barobar" at the end of an explanation is a filler, not a question, and
must not inflate the question count. A phrase is only filtered when the whole
segment text is (close to) just that phrase; "barobar ka?" with rising intent
words still counts via QUESTION_PHRASES.
"""

# Question words and phrases keyed by language code.
QUESTION_WORDS: dict[str, list[str]] = {
    "mr": [
        # romanized
        "kay", "kon", "ka", "kasa", "kashi", "kase", "kevha", "kuthe", "kiti",
        "samajle", "samajla ka", "barobar ka", "sang", "sanga", "kon sangel",
        # devanagari
        "काय", "कोण", "का", "कसा", "कशी", "कसे", "केव्हा", "कुठे", "किती",
        "समजले", "समजलं का", "बरोबर का", "सांग", "सांगा", "कोण सांगेल",
    ],
    "hi": [
        "kya", "kaun", "kyun", "kyu", "kaise", "kab", "kahan", "kitna",
        "samjhe", "samajh aaya", "batao", "koi bataye",
        "क्या", "कौन", "क्यों", "क्यूं", "कैसे", "कब", "कहां", "कहाँ", "कितना",
        "समझे", "समझ आया", "बताओ", "कोई बताए",
    ],
    "en": [
        "what", "why", "how", "who", "when", "where", "which",
        "can anyone", "does everyone", "is that clear",
    ],
}

# Phrases that read as fillers when they make up (almost) the entire segment.
NEGATIVE_FILTERS: list[str] = [
    "theek hai", "thik hai", "thik aahe", "theek aahe", "ठीक है", "ठीक आहे",
    "barobar", "बरोबर",
    "ho ka", "हो का",
    "haan", "हां", "हाँ", "ha",
    "accha", "acha", "अच्छा",
    "chala", "chalo", "चला", "चलो",
    "ok", "okay",
]

# Teacher instructional cues. Weighted use in speaker label correction: these
# words are near-exclusive to the teacher in a classroom recording.
TEACHER_CUES: dict[str, list[str]] = {
    "mr": [
        "bagha", "aika", "liha", "ughda", "shant",
        "बघा", "ऐका", "लिहा", "उघडा", "शांत",
    ],
    "hi": [
        "dekho", "suno", "likho", "chalo", "kholo", "chup",
        "देखो", "सुनो", "लिखो", "चलो", "खोलो", "चुप",
    ],
    "en": [
        "open your books", "quiet please", "listen", "write this down",
        "sit down", "stand up", "repeat after me", "very good",
    ],
}

# Roll call patterns: a teacher reading names off a register produces short
# name-plus-number segments; the words below anchor that pattern.
ROLL_CALL_CUES: list[str] = [
    "hajar", "hajir", "hazir", "present", "absent",
    "हजर", "हाजिर", "गैरहजर",
]

# Student reply cues: near-exclusive to students answering.
STUDENT_CUES: dict[str, list[str]] = {
    "mr": [
        "hoy", "nahi", "ho madam", "ho sir",
        "होय", "नाही", "हो मॅडम", "हो सर",
    ],
    "hi": [
        "haan ji", "ji madam", "ji sir", "nahin",
        "हां जी", "जी मैडम", "जी सर", "नहीं",
    ],
    "en": [
        "yes ma'am", "yes maam", "yes madam", "yes sir", "no ma'am", "no sir",
        "good morning ma'am", "good morning sir",
    ],
}


def all_question_words() -> list[str]:
    """Flatten QUESTION_WORDS across languages, longest phrase first so that
    multi-word phrases match before their single-word prefixes."""
    flat = [w for words in QUESTION_WORDS.values() for w in words]
    return sorted(set(flat), key=len, reverse=True)


def all_teacher_cues() -> list[str]:
    flat = [w for words in TEACHER_CUES.values() for w in words]
    flat.extend(ROLL_CALL_CUES)
    return sorted(set(flat), key=len, reverse=True)


def all_student_cues() -> list[str]:
    flat = [w for words in STUDENT_CUES.values() for w in words]
    return sorted(set(flat), key=len, reverse=True)
