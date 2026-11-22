"""Autocura: corte seletivo de cargas por criticidade quando a UPS ou a temperatura saem do limite."""
from sqlalchemy.orm import Session

from .. import config
from ..models import Ativo, PontoConexao, Rack, registrar_log


def _desligar(db: Session, ativo: Ativo, motivo: str, msg: str) -> None:
    ativo.status = "desligado_autocura"
    ativo.motivo_autocura = motivo
    registrar_log(db, "CRITICO", "self_healing", msg, ativo.rack_id)


def _religar(db: Session, ativo: Ativo, msg: str) -> None:
    ativo.status = "online"
    ativo.motivo_autocura = None
    registrar_log(db, "INFO", "self_healing", msg, ativo.rack_id)


def _tem_fonte_alternativa(db: Session, ativo: Ativo, ups_id: int) -> bool:
    ids = [c.origem_id for c in db.query(PontoConexao).filter_by(destino_id=ativo.id, tipo="energia")
           if c.origem_id != ups_id]
    if not ids:
        return False
    return any(f.status == "online" and not f.em_bateria
               for f in db.query(Ativo).filter(Ativo.id.in_(ids)).all())


def avaliar(db: Session) -> int:
    """Aplica as regras e devolve quantas mudanças fez."""
    mudancas = 0
    ativos = db.query(Ativo).all()

    for ups in (a for a in ativos if a.tipo == "ups"):
        cargas_ids = {c.destino_id for c in db.query(PontoConexao).filter_by(origem_id=ups.id, tipo="energia")}
        cargas = [a for a in ativos if a.id in cargas_ids]
        nivel = ups.bateria_pct or 0
        if ups.em_bateria:
            criticidades = set()
            if nivel <= config.UPS_BATERIA_CORTE_NIVEL3:
                criticidades.add(3)
            if nivel <= config.UPS_BATERIA_CORTE_NIVEL2:
                criticidades.add(2)
            for c in cargas:
                if c.status != "online" or c.criticidade not in criticidades:
                    continue
                if _tem_fonte_alternativa(db, c, ups.id):
                    continue  # outra UPS saudável sustenta o ativo
                _desligar(db, c, f"ups:{ups.id}",
                          f"{ups.nome} em {nivel:.0f}%: {c.nome} (C{c.criticidade}) desligado para preservar cargas críticas.")
                mudancas += 1
        elif nivel >= config.UPS_BATERIA_RELIGAR:
            for c in cargas:
                if c.status == "desligado_autocura" and c.motivo_autocura == f"ups:{ups.id}":
                    _religar(db, c, f"Energia restabelecida em {ups.nome}: {c.nome} religado.")
                    mudancas += 1

    for rack in db.query(Rack).all():
        candidatos = [a for a in rack.ativos if a.tipo not in ("ups", "switch")]
        if rack.temperatura >= config.TEMP_CRITICA:
            for a in candidatos:
                limite = 3 if rack.temperatura < config.TEMP_CRITICA + 4 else 2
                if a.status == "online" and a.criticidade >= limite:
                    _desligar(db, a, "termico",
                              f"{rack.nome} a {rack.temperatura:.1f} °C: {a.nome} (C{a.criticidade}) desligado por proteção térmica.")
                    mudancas += 1
        elif rack.temperatura < config.TEMP_ALERTA:
            for a in candidatos:
                if a.status == "desligado_autocura" and a.motivo_autocura == "termico":
                    _religar(db, a, f"Temperatura normalizada em {rack.nome}: {a.nome} religado.")
                    mudancas += 1

    if mudancas:
        db.commit()
    return mudancas
