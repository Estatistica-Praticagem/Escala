"""
Gerador de escalas EXP/AUX
---------------------------------
Versão otimizada – START INTELIGENTE + FALLBACK CONTROLADO
2025-12-10

OBJETIVOS:
• Eliminar pipocagem após a 1ª semana
• Preservar banco de funcionários
• Garantir sequências 4–5 dias sem estrangular o mês
"""

import json
import calendar
from datetime import datetime
import random
import statistics

# ========================
# CONFIGURAÇÃO GLOBAL
# ========================

TURNOS = ["00H", "06H", "12H", "18H"]
HORAS_POR_TURNO = 6
CICLO_TURNOS = {"00H": "12H", "12H": "00H", "06H": "18H", "18H": "06H"}

START_DIAS = 7               # janela crítica inicial
START_MAX_CONSEC = 3         # limite de dias seguidos no início

TARGET_SEQ_MIN = 4
TARGET_SEQ_MAX = 5

# ========================
# HARD RULES
# ========================

HARD_RULES = {
    "limite_dias_consecutivos": 5,
    "limite_dias_mesmo_turno": 8,
}

# ========================
# SOFT WEIGHTS
# ========================

SOFT_WEIGHTS = {
    "preferencia_turno": 10,
    "desvio_turno": 600,
    "desvio_horas": 20,
    "troca_turno": 120,
    "sequencia_curta": 300,
    "sequencia_ideal": -200,
    "sequencia_longa": 400,
    "ausencia_turno": 900,
    "folga_agrupada": -40,
}

# ========================
# UTIL
# ========================

parse_mes = lambda m: f"{int(m):02d}"
dias_do_mes = lambda y, m: calendar.monthrange(y, m)[1]
str_data = lambda y, m, d: f"{y}-{parse_mes(m)}-{int(d):02d}"

# ========================
# PARSERS
# ========================

def parse_ferias(lista):
    out = {}
    for f in lista or []:
        fid = str(f["funcionario_id"])
        ini = datetime.strptime(f["data_inicio"], "%Y-%m-%d").date()
        fim = datetime.strptime(f["data_fim"], "%Y-%m-%d").date()
        out.setdefault(fid, []).append((ini, fim))
    return out

def parse_preferencias(lista):
    out = {}
    for p in lista or []:
        fid = str(p["funcionario_id"])
        out[fid] = set(p.get("turnos_preferidos", []))
    return out

def parse_restricoes(lista):
    out = {
        "dia_semana_proibido": {},
        "turno_proibido": {},
        "data_proibida": {},
    }
    for r in lista or []:
        fid = str(r["funcionario_id"])
        if r["tipo"] == "DIA_SEMANA_PROIBIDO":
            out["dia_semana_proibido"].setdefault(fid, set()).add(int(r["dia_semana"]))
        elif r["tipo"] == "TURNO_PROIBIDO":
            out["turno_proibido"].setdefault(fid, set()).add(r["turno"])
        elif r["tipo"] == "DATA_PROIBIDA":
            d = datetime.strptime(r["data"], "%Y-%m-%d").date()
            out["data_proibida"].setdefault(fid, set()).add(d)
    return out

# ========================
# HARD CHECK
# ========================

def restricoes_hard(fid, turno, data, info, consec, ultimo_turno, stats, dia):
    if any(s <= data <= e for s, e in info["ferias"].get(fid, [])):
        return False

    wd = data.weekday()
    rst = info["restricoes"]

    if wd in rst["dia_semana_proibido"].get(fid, set()):
        return False
    if turno in rst["turno_proibido"].get(fid, set()):
        return False
    if data in rst["data_proibida"].get(fid, set()):
        return False

    # START inteligente
    if dia <= START_DIAS and consec[fid] >= START_MAX_CONSEC:
        return False

    # sequência normal
    if consec[fid] >= HARD_RULES["limite_dias_consecutivos"]:
        return False

    if stats[fid][turno] >= HARD_RULES["limite_dias_mesmo_turno"]:
        return False

    ut = ultimo_turno.get(fid)
    if consec[fid] > 0 and ut != turno:
        return False

    if consec[fid] == 0 and ut and turno != CICLO_TURNOS[ut]:
        return False

    return True

