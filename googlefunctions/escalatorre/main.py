# Gerador de escalas EXP/AUX
# ---------------------------------
# Versão revisada em 2025-12-10  (patch “start-strategy” 2025-12-15)
# Hot-fix “START-BLOCO” 2025-12-16 – elimina pipocar na 1ª semana criando blocos mínimos de 3 dias
# Patch “continuidade” 2025-12-17 – suporte completo à geração contínua
# Patch “continuidade-seq” 2025-12-17 – respeita sequência e turno do mês anterior
#
# Regras duras PRIORITÁRIAS
#     1. Respeita férias, datas e turnos proibidos
#     2. Máx. 6 dias consecutivos de trabalho   (3 logo na 1ª semana)
#     3. Durante sequência (consec > 0) o funcionário deve manter o MESMO turno
#     4. Após folga (consec == 0) deve seguir o ciclo 00↔12 / 06↔18
#     5. Máximo 8 dias por turno/mês (parâmetro)
#
# Regras suaves ponderadas por SOFT_WEIGHTS
# Nenhum reset de ultimo_turno durante folga
# Funções claramente separadas

import json, calendar, random, statistics
from datetime import datetime, timedelta

# ========================
#   CONFIGURAÇÃO DE PESOS E PARÂMETROS
# ========================
START_WINDOW_DIAS    = 7      # 1ª semana
MAX_SEQ_START_WINDOW = 6      # só 6 dias seguidos no start
HORAS_POR_TURNO      = 6

# -------- HARD CONSTRAINTS --------
HARD_RULES = {
    "ferias": True,
    "dia_semana_proibido": True,
    "turno_proibido": True,
    "data_proibida": True,
    "troca_de_turno_sem_folga": True,
    "mesmo_turno_sem_folga": True,
    "limite_dias_consecutivos": 6,   # usado depois da 1ª semana
    "limite_dias_mesmo_turno": 8,
}

# -------- SOFT CONSTRAINTS --------
SOFT_WEIGHTS = {
    # ---------- PENALTIES (↑ score = pior) ----------
    "balanceamento_turnos":            120,
    "penaliza_zero_turno":             300,
    "penaliza_intercalado_trab_folga": 500,
    "penaliza_seq_curta":              460,
    "penaliza_seq_longa":              460,
    "penaliza_ausencia_turno":         500,
    "troca_de_turno":                  480,
    "penaliza_parceiro_repetido":       0,
    "dias_trabalhados":                 0,
    "desequilibrio_horas":             400,

    # ---------- BONUSES (↓ score = melhor) ----------
    "preferencia_turno":              -15,
    "bonus_seq_alvo":                -500,
    "bonus_folga_agrupada":          -400,
    "bonus_sequencia_mesmo_turno":   -500,
}

TARGET_SEQ_MIN, TARGET_SEQ_MAX = 3, 5
BLOCK_MIN_SIZE                = TARGET_SEQ_MIN
MIN_SEQ_AFTER_START           = 3

# ========================
#   TURNOS E CONSTANTES
# ========================
TURNOS       = ["00H", "06H", "12H", "18H"]
CICLO_TURNOS = {"00H": "12H", "12H": "00H", "06H": "18H", "18H": "06H"}

parse_mes   = lambda m: f"{int(m):02d}"
dias_do_mes = lambda y, m: calendar.monthrange(y, m)[1]
str_data    = lambda y, m, d: f"{y}-{parse_mes(m)}-{int(d):02d}"

# ========================
#   PARSERS DE ENTRADA
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
        turnos = set(p.get("turnos_preferidos", []))
        if p.get("turno"):
            turnos.add(p["turno"])
        if turnos:
            out.setdefault(fid, set()).update(turnos)
    return out


