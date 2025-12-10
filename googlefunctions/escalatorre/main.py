"""
Gerador de escalas EXP/AUX
---------------------------------
Versão revisada em 2025-12-10

• Regras duras PRIORITÁRIAS
    1. Respeita férias, datas e turnos proibidos
    2. Máx. 6 dias consecutivos de trabalho
    3. Durante sequência (consec > 0) o funcionário
       deve manter o MESMO turno
    4. Após folga (consec == 0) deve seguir o ciclo 00↔12 / 06↔18
• Regras suaves ponderadas por SOFT_WEIGHTS
• Nenhum reset de ultimo_turno durante folga
• Funções claramente separadas
"""

import json
import calendar
from datetime import datetime, timedelta
import random
import statistics

# ========================
#   CONFIGURAÇÃO DE PESOS
# ========================
# -------- HARD CONSTRAINTS (imutáveis) --------
HARD_RULES = {
    "ferias": True,
    "dia_semana_proibido": True,
    "turno_proibido": True,
    "data_proibida": True,
    # mantém ciclo apenas APÓS folga  (implementado na lógica)
    "troca_de_turno_sem_folga": True,
    # exige mesmo turno DURANTE sequência
    "mesmo_turno_sem_folga": True,
    "limite_dias_consecutivos": 6,
}

# -------- SOFT CONSTRAINTS (ajustáveis) --------
SOFT_WEIGHTS = {
    "preferencia_turno": 10,
    "balanceamento_turnos": 50,
    "dias_trabalhados": 3,
    "desequilibrio_horas": 5,
    "troca_de_turno": 50,
    # novas regras de sequência / folga
    "bonus_sequencia_mesmo_turno": 80,
    "penaliza_intercalado_trab_folga": 80,
    "bonus_folga_agrupada": 20,
}

# ========================
#   TURNOS E CONSTANTES
# ========================
TURNOS = ["00H", "06H", "12H", "18H"]
HORAS_POR_TURNO = 6

CICLO_TURNOS = {"00H": "12H", "12H": "00H", "06H": "18H", "18H": "06H"}

# ========================
#   FUNÇÕES UTILITÁRIAS
# ========================
parse_mes = lambda m: f"{int(m):02d}"
dias_do_mes = lambda y, m: calendar.monthrange(y, m)[1]
str_data = lambda y, m, d: f"{y}-{parse_mes(m)}-{int(d):02d}"

# ========================
#   PARSER DE ENTRADA
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
def restricoes_hard(fid, turno, data, info, consec, ultimo_turno):
    """Valida todas as regras duras SEM conflito."""
    # --- Férias / restrições de dia-semana / data / turno -----------------
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

    # --- Sequência / ciclo -----------------------------------------------
    ut, cons = ultimo_turno.get(fid), consec[fid]

    # 1) Durante sequência → mesmo turno obrigatório
    if cons > 0 and ut != turno:
        return False

    # 2) Após folga (cons == 0) → deve seguir ciclo se já tem histórico
    if cons == 0 and ut is not None and turno != CICLO_TURNOS[ut]:
        return False

    # 3) Limite de dias consecutivos
    if cons >= HARD_RULES["limite_dias_consecutivos"]:
        return False

    return True


