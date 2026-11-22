"""Consulta de racks, ativos, conexões e o snapshot completo usado pelo painel NOC."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import config, schemas
from ..database import get_db
from ..models import Ativo, Intervencao, Log, PontoConexao, Rack
from ..services import watchdog

router = APIRouter(prefix="/api", tags=["racks"])


@router.get("/racks", response_model=list[schemas.RackOut])
def listar_racks(db: Session = Depends(get_db)):
    return db.query(Rack).order_by(Rack.posicao_y, Rack.posicao_x).all()


@router.get("/racks/painel")
def painel(db: Session = Depends(get_db)):
    viol = watchdog.violacoes_ativas(db)
    racks_viol = {v["rack_id"] for v in viol}
    racks = []
    for r in db.query(Rack).order_by(Rack.posicao_y, Rack.posicao_x).all():
        item = schemas.RackOut.model_validate(r)
        item.violacao = r.id in racks_viol
        racks.append(item.model_dump(mode="json"))
    oss = db.query(Intervencao).order_by(Intervencao.id.desc()).limit(15).all()
    logs = db.query(Log).order_by(Log.id.desc()).limit(40).all()
    return {
        "ts": datetime.now(timezone.utc).isoformat(),
        "racks": racks,
        "intervencoes": [schemas.IntervencaoOut.model_validate(o).model_dump(mode="json") for o in oss],
        "logs": [schemas.LogOut.model_validate(l).model_dump(mode="json") for l in logs],
        "violacoes": viol,
        "limites": {
            "temp_alerta": config.TEMP_ALERTA, "temp_critica": config.TEMP_CRITICA,
            "bateria_alerta": config.UPS_BATERIA_ALERTA,
            "corte3": config.UPS_BATERIA_CORTE_NIVEL3, "corte2": config.UPS_BATERIA_CORTE_NIVEL2,
            "religar": config.UPS_BATERIA_RELIGAR,
        },
    }


@router.get("/racks/{rack_id}", response_model=schemas.RackOut)
def obter_rack(rack_id: int, db: Session = Depends(get_db)):
    rack = db.get(Rack, rack_id)
    if rack is None:
        raise HTTPException(404, "Rack não encontrado.")
    return rack


@router.get("/ativos", response_model=list[schemas.AtivoOut])
def listar_ativos(db: Session = Depends(get_db)):
    return db.query(Ativo).order_by(Ativo.rack_id, Ativo.posicao_u).all()


@router.get("/conexoes", response_model=list[schemas.ConexaoOut])
def listar_conexoes(db: Session = Depends(get_db)):
    return db.query(PontoConexao).all()