def parse_restricoes(lista):
    out = {
        "dia_semana_proibido": {},
        "turno_proibido": {},
        "data_proibida": {},
        "turno_permitido_por_dia": {},
    }
    for r in lista or []:
        fid, tipo = str(r["funcionario_id"]), r["tipo"]
        if tipo == "DIA_SEMANA_PROIBIDO":
            out["dia_semana_proibido"].setdefault(fid, set()).add(int(r["dia_semana"]))
        elif tipo == "TURNO_PROIBIDO":
            out["turno_proibido"].setdefault(fid, set()).add(r["turno"])
        elif tipo == "DATA_PROIBIDA":
            d = datetime.strptime(r["data"], "%Y-%m-%d").date()
            out["data_proibida"].setdefault(fid, set()).add(d)
        elif tipo == "TURNO_PERMITIDO_POR_DIA":
            ds = int(r["dia_semana"])
            tset = set(t.strip() for t in r["turnos_permitidos"].split(",") if t.strip())
            out["turno_permitido_por_dia"].setdefault(fid, {})[ds] = tset
    return out

# ========================
#   REGRAS DURAS
# ========================
def limite_consecutivo(dia_corrente):
    """3 dias na primeira semana; depois 6"""
    return MAX_SEQ_START_WINDOW if dia_corrente <= START_WINDOW_DIAS else HARD_RULES["limite_dias_consecutivos"]


def restricoes_hard(fid, turno, data, info, consec, ultimo_turno, stats):
    if any(s <= data <= e for s, e in info["ferias"].get(fid, [])):
        return False

    rst, wd = info["restricoes"], data.weekday()
    if wd in rst["dia_semana_proibido"].get(fid, set()):
        return False
    if turno in rst["turno_proibido"].get(fid, set()):
        return False
    if data in rst["data_proibida"].get(fid, set()):
        return False
    if wd in rst["turno_permitido_por_dia"].get(fid, {}):
        if turno not in rst["turno_permitido_por_dia"][fid][wd]:
            return False

    ut, cons = ultimo_turno.get(fid), consec[fid]

    if cons > 0 and ut != turno:
        return False
    if cons == 0 and ut is not None and turno != CICLO_TURNOS[ut]:
        return False
    if cons >= limite_consecutivo(data.day):
        return False
    if stats and stats.get(fid, {}).get(turno, 0) >= HARD_RULES["limite_dias_mesmo_turno"]:
        return False
    if data.day > START_WINDOW_DIAS and cons == 0 and ut is not None:
        if stats[fid][ut] < MIN_SEQ_AFTER_START:
            return False
    return True

# ========================
#   SCORE SOFT
# ========================
def score_func(params, func, turno, horas, consec, dia, prefs,
               ultimo_turno, stats, mes_acum_horas,
               seq_trab=None, seq_folga=None, parceiro_ult=None, parceiro_atual=None, estado_continuo=None):
    fid = str(func["id"])
    s = 0

    if estado_continuo and dia <= START_WINDOW_DIAS:
        s += estado_continuo["penalidade_start"].get(fid, 0) * 800

    if turno not in prefs.get(fid, set()):
        s += SOFT_WEIGHTS["preferencia_turno"]

    media = statistics.mean(stats[fid].values())
    if stats[fid][turno] > media + 2:
        s += SOFT_WEIGHTS["balanceamento_turnos"] * (stats[fid][turno] - media)

    s += consec[fid] * SOFT_WEIGHTS["dias_trabalhados"]

    if mes_acum_horas and fid in mes_acum_horas:
        s += (mes_acum_horas[fid] / 10) * SOFT_WEIGHTS["desequilibrio_horas"]

    if ultimo_turno.get(fid) and ultimo_turno[fid] != turno:
        s += SOFT_WEIGHTS["troca_de_turno"]

    if stats[fid][turno] > 10:
        s += 100 * (stats[fid][turno] - 10)

    if dia > 20 and sum(1 for t in TURNOS if stats[fid][t] > 0) < 3:
        s += 150

    seq_atual = consec[fid]
    continua  = ultimo_turno.get(fid) == turno
    if continua:
        futura = seq_atual + 1
        if futura < TARGET_SEQ_MIN:
            s += SOFT_WEIGHTS["penaliza_seq_curta"]
        elif TARGET_SEQ_MIN <= futura <= TARGET_SEQ_MAX:
            s -= SOFT_WEIGHTS["bonus_seq_alvo"]
        elif futura > TARGET_SEQ_MAX:
            s += SOFT_WEIGHTS["penaliza_seq_longa"]

    if seq_trab and seq_folga:
        if seq_trab[fid] == 1 and seq_folga[fid] == 1:
            s += SOFT_WEIGHTS["penaliza_intercalado_trab_folga"]
        if seq_folga[fid] > 1:
            s -= seq_folga[fid] * SOFT_WEIGHTS["bonus_folga_agrupada"]

    if stats[fid][turno] == 0 and dia > 7:
        s += SOFT_WEIGHTS["penaliza_zero_turno"]

    if parceiro_ult and parceiro_ult.get(fid) == parceiro_atual:
        s += SOFT_WEIGHTS["penaliza_parceiro_repetido"]

    if stats[fid][turno] >= 8:
        s += 120 + 40 * (stats[fid][turno] - 7)

    return s + random.uniform(-1, 1)

