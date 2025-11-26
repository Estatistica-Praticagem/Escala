import json
import calendar
from datetime import datetime, timedelta
import random
import statistics

# ========================
#   CONSTANTES PRINCIPAIS
# ========================
TURNOS = ["00H", "06H", "12H", "18H"]
HORAS_POR_TURNO = 6
LIMITE_DIAS_CONSECUTIVOS = 4

# ========================
#   MODELOS & UTILITÁRIOS
# ========================
def parse_mes(mes):
    return f"{int(mes):02d}"

def dias_do_mes(ano, mes):
    return calendar.monthrange(ano, mes)[1]

def str_data(ano, mes, dia):
    return f"{ano}-{parse_mes(mes)}-{int(dia):02d}"

def parse_ferias(lista_ferias):
    ferias = {}
    for f in lista_ferias or []:
        fid = str(f["funcionario_id"])
        ini = datetime.strptime(f["data_inicio"], "%Y-%m-%d").date()
        fim = datetime.strptime(f["data_fim"], "%Y-%m-%d").date()
        ferias.setdefault(fid, []).append((ini, fim))
    return ferias

def parse_preferencias(lista_pref):
    prefs = {}
    for p in lista_pref or []:
        fid = str(p["funcionario_id"])
        turnos = set(p.get("turnos_preferidos", []))
        if p.get("turno"):
            turnos.add(p["turno"])
        if turnos:
            prefs.setdefault(fid, set()).update(turnos)
    return prefs

def parse_restricoes(lista_rest):
    rest = {
        "dia_semana_proibido": {},
        "turno_proibido": {},
        "data_proibida": {},
        "turno_permitido_por_dia": {},
    }
    for r in lista_rest or []:
        fid = str(r["funcionario_id"])
        tipo = r["tipo"]
        if tipo == "DIA_SEMANA_PROIBIDO":
            ds = int(r["dia_semana"])
            rest["dia_semana_proibido"].setdefault(fid, set()).add(ds)
        if tipo == "TURNO_PROIBIDO":
            turno = r.get("turno")
            if turno:
                rest["turno_proibido"].setdefault(fid, set()).add(turno)
        if tipo == "DATA_PROIBIDA":
            data = r.get("data")
            if data:
                d = datetime.strptime(data, "%Y-%m-%d").date()
                rest["data_proibida"].setdefault(fid, set()).add(d)
        if tipo == "TURNO_PERMITIDO_POR_DIA":
            ds = int(r["dia_semana"])
            turnos = r.get("turnos_permitidos")
            if turnos:
                tset = set(t.strip() for t in turnos.split(",") if t.strip())
                rest["turno_permitido_por_dia"].setdefault(fid, {})[ds] = tset
    return rest

def is_ferias(ferias, func_id, data):
    return any(start <= data <= end for start, end in ferias.get(str(func_id), []))

def is_dia_semana_proibido(rest, func_id, dia_semana):
    return dia_semana in rest["dia_semana_proibido"].get(str(func_id), set())

def is_turno_proibido(rest, func_id, turno):
    return turno in rest["turno_proibido"].get(str(func_id), set())

def is_data_proibida(rest, func_id, data):
    return data in rest["data_proibida"].get(str(func_id), set())

def is_turno_permitido_por_dia(rest, func_id, dia_semana, turno):
    return turno in rest["turno_permitido_por_dia"].get(str(func_id), {}).get(dia_semana, set()) if \
        dia_semana in rest["turno_permitido_por_dia"].get(str(func_id), {}) else True

# ============================
#      MOTOR PRINCIPAL
# ============================
def pode_trabalhar(params, func, turno, data, info):
    ferias = info["ferias"]
    rest = info["restricoes"]
    dia_semana = data.weekday()  # 0=segunda
    func_id = str(func["id"])
    if is_ferias(ferias, func_id, data): return False
    if is_dia_semana_proibido(rest, func_id, dia_semana): return False
    if is_turno_proibido(rest, func_id, turno): return False
    if is_data_proibida(rest, func_id, data): return False
    permitted = is_turno_permitido_por_dia(rest, func_id, dia_semana, turno)
    if permitted is False or (isinstance(permitted, set) and turno not in permitted): return False
    return True

def score_func(params, func, turno, horas, consec, modo, w_pref, dia, prefs, ultimo_turno, stats, mes_acum_horas):
    func_id = str(func["id"])
    base = horas[func_id] / 10 + consec[func_id] * 3
    if modo == "A":
        if turno in prefs.get(func_id, set()):
            base -= w_pref
    else:
        base += horas[func_id] / 5
    if ultimo_turno.get(func_id) and ultimo_turno[func_id] != turno and consec[func_id] > 0:
        base += 8
    if mes_acum_horas and func_id in mes_acum_horas:
        base += (mes_acum_horas[func_id] / 50)
    base += random.uniform(-0.2, 0.2) * (abs(base) + 1)
    base += random.uniform(-2, 2)
    return base

