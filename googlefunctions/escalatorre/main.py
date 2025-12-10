import json
import calendar
from datetime import datetime, timedelta
import random
import statistics

# ========================
#   CONFIGURAÇÃO DE PESOS
# ========================
# -------- HARD CONSTRAINTS (REGRAS DURAS) --------
HARD_RULES = {
    "ferias": True,
    "dia_semana_proibido": True,
    "turno_proibido": True,
    "data_proibida": True,
    "troca_de_turno_sem_folga": True,
    "limite_dias_consecutivos": 6
}

# -------- SOFT CONSTRAINTS (REGRAS FLEXÍVEIS - PESOS) --------
SOFT_WEIGHTS = {
    "preferencia_turno": 10,
    "balanceamento_turnos": 50,
    "dias_trabalhados": 3,
    "desequilibrio_horas": 5,
    "troca_de_turno": 50
}

# ========================
#   TURNOS E CONSTANTES
# ========================
TURNOS = ["00H", "06H", "12H", "18H"]
HORAS_POR_TURNO = 6

CICLO_TURNOS = {
    "00H": "12H",
    "12H": "00H",
    "06H": "18H",
    "18H": "06H"
}

# ========================
#   FUNÇÕES UTILITÁRIAS
# ========================
def parse_mes(mes): return f"{int(mes):02d}"
def dias_do_mes(ano, mes): return calendar.monthrange(ano, mes)[1]
def str_data(ano, mes, dia): return f"{ano}-{parse_mes(mes)}-{int(dia):02d}"

# ========================
#   PARSERS DE ENTRADA
# ========================
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
        if p.get("turno"): turnos.add(p["turno"])
        if turnos: prefs.setdefault(fid, set()).update(turnos)
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
            if turno: rest["turno_proibido"].setdefault(fid, set()).add(turno)
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

# ========================
#   RESTRIÇÕES HARD (NÃO PODE)
# ========================
def restricoes_hard(func_id, turno, data, info, consec, ultimo_turno):
    """
    Restringe a escolha de funcionário com base nas hard rules.
    Garante que, durante uma sequência, o funcionário só siga o ciclo de turnos.
    """
    # Férias
    if HARD_RULES["ferias"] and is_ferias(info["ferias"], func_id, data):
        return False
    # Dia da semana proibido
    if HARD_RULES["dia_semana_proibido"] and is_dia_semana_proibido(info["restricoes"], func_id, data.weekday()):
        return False
    # Turno proibido
    if HARD_RULES["turno_proibido"] and is_turno_proibido(info["restricoes"], func_id, turno):
        return False
    # Data proibida
    if HARD_RULES["data_proibida"] and is_data_proibida(info["restricoes"], func_id, data):
        return False
    # Turno permitido apenas por dia da semana
    if not is_turno_permitido_por_dia(info["restricoes"], func_id, data.weekday(), turno):
        return False
    # Troca de turno só se folgar: se está em sequência, tem que seguir o ciclo!
    if HARD_RULES["troca_de_turno_sem_folga"]:
        ut = ultimo_turno.get(func_id)
        if consec[func_id] > 0:
            turno_esperado = CICLO_TURNOS.get(ut)
            # Só pode seguir o ciclo correto
            if ut is not None and turno != turno_esperado:
                return False
    # Limite de dias consecutivos
    if consec[func_id] >= HARD_RULES["limite_dias_consecutivos"]:
        return False
    return True

def is_ferias(ferias, func_id, data):
    return any(start <= data <= end for start, end in ferias.get(str(func_id), []))

def is_dia_semana_proibido(rest, func_id, dia_semana):
    return dia_semana in rest["dia_semana_proibido"].get(str(func_id), set())

def is_turno_proibido(rest, func_id, turno):
    return turno in rest["turno_proibido"].get(str(func_id), set())

def is_data_proibida(rest, func_id, data):
    return data in rest["data_proibida"].get(str(func_id), set())

def is_turno_permitido_por_dia(rest, func_id, dia_semana, turno):
    if dia_semana in rest["turno_permitido_por_dia"].get(str(func_id), {}):
        return turno in rest["turno_permitido_por_dia"][str(func_id)][dia_semana]
    return True