# ========================
#   SCORE SOFT
# ========================
def score_func(params, func, turno, horas, consec, dia, prefs,
               ultimo_turno, stats, mes_acum_horas,
               seq_trab=None, seq_folga=None):
    fid = str(func["id"])
    s = 0

    # Preferência de turno
    if turno not in prefs.get(fid, set()):
        s += SOFT_WEIGHTS["preferencia_turno"]

    # Balanceamento interno de turnos
    media = statistics.mean(stats[fid].values())
    if stats[fid][turno] > media + 2:
        s += SOFT_WEIGHTS["balanceamento_turnos"] * (stats[fid][turno] - media)

    # Dias consecutivos
    s += consec[fid] * SOFT_WEIGHTS["dias_trabalhados"]

    # Desequilíbrio de horas acumuladas (mês/ano)
    if mes_acum_horas and fid in mes_acum_horas:
        s += (mes_acum_horas[fid] / 10) * SOFT_WEIGHTS["desequilibrio_horas"]

    # Troca de turno soft
    if ultimo_turno.get(fid) and ultimo_turno[fid] != turno:
        s += SOFT_WEIGHTS["troca_de_turno"]

    # --- Avaliação da sequência desejada (4-5 dias) -----------------------
    seq_atual = consec[fid]          # antes de ESCOLHER hoje
    continua_mesmo = ultimo_turno.get(fid) == turno
    if continua_mesmo:
        futura = seq_atual + 1
        if futura < TARGET_SEQ_MIN:
            s += SOFT_WEIGHTS["penaliza_seq_curta"]
        elif TARGET_SEQ_MIN <= futura <= TARGET_SEQ_MAX:
            s -= SOFT_WEIGHTS["bonus_seq_alvo"]
        elif futura > TARGET_SEQ_MAX:
            s += SOFT_WEIGHTS["penaliza_seq_longa"]

    # Bônus / penalidades por padrão trab-folga
    if seq_trab and seq_folga:
        if seq_trab[fid] == 1 and seq_folga[fid] == 1:
            s += SOFT_WEIGHTS["penaliza_intercalado_trab_folga"]
        if seq_folga[fid] > 1:
            s -= seq_folga[fid] * SOFT_WEIGHTS["bonus_folga_agrupada"]

    # Ruído para desempate
    s += random.uniform(-1, 1)
    return s

# ---------------------------------
#   PREFERÊNCIA DE SEQUÊNCIA
# ---------------------------------
TARGET_SEQ_MIN = 4          # queremos pelo menos 4 dias seguidos
TARGET_SEQ_MAX = 5          # e no máximo 5 (6 só se não houver alternativa)

SOFT_WEIGHTS.update({
    "penaliza_seq_curta": 120,   # sequência < 4
    "penaliza_seq_longa": 40,    # sequência > 5 (até 6)
    "bonus_seq_alvo": 100        # sequência entre 4-5 dias
})



# ========================
#   ESCOLHA DO FUNCIONÁRIO
# ========================
def escolher_func(pool, turno, horas, consec, dia, prefs,
                  ultimo_turno, stats, params, data, info,
                  mes_acum_horas, seq_trab, seq_folga):
    """Prioridade: obrigatórios ▸ pós-folga (ciclo) ▸ livres."""
    cand = [f for f in pool
            if restricoes_hard(str(f["id"]), turno, data, info, consec, ultimo_turno)]
    if not cand:
        return random.choice(pool)

    obrigatorios, pos_folga, livres = [], [], []

    for f in cand:
        fid, ut, cons = str(f["id"]), ultimo_turno.get(str(f["id"])), consec[str(f["id"])]

        if cons > 0:                      # sequência em andamento
            if ut == turno:
                obrigatorios.append(f)
            else:
                # quebra prematura (<4 dias) não permitida
                if cons < TARGET_SEQ_MIN:
                    continue
                livres.append(f)
            continue

        if cons == 0 and ut is not None:  # acabou de folgar
            if turno == CICLO_TURNOS[ut]:
                pos_folga.append(f)
            continue

        livres.append(f)                  # sem histórico

    escolha_pool = obrigatorios or pos_folga or livres or cand

    return min(
        escolha_pool,
        key=lambda fx: score_func(
            params, fx, turno, horas, consec, dia, prefs,
            ultimo_turno, stats, mes_acum_horas, seq_trab, seq_folga
        )
    )



