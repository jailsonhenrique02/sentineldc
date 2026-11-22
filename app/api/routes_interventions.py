"""Ciclo de vida da OS: validar -> abrir -> iniciar -> encerrar."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import schemas
from ..database import get_db
from ..models import Intervencao, agora, registrar_log
from ..services import gatekeeper, watchdog

router = APIRouter(prefix="/api/intervencoes", tags=["intervencoes"])


@router.get("", response_model=list[schemas.IntervencaoOut])
def listar(db: Session = Depends(get_db)):
    return db.query(Intervencao).order_by(Intervencao.id.desc()).limit(50).all()


@router.post("/validar", response_model=schemas.ValidacaoOut)
def validar(dados: schemas.IntervencaoCreate, db: Session = Depends(get_db)):
    """Simulação: roda o gatekeeper sem criar nada (usada para pré-visualizar o raio de impacto)."""
    return gatekeeper.validar_intervencao(db, dados.rack_id, dados.ativos_ids)


@router.post("", response_model=schemas.IntervencaoOut)
def abrir(dados: schemas.IntervencaoCreate, db: Session = Depends(get_db)):
    v = gatekeeper.validar_intervencao(db, dados.rack_id, dados.ativos_ids)
    os_ = Intervencao(
        descricao=dados.descricao, rack_id=dados.rack_id, responsavel=dados.responsavel,
        ativos_escopo=dados.ativos_ids, raio_impacto=v["raio_impacto"],
        status="validada" if v["aprovada"] else "rejeitada",
        validacao={"erros": v["erros"], "avisos": v["avisos"]},
    )
    db.add(os_)
    db.flush()
    os_.codigo = f"OS-{os_.id:04d}"
    if v["aprovada"]:
        registrar_log(db, "INFO", "gatekeeper",
                      f"{os_.codigo} validada: {len(dados.ativos_ids)} ativo(s) no escopo, "
                      f"{len(v['raio_impacto'])} no raio de impacto.", dados.rack_id)
    else:
        registrar_log(db, "ALERTA", "gatekeeper", f"{os_.codigo} rejeitada: {v['erros'][0]}", dados.rack_id)
    db.commit()
    return os_


def _obter(db: Session, os_id: int) -> Intervencao:
    os_ = db.get(Intervencao, os_id)
    if os_ is None:
        raise HTTPException(404, "OS não encontrada.")
    return os_


@router.post("/{os_id}/iniciar", response_model=schemas.IntervencaoOut)
def iniciar(os_id: int, db: Session = Depends(get_db)):
    os_ = _obter(db, os_id)
    if os_.status != "validada":
        raise HTTPException(409, f"{os_.codigo} está '{os_.status}'; só OS validada pode iniciar.")
    # O ambiente pode ter mudado desde a abertura: valida de novo.
    v = gatekeeper.validar_intervencao(db, os_.rack_id, os_.ativos_escopo, ignorar_os_id=os_.id)
    if not v["aprovada"]:
        registrar_log(db, "ALERTA", "gatekeeper", f"{os_.codigo} bloqueada na partida: {v['erros'][0]}", os_.rack_id)
        db.commit()
        raise HTTPException(409, "Revalidação falhou: " + " ".join(v["erros"]))
    os_.status = "em_execucao"
    os_.iniciado_em = agora()
    os_.raio_impacto = v["raio_impacto"]
    registrar_log(db, "INFO", "gatekeeper", f"{os_.codigo} iniciada por {os_.responsavel}. Watchdog armado.", os_.rack_id)
    db.commit()
    return os_


@router.post("/{os_id}/encerrar", response_model=schemas.IntervencaoOut)
def encerrar(os_id: int, corpo: schemas.EncerrarIn = schemas.EncerrarIn(), db: Session = Depends(get_db)):
    os_ = _obter(db, os_id)
    if os_.status not in ("em_execucao", "validada"):
        raise HTTPException(409, f"{os_.codigo} já está '{os_.status}'.")
    pendentes = gatekeeper.ativos_pendentes_no_encerramento(db, os_) if os_.status == "em_execucao" else []
    if pendentes and not corpo.forcar:
        nomes = ", ".join(a.nome for a in pendentes)
        raise HTTPException(409, f"Ainda fora do ar: {nomes}. Restaure-os ou force o encerramento.")
    os_.status = "encerrada"
    os_.encerrado_em = agora()
    if pendentes:
        registrar_log(db, "ALERTA", "gatekeeper",
                      f"{os_.codigo} encerrada À FORÇA com ativos fora do ar: {', '.join(a.nome for a in pendentes)}.",
                      os_.rack_id)
    else:
        registrar_log(db, "INFO", "gatekeeper", f"{os_.codigo} encerrada com todos os ativos online.", os_.rack_id)
    db.commit()
    watchdog.varredura(db)  # o que continuar fora do ar agora deixa de estar coberto pela OS
    return os_