# ========================
#   ESCOLHA DO FUNCIONÁRIO
# ========================
def escolher_func(pool, turno, horas, consec, dia, prefs,
                  ultimo_turno, stats, params, data, info,
                  mes_acum_horas, seq_trab, seq_folga,
                  parceiro_ult, parceiro_candidato, estado_continuo):
    cand = [f for f in pool if restricoes_hard(str(f["id"]), turno, data, info,
                                              consec, ultimo_turno, stats)]
    if not cand:
        print(f"\033[91m[ALERTA] Sem opção para {turno} dia {data}: relaxando regras\033[0m")
        return random.choice(pool)

    obrigatorios, pos_folga, livres = [], [], []
    for f in cand:
        fid, ut, cons = str(f["id"]), ultimo_turno.get(str(f["id"])), consec[str(f["id"])]
        if cons > 0:
            if ut == turno:
                obrigatorios.append(f)
            elif cons >= TARGET_SEQ_MIN:
                livres.append(f)
            continue
        if cons == 0 and ut is not None and turno == CICLO_TURNOS[ut]:
            pos_folga.append(f)
            continue
        livres.append(f)

    escolha_pool = obrigatorios or pos_folga or livres
    return min(
        escolha_pool,
        key=lambda fx: score_func(
            params, fx, turno, horas, consec, dia, prefs,
            ultimo_turno, stats, mes_acum_horas,
            seq_trab, seq_folga, parceiro_ult, parceiro_candidato, estado_continuo        )
    )

# ========================
#   FUNÇÃO AUX – duplas iniciais
# ========================
def gerar_duplas_iniciais(funcionarios, perfis):
    exp = perfis["EXP"][:]
    aux = perfis["AUX"][:]
    random.shuffle(exp)
    random.shuffle(aux)

    n_duplas = min(4, len(exp), len(aux))
    duplas = [(exp.pop(), aux.pop()) for _ in range(n_duplas)]

    while len(duplas) < 4:
        cand1 = random.choice(perfis["EXP"])
        cand2 = random.choice(perfis["AUX"])
        while cand2["id"] == cand1["id"]:
            cand2 = random.choice(perfis["AUX"])
        duplas.append((cand1, cand2))

    return duplas[:2], duplas[2:]

