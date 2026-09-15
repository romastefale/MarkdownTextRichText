"""User-scoped accent palette shared by the bot and Mini App."""
import unicodedata

DEFAULT_ACCENT = "laranja"
ACCENTS = {
    "vermelho": {"label": "Vermelho", "color": "#e53935", "text": "#000000"},
    "laranja": {"label": "Laranja", "color": "#ff7a00", "text": "#000000"},
    "amarelo": {"label": "Amarelo", "color": "#fdd835", "text": "#000000"},
    "verde": {"label": "Verde", "color": "#43a047", "text": "#000000"},
    "azul": {"label": "Azul", "color": "#1976d2", "text": "#ffffff"},
    "anil": {"label": "Anil", "color": "#3949ab", "text": "#ffffff"},
    "violeta": {"label": "Violeta", "color": "#8e24aa", "text": "#ffffff"},
}

def normalize_accent(value):
    if not isinstance(value, str):
        raise ValueError("Escolha uma das sete cores do arco-íris.")
    key = ''.join(c for c in unicodedata.normalize('NFD', value.strip().lower()) if not unicodedata.combining(c))
    if key not in ACCENTS:
        raise ValueError("Escolha: " + ", ".join(ACCENTS) + ".")
    return key

def appearance(preferences):
    key = preferences.get("accent", DEFAULT_ACCENT)
    if not isinstance(key, str) or key not in ACCENTS:
        key = DEFAULT_ACCENT
    return {"accent": key, "palette": ACCENTS}
