"""Configurações e limites (thresholds) do SentinelDC. Tudo pode ser sobrescrito via .env."""
import os
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:  # python-dotenv é opcional
    pass


def _f(nome: str, padrao: float) -> float:
    return float(os.getenv(nome, padrao))


DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./sentineldc.db")

# Temperatura do rack (°C)
TEMP_ALERTA = _f("TEMP_ALERTA", 27)
TEMP_CRITICA = _f("TEMP_CRITICA", 32)

# Bateria da UPS (%)
UPS_BATERIA_ALERTA = _f("UPS_BATERIA_ALERTA", 50)
UPS_BATERIA_CORTE_NIVEL3 = _f("UPS_BATERIA_CORTE_NIVEL3", 30)  # corta criticidade 3
UPS_BATERIA_CORTE_NIVEL2 = _f("UPS_BATERIA_CORTE_NIVEL2", 15)  # corta criticidade 2
UPS_BATERIA_RELIGAR = _f("UPS_BATERIA_RELIGAR", 60)  # religa cargas após a rede voltar

# Intervalo da varredura em segundo plano (watchdog + autocura)
WATCHDOG_INTERVALO_S = _f("WATCHDOG_INTERVALO_S", 3)

SEED_DEMO = os.getenv("SEED_DEMO", "true").lower() == "true"