# ========================
#   PARECER / RELATÓRIO
# ========================
def gerar_parecer_escala(dias, funcionarios):
    p = {
        str(f["id"]): {
            "funcionario_id": f["id"],
            "nome":           f.get("nome"),
            "dias_trabalhados": 0,
            "dias_folga":       0,
            "total_horas":      0,
            "vezes_00h":        0,
            "vezes_06h":        0,
            "vezes_12h":        0,
            "vezes_18h":        0,
            "maior_seq_dias_trab":          0,
            "menor_seq_dias_mesmo_turno":  None,
            "trocas_de_turno":              0,
        }
        for f in funcionarios
    }
    ult         = {str(f["id"]): None for f in funcionarios}
    seq_trab    = {str(f["id"]): 0    for f in funcionarios}
    seq_t_mesmo = {str(f["id"]): 0    for f in funcionarios}

    for dia in dias:
        trabalhou = {str(f["id"]): False for f in funcionarios}
        for turno, dupla in dia["turnos"].items():
            for nome in dupla:
                fid = next((str(f["id"]) for f in funcionarios if f["nome"] == nome), None)
                if not fid:
                    continue
                pr = p[fid]
                if not trabalhou[fid]:
                    pr["dias_trabalhados"] += 1
                trabalhou[fid]   = True
                pr["total_horas"] += HORAS_POR_TURNO
                pr[f"vezes_{turno.lower()}"] += 1

                if ult[fid] == turno:
                    seq_t_mesmo[fid] += 1
                else:
                    if seq_t_mesmo[fid]:
                        pr["menor_seq_dias_mesmo_turno"] = (
                            seq_t_mesmo[fid] if pr["menor_seq_dias_mesmo_turno"] is None
                            else min(pr["menor_seq_dias_mesmo_turno"], seq_t_mesmo[fid])
                        )
                    seq_t_mesmo[fid] = 1
                    if ult[fid] is not None:
                        pr["trocas_de_turno"] += 1
                ult[fid] = turno

        for f in funcionarios:
            fid = str(f["id"])
            if trabalhou[fid]:
                seq_trab[fid] += 1
                p[fid]["maior_seq_dias_trab"] = max(p[fid]["maior_seq_dias_trab"], seq_trab[fid])
            else:
                if seq_t_mesmo[fid]:
                    p[fid]["menor_seq_dias_mesmo_turno"] = (
                        seq_t_mesmo[fid] if p[fid]["menor_seq_dias_mesmo_turno"] is None
                        else min(p[fid]["menor_seq_dias_mesmo_turno"], seq_t_mesmo[fid])
                    )
                seq_trab[fid] = seq_t_mesmo[fid] = 0

    for fid, pr in p.items():
        pr["dias_folga"] = len(dias) - pr["dias_trabalhados"]
        if pr["menor_seq_dias_mesmo_turno"] is None:
            pr["menor_seq_dias_mesmo_turno"] = 1
    return list(p.values())

