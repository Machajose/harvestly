"""explain.py - OPTIONAL: let Oracle Generative AI reword an alert in simpler language.

The rules in risk.py always make the DECISION and choose the ACTION. The AI never decides anything.
It may only rewrite the explanation and the advice in plainer words. After it answers, this file
checks the answer and silently falls back to the normal rule-based text if anything looks wrong:
  - the feature is switched off, the oci package is missing, or the call fails or is slow,
  - the AI used a number that was not in the original text,
  - the answer is empty or far longer than the original.

It is OFF by default. To turn it on, see the "Generative AI wording" section of README.md.
Settings (in .env):
  GENAI_ENABLED=true
  GENAI_COMPARTMENT_ID=ocid1.compartment...      (your compartment OCID)
  GENAI_MODEL_ID=...                             (a chat model available to you in the Console)
  GENAI_ENDPOINT=https://inference.generativeai.<region>.oci.oraclecloud.com
  OCI_CONFIG_FILE=~/.oci/config                  (API key settings, created in the Console)
  OCI_CONFIG_PROFILE=DEFAULT
"""
import logging
import os
import re

from dotenv import load_dotenv

import risk

load_dotenv()
log = logging.getLogger("harvestly-explain")

LANGUAGE_NAME = {"en": "simple English", "sw": "simple Kiswahili"}
AI_NOTE = {
    "en": "The wording was simplified with AI.",
    "sw": "Maneno yamerahisishwa kwa msaada wa AI.",
}

PROMPT = (
    "You help Kenyan maize farmers. Rewrite the text below in {language}, for a farmer who reads "
    "little. Use short, friendly sentences (at most 5). Keep EVERY fact, number and instruction. "
    "Do not add advice, numbers, brands or medical claims. Do not use markdown, lists or emojis. "
    "Reply with the rewritten text only.\n\nTEXT:\n{text}"
)


def enabled():
    return os.getenv("GENAI_ENABLED", "").strip().lower() in ("1", "true", "yes", "on")


def _numbers(text):
    return set(re.findall(r"\d+", text or ""))


def _ask_model(prompt):
    """Call Oracle Generative AI chat and return the reply text. Raises on any problem."""
    import oci  # imported here so the rest of the project works without the oci package

    config = oci.config.from_file(
        os.path.expanduser(os.getenv("OCI_CONFIG_FILE", "~/.oci/config")),
        os.getenv("OCI_CONFIG_PROFILE", "DEFAULT"))
    client = oci.generative_ai_inference.GenerativeAiInferenceClient(
        config=config,
        service_endpoint=os.getenv("GENAI_ENDPOINT", "").strip(),
        retry_strategy=oci.retry.NoneRetryStrategy(),
        timeout=(5, 20))
    models = oci.generative_ai_inference.models

    content = models.TextContent()
    content.text = prompt
    message = models.Message()
    message.role = "USER"
    message.content = [content]

    request = models.GenericChatRequest()
    request.api_format = models.BaseChatRequest.API_FORMAT_GENERIC
    request.messages = [message]
    request.max_tokens = 400
    request.temperature = 0.2

    details = models.ChatDetails()
    details.compartment_id = os.getenv("GENAI_COMPARTMENT_ID", "").strip()
    details.serving_mode = models.OnDemandServingMode(model_id=os.getenv("GENAI_MODEL_ID", "").strip())
    details.chat_request = request

    response = client.chat(details)
    return response.data.chat_response.choices[0].message.content[0].text.strip()


def simplify(text, lang):
    """Return (reworded text, True) if the AI produced a safe rewrite, else (text, False)."""
    if not enabled() or not text:
        return text, False
    try:
        answer = _ask_model(PROMPT.format(language=LANGUAGE_NAME.get(lang, LANGUAGE_NAME["en"]), text=text))
    except Exception as exc:  # noqa: BLE001 - any failure means "use the normal text"
        log.warning("Generative AI not used (%s: %s)", exc.__class__.__name__, str(exc)[:150])
        return text, False
    if not answer or len(answer) > max(300, int(len(text) * 1.5)):
        log.warning("Generative AI answer rejected (empty or too long)")
        return text, False
    if not _numbers(answer) <= _numbers(text):
        log.warning("Generative AI answer rejected (it used a number that was not in the original)")
        return text, False
    return answer, True


def final_message(assessment, lang, checked_at=""):
    """The alert text to send. Same as risk.build_message, with the explanation optionally reworded."""
    lang = lang if lang in risk.LABELS else "en"
    label, why, advice, source = risk.message_parts(assessment, lang, checked_at)
    body, changed = simplify(f"{why}.\n\n{advice}", lang)
    note = f"\n{AI_NOTE[lang]}" if changed else ""
    return f"{label}\n{body}\n\n{source}{note}"
