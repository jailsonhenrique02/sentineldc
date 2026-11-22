"""Validação de entrada/saída (Pydantic v2)."""
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict


class _ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class AtivoOut(_ORM):
    id: int
    nome: str
    tipo: str
    rack_id: int
    posicao_u: int
    altura_u: int
    criticidade: int
    status: str
    bateria_pct: Optional[float] = None
    em_bateria: bool = False
    motivo_autocura: Optional[str] = None


class RackOut(_ORM):
    id: int
    nome: str
    sala: str
    posicao_x: int
    posicao_y: int
    capacidade_u: int
    temperatura: float
    status_fisico: str
    violacao: bool = False
    ativos: list[AtivoOut] = []


class ConexaoOut(_ORM):
    id: int
    origem_id: int
    destino_id: int
    tipo: str
    descricao: Optional[str] = None


class IntervencaoCreate(BaseModel):
    descricao: str = ""
    rack_id: int
    ativos_ids: list[int]
    responsavel: str = "noc"


class EncerrarIn(BaseModel):
    forcar: bool = False


class ValidacaoOut(BaseModel):
    aprovada: bool
    erros: list[str]
    avisos: list[str]
    raio_impacto: list[int]
    impacto_detalhe: list[dict]


class IntervencaoOut(_ORM):
    id: int
    codigo: Optional[str] = None
    descricao: str
    rack_id: int
    responsavel: str
    ativos_escopo: list[int]
    raio_impacto: list[int]
    status: str
    validacao: Optional[dict] = None
    violacoes: int
    criado_em: Optional[datetime] = None
    iniciado_em: Optional[datetime] = None
    encerrado_em: Optional[datetime] = None


class LogOut(_ORM):
    id: int
    ts: datetime
    nivel: str
    origem: str
    mensagem: str
    rack_id: Optional[int] = None


class TelemetriaEvento(BaseModel):
    tipo: Literal["ups", "temperatura", "ativo_status"]
    ativo_id: Optional[int] = None
    rack_id: Optional[int] = None
    valor: Optional[float] = None  # temperatura em °C
    bateria_pct: Optional[float] = None
    em_bateria: Optional[bool] = None
    status: Optional[Literal["online", "offline"]] = None


class WebhookAlerta(BaseModel):
    """Formato mínimo para webhook (ex.: ação de mídia 'Webhook' do Zabbix)."""
    host: str
    trigger: str = ""
    status: str = "PROBLEM"  # PROBLEM | OK
    severity: str = "warning"
