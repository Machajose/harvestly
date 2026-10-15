"""prompts.py - the words and buttons for the two follow-up questions Harvestly asks a farmer:

  1. FEEDBACK: after a warning, "was this useful?"  (answers are saved on the alert row)
  2. RE-CHECK: a few days later, "is your maize dry now?"  (updates the batch and re-scores it)

Both bot.py (which receives the button taps) and scheduler.py (which sends the messages)
use this file, so the wording and the button codes are defined once.
A button is a (label, callback_data) pair. callback_data looks like  fb:<batch id>:<code>
or  mc:<batch id>:<code>  (Telegram allows up to 64 bytes).
"""

# ---- 1. feedback on a warning ---------------------------------------------------------------
FEEDBACK_ASK = {
    "en": "Was this warning useful?",
    "sw": "Onyo hili lilikusaidia?",
}
FEEDBACK_BUTTONS = {
    "en": [("Yes, useful", "h"), ("My grain was already spoiling", "s"), ("Not needed", "n")],
    "sw": [("Ndiyo, lilisaidia", "h"), ("Nafaka ilikuwa tayari inaharibika", "s"),
           ("Halikuhitajika", "n")],
}
FEEDBACK_VALUE = {"h": "useful", "s": "already_spoiling", "n": "not_needed"}
FEEDBACK_THANKS = {
    "en": "Thank you. Your answer helps us improve the warnings.",
    "sw": "Asante. Jibu lako linatusaidia kuboresha maonyo.",
}

# ---- 2. moisture re-check ---------------------------------------------------------------------
RECHECK_ASK = {
    "en": ("Time to re-check your maize (harvested {harvest}).\n"
           "Take a kernel and bite it. What happens now?"),
    "sw": ("Wakati wa kukagua tena mahindi yako (yaliyovunwa {harvest}).\n"
           "Chukua punje moja na uiume. Inakuwaje sasa?"),
}
RECHECK_BUTTONS = {
    "en": [("Cracks when bitten (dry)", "d"), ("Dents, does not crack (unsure)", "u"),
           ("Soft or wet (damp)", "w")],
    "sw": [("Inapasuka ikiumwa (kavu)", "d"), ("Inabonyea, haipasuki (sina uhakika)", "u"),
           ("Laini au nyevu (unyevu)", "w")],
}
RECHECK_VALUE = {"d": "dry", "u": "unsure", "w": "damp"}
RECHECK_THANKS = {
    "en": "Thank you. Here is your updated check:",
    "sw": "Asante. Hii ndiyo ukaguzi wako mpya:",
}


def _lang(lang):
    return lang if lang in FEEDBACK_ASK else "en"


def feedback_rows(batch_id, lang):
    """Buttons as rows of (label, callback_data), one button per row."""
    return [[(label, f"fb:{batch_id}:{code}")] for label, code in FEEDBACK_BUTTONS[_lang(lang)]]


def recheck_rows(batch_id, lang):
    return [[(label, f"mc:{batch_id}:{code}")] for label, code in RECHECK_BUTTONS[_lang(lang)]]


def recheck_text(lang, harvest):
    return RECHECK_ASK[_lang(lang)].format(harvest=harvest or "?")