# ========================
#   GERADOR DE ESCALA (MÊS)
# ========================
def gerar_escala_mes(ano, mes, funcionarios, params, info,
                     estado_acumulado=None, FLEXIBILIZAR=True,
                     tentativas=50, perfis=None, mes_acum_horas=None,
                     estado_continuo=None):

    dias_no_mes = dias_do_mes(ano, mes)
    if perfis is None:
        perfis = {"EXP": [], "AUX": []}
        for f in funcionarios:
            perfis[f["perfil"]].append(f)

    horas     = dict(estado_acumulado["horas"])     if estado_acumulado else {str(f["id"]): 0 for f in funcionarios}
    dias_trab = dict(estado_acumulado["dias_trab"]) if estado_acumulado else {str(f["id"]): 0 for f in funcionarios}

    melhor_score, melhor_dias, melhor_outros = float("inf"), None, {}

    for tentativa in range(tentativas):
        # --------------------------------------------
        # ► Estado inicial trazido da escala anterior
        # --------------------------------------------
        c = {
            str(f["id"]): estado_continuo["consec"].get(str(f["id"]), 0) if estado_continuo else 0
            for f in funcionarios
        }
        u_turno = {
            str(f["id"]): estado_continuo["ultimo_turno"].get(str(f["id"])) if estado_continuo else None
            for f in funcionarios
        }

        stats        = {str(f["id"]): {t: 0 for t in TURNOS} for f in funcionarios}
        h_local      = dict(horas)
        d_local      = dict(dias_trab)
        seq_trab     = {str(f["id"]): 0 for f in funcionarios}
        seq_folga    = {str(f["id"]): 0 for f in funcionarios}
        parceiro_ult = {str(f["id"]): None for f in funcionarios}

        # --- BLOCO: já inicia respeitando sequências vigentes --------------
        bloco = {}
        if estado_continuo:
            for fid, cons in estado_continuo["consec"].items():
                if cons > 0 and estado_continuo["ultimo_turno"].get(fid):
                    rem = max(0, BLOCK_MIN_SIZE - cons)
                    bloco[fid] = {
                        "turno": estado_continuo["ultimo_turno"][fid],
                        "remaining": rem
                    }
        # ------------------------------------------------------------------

        dias_mes = []

        duplas5, duplas3 = gerar_duplas_iniciais(funcionarios, perfis)
        USE_START_STRATEGY = (
            not estado_continuo and  # ► desliga estratégia quando há continuidade
            len(perfis["EXP"]) >= 4 and len(perfis["AUX"]) >= 4
        )

        for dia in range(1, dias_no_mes + 1):
            data_atual = datetime(ano, mes, dia).date()
            linha = {"data": str_data(ano, mes, dia), "turnos": {}}

            disp = [
                f for f in funcionarios
                if not any(s <= data_atual <= e for s, e in info["ferias"].get(str(f["id"]), []))
            ]
            random.shuffle(disp)

            obrig_por_turno = {t: [] for t in TURNOS}
            if dia <= START_WINDOW_DIAS:
                for fid, binfo in list(bloco.items()):
                    if binfo["remaining"] <= 0:
                        bloco.pop(fid)
                        continue
                    if c[fid] >= HARD_RULES["limite_dias_consecutivos"]:
                        bloco.pop(fid)
                        continue
                    emp = next((e for e in disp if str(e["id"]) == fid), None)
                    if emp is None:
                        bloco.pop(fid)
                        continue
                    if len(obrig_por_turno[binfo["turno"]]) < 2:
                        obrig_por_turno[binfo["turno"]].append(emp)
                        disp.remove(emp)

            for turno_i, turno in enumerate(TURNOS):
                dupla = []
                dupla.extend(obrig_por_turno[turno])

                while len(dupla) < 2:
                    if dia <= START_WINDOW_DIAS and USE_START_STRATEGY and not dupla:
                        src = duplas5 if dia <= 5 else duplas3
                        if turno_i < len(src):
                            op1, op2 = src[turno_i]
                            if (op1 not in disp) or (op2 not in disp):
                                op1, op2 = escolher_dupla_fallback(disp, disp, funcionarios)
                        else:
                            op1, op2 = escolher_dupla_fallback(disp, disp, funcionarios)
                    else:
                        exp_pool = [f for f in disp if f["perfil"] == "EXP"]
                        aux_pool = [f for f in disp if f["perfil"] == "AUX"]
                        if FLEXIBILIZAR and (len(exp_pool) < 1 or len(aux_pool) < 1):
                            op1, op2 = random.sample(disp, 2) if len(disp) >= 2 else random.sample(funcionarios, 2)
                        else:
                            op1 = escolher_func(exp_pool, turno, h_local, c, dia, info["preferencias"],
                                                u_turno, stats, params, data_atual, info,
                                                mes_acum_horas, seq_trab, seq_folga,
                                                parceiro_ult, None, estado_continuo)
                            op2 = escolher_func(aux_pool, turno, h_local, c, dia, info["preferencias"],
                                                u_turno, stats, params, data_atual, info,
                                                mes_acum_horas, seq_trab, seq_folga,
                                                parceiro_ult, op1["id"], estado_continuo)
                    candidatos = [op1, op2]
                    for op in candidatos:
                        if op in disp and op not in dupla and len(dupla) < 2:
                            dupla.append(op)
                            disp.remove(op)
                    if len(dupla) < 2:
                        if disp:
                            op_rand = random.choice(disp)
                            disp.remove(op_rand)
                        else:
                            remaining = [f for f in funcionarios if f not in dupla]
                            op_rand = random.choice(remaining)
                        if op_rand not in dupla:
                            dupla.append(op_rand)

                linha["turnos"][turno] = dupla

                for op in dupla:
                    fid = str(op["id"])
                    h_local[fid] += HORAS_POR_TURNO
                    c[fid]       += 1
                    stats[fid][turno] += 1
                    parceiro_ult[fid] = dupla[1]["id"] if op is dupla[0] else dupla[0]["id"]
                    u_turno[fid]      = turno
                    d_local[fid]     += 1

                    if dia <= START_WINDOW_DIAS:
                        if fid not in bloco:
                            bloco[fid] = {"turno": turno, "remaining": BLOCK_MIN_SIZE - 1}
                        else:
                            if bloco[fid]["turno"] == turno and bloco[fid]["remaining"] > 0:
                                bloco[fid]["remaining"] -= 1
                            if bloco[fid]["remaining"] <= 0:
                                bloco.pop(fid, None)

            ids_trab = {str(e["id"]) for t in TURNOS for e in linha["turnos"][t]}
            for f in funcionarios:
                fid = str(f["id"])
                if fid in ids_trab:
                    seq_trab[fid] += 1
                    seq_folga[fid] = 0
                else:
                    seq_trab[fid] = 0
                    seq_folga[fid] += 1
                    c[fid] = 0
            dias_mes.append(linha)

        valores = h_local.values()
        score   = (max(valores) - min(valores)) + statistics.mean(valores) / 5
        if score < melhor_score:
            melhor_score = score
            melhor_dias  = dias_mes
            melhor_outros = {"horas": h_local, "stats": stats, "dias_trab": d_local}

    dias_out = [
        {
            "data":  d["data"],
            "turnos": {t: [f["nome"] for f in dupla] for t, dupla in d["turnos"].items()},
        }
        for d in melhor_dias
    ]
    parecer = gerar_parecer_escala(dias_out, funcionarios)
    print(f"\033[92mMelhor score {ano}-{parse_mes(mes)}: {melhor_score:.2f}\033[0m")

    return {
        "dias":    dias_out,
        **melhor_outros,
        "score":   melhor_score,
        "parecer": parecer,
    }

