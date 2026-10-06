"""Einstellungen. Hier kannst du alles Wichtige drehen."""

# Name des Spiels (steht im Fenstertitel und oben im Spiel)
TITLE = "ABSEITS"

# Ollama
MODEL = "qwen2.5:7b"
OLLAMA_URL = "http://localhost:11434/api/chat"
LLM_TIMEOUT = 40          # Sekunden, danach springt der Notbetrieb ein
LLM_RETRY_AFTER = 20      # so lange wartet das Spiel nach einem Fehler, bevor es Ollama wieder probiert
LLM_TEMPERATURE = 0.9

# Server (nur dein eigener Rechner)
HOST = "127.0.0.1"
PORT = 8765

# Spiel
MATCH_REAL_SECONDS = 360  # so lange dauern 90 Spielminuten in echt (ohne Unterbrechungen)
APPEAL_SECONDS = 8        # nach dem Pfiff: so lange kannst du auf den Schiri einreden
PROTEST_SECONDS = 4       # nach der Entscheidung: so lange kannst du noch protestieren
MIN_INCIDENT_GAP = 18     # mindestens so viele Sekunden zwischen zwei Pfiffen
START_MONEY = 300         # Bestechungsgeld in Euro
ACT_COOLDOWN = 2.0        # Sekunden zwischen deinen Aktionen
MAX_RULES = 10            # so viele Regeln stehen gleichzeitig im Regelbuch
HOME_NAME = "SV Dorfkante"
AWAY_NAME = "Real Betonmischer"