# ========================
#   RESTRIÇÕES SOFT (AJUSTE PELO SCORE)
# ========================
def score_func(
    params, func, turno, horas, consec, modo, dia, prefs,
    ultimo_turno, stats, mes_acum_horas
):
    """
    Calcula o score (quanto menor, melhor) para ajudar a balancear as escolhas.
    Penaliza trocas de turno, excesso de horas, dias consecutivos etc.
    """
    func_id = str(func["id"])
    base = 0

    # Preferência de turno
    if turno not in prefs.get(func_id, set()):
        base += SOFT_WEIGHTS["preferencia_turno"]

    # Penaliza turnos desbalanceados
    media_turno = statistics.mean([stats[func_id][t] for t in TURNOS])
    if stats[func_id][turno] > media_turno + 2:
        base += SOFT_WEIGHTS["balanceamento_turnos"] * (stats[func_id][turno] - media_turno)

    # Penaliza muitos dias consecutivos sem folga
    base += consec[func_id] * SOFT_WEIGHTS["dias_trabalhados"]

    # Penaliza excesso de horas acumuladas (ajuda a balancear)
    if mes_acum_horas and func_id in mes_acum_horas:
        base += (mes_acum_horas[func_id] / 10) * SOFT_WEIGHTS["desequilibrio_horas"]

    # Penaliza troca de turno (soft, além do hard)
    if ultimo_turno.get(func_id) and ultimo_turno[func_id] != turno:
        base += SOFT_WEIGHTS["troca_de_turno"]

    # Ruído randômico para evitar empate
    base += random.uniform(-1, 1)
    return base

# ========================
#   ESCOLHA DO FUNCIONÁRIO (Respeitando máximo a sequência no ciclo)
# ========================
def escolher_func(
    lista, turno, modo, horas, consec, dia, prefs, ultimo_turno,
    stats, params, data, info, mes_acum_horas
):
    """
    Seleciona o funcionário garantindo máxima sequência de turnos.
    1. Prioriza manter no ciclo (mesmo turno até folga).
    2. Só troca ciclo após folga.
    """
    candidatos = []
    for f in lista:
        fid = str(f["id"])
        if restricoes_hard(fid, turno, data, info, consec, ultimo_turno):
            candidatos.append(f)
    if not candidatos:
        return random.choice(lista)  # Se não há, sorteia alguém

    mantendo_ciclo = []
    quebrando_ciclo = []

    for f in candidatos:
        fid = str(f["id"])
        ut = ultimo_turno.get(fid)
        # Se está em sequência de dias, só pode seguir o ciclo exato!
        if consec[fid] > 0:
            turno_esperado = CICLO_TURNOS.get(ut)
            if turno == turno_esperado:
                mantendo_ciclo.append(f)
            else:
                # Não está no ciclo, só aceita se não houver ninguém melhor
                quebrando_ciclo.append(f)
        else:
            # Após folga, pode reiniciar ciclo (pegar qualquer turno)
            mantendo_ciclo.append(f)

    # Prioriza quem mantém o ciclo (sequência máxima)
    escolhidos = mantendo_ciclo if mantendo_ciclo else quebrando_ciclo
    ordenados = sorted(
        escolhidos,
        key=lambda f: score_func(params, f, turno, horas, consec, modo, dia, prefs, ultimo_turno, stats, mes_acum_horas)
    )
    return ordenados[0]