# ========================
#   PARECER / RELATÓRIO
# ========================
def gerar_parecer_escala(dias, funcionarios):
    p = {
        str(f["id"]): {
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
            "trocas_de_turno": 0,
        }
        for f in funcionarios
    }

    ult = {str(f["id"]): None for f in funcionarios}
    seq_trab, seq_t_mesmo = {}, {}
    for fid in p:
        seq_trab[fid] = seq_t_mesmo[fid] = 0

    for dia in dias:
        trabalhou = {str(f["id"]): False for f in funcionarios}
        # percorre turnos
        for turno, dupla in dia["turnos"].items():
            for nome in dupla:
                fid = next((str(f["id"]) for f in funcionarios if f["nome"] == nome), None)
                if fid is None:
                    continue
                pr = p[fid]
                if not trabalhou[fid]:
                    pr["dias_trabalhados"] += 1
                trabalhou[fid] = True
                pr["total_horas"] += 6
                pr[f"vezes_{turno.lower()}"] += 1

                if ult[fid] == turno:
                    seq_t_mesmo[fid] += 1
                else:
                    if seq_t_mesmo[fid]:
                        pr["menor_seq_dias_mesmo_turno"] = (
                            seq_t_mesmo[fid]
                            if pr["menor_seq_dias_mesmo_turno"] is None
                            else min(pr["menor_seq_dias_mesmo_turno"], seq_t_mesmo[fid])
                        )
                    seq_t_mesmo[fid] = 1
                    if ult[fid] is not None:
                        pr["trocas_de_turno"] += 1
                ult[fid] = turno

        # atualiza sequências diário
        for f in funcionarios:
            fid = str(f["id"])
            if trabalhou[fid]:
                seq_trab[fid] += 1
                p[fid]["maior_seq_dias_trab"] = max(
                    p[fid]["maior_seq_dias_trab"], seq_trab[fid]
                )
            else:
                if seq_t_mesmo[fid]:
                    p[fid]["menor_seq_dias_mesmo_turno"] = (
                        seq_t_mesmo[fid]
                        if p[fid]["menor_seq_dias_mesmo_turno"] is None
                        else min(
                            p[fid]["menor_seq_dias_mesmo_turno"], seq_t_mesmo[fid]
                        )
                    )
                seq_trab[fid] = seq_t_mesmo[fid] = 0
                # NÃO zera ult[fid]; apenas manter registro p/ ciclo

    for fid, pr in p.items():
        pr["dias_folga"] = len(dias) - pr["dias_trabalhados"]
        if pr["menor_seq_dias_mesmo_turno"] is None:
            pr["menor_seq_dias_mesmo_turno"] = 1
    return list(p.values())


# ========================
#   GERADOR DE ESCALA (MÊS)
# ========================
def gerar_escala_mes(
    ano,
    mes,
    funcionarios,
    params,
    info,
    estado_acumulado=None,
    FLEXIBILIZAR=True,
    tentativas=50,
    perfis=None,
    mes_acum_horas=None,
):
    dias_no_mes = dias_do_mes(ano, mes)
    if perfis is None:
        perfis = {"EXP": [], "AUX": []}
        for f in funcionarios:
            perfis[f["perfil"]].append(f)

    # estado acumulado de anos/meses anteriores
    horas = (
        dict(estado_acumulado["horas"])
        if estado_acumulado
        else {str(f["id"]): 0 for f in funcionarios}
    )
    dias_trab = (
        dict(estado_acumulado["dias_trab"])
        if estado_acumulado
        else {str(f["id"]): 0 for f in funcionarios}
    )

    melhor_score, melhor_dias, melhor_outros = float("inf"), None, {}

    for _ in range(tentativas):
        c = {str(f["id"]): 0 for f in funcionarios}
        u_turno = {str(f["id"]): None for f in funcionarios}
        stats = {str(f["id"]): {t: 0 for t in TURNOS} for f in funcionarios}
        h_local = dict(horas)
        d_local = dict(dias_trab)

        seq_trab = {str(f["id"]): 0 for f in funcionarios}
        seq_folga = {str(f["id"]): 0 for f in funcionarios}

        dias_mes = []
        for dia in range(1, dias_no_mes + 1):
            data_atual = datetime(ano, mes, dia).date()
            linha = {"data": str_data(ano, mes, dia), "turnos": {}}
            disp = funcionarios.copy()
            random.shuffle(disp)

            for turno in TURNOS:
                exp_pool = [f for f in disp if f["perfil"] == "EXP"]
                aux_pool = [f for f in disp if f["perfil"] == "AUX"]

                if FLEXIBILIZAR and (len(exp_pool) < 1 or len(aux_pool) < 1):
                    op1, op2 = random.sample(disp, 2)
                else:
                    op1 = escolher_func(
                        exp_pool,
                        turno,
                        h_local,
                        c,
                        dia,
                        info["preferencias"],
                        u_turno,
                        stats,
                        params,
                        data_atual,
                        info,
                        mes_acum_horas,
                        seq_trab,
                        seq_folga,
                    )
                    op2 = escolher_func(
                        aux_pool,
                        turno,
                        h_local,
                        c,
                        dia,
                        info["preferencias"],
                        u_turno,
                        stats,
                        params,
                        data_atual,
                        info,
                        mes_acum_horas,
                        seq_trab,
                        seq_folga,
                    )

                linha["turnos"][turno] = [op1, op2]

                # atualiza estados
                for op in (op1, op2):
                    fid = str(op["id"])
                    h_local[fid] += HORAS_POR_TURNO
                    c[fid] += 1
                    stats[fid][turno] += 1
                    u_turno[fid] = turno
                    d_local[fid] += 1
                    disp.remove(op)

            # pós-dia: seq_trab / seq_folga
            ids_trabalharam = {
                str(e["id"]) for t in TURNOS for e in linha["turnos"][t]
            }
            for f in funcionarios:
                fid = str(f["id"])
                if fid in ids_trabalharam:
                    seq_trab[fid] += 1
                    seq_folga[fid] = 0
                else:
                    seq_trab[fid] = 0
                    seq_folga[fid] += 1
                    c[fid] = 0  # encerra sequência, mas mantém u_turno p/ ciclo

            dias_mes.append(linha)

        # score simples: diferença de horas + média/5
        valores = h_local.values()
        score = (max(valores) - min(valores)) + statistics.mean(valores) / 5
        if score < melhor_score:
            melhor_score = score
            melhor_dias = dias_mes
            melhor_outros = {
                "horas": h_local,
                "stats": stats,
                "dias_trab": d_local,
            }

    # gerar saída
    dias_out = [
        {
            "data": d["data"],
            "turnos": {t: [f["nome"] for f in dupla] for t, dupla in d["turnos"].items()},
        }
        for d in melhor_dias
    ]
    parecer = gerar_parecer_escala(dias_out, funcionarios)

    return {
        "dias": dias_out,
        **melhor_outros,
        "score": melhor_score,
        "parecer": parecer,
    }


