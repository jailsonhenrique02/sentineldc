"""Watchdog: detecta queda de ativo FORA do raio de impacto de qualquer OS em execução."""
import threading

from sqlalchemy.orm import Session

from ..models import Ativo, Intervencao, registrar_log

_alertados: set[int] = set()
_lock = threading.Lock()


def limpar_estado() -> None:
    _alertados.clear()


def violacoes_ativas(db: Session) -> list[dict]:
    ativas = db.query(Intervencao).filter(Intervencao.status == "em_execucao").all()
    saida = []
    for a in db.query(Ativo).filter(Ativo.status == "offline").all():
        if any(a.id in (o.raio_impacto or []) for o in ativas):
            continue  # queda esperada: faz parte da OS
        relacionadas = [o for o in ativas if o.rack_id == a.rack_id] or ativas
        os_ = relacionadas[0] if relacionadas else None
        saida.append({
            "ativo_id": a.id, "nome": a.nome, "rack_id": a.rack_id,
            "tipo": "fora_do_escopo" if os_ else "sem_os",
            "os_id": os_.id if os_ else None, "os_codigo": os_.codigo if os_ else None,
        })
    return saida


def varredura(db: Session) -> list[dict]:
    """Registra no log cada violação nova (uma vez por ativo) e conta na OS."""
    with _lock:
        viol = violacoes_ativas(db)
        _alertados.intersection_update({v["ativo_id"] for v in viol})
        novos = [v for v in viol if v["ativo_id"] not in _alertados]
        for v in novos:
            _alertados.add(v["ativo_id"])
            if v["tipo"] == "fora_do_escopo":
                os_ = db.get(Intervencao, v["os_id"])
                os_.violacoes = (os_.violacoes or 0) + 1
                registrar_log(db, "CRITICO", "watchdog",
                              f"Queda de {v['nome']} FORA DO ESCOPO da {v['os_codigo']}. "
                              "Interromper a intervenção e verificar o rack.", v["rack_id"])
            else:
                registrar_log(db, "ALERTA", "watchdog",
                              f"Queda de {v['nome']} sem nenhuma OS de manutenção ativa.", v["rack_id"])
        if novos:
            db.commit()
        return novos