# ========================
#   GERA PARECER ESCALA
# ========================
def gerar_parecer_escala(dias, funcionarios):
    pareceres = {str(f["id"]): {
        "funcionario_id": f["id"],
        "nome": f.get("nome"),
        "dias_trabalhados": 0,
        "dias_folga": 0,
        "total_horas": 0,
        "vezes_00h": 0,
        "vezes_06h": 0,
        "vezes_12h": 0,
        "vezes_18h": 0,
        "maior_seq_dias_trab": 0,
        "menor_seq_dias_mesmo_turno": None,
        "trocas_de_turno": 0
    } for f in funcionarios}

    ultimos_turnos = {str(f["id"]): None for f in funcionarios}
    seq_dias_trab = {str(f["id"]): 0 for f in funcionarios}
    seq_mesmo_turno = {str(f["id"]): 0 for f in funcionarios}
    menor_seq_mesmo_turno = {str(f["id"]): None for f in funcionarios}

    for dia in dias:
        trabalhou_hoje = {str(f["id"]): False for f in funcionarios}
        for turno, dupla in dia["turnos"].items():
            for nome in dupla:
                func_id = None
                for f in funcionarios:
                    if f["nome"] == nome:
                        func_id = str(f["id"])
                        break
                if func_id is None:
                    continue
                parecer = pareceres[func_id]
                parecer["dias_trabalhados"] += 1 if not trabalhou_hoje[func_id] else 0
                trabalhou_hoje[func_id] = True
                parecer["total_horas"] += 6
                key_turno = f"vezes_{turno.lower()}"
                if key_turno in parecer:
                    parecer[key_turno] += 1
                # Sequência no mesmo turno
                if ultimos_turnos[func_id] == turno:
                    seq_mesmo_turno[func_id] += 1
                else:
                    if seq_mesmo_turno[func_id]:
                        if (menor_seq_mesmo_turno[func_id] is None or
                            seq_mesmo_turno[func_id] < menor_seq_mesmo_turno[func_id]):
                            menor_seq_mesmo_turno[func_id] = seq_mesmo_turno[func_id]
                    seq_mesmo_turno[func_id] = 1
                    if ultimos_turnos[func_id] is not None:
                        parecer["trocas_de_turno"] += 1
                ultimos_turnos[func_id] = turno
        for func in funcionarios:
            fid = str(func["id"])
            if trabalhou_hoje[fid]:
                seq_dias_trab[fid] += 1
                if seq_dias_trab[fid] > pareceres[fid]["maior_seq_dias_trab"]:
                    pareceres[fid]["maior_seq_dias_trab"] = seq_dias_trab[fid]
            else:
                if seq_dias_trab[fid]:
                    if (menor_seq_mesmo_turno[fid] is None or
                        seq_mesmo_turno[fid] < menor_seq_mesmo_turno[fid]):
                        menor_seq_mesmo_turno[fid] = seq_mesmo_turno[fid]
                seq_dias_trab[fid] = 0
                seq_mesmo_turno[fid] = 0
                ultimos_turnos[fid] = None
    for fid, p in pareceres.items():
        p["dias_folga"] = len(dias) - p["dias_trabalhados"]
        p["menor_seq_dias_mesmo_turno"] = menor_seq_mesmo_turno[fid] or 1
    return list(pareceres.values())

# ========================
#   GERADOR DE ESCALA
# ========================
def gerar_escala_mes(
    ano, mes, funcionarios, params, info,
    estado_acumulado=None, FLEXIBILIZAR=True,
    modo_global="AMBOS", tentativas=50,
    perfis=None, mes_acum_horas=None
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

    # Estado inicial
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
            linha = {"data": str_data(ano, mes, dia), "turnos": {}}
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
                        exp_list, turno, modo_global, h, c, dia, prefs, u_turno, s,
                        params, data_atual, info, mes_acum_horas
                    )
                    op2 = escolher_func(
                        aux_list, turno, modo_global, h, c, dia, prefs, u_turno, s,
                        params, data_atual, info, mes_acum_horas
                    )
                linha["turnos"][turno] = [op1, op2]
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

    # Gera o parecer deste mês e retorna junto!
    parecer = gerar_parecer_escala(dias_out, funcionarios)

    return {
        "dias": dias_out,
        "horas": melhor_horas,
        "stats": melhor_stats,
        "dias_trab": melhor_dias_trab,
        "score": melhor_score,
        "parecer": parecer
    }

def gerar_escala_ano(
    ano, mes_inicio, funcionarios, params, info,
    FLEXIBILIZAR=True, modo_global="AMBOS", tentativas=50
):
    resultados = {}
    estado_acumulado = None
    meses_processados = []
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
        # Agora salva cada mês já com o parecer do mês!
        resultados[chave] = {
            "dias": res["dias"],
            "parecer": res["parecer"],
            "horas": res.get("horas"),
            "stats": res.get("stats"),
            "dias_trab": res.get("dias_trab"),
            "score": res.get("score"),
        }
        meses_processados.append(parse_mes(m))
        estado_acumulado = {
            "horas": res["horas"],
            "dias_trab": res["dias_trab"]
        }
    return {
        "ano": ano,
        "mes_inicio": parse_mes(mes_inicio),
        "meses_processados": meses_processados,
        "escala": resultados,
    }

# ========================
#   MAIN HANDLER
# ========================
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