# ========================
#   FUNÇÃO AUX – dupla fallback
# ========================
def escolher_dupla_fallback(disp, aux_pool, funcionarios):
    if not disp:
        disp[:] = aux_pool or funcionarios
    op1 = random.choice(disp)
    op2 = random.choice(aux_pool)
    while op2["id"] == op1["id"]:
        op2 = random.choice(aux_pool)
    return op1, op2

# ========================
#   GERADOR DE ESCALA (ANO)
# ========================
def gerar_escala_ano(ano, mes_inicio, funcionarios, params, info,
                     FLEXIBILIZAR=True, tentativas=50):
    resultados = {}
    estado = None
    for m in range(int(mes_inicio), 13):
        print(f"\033[94mGerando escala para {ano}-{parse_mes(m)}\033[0m")
        res = gerar_escala_mes(
            ano, m, funcionarios, params, info,
            estado_acumulado=estado, FLEXIBILIZAR=FLEXIBILIZAR,
            tentativas=tentativas, mes_acum_horas=estado["horas"] if estado else None,
        )
        chave = f"{ano}-{parse_mes(m)}"
        resultados[chave] = res
        estado = {"horas": res["horas"], "dias_trab": res["dias_trab"]}
    return {"ano": ano, "mes_inicio": parse_mes(mes_inicio), "escala": resultados}