# ========================
# SCORE
# ========================

def score_func(fid, turno, dia, consec, ultimo_turno, stats, prefs, horas):
    s = 0

    if turno not in prefs.get(fid, set()):
        s += SOFT_WEIGHTS["preferencia_turno"]

    media = statistics.mean(stats[fid].values())
    s += abs(stats[fid][turno] - media) * SOFT_WEIGHTS["desvio_turno"]

    s += horas[fid] * SOFT_WEIGHTS["desvio_horas"] / 100

    if ultimo_turno.get(fid) and ultimo_turno[fid] != turno:
        s += SOFT_WEIGHTS["troca_turno"]

    futura = consec[fid] + 1
    if futura < TARGET_SEQ_MIN:
        s += SOFT_WEIGHTS["sequencia_curta"]
    elif TARGET_SEQ_MIN <= futura <= TARGET_SEQ_MAX:
        s += SOFT_WEIGHTS["sequencia_ideal"]
    else:
        s += SOFT_WEIGHTS["sequencia_longa"]

    if stats[fid][turno] == 0 and dia > 10:
        s += SOFT_WEIGHTS["ausencia_turno"]

    return s + random.uniform(-1, 1)

# ========================
# ESCOLHA
# ========================

def escolher_func(pool, turno, data, dia, info, consec, ultimo_turno, stats, prefs, horas):
    validos = [
        f for f in pool
        if restricoes_hard(str(f["id"]), turno, data, info, consec, ultimo_turno, stats, dia)
    ]

    if not validos:
        print(f"\033[91m[RELAX] {turno} {data}\033[0m")
        validos = pool[:]  # fallback controlado

    return min(
        validos,
        key=lambda f: score_func(
            str(f["id"]), turno, dia, consec, ultimo_turno, stats, prefs, horas
        )
    )

# ========================
# GERADOR MÊS
# ========================

def gerar_escala_mes(ano, mes, funcionarios, info, tentativas=40):
    dias_no_mes = dias_do_mes(ano, mes)
    melhor = None
    melhor_score = float("inf")

    for _ in range(tentativas):
        horas = {str(f["id"]): 0 for f in funcionarios}
        stats = {str(f["id"]): {t: 0 for t in TURNOS} for f in funcionarios}
        consec = {str(f["id"]): 0 for f in funcionarios}
        ultimo_turno = {str(f["id"]): None for f in funcionarios}
        dias = []

        for dia in range(1, dias_no_mes + 1):
            data = datetime(ano, mes, dia).date()
            disp = funcionarios[:]
            random.shuffle(disp)
            linha = {"data": str_data(ano, mes, dia), "turnos": {}}

            for turno in TURNOS:
                op1 = escolher_func(disp, turno, data, dia, info, consec, ultimo_turno, stats, info["preferencias"], horas)
                disp.remove(op1)
                op2 = escolher_func(disp, turno, data, dia, info, consec, ultimo_turno, stats, info["preferencias"], horas)
                disp.remove(op2)

                linha["turnos"][turno] = [op1["nome"], op2["nome"]]

                for op in (op1, op2):
                    fid = str(op["id"])
                    horas[fid] += 6
                    stats[fid][turno] += 1
                    consec[fid] += 1
                    ultimo_turno[fid] = turno

            for f in funcionarios:
                fid = str(f["id"])
                if fid not in sum(linha["turnos"].values(), []):
                    consec[fid] = 0

            dias.append(linha)

        score = max(horas.values()) - min(horas.values())
        if score < melhor_score:
            melhor_score = score
            melhor = dias

    return {"dias": melhor, "score": melhor_score}

# ========================
# HANDLER
# ========================

def main(request):
    payload = request.get_json(force=True)
    info = {
        "ferias": parse_ferias(payload.get("ferias")),
        "preferencias": parse_preferencias(payload.get("preferencias")),
        "restricoes": parse_restricoes(payload.get("restricoes")),
    }
    res = gerar_escala_mes(
        payload["ano"],
        payload["mes_inicio"],
        payload["funcionarios"],
        info
    )
    return (
        json.dumps(res, ensure_ascii=False, indent=2),
        200,
        {"Content-Type": "application/json"},
    )
