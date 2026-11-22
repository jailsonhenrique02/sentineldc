"""Tabelas: racks, ativos, pontos_conexao, intervencoes, logs."""
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from . import config
from .database import Base


def agora() -> datetime:
    return datetime.now(timezone.utc)


class Rack(Base):
    __tablename__ = "racks"
    id = Column(Integer, primary_key=True)
    nome = Column(String(40), unique=True, nullable=False)
    sala = Column(String(40), default="Sala 01")
    posicao_x = Column(Integer, default=0)
    posicao_y = Column(Integer, default=0)
    capacidade_u = Column(Integer, default=24)
    temperatura = Column(Float, default=22.0)
    ativos = relationship("Ativo", back_populates="rack", order_by="Ativo.posicao_u")

    @property
    def status_fisico(self) -> str:
        """ok | alerta | critico, a partir de temperatura, UPS e ativos fora do ar."""
        ups = [a for a in self.ativos if a.tipo == "ups"]
        if self.temperatura >= config.TEMP_CRITICA or any(
            u.em_bateria and (u.bateria_pct or 0) <= config.UPS_BATERIA_CORTE_NIVEL2 for u in ups
        ):
            return "critico"
        if (
            self.temperatura >= config.TEMP_ALERTA
            or any(u.em_bateria for u in ups)
            or any(a.status != "online" for a in self.ativos)
        ):
            return "alerta"
        return "ok"


class Ativo(Base):
    __tablename__ = "ativos"
    id = Column(Integer, primary_key=True)
    nome = Column(String(60), unique=True, nullable=False)
    tipo = Column(String(20), nullable=False)  # server | switch | storage | ups
    rack_id = Column(Integer, ForeignKey("racks.id"), nullable=False)
    posicao_u = Column(Integer, default=1)  # U inicial, contado de baixo para cima
    altura_u = Column(Integer, default=1)
    criticidade = Column(Integer, default=2)  # 1 = essencial ... 3 = descartável
    status = Column(String(24), default="online")  # online | offline | desligado_autocura
    bateria_pct = Column(Float, nullable=True)  # só UPS
    em_bateria = Column(Boolean, default=False)  # só UPS
    motivo_autocura = Column(String(30), nullable=True)  # "ups:<id>" | "termico"
    rack = relationship("Rack", back_populates="ativos")


class PontoConexao(Base):
    __tablename__ = "pontos_conexao"
    id = Column(Integer, primary_key=True)
    origem_id = Column(Integer, ForeignKey("ativos.id"), nullable=False)
    destino_id = Column(Integer, ForeignKey("ativos.id"), nullable=False)
    tipo = Column(String(10), nullable=False)  # energia | rede
    descricao = Column(String(80), nullable=True)


class Intervencao(Base):
    __tablename__ = "intervencoes"
    id = Column(Integer, primary_key=True)
    codigo = Column(String(12), unique=True)
    descricao = Column(Text, default="")
    rack_id = Column(Integer, ForeignKey("racks.id"), nullable=False)
    responsavel = Column(String(60), default="noc")
    ativos_escopo = Column(JSON, default=list)
    raio_impacto = Column(JSON, default=list)  # escopo + dependentes sem redundância
    status = Column(String(16), default="validada")  # rejeitada | validada | em_execucao | encerrada
    validacao = Column(JSON, nullable=True)
    violacoes = Column(Integer, default=0)
    criado_em = Column(DateTime(timezone=True), default=agora)
    iniciado_em = Column(DateTime(timezone=True), nullable=True)
    encerrado_em = Column(DateTime(timezone=True), nullable=True)


class Log(Base):
    __tablename__ = "logs"
    id = Column(Integer, primary_key=True)
    ts = Column(DateTime(timezone=True), default=agora, index=True)
    nivel = Column(String(10), default="INFO")  # INFO | ALERTA | CRITICO
    origem = Column(String(20), default="sistema")
    mensagem = Column(Text, nullable=False)
    rack_id = Column(Integer, ForeignKey("racks.id"), nullable=True)


def registrar_log(db, nivel: str, origem: str, mensagem: str, rack_id: int | None = None) -> None:
    db.add(Log(nivel=nivel, origem=origem, mensagem=mensagem, rack_id=rack_id))