# ========================
#   GERADOR DE ESCALA (ANO)
# ========================
def gerar_escala_ano(
    ano,
    mes_inicio,
    funcionarios,
    params,
    info,
    FLEXIBILIZAR=True,
    tentativas=50,
):
    resultados = {}
    estado = None
    for m in range(int(mes_inicio), 13):
        res = gerar_escala_mes(
            ano,
            m,
            funcionarios,
            params,
            info,
            estado_acumulado=estado,
            FLEXIBILIZAR=FLEXIBILIZAR,
            tentativas=tentativas,
            mes_acum_horas=estado["horas"] if estado else None,
        )
        chave = f"{ano}-{parse_mes(m)}"
        resultados[chave] = res
        estado = {"horas": res["horas"], "dias_trab": res["dias_trab"]}
    return {"ano": ano, "mes_inicio": parse_mes(mes_inicio), "escala": resultados}


# ========================
#   HANDLER WEB (opcional Cloud Function)
# ========================
def main(request):
    try:
        if request.method == "OPTIONS":
            return ("", 204, _cors_headers())
        if request.method != "POST":
            return _json({"erro": "Use POST"}, status=405)

        payload = request.get_json(force=True)
        ano = int(payload["ano"])
        mes_inicio = int(payload["mes_inicio"])
        funcionarios = payload["funcionarios"]
        params = payload.get("parametros", {})
        tentativas = int(params.get("quantidade_escalas", 50))
        FLEX = bool(params.get("permite_dupla_exp", True) and params.get("permite_dupla_aux", True))

        info = {
            "ferias": parse_ferias(payload.get("ferias")),
            "preferencias": parse_preferencias(payload.get("preferencias")),
            "restricoes": parse_restricoes(payload.get("restricoes")),
        }

        if payload.get("tipo", "ano") == "mes":
            res = gerar_escala_mes(
                ano,
                mes_inicio,
                funcionarios,
                params,
                info,
                FLEXIBILIZAR=FLEX,
                tentativas=tentativas,
            )
            return _json(res)
        res = gerar_escala_ano(
            ano,
            mes_inicio,
            funcionarios,
            params,
            info,
            FLEXIBILIZAR=FLEX,
            tentativas=tentativas,
        )
        return _json(res)
    except Exception as e:
        return _json({"erro": "Falha inesperada", "detalhe": str(e)}, status=500)


# ========================
#   HELPERS HTTP
# ========================
def _cors_headers():
    return {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "POST,OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type",
    }


def _json(obj, status=200):
    return (
        json.dumps(obj, ensure_ascii=False, indent=2),
        status,
        {"Content-Type": "application/json", **_cors_headers()},
    )