# ========================
#   HANDLER WEB
# ========================
def main(request):
    try:
        if request.method == "OPTIONS":
            return ("", 204, _cors_headers())
        if request.method != "POST":
            return _json({"erro": "Use POST"}, status=405)

        payload       = request.get_json(force=True)
        ano           = int(payload["ano"])
        mes_inicio    = int(payload["mes_inicio"])
        funcionarios  = payload["funcionarios"]
        params        = payload.get("parametros", {})
        tentativas    = int(params.get("quantidade_escalas", 50))
        FLEX          = bool(params.get("permite_dupla_exp", True) and params.get("permite_dupla_aux", True))

        info = {
            "ferias":       parse_ferias(payload.get("ferias")),
            "preferencias": parse_preferencias(payload.get("preferencias")),
            "restricoes":   parse_restricoes(payload.get("restricoes")),
        }

        estado_continuo = None
        if payload.get("gerar_continua"):
            estado_continuo = preparar_estado_continuo(
                payload.get("escala_mes_anterior"),
                funcionarios
            )

        if payload.get("tipo", "ano") == "mes":
            res = gerar_escala_mes(
                ano, mes_inicio, funcionarios, params, info,
                FLEXIBILIZAR=FLEX, tentativas=tentativas,
                estado_continuo=estado_continuo,
            )
            return _json(res)

        res = gerar_escala_ano(
            ano, mes_inicio, funcionarios, params, info,
            FLEXIBILIZAR=FLEX, tentativas=tentativas,
        )
        return _json(res)

    except Exception as e:
        print("\033[91m[ERRO]\033[0m", e)
        return _json({"erro": "Falha inesperada", "detalhe": str(e)}, status=500)


# ==========================
#   Prepara start continuo
# ==========================
def preparar_estado_continuo(escala_mes_anterior, funcionarios):
    """
    Lê a escala do mês anterior (inteira) e reconstrói o estado inicial
    para a geração contínua.

    Retorna:
        estado = {
            "consec": {fid: int},
            "ultimo_turno": {fid: str|None},
            "dias_trabalhados": {fid: int},
            "pipocacoes": {fid: int},
            "penalidade_start": {fid: float}
        }
    """

    if not escala_mes_anterior or "dias" not in escala_mes_anterior:
        return None

    fids_validos = {str(f["id"]) for f in funcionarios}

    consec           = {fid: 0 for fid in fids_validos}
    ultimo_turno     = {fid: None for fid in fids_validos}
    dias_trabalhados = {fid: 0 for fid in fids_validos}
    pipocacoes       = {fid: 0 for fid in fids_validos}

    dias = sorted(escala_mes_anterior["dias"], key=lambda d: d["data"])
    trabalhou_ontem = {fid: False for fid in fids_validos}

    for dia in dias:
        trabalhou_hoje = {fid: False for fid in fids_validos}

        for turno, pessoas in dia["turnos"].items():
            for p in pessoas:
                fid = str(p["funcionario_id"])
                if fid not in fids_validos:
                    continue

                trabalhou_hoje[fid] = True
                dias_trabalhados[fid] += 1

                if trabalhou_ontem[fid]:
                    consec[fid] += 1
                else:
                    consec[fid] = 1

                if ultimo_turno[fid] and ultimo_turno[fid] != turno:
                    if consec[fid] <= 2:
                        pipocacoes[fid] += 1

                ultimo_turno[fid] = turno

        for fid in fids_validos:
            if not trabalhou_hoje[fid]:
                if consec[fid] > 0 and consec[fid] <= 2:
                    pipocacoes[fid] += 1
                consec[fid] = 0

        trabalhou_ontem = trabalhou_hoje

    penalidade_start = {}
    max_trab = max(dias_trabalhados.values()) or 1
    max_pipo = max(pipocacoes.values()) or 1

    for fid in fids_validos:
        peso_trabalho = dias_trabalhados[fid] / max_trab
        peso_pipoca   = pipocacoes[fid] / max_pipo
        penalidade_start[fid] = peso_trabalho * 0.6 + peso_pipoca * 1.2

    return {
        "consec": consec,
        "ultimo_turno": ultimo_turno,
        "dias_trabalhados": dias_trabalhados,
        "pipocacoes": pipocacoes,
        "penalidade_start": penalidade_start
    }

# ========================
#   HELPERS HTTP
# ========================
def _cors_headers():
    return {
        "Access-Control-Allow-Origin":  "*",
        "Access-Control-Allow-Methods": "POST,OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type",
    }

def _json(obj, status=200):
    return (
        json.dumps(obj, ensure_ascii=False, indent=2),
        status,
        {"Content-Type": "application/json", **_cors_headers()},
    )
