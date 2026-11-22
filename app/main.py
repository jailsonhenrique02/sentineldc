"""SentinelDC — ponto de entrada FastAPI."""
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import config
from .api import routes_interventions, routes_racks, routes_telemetry
from .database import Base, SessionLocal, engine
from .models import Ativo, PontoConexao, Rack, registrar_log
from .services import self_healing, watchdog

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


def seed_demo(db) -> None:
    """Data center de demonstração: 3 racks, 2 UPS, 2 core, 2 acesso, servidores com e sem redundância."""
    racks = {}
    for nome, x in [("RACK-A01", 0), ("RACK-A02", 1), ("RACK-B01", 2)]:
        racks[nome] = Rack(nome=nome, sala="Sala 01", posicao_x=x, posicao_y=0, capacidade_u=24, temperatura=22.0)
        db.add(racks[nome])
    db.flush()

    spec = [  # nome, tipo, rack, U inicial, altura, criticidade
        ("SRV-DB-01", "server", "RACK-A01", 2, 2, 1), ("SRV-DB-02", "server", "RACK-A01", 4, 2, 1),
        ("SRV-APP-01", "server", "RACK-A01", 7, 1, 2), ("SRV-APP-02", "server", "RACK-A01", 8, 1, 2),
        ("SRV-BKP-01", "server", "RACK-A01", 11, 2, 3), ("SW-ACC-A", "switch", "RACK-A01", 22, 1, 1),
        ("SRV-WEB-01", "server", "RACK-A02", 2, 1, 2), ("SRV-WEB-02", "server", "RACK-A02", 3, 1, 2),
        ("SRV-DEV-01", "server", "RACK-A02", 6, 2, 3), ("SRV-DEV-02", "server", "RACK-A02", 8, 2, 3),
        ("STG-01", "storage", "RACK-A02", 11, 4, 1), ("SW-ACC-B", "switch", "RACK-A02", 22, 1, 1),
        ("UPS-A", "ups", "RACK-B01", 1, 3, 1), ("UPS-B", "ups", "RACK-B01", 4, 3, 1),
        ("SW-CORE-1", "switch", "RACK-B01", 18, 1, 1), ("SW-CORE-2", "switch", "RACK-B01", 19, 1, 1),
    ]
    at = {}
    for nome, tipo, rack, u, h, crit in spec:
        at[nome] = Ativo(nome=nome, tipo=tipo, rack_id=racks[rack].id, posicao_u=u, altura_u=h,
                         criticidade=crit, bateria_pct=100.0 if tipo == "ups" else None)
        db.add(at[nome])
    db.flush()

    def liga(origem, destinos, tipo):
        for d in destinos:
            db.add(PontoConexao(origem_id=at[origem].id, destino_id=at[d].id, tipo=tipo, descricao=f"{origem} -> {d}"))

    comuns = ["SRV-DB-01", "SRV-DB-02", "STG-01", "SW-ACC-A", "SW-ACC-B", "SW-CORE-1", "SW-CORE-2"]
    liga("UPS-A", comuns + ["SRV-APP-01", "SRV-WEB-01", "SRV-BKP-01", "SRV-DEV-01"], "energia")
    liga("UPS-B", comuns + ["SRV-APP-02", "SRV-WEB-02", "SRV-DEV-02"], "energia")
    for core in ("SW-CORE-1", "SW-CORE-2"):
        liga(core, ["SW-ACC-A", "SW-ACC-B"], "rede")
    liga("SW-ACC-A", ["SRV-DB-01", "SRV-DB-02", "SRV-APP-01", "SRV-APP-02", "SRV-BKP-01"], "rede")
    liga("SW-ACC-B", ["SRV-WEB-01", "SRV-WEB-02", "SRV-DEV-01", "SRV-DEV-02", "STG-01"], "rede")
    registrar_log(db, "INFO", "sistema", "Ambiente de demonstração carregado.")
    db.commit()


def _tick() -> None:
    with SessionLocal() as db:
        watchdog.varredura(db)
        self_healing.avaliar(db)


async def _loop() -> None:
    while True:
        await asyncio.sleep(config.WATCHDOG_INTERVALO_S)
        try:
            await asyncio.to_thread(_tick)
        except Exception as exc:  # o vigia nunca pode morrer
            print(f"[sentineldc] falha na varredura: {exc}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(engine)
    if config.SEED_DEMO:
        with SessionLocal() as db:
            if db.query(Rack).first() is None:
                seed_demo(db)
    tarefa = asyncio.create_task(_loop())
    yield
    tarefa.cancel()


app = FastAPI(title="SentinelDC", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.include_router(routes_racks.router)
app.include_router(routes_interventions.router)
app.include_router(routes_telemetry.router)


@app.get("/api/saude", tags=["sistema"])
def saude():
    return {"status": "ok"}


@app.post("/api/demo/reset", tags=["sistema"])
def reset_demo():
    """Apaga tudo e recarrega o ambiente de demonstração."""
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    watchdog.limpar_estado()
    with SessionLocal() as db:
        seed_demo(db)
    return {"ok": True}


if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