def escolher_func(lista, turno, modo, horas, consec, w_pref, dia, prefs, ultimo_turno, stats, params, data, info, mes_acum_horas):
    validos = [
        f for f in lista
        if pode_trabalhar(params, f, turno, data, info) and consec[str(f["id"])] < LIMITE_DIAS_CONSECUTIVOS
    ]
    if not validos:
        return random.choice(lista)
    random.shuffle(validos)
    ordenados = sorted(validos, key=lambda f: score_func(
        params, f, turno, horas, consec, modo, w_pref, dia, prefs, ultimo_turno, stats, mes_acum_horas))
    return random.choice(ordenados[:2])

def gerar_escala_mes(
    ano, mes, funcionarios, params, info,
    estado_acumulado=None,
    FLEXIBILIZAR=True,
    modo_global="AMBOS",
    tentativas=50,
    perfis=None,
    mes_acum_horas=None
):
    dias_no_mes = dias_do_mes(ano, mes)
    if perfis is None:
        perfis = {"EXP": [], "AUX": []}
        for f in funcionarios:
            perfis.setdefault(f["perfil"], []).append(f)
    melhor_score = float("inf")
    melhor = None
    melhor_horas = None
    melhor_stats = None
    melhor_dias_trab = None
    melhor_consec = None
    melhor_ultimo_turno = None

    if estado_acumulado:
        horas = dict(estado_acumulado["horas"])
        dias_trab = dict(estado_acumulado["dias_trab"])
    else:
        horas = {str(f["id"]): 0 for f in funcionarios}
        dias_trab = {str(f["id"]): 0 for f in funcionarios}
    consec = {str(f["id"]): 0 for f in funcionarios}
    ultimo_turno = {str(f["id"]): None for f in funcionarios}

    prefs = info["preferencias"]
    stats = {str(f["id"]): {t: 0 for t in TURNOS} for f in funcionarios}
    for i in range(1, tentativas + 1):
        dias_mes = []
        h = dict(horas)
        d_trab = dict(dias_trab)
        c = dict(consec)
        u_turno = dict(ultimo_turno)
        s = {k: dict(v) for k, v in stats.items()}
        for dia in range(1, dias_no_mes + 1):
            linha = {
                "data": str_data(ano, mes, dia),
                "turnos": {}
            }
            disp = list(funcionarios)
            random.shuffle(disp)
            data_atual = datetime(ano, mes, dia).date()
            for turno in TURNOS:
                exp_list = [f for f in disp if f["perfil"] == "EXP"]
                aux_list = [f for f in disp if f["perfil"] == "AUX"]
                if FLEXIBILIZAR and (len(exp_list) < 1 or len(aux_list) < 1):
                    op1, op2 = random.sample(disp, 2)
                else:
                    op1 = escolher_func(
                        exp_list, turno, modo_global, h, c, 5, dia, prefs, u_turno, s,
                        params, data_atual, info, mes_acum_horas
                    )
                    op2 = escolher_func(
                        aux_list, turno, modo_global, h, c, 5, dia, prefs, u_turno, s,
                        params, data_atual, info, mes_acum_horas
                    )
                linha["turnos"][turno] = [op1, op2]  # MANTÉM OBJETOS, NÃO NOMES!
                h[str(op1["id"])] += HORAS_POR_TURNO
                h[str(op2["id"])] += HORAS_POR_TURNO
                c[str(op1["id"])] += 1
                c[str(op2["id"])] += 1
                s[str(op1["id"])][turno] += 1
                s[str(op2["id"])][turno] += 1
                u_turno[str(op1["id"])] = turno
                u_turno[str(op2["id"])] = turno
                disp.remove(op1)
                disp.remove(op2)
            ids_trabalharam = set()
            for turn in TURNOS:
                ids_trabalharam.add(str(linha["turnos"][turn][0]["id"]))
                ids_trabalharam.add(str(linha["turnos"][turn][1]["id"]))
            for f in funcionarios:
                if str(f["id"]) not in ids_trabalharam:
                    c[str(f["id"])] = 0
                    u_turno[str(f["id"])] = None
            for fid in ids_trabalharam:
                d_trab[fid] += 1
            dias_mes.append(linha)
        valores = list(h.values())
        dif = max(valores) - min(valores)
        media = statistics.mean(valores)
        score = dif + media / 5
        if score < melhor_score:
            melhor_score = score
            melhor = dias_mes
            melhor_horas = dict(h)
            melhor_stats = {k: dict(v) for k, v in s.items()}
            melhor_dias_trab = dict(d_trab)
            melhor_consec = dict(c)
            melhor_ultimo_turno = dict(u_turno)
    proximo_estado = {
        "horas": dict(melhor_horas),
        "dias_trab": dict(melhor_dias_trab)
    }

    # --- Gera saída convertendo objetos para nomes na resposta ---
    dias_out = []
    for linha in melhor:
        linha_out = {
            "data": linha["data"],
            "turnos": {
                turno: [f["nome"] for f in dupla]
                for turno, dupla in linha["turnos"].items()
            }
        }
        dias_out.append(linha_out)

    return {
        "dias": dias_out,
        "horas": melhor_horas,
        "stats": melhor_stats,
        "dias_trab": melhor_dias_trab,
        "score": melhor_score,
        "media": statistics.mean(list(melhor_horas.values())),
        "max": max(melhor_horas.values()),
        "min": min(melhor_horas.values()),
        "proximo_estado": proximo_estado
    }

