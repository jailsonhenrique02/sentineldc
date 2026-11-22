#!/usr/bin/env python3
"""Simulador de hardware do SentinelDC (independente da API, só biblioteca padrão).

Exemplos:
  python simulator/hardware_sim.py ups-drain --ups UPS-A
  python simulator/hardware_sim.py thermal --rack RACK-A02
  python simulator/hardware_sim.py queda --ativo SRV-WEB-01
  python simulator/hardware_sim.py restaurar
  python simulator/hardware_sim.py caos --duracao 60
  python simulator/hardware_sim.py reset
"""
import argparse
import json
import random
import time
import urllib.error
import urllib.request

API = "http://localhost:8000"


def chamar(metodo: str, caminho: str, corpo: dict | None = None):
    dados = json.dumps(corpo).encode() if corpo is not None else None
    req = urllib.request.Request(API + caminho, data=dados, method=metodo,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read() or "null")
    except urllib.error.HTTPError as e:
        raise SystemExit(f"Erro {e.code} em {caminho}: {e.read().decode()}")
    except urllib.error.URLError as e:
        raise SystemExit(f"API inacessível em {API}: {e.reason}")


def ativos() -> dict[str, dict]:
    return {a["nome"]: a for a in chamar("GET", "/api/ativos")}


def racks() -> dict[str, dict]:
    return {r["nome"]: r for r in chamar("GET", "/api/racks")}


def evento(**corpo):
    chamar("POST", "/api/telemetria/evento", corpo)


def cenario_ups(args):
    ups = ativos().get(args.ups) or raise_nome(args.ups)
    print(f"Falta de energia em {args.ups}: descarregando de 100% a 0%.")
    nivel = 100
    while nivel >= 0:
        evento(tipo="ups", ativo_id=ups["id"], bateria_pct=nivel, em_bateria=True)
        print(f"  bateria {nivel:3d}%")
        nivel -= args.passo
        time.sleep(args.intervalo)
    time.sleep(args.intervalo)
    print("Energia restabelecida (bateria em 70%).")
    evento(tipo="ups", ativo_id=ups["id"], bateria_pct=70, em_bateria=False)


def cenario_termico(args):
    rack = racks().get(args.rack) or raise_nome(args.rack)
    print(f"Falha de refrigeração em {args.rack}.")
    for t in [24, 26, 28, 30, 32, 34, 36, 38]:
        evento(tipo="temperatura", rack_id=rack["id"], valor=t)
        print(f"  {t} °C")
        time.sleep(args.intervalo)
    time.sleep(args.intervalo * 2)
    print("Refrigeração restabelecida.")
    for t in [30, 26, 23]:
        evento(tipo="temperatura", rack_id=rack["id"], valor=t)
        time.sleep(args.intervalo)


def cenario_queda(args):
    a = ativos().get(args.ativo) or raise_nome(args.ativo)
    evento(tipo="ativo_status", ativo_id=a["id"], status="offline")
    print(f"{args.ativo} derrubado. Se houver OS em execução que não o cobre, o watchdog dispara.")


def cenario_restaurar(_):
    for a in ativos().values():
        if a["status"] == "offline":
            evento(tipo="ativo_status", ativo_id=a["id"], status="online")
            print(f"{a['nome']} restaurado.")


def cenario_caos(args):
    fim = time.time() + args.duracao
    todos = [a for a in ativos().values() if a["tipo"] != "ups"]
    rs = list(racks().values())
    while time.time() < fim:
        acao = random.choice(["queda", "volta", "temp"])
        if acao == "queda":
            a = random.choice(todos)
            evento(tipo="ativo_status", ativo_id=a["id"], status="offline")
            print(f"queda: {a['nome']}")
        elif acao == "volta":
            for a in ativos().values():
                if a["status"] == "offline":
                    evento(tipo="ativo_status", ativo_id=a["id"], status="online")
                    print(f"volta: {a['nome']}")
                    break
        else:
            r = random.choice(rs)
            t = round(random.uniform(21, 35), 1)
            evento(tipo="temperatura", rack_id=r["id"], valor=t)
            print(f"temperatura: {r['nome']} {t} °C")
        time.sleep(args.intervalo)


def raise_nome(nome):
    raise SystemExit(f"'{nome}' não encontrado. Use nomes como UPS-A, RACK-A01, SRV-WEB-01.")


def main():
    global API
    p = argparse.ArgumentParser(description="Simulador de hardware do SentinelDC")
    p.add_argument("--api", default=API, help="URL base da API (padrão: %(default)s)")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("ups-drain", help="UPS perde a rede e a bateria descarrega")
    s.add_argument("--ups", default="UPS-A"); s.add_argument("--passo", type=int, default=5)
    s.add_argument("--intervalo", type=float, default=2.0); s.set_defaults(fn=cenario_ups)

    s = sub.add_parser("thermal", help="Temperatura do rack sobe")
    s.add_argument("--rack", default="RACK-A02"); s.add_argument("--intervalo", type=float, default=2.0)
    s.set_defaults(fn=cenario_termico)

    s = sub.add_parser("queda", help="Derruba um ativo")
    s.add_argument("--ativo", required=True); s.set_defaults(fn=cenario_queda)

    s = sub.add_parser("restaurar", help="Põe online todos os ativos offline")
    s.set_defaults(fn=cenario_restaurar)

    s = sub.add_parser("caos", help="Eventos aleatórios")
    s.add_argument("--duracao", type=int, default=60); s.add_argument("--intervalo", type=float, default=2.0)
    s.set_defaults(fn=cenario_caos)

    s = sub.add_parser("reset", help="Recarrega o ambiente de demonstração")
    s.set_defaults(fn=lambda _: print(chamar("POST", "/api/demo/reset")))

    args = p.parse_args()
    API = args.api.rstrip("/")
    try:
        args.fn(args)
    except KeyboardInterrupt:
        print("\nInterrompido.")


if __name__ == "__main__":
    main()
