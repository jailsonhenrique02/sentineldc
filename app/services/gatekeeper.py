"""Gatekeeper: valida fisicamente uma OS antes de ela começar e calcula o raio de impacto."""
from collections import defaultdict

from sqlalchemy.orm import Session

from .. import config
from ..models import Ativo, Intervencao, PontoConexao, Rack


def calcular_raio_impacto(db: Session, escopo: set[int]) -> set[int]:
    """Escopo + tudo que perde TODAS as fontes de um mesmo tipo (energia ou rede).

    Ativos com fonte redundante fora do escopo não entram no raio.
    """
    fontes: dict[int, dict[str, set[int]]] = defaultdict(lambda: defaultdict(set))
    for c in db.query(PontoConexao).all():
        fontes[c.destino_id][c.tipo].add(c.origem_id)

    afetados = set(escopo)
    mudou = True
    while mudou:
        mudou = False
        for destino, por_tipo in fontes.items():
            if destino in afetados:
                continue
            if any(origens <= afetados for origens in por_tipo.values()):
                afetados.add(destino)
                mudou = True
    return afetados


def validar_intervencao(
    db: Session, rack_id: int, ativos_ids: list[int], ignorar_os_id: int | None = None
) -> dict:
    erros: list[str] = []
    avisos: list[str] = []
    escopo = set(ativos_ids)

    rack = db.get(Rack, rack_id)
    if rack is None:
        return {"aprovada": False, "erros": [f"Rack {rack_id} não existe."], "avisos": [],
                "raio_impacto": [], "impacto_detalhe": []}
    if not escopo:
        erros.append("Escopo vazio: selecione ao menos um ativo.")

    ativos = db.query(Ativo).filter(Ativo.id.in_(escopo)).all() if escopo else []
    inexistentes = escopo - {a.id for a in ativos}
    if inexistentes:
        erros.append(f"Ativos inexistentes: {sorted(inexistentes)}.")

    # 1) Validação física cruzada: o ativo precisa estar mesmo no rack da OS.
    racks_nome = {r.id: r.nome for r in db.query(Rack).all()}
    for a in ativos:
        if a.rack_id != rack_id:
            erros.append(
                f"{a.nome} está no {racks_nome.get(a.rack_id)}, não no {rack.nome}. "
                "Corrija o rack da OS ou o escopo."
            )

    # 2) Estado do ambiente
    if rack.temperatura >= config.TEMP_CRITICA:
        erros.append(f"{rack.nome} em estado térmico crítico ({rack.temperatura:.1f} °C).")
    for u in db.query(Ativo).filter(Ativo.tipo == "ups", Ativo.em_bateria.is_(True)).all():
        erros.append(f"Janela bloqueada: {u.nome} operando em bateria ({(u.bateria_pct or 0):.0f}%).")
    for a in ativos:
        if a.status != "online":
            avisos.append(f"{a.nome} já está {a.status.replace('_', ' ')}.")

    # 3) Conflito com outras OS
    outras = db.query(Intervencao).filter(Intervencao.status.in_(["validada", "em_execucao"])).all()
    for o in outras:
        if ignorar_os_id and o.id == ignorar_os_id:
            continue
        comum = set(o.ativos_escopo or []) & escopo
        if o.status == "em_execucao" and comum:
            erros.append(f"Conflito com {o.codigo} (em execução) nos mesmos ativos.")
        elif o.status == "em_execucao" and o.rack_id == rack_id:
            avisos.append(f"{o.codigo} já está em execução neste rack.")
        elif comum:
            avisos.append(f"{o.codigo} (validada) tem ativos em comum.")

    # 4) Raio de impacto
    raio = calcular_raio_impacto(db, {a.id for a in ativos})
    mapa = {a.id: a for a in db.query(Ativo).filter(Ativo.id.in_(raio)).all()} if raio else {}
    detalhe = []
    for i in sorted(raio):
        a = mapa[i]
        no_escopo = i in escopo
        detalhe.append({"id": a.id, "nome": a.nome, "rack_id": a.rack_id, "criticidade": a.criticidade,
                        "motivo": "escopo da OS" if no_escopo else "perde toda alimentação/rede"})
        if no_escopo:
            if a.criticidade == 1:
                avisos.append(f"{a.nome} é crítico (C1): confirme a janela de manutenção.")
            continue
        if a.criticidade == 1:
            erros.append(f"Derrubaria {a.nome} (C1) fora do escopo. Planeje redundância antes.")
        if a.rack_id != rack_id:
            avisos.append(f"Impacto fora do rack: {a.nome} ({racks_nome.get(a.rack_id)}).")

    return {"aprovada": not erros, "erros": erros, "avisos": avisos,
            "raio_impacto": sorted(raio), "impacto_detalhe": detalhe}


def ativos_pendentes_no_encerramento(db: Session, os_: Intervencao) -> list[Ativo]:
    """Ativos do raio de impacto que ainda não voltaram a ficar online."""
    ids = os_.raio_impacto or []
    if not ids:
        return []
    return db.query(Ativo).filter(Ativo.id.in_(ids), Ativo.status != "online").all()