def gerar_escala_ano(
    ano, mes_inicio, funcionarios, params, info,
    FLEXIBILIZAR=True, modo_global="AMBOS", tentativas=50
):
    resultados = {}
    estado_acumulado = None
    meses_processados = []
    analise_ano = {
        "score_total": 0,
        "media_horas_total": 0,
        "max_horas": 0,
        "min_horas": 10000,
    }
    estatisticas_finais = {
        "horas": {},
        "dias_trabalhados": {},
    }
    for m in range(int(mes_inicio), 13):
        res = gerar_escala_mes(
            ano, m, funcionarios, params, info,
            estado_acumulado=estado_acumulado,
            FLEXIBILIZAR=FLEXIBILIZAR,
            modo_global=modo_global,
            tentativas=tentativas,
            mes_acum_horas=estado_acumulado["horas"] if estado_acumulado else None
        )
        chave = f"{ano}-{parse_mes(m)}"
        resultados[chave] = res["dias"]
        meses_processados.append(parse_mes(m))
        analise_ano["score_total"] += res["score"]
        analise_ano["media_horas_total"] += res["media"]
        if res["max"] > analise_ano["max_horas"]:
            analise_ano["max_horas"] = res["max"]
        if res["min"] < analise_ano["min_horas"]:
            analise_ano["min_horas"] = res["min"]
        estatisticas_finais["horas"] = res["horas"]
        estatisticas_finais["dias_trabalhados"] = res["dias_trab"]
        estado_acumulado = res["proximo_estado"]
    meses_count = len(meses_processados)
    analise = {
        "melhor_score": round(analise_ano["score_total"] / meses_count, 2) if meses_count else None,
        "media_horas": round(analise_ano["media_horas_total"] / meses_count, 2) if meses_count else None,
        "max_horas": analise_ano["max_horas"],
        "min_horas": analise_ano["min_horas"]
    }
    return {
        "ano": ano,
        "mes_inicio": parse_mes(mes_inicio),
        "meses_processados": meses_processados,
        "escala": resultados,
        "analise": analise,
        "estatisticas": estatisticas_finais
    }

def main(request):
    try:
        if request.method == "OPTIONS":
            return ("", 204, _cors_headers())
        if request.method != "POST":
            return _json({"erro": "Use POST"}, status=405)
        try:
            payload = request.get_json(force=True)
        except Exception as ex:
            return _json({"erro": "JSON inválido", "detalhe": str(ex)}, status=400)
        if "ano" not in payload or "mes_inicio" not in payload or "funcionarios" not in payload:
            return _json({"erro": "Campos obrigatórios: ano, mes_inicio, funcionarios"}, status=400)
        ano = int(payload["ano"])
        mes_inicio = int(payload["mes_inicio"])
        funcionarios = payload["funcionarios"]
        params = payload.get("parametros", {})
        tentativas = int(params.get("quantidade_escalas", 50))
        FLEXIBILIZAR = bool(params.get("permite_dupla_exp", True) and params.get("permite_dupla_aux", True))
        modo_global = "AMBOS"
        ferias = parse_ferias(payload.get("ferias"))
        preferencias = parse_preferencias(payload.get("preferencias"))
        restricoes = parse_restricoes(payload.get("restricoes"))
        info = {
            "ferias": ferias,
            "preferencias": preferencias,
            "restricoes": restricoes
        }

        # Aqui: retorna só mês ou ano dependendo do parâmetro (tipo)
        tipo = payload.get("tipo", "ano")  # "mes" ou "ano"
        if tipo == "mes":
            res = gerar_escala_mes(
                ano=ano,
                mes=mes_inicio,
                funcionarios=funcionarios,
                params=params,
                info=info,
                FLEXIBILIZAR=FLEXIBILIZAR,
                modo_global=modo_global,
                tentativas=tentativas
            )
            return _json(res)
        else:
            resultado = gerar_escala_ano(
                ano=ano,
                mes_inicio=mes_inicio,
                funcionarios=funcionarios,
                params=params,
                info=info,
                FLEXIBILIZAR=FLEXIBILIZAR,
                modo_global=modo_global,
                tentativas=tentativas
            )
            return _json(resultado)
    except Exception as e:
        return _json({"erro": "Falha inesperada", "detalhe": str(e)}, status=500)

def _cors_headers():
    return {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "POST,OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type"
    }

def _json(obj, status=200):
    return (json.dumps(obj, ensure_ascii=False, indent=2), status, {
        "Content-Type": "application/json",
        **_cors_headers()
    })
