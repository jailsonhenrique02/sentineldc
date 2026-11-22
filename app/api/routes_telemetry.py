"""Entrada de eventos de sensores (simulador/agentes) e webhooks de alerta (Zabbix)."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import config, schemas
from ..database import get_db
from ..models import Ativo, Log, Rack, registrar_log
from ..services import self_healing, watchdog

router = APIRouter(prefix="/api/telemetria", tags=["telemetria"])


def _nivel_temp(t: float) -> str:
    if t >= config.TEMP_CRITICA:
        return "critico"
    return "alerta" if t >= config.TEMP_ALERTA else "ok"


def _reagir(db: Session) -> None:
    watchdog.varredura(db)
    self_healing.avaliar(db)


@router.post("/evento")
def receber_evento(ev: schemas.TelemetriaEvento, db: Session = Depends(get_db)):
    if ev.tipo == "temperatura":
        rack = db.get(Rack, ev.rack_id) if ev.rack_id else None
        if rack is None or ev.valor is None:
            raise HTTPException(422, "Evento de temperatura exige rack_id e valor.")
        antes, rack.temperatura = _nivel_temp(rack.temperatura), ev.valor
        depois = _nivel_temp(ev.valor)
        if antes != depois:
            nivel = {"ok": "INFO", "alerta": "ALERTA", "critico": "CRITICO"}[depois]
            registrar_log(db, nivel, "telemetria", f"{rack.nome}: temperatura {ev.valor:.1f} °C ({depois}).", rack.id)

    elif ev.tipo == "ups":
        ups = db.get(Ativo, ev.ativo_id) if ev.ativo_id else None
        if ups is None or ups.tipo != "ups":
            raise HTTPException(422, "Evento de UPS exige ativo_id de uma UPS.")
        antes = ups.em_bateria
        if ev.bateria_pct is not None:
            ups.bateria_pct = max(0.0, min(100.0, ev.bateria_pct))
        if ev.em_bateria is not None:
            ups.em_bateria = ev.em_bateria
        if antes != ups.em_bateria:
            if ups.em_bateria:
                registrar_log(db, "ALERTA", "telemetria", f"{ups.nome} perdeu a rede e passou a operar em bateria.", ups.rack_id)
            else:
                registrar_log(db, "INFO", "telemetria", f"{ups.nome} voltou a operar na rede.", ups.rack_id)

    else:  # ativo_status
        ativo = db.get(Ativo, ev.ativo_id) if ev.ativo_id else None
        if ativo is None or ev.status is None:
            raise HTTPException(422, "Evento de status exige ativo_id e status.")
        if ativo.status != ev.status:
            ativo.status = ev.status
            ativo.motivo_autocura = None
            registrar_log(db, "INFO" if ev.status == "online" else "ALERTA", "telemetria",
                          f"{ativo.nome} está {ev.status}.", ativo.rack_id)
    db.commit()
    _reagir(db)
    return {"ok": True}


@router.post("/webhook")
def webhook_alerta(corpo: schemas.WebhookAlerta, db: Session = Depends(get_db)):
    """Aceita alertas externos. Gatilhos de indisponibilidade mudam o status do ativo."""
    ativo = db.query(Ativo).filter(Ativo.nome == corpo.host).first()
    if ativo is None:
        raise HTTPException(404, f"Host '{corpo.host}' não cadastrado como ativo.")
    indisponivel = any(p in corpo.trigger.lower() for p in ("down", "unreachable", "indispon", "offline"))
    problema = corpo.status.upper() == "PROBLEM"
    if indisponivel:
        ativo.status = "offline" if problema else "online"
        ativo.motivo_autocura = None
    registrar_log(db, "ALERTA" if problema else "INFO", "webhook",
                  f"{corpo.host}: {corpo.trigger or 'alerta'} ({corpo.status}, {corpo.severity}).", ativo.rack_id)
    db.commit()
    _reagir(db)
    return {"ok": True}


@router.get("/logs", response_model=list[schemas.LogOut])
def listar_logs(limite: int = 100, db: Session = Depends(get_db)):
    return db.query(Log).order_by(Log.id.desc()).limit(min(limite, 500)).all()
