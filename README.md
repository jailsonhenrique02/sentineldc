<img width="1522" height="723" alt="image" src="https://github.com/user-attachments/assets/d5dce554-1a5b-4c42-a464-dce3fdd0446c" />





# SentinelDC

Painel NOC para data center: valida a ordem de serviço (OS) contra a topologia física **antes** de a equipe mexer no rack, vigia quedas **durante** a OS e corta cargas de baixa criticidade quando a UPS ou a temperatura saem do limite.

## Como funciona

| Serviço | O que faz |
|---|---|
| `gatekeeper` | Valida a OS: os ativos estão mesmo no rack informado? Há UPS em bateria, rack quente ou OS conflitante? Calcula o **raio de impacto** (escopo + ativos que perdem *toda* a energia ou *toda* a rede; ativos com fonte redundante fora do escopo não entram). Bloqueia se a OS derrubar um ativo C1 fora do escopo. |
| `watchdog` | Com OS em execução, qualquer ativo offline que **não** esteja no raio de impacto gera alerta crítico, log e contagem de violações na OS. Sem OS ativa, a queda vira alerta de falha não planejada. |
| `self_healing` | UPS em bateria: ≤30% desliga ativos C3, ≤15% desliga C2 (C1 nunca é cortado; ativos com outra UPS saudável são preservados). Rack ≥32 °C desliga C3 (C2 a partir de 36 °C). Ao normalizar, religa só o que a própria autocura desligou. |

Criticidade: **C1** essencial, **C2** importante, **C3** descartável.

## Executar

**Docker (PostgreSQL):**
```bash
docker compose up -d --build
# opcional: Zabbix (fase 2)
docker compose --profile zabbix up -d
```
Painel em http://localhost:8000 · documentação da API em http://localhost:8000/docs

**Local (SQLite, sem Docker), Python 3.10+:**
```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Troque `POSTGRES_PASSWORD` no `.env` antes de usar fora de demonstração.

## Roteiro de demonstração

Na primeira subida o banco recebe 3 racks, 2 UPS, 2 switches core, 2 de acesso e 10 servidores/storage.

1. **Validação física:** no painel, clique em `SRV-WEB-01` (RACK-A02) e troque o "Rack da OS" para RACK-A01. O gatekeeper bloqueia.
2. **Raio de impacto:** selecione `SW-ACC-A`. Bloqueada: derrubaria `SRV-DB-01` e `SRV-DB-02` (C1). Selecione `SW-CORE-1`: aprovada, sem efeito colateral (core redundante).
3. **Watchdog:** abra e inicie uma OS para `SRV-BKP-01`; na aba Simulador, derrube `SRV-WEB-01`. Banner vermelho: queda fora do escopo. Derrubar o `SRV-BKP-01` não alerta.
4. **Autocura:** `python simulator/hardware_sim.py ups-drain --ups UPS-A` (ou use o simulador na tela). Em 30% caem `SRV-BKP-01` e `SRV-DEV-01`; em 15%, `SRV-APP-01` e `SRV-WEB-01`. Os C1 e os ativos com UPS-B ficam de pé. Com a energia de volta (≥60%) tudo é religado.
5. **Térmico:** `python simulator/hardware_sim.py thermal --rack RACK-A02`.

Outros cenários do simulador: `queda --ativo NOME`, `restaurar`, `caos`, `reset` (use `--api URL` se a API não estiver em localhost:8000).

## API

| Método e rota | Função |
|---|---|
| `GET /api/racks`, `/api/racks/{id}`, `/api/ativos`, `/api/conexoes` | Consulta de racks, ativos e topologia |
| `GET /api/racks/painel` | Snapshot completo usado pelo painel |
| `POST /api/intervencoes/validar` | Simula o gatekeeper sem criar nada |
| `POST /api/intervencoes` | Abre OS (fica `validada` ou `rejeitada`) |
| `POST /api/intervencoes/{id}/iniciar` | Revalida e arma o watchdog |
| `POST /api/intervencoes/{id}/encerrar` | Encerra; `{"forcar": true}` se ainda há ativo fora do ar |
| `POST /api/telemetria/evento` | Eventos `ups`, `temperatura`, `ativo_status` |
| `POST /api/telemetria/webhook` | Alertas externos, ex.: `{"host":"SRV-DB-01","trigger":"Host unreachable","status":"PROBLEM"}` |
| `GET /api/telemetria/logs` | Histórico de eventos |
| `POST /api/demo/reset` | Recarrega o ambiente de demonstração |

## Limites desta versão

- Sem autenticação; use apenas em rede interna.
- O painel usa polling de 2 s; WebSocket é uma evolução possível.
- A topologia vem do seed em `app/main.py`; ainda não há CRUD de racks e ativos.
- Não há migrações (Alembic): o esquema é criado com `create_all`.
- Zabbix sobe no compose, mas a integração é só pelo webhook acima.
