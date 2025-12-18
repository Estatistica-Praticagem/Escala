# Gerador de escalas EXP/AUX – versão refatorada em 2025-12-18
# ------------------------------------------------------------
# Mantém 100 % de compatibilidade de I/O: main(request),
# gerar_parecer_escala, gerar_escala_mes e gerar_escala_ano continuam
# iguais por fora. Toda a inteligência de construção diária foi
# isolada no bloco MOTOR_DE_ESCALA, facilitando futuras evoluções.

import json
import calendar
import random
import statistics
import math
from datetime import datetime, timedelta

HORAS_POR_TURNO = 6  # usado fora do motor (parecer)


# ========================
# PARSERS / INPUT
# ========================

parse_mes   = lambda m: f"{int(m):02d}"
dias_do_mes = lambda y, m: calendar.monthrange(y, m)[1]
str_data    = lambda y, m, d: f"{y}-{parse_mes(m)}-{int(d):02d}"


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
            tset = {t.strip() for t in r["turnos_permitidos"].split(",") if t.strip()}
            out["turno_permitido_por_dia"].setdefault(fid, {})[ds] = tset
    return out


# ========================
# MOTOR_DE_ESCALA (ISOLADO)
# ========================
"""
Responsabilidade:
    • Gerar a grade de dias de um mês (‘dias_mes_raw’), alocando duplas EXP/AUX
      em cada turno, obedecendo constraints hard/soft, férias, preferências etc.
    • Retornar também métricas auxiliares (horas, dias_trab, stats, score).

Entradas:
    ano, mes, funcionarios, params, info
    (ver assinatura motor_gerar_dias_mes)

Saídas:
    {
        "dias":      dias_mes_raw,   # lista de dicionários com objetos funcionário
        "horas":     dict {fid: int},
        "stats":     dict {fid: {turno: cont}},
        "dias_trab": dict {fid: int},
        "score":     float
    }

O QUE NÃO ALTERAR FORA DO BLOCO:
    • Funções públicas (main, gerar_escala_mes, gerar_escala_ano, gerar_parecer_escala)
    • Formatos de JSON de entrada/saída
    • Nome dos turnos
"""

# --- CONSTANTES / CONFIG DO MOTOR ---------------------------------
START_WINDOW_DIAS    = 7
MAX_SEQ_START_WINDOW = 4  # continua válido apenas para primeiras tentativas

TURNOS       = ["00H", "06H", "12H", "18H"]
CICLO_TURNOS = {"00H": "18H", "18H": "12H", "12H": "06H", "06H": "00H"}

HARD_RULES = {
    "ferias": True,
    "dia_semana_proibido": True,
    "turno_proibido": True,
    "data_proibida": True,
    "troca_de_turno_sem_folga": True,
    "mesmo_turno_sem_folga": True,
    "limite_dias_consecutivos": 6,
    "limite_dias_mesmo_turno": 8,
}

SOFT_WEIGHTS = {
    # ---------- PENALTIES ----------
    "balanceamento_turnos":            720,
    "penaliza_zero_turno":             300,
    "penaliza_intercalado_trab_folga": 500,
    "penaliza_seq_curta":              460,
    "penaliza_seq_longa":              460,
    "penaliza_ausencia_turno":         700,
    "troca_de_turno":                  480,
    "penaliza_parceiro_repetido":       0,
    "dias_trabalhados":                 0,
    "desequilibrio_horas":             400,
    # ---------- BONUSES ------------
    "preferencia_turno":              -15,
    "bonus_seq_alvo":                -500,
    "bonus_folga_agrupada":          -400,
    "bonus_sequencia_mesmo_turno":   -500,
}

TARGET_SEQ_MIN = 4  # ainda usado pelo score herdado
BLOCK_MIN_SIZE = TARGET_SEQ_MIN

clamp = lambda x, a, b: max(a, min(b, x))
# -------------------------------------------------------------------


def limite_consecutivo(dia_corrente):
    return MAX_SEQ_START_WINDOW if dia_corrente <= START_WINDOW_DIAS else HARD_RULES["limite_dias_consecutivos"]


# ---------- HARD CONSTRAINTS ----------
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

    return True


# ---------- SOFT SCORE ----------
def score_func(params, func, turno, horas, consec, dia, prefs,
               ultimo_turno, stats, mes_acum_horas, dias_trab_mes,
               seq_trab=None, seq_folga=None, parceiro_ult=None, parceiro_atual=None,
               estado_continuo=None, dias_semana=None, week_id=None, meta_semana=None):
    fid = str(func["id"])
    s = 0

    if dias_semana is not None and week_id is not None and meta_semana is not None:
        trabalhou_semana = dias_semana.get(fid, {}).get(week_id, 0)
        if trabalhou_semana >= meta_semana:
            s += 5000
        elif trabalhou_semana == meta_semana - 1:
            s += 800

    if estado_continuo and dia <= START_WINDOW_DIAS:
        s += estado_continuo["penalidade_start"].get(fid, 0) * 800

    if turno in prefs.get(fid, set()):
        s += SOFT_WEIGHTS["preferencia_turno"]

    ut_prev = ultimo_turno.get(fid)
    if consec[fid] > 0 and ut_prev and turno != ut_prev and stats[fid][ut_prev] < 4 and dia > START_WINDOW_DIAS:
        s += 250

    total_turnos = sum(stats[fid].values())
    target = (total_turnos + 1) / 4 if total_turnos else 0.25
    futura = stats[fid][turno] + 1
    diff = futura - target
    s += SOFT_WEIGHTS["balanceamento_turnos"] * (diff ** 2)

    if dia >= 10 and stats[fid][turno] == 0:
        s += SOFT_WEIGHTS["penaliza_ausencia_turno"]

    if consec[fid] > 0 and ultimo_turno.get(fid) and ultimo_turno[fid] != turno:
        s += SOFT_WEIGHTS["troca_de_turno"]

    if stats[fid][turno] >= HARD_RULES["limite_dias_mesmo_turno"]:
        s += 120 + 40 * (stats[fid][turno] - HARD_RULES["limite_dias_mesmo_turno"])

    seq_atual = consec[fid]
    continua  = ultimo_turno.get(fid) == turno
    if continua:
        futura = seq_atual + 1
        if futura < 4:
            s += SOFT_WEIGHTS["bonus_sequencia_mesmo_turno"] * 0.10
        elif futura == 4:
            s += SOFT_WEIGHTS["bonus_seq_alvo"]
        else:
            s += SOFT_WEIGHTS["penaliza_seq_longa"]

    if seq_folga and seq_trab:
        if seq_trab[fid] == 1 and seq_folga[fid] == 1:
            s += SOFT_WEIGHTS["penaliza_intercalado_trab_folga"]
        if seq_folga[fid] >= 2:
            s += seq_folga[fid] * SOFT_WEIGHTS["bonus_folga_agrupada"]

    if parceiro_ult and parceiro_ult.get(fid) == parceiro_atual:
        s += SOFT_WEIGHTS["penaliza_parceiro_repetido"]

    if mes_acum_horas and fid in mes_acum_horas:
        s += (mes_acum_horas[fid] / 10) * SOFT_WEIGHTS["desequilibrio_horas"]

    futura_dias_trab = dias_trab_mes.get(fid, 0) + 1
    diff_days = abs(futura_dias_trab - 21)
    s += diff_days * 45

    return s + random.uniform(-1, 1)


# ---------- ESCOLHA DO FUNCIONÁRIO (ajuste de fallback seguro) ----------
def escolher_func(pool, turno, horas, consec, dia, prefs,
                  ultimo_turno, stats, params, data, info,
                  mes_acum_horas, seq_trab, seq_folga,
                  parceiro_ult, parceiro_candidato, estado_continuo,
                  dias_trab_mes, dias_semana, week_id, meta_semana,
                  folga_rest):

    cand = [
        f for f in pool
        if folga_rest.get(str(f["id"]), 0) == 0 and
           restricoes_hard(str(f["id"]), turno, data, info, consec, ultimo_turno, stats)
    ]
    if not cand:
        cand = [f for f in pool if folga_rest.get(str(f["id"]), 0) == 0]

    if not cand:  # último recurso
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
    if not escolha_pool:  # garantia contra sequência vazia
        return random.choice(cand)

    return min(
        escolha_pool,
        key=lambda fx: score_func(
            params, fx, turno, horas, consec, dia, prefs,
            ultimo_turno, stats, mes_acum_horas,
            dias_trab_mes=dias_trab_mes,
            seq_trab=seq_trab, seq_folga=seq_folga,
            parceiro_ult=parceiro_ult, parceiro_atual=parceiro_candidato,
            estado_continuo=estado_continuo,
            dias_semana=dias_semana, week_id=week_id, meta_semana=meta_semana
        )
    )

# ---------- SUPORTE – duplas iniciais ----------
def gerar_duplas_iniciais(funcionarios, perfis):
    exp, aux = perfis["EXP"][:], perfis["AUX"][:]
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



# ---------- SUPORTE – dupla fallback (pequeno ajuste para segurança) ----------
def escolher_dupla_fallback(disp, aux_pool, funcionarios, folga_rest):
    principal_pool = [f for f in (disp if disp else (aux_pool if aux_pool else funcionarios))
                      if folga_rest.get(str(f["id"]), 0) == 0]
    if not principal_pool:
        principal_pool = [f for f in funcionarios if folga_rest.get(str(f["id"]), 0) == 0] or funcionarios
    op1 = random.choice(principal_pool)

    pool2 = [f for f in principal_pool if f["id"] != op1["id"]] or \
            [f for f in funcionarios if f["id"] != op1["id"]]
    op2 = random.choice(pool2)
    return op1, op2


# ---------- MOTOR PRINCIPAL ----------
def motor_gerar_dias_mes(ano, mes, funcionarios, params, info,
                         estado_acumulado=None, estado_continuo=None,
                         FLEXIBILIZAR=True, tentativas=50, perfis=None,
                         mes_acum_horas=None):
    """Bloco gerador puro: devolve grade crua + métricas."""
    funcionarios = [f for f in funcionarios if f.get("perfil") in ("EXP", "AUX")]
    dias_no_mes  = dias_do_mes(ano, mes)

    if perfis is None:
        perfis = {"EXP": [], "AUX": []}
        for f in funcionarios:
            perfis[f["perfil"]].append(f)

    horas     = dict(estado_acumulado["horas"])     if estado_acumulado else {str(f["id"]): 0 for f in funcionarios}
    dias_trab = dict(estado_acumulado["dias_trab"]) if estado_acumulado else {str(f["id"]): 0 for f in funcionarios}

    melhor_score, melhor_dias, melhor_outros = float("inf"), None, {}

    # ---------- inicial fixo para semana/padrão ----------
    week_alvos_cache = {}  # week_id -> dias_trab_alvo

    for _ in range(tentativas):

        # --- estado de sequência hard do código antigo ---
        c = {str(f["id"]): estado_continuo["consec"].get(str(f["id"]), 0) if estado_continuo else 0
             for f in funcionarios}
        u_turno = {str(f["id"]): estado_continuo["ultimo_turno"].get(str(f["id"])) if estado_continuo else None
                   for f in funcionarios}

        # ---------- estado de novo ciclo 4/5 x 3/2 ----------
        trab_rest        = {str(f["id"]): 0 for f in funcionarios}
        folga_rest       = {str(f["id"]): 0 for f in funcionarios}
        alvo_trab_atual  = {str(f["id"]): None for f in funcionarios}
        alvo_folga_atual = {str(f["id"]): None for f in funcionarios}

        if estado_continuo:
            for fid, cons in estado_continuo["consec"].items():
                if cons > 0:
                    alvo = 5 if cons >= 5 else 4
                    alvo_trab_atual[fid] = alvo
                    alvo_folga_atual[fid] = 7 - alvo
                    trab_rest[fid] = max(0, alvo - cons)

        stats        = {str(f["id"]): {t: 0 for t in TURNOS} for f in funcionarios}
        h_local      = dict(horas)
        d_local      = dict(dias_trab)
        dias_trab_mes = {str(f["id"]): 0 for f in funcionarios}
        seq_trab     = {str(f["id"]): 0 for f in funcionarios}
        seq_folga    = {str(f["id"]): 0 for f in funcionarios}
        parceiro_ult = {str(f["id"]): None for f in funcionarios}
        dias_semana  = {str(f["id"]): {} for f in funcionarios}

        bloco_inicial = {}
        if estado_continuo:
            for fid, cons in estado_continuo["consec"].items():
                if cons > 0 and estado_continuo["ultimo_turno"].get(fid):
                    rem = max(0, BLOCK_MIN_SIZE - cons)
                    bloco_inicial[fid] = {"turno": estado_continuo["ultimo_turno"][fid], "remaining": rem}

        dias_mes = []
        duplas5, duplas3 = gerar_duplas_iniciais(funcionarios, perfis)
        use_start_strategy = (
            not estado_continuo and
            len(perfis["EXP"]) >= 4 and len(perfis["AUX"]) >= 4
        )

        for dia in range(1, dias_no_mes + 1):
            data_atual = datetime(ano, mes, dia).date()
            week_year, week_num, _ = data_atual.isocalendar()
            week_id = f"{week_year}-{week_num:02d}"

            # ---------- calcula alvo semanal se ainda não houver ----------
            if week_id not in week_alvos_cache:
                monday = datetime.fromisocalendar(week_year, week_num, 1).date()
                sunday = monday + timedelta(days=6)

                ativos = 0
                for f in funcionarios:
                    fid = str(f["id"])
                    ausente_semana = False
                    for ini, fim in info["ferias"].get(fid, []):
                        if ini <= monday and fim >= sunday:
                            ausente_semana = True
                            break
                    if not ausente_semana:
                        ativos += 1
                ativos = max(1, ativos)
                meta_semana = math.ceil(56 / ativos)
                dias_trab_alvo = clamp(meta_semana, 4, 5)
                week_alvos_cache[week_id] = dias_trab_alvo
            else:
                dias_trab_alvo = week_alvos_cache[week_id]

            linha = {"data": str_data(ano, mes, dia), "turnos": {}}
            alocados_hoje = set()

            disp = [
                f for f in funcionarios
                if folga_rest[str(f["id"])] == 0 and
                   not any(s <= data_atual <= e for s, e in info["ferias"].get(str(f["id"]), []))
            ]
            random.shuffle(disp)

            obrig_por_turno = {t: [] for t in TURNOS}
            if dia <= START_WINDOW_DIAS:
                for fid, binfo in list(bloco_inicial.items()):
                    if binfo["remaining"] <= 0 or c[fid] >= HARD_RULES["limite_dias_consecutivos"]:
                        bloco_inicial.pop(fid); continue
                    emp = next((e for e in disp if str(e["id"]) == fid), None)
                    if not emp:
                        bloco_inicial.pop(fid); continue
                    if len(obrig_por_turno[binfo["turno"]]) < 2:
                        obrig_por_turno[binfo["turno"]].append(emp)
                        disp.remove(emp)

            for turno_i, turno in enumerate(TURNOS):
                dupla = []
                dupla.extend(obrig_por_turno[turno])
                for emp in dupla:
                    alocados_hoje.add(str(emp["id"]))

                while len(dupla) < 2:
                    if dia <= START_WINDOW_DIAS and use_start_strategy and not dupla:
                        src = duplas5 if dia <= 5 else duplas3
                        if turno_i < len(src):
                            op1, op2 = src[turno_i]
                            if (op1 not in disp) or (op2 not in disp):
                                op1, op2 = escolher_dupla_fallback(disp, disp, funcionarios, folga_rest)
                        else:
                            op1, op2 = escolher_dupla_fallback(disp, disp, funcionarios, folga_rest)
                    else:
                        exp_pool = [f for f in disp if f["perfil"] == "EXP" and str(f["id"]) not in alocados_hoje]
                        aux_pool = [f for f in disp if f["perfil"] == "AUX" and str(f["id"]) not in alocados_hoje]
                        if FLEXIBILIZAR and (len(exp_pool) < 1 or len(aux_pool) < 1):
                            global_pool = [f for f in funcionarios
                                           if str(f["id"]) not in alocados_hoje and folga_rest[str(f["id"])] == 0]
                            if len(global_pool) >= 2:
                                op1, op2 = random.sample(global_pool, 2)
                            else:
                                op1, op2 = escolher_dupla_fallback([], [], funcionarios, folga_rest)
                        else:
                            op1 = escolher_func(
                                exp_pool, turno, h_local, c, dia, info["preferencias"],
                                u_turno, stats, params, data_atual, info,
                                mes_acum_horas, seq_trab, seq_folga,
                                parceiro_ult, None, estado_continuo,
                                dias_trab_mes, dias_semana, week_id, dias_trab_alvo,
                                folga_rest)
                            op2 = escolher_func(
                                aux_pool, turno, h_local, c, dia, info["preferencias"],
                                u_turno, stats, params, data_atual, info,
                                mes_acum_horas, seq_trab, seq_folga,
                                parceiro_ult, op1["id"], estado_continuo,
                                dias_trab_mes, dias_semana, week_id, dias_trab_alvo,
                                folga_rest)
                    candidatos = [op1, op2]
                    for op in candidatos:
                        if op in disp and op not in dupla and len(dupla) < 2:
                            dupla.append(op); disp.remove(op); alocados_hoje.add(str(op["id"]))
                    if len(dupla) < 2:
                        op_rand = random.choice([f for f in disp if folga_rest[str(f["id"])] == 0]) if disp \
                                  else random.choice([f for f in funcionarios
                                                      if f not in dupla and folga_rest[str(f["id"])] == 0])
                        dupla.append(op_rand); alocados_hoje.add(str(op_rand["id"]))
                        if op_rand in disp: disp.remove(op_rand)

                linha["turnos"][turno] = dupla

                for op in dupla:
                    fid = str(op["id"])
                    stats[fid][turno] += 1
                    parceiro_ult[fid] = dupla[1]["id"] if op is dupla[0] else dupla[0]["id"]
                    u_turno[fid]      = turno

            ids_trab = {str(e["id"]) for t in TURNOS for e in linha["turnos"][t]}

            # ---------- update horas e stats gerais ----------
            for fid in ids_trab:
                h_local[fid] += HORAS_POR_TURNO
                c[fid] += 1
                d_local[fid] += 1
                dias_trab_mes[fid] += 1
                dias_semana[fid][week_id] = dias_semana[fid].get(week_id, 0) + 1

            # ---------- UPDATE DO NOVO CICLO (obrigatório) ----------
            for fid in ids_trab:
                # início de ciclo se estava livre
                if trab_rest[fid] == 0 and folga_rest[fid] == 0:
                    alvo_trab_atual[fid]  = dias_trab_alvo
                    alvo_folga_atual[fid] = 7 - dias_trab_alvo
                    trab_rest[fid]        = alvo_trab_atual[fid]

                # consome um dia de trabalho
                trab_rest[fid] = max(0, trab_rest[fid] - 1)

                # se acabou bloco de trabalho, agenda folga
                if trab_rest[fid] == 0:
                    folga_rest[fid] = alvo_folga_atual[fid]

            for f in funcionarios:
                fid = str(f["id"])
                if fid not in ids_trab:
                    if folga_rest[fid] > 0:
                        folga_rest[fid] = max(0, folga_rest[fid] - 1)
                    elif trab_rest[fid] > 0:
                        # quebrou bloco de trabalho
                        trab_rest[fid] = 0
                        folga_rest[fid] = alvo_folga_atual[fid] if alvo_folga_atual[fid] is not None else 2

            # ---------- sequências antigas ----------
            for f in funcionarios:
                fid = str(f["id"])
                if fid in ids_trab:
                    seq_trab[fid] += 1; seq_folga[fid] = 0
                else:
                    seq_trab[fid] = 0; seq_folga[fid] += 1; c[fid] = 0

            dias_mes.append(linha)

            # fim do mês, calcula score seguro
        valores = list(h_local.values())
        if not valores:        # evita erro de sequência vazia
            continue
        score = (max(valores) - min(valores)) + statistics.mean(valores) / 5
        if score < melhor_score:
            melhor_score = score
            melhor_dias  = dias_mes
            melhor_outros = {"horas": h_local, "stats": stats, "dias_trab": d_local}

    return {
        "dias":   melhor_dias,
        **melhor_outros,
        "score":  melhor_score,
    }


# ========================
# RELATÓRIO / PARECER (MANTER COMO HOJE)
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
# GERADORES (MÊS/ANO) – CASCA
# ========================
def gerar_escala_mes(ano, mes, funcionarios, params, info,
                     estado_acumulado=None, FLEXIBILIZAR=True,
                     tentativas=50, perfis=None, mes_acum_horas=None,
                     estado_continuo=None):
    """Casca fina: prepara, chama motor, formata saída e parecer."""
    funcionarios = [f for f in funcionarios if f.get("perfil") in ("EXP", "AUX")]

    res_motor = motor_gerar_dias_mes(
        ano, mes, funcionarios, params, info,
        estado_acumulado=estado_acumulado,
        estado_continuo=estado_continuo,
        FLEXIBILIZAR=FLEXIBILIZAR,
        tentativas=tentativas,
        perfis=perfis,
        mes_acum_horas=mes_acum_horas,
    )

    dias_out = [
        {
            "data":  d["data"],
            "turnos": {t: [f["nome"] for f in dupla] for t, dupla in d["turnos"].items()},
        }
        for d in res_motor["dias"]
    ]

    parecer = gerar_parecer_escala(dias_out, funcionarios)
    print(f"\033[92mMelhor score {ano}-{parse_mes(mes)}: {res_motor['score']:.2f}\033[0m")

    return {
        "dias":    dias_out,
        "horas":   res_motor["horas"],
        "stats":   res_motor["stats"],
        "dias_trab": res_motor["dias_trab"],
        "score":   res_motor["score"],
        "parecer": parecer,
    }


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
# HANDLER WEB / HTTP HELPERS
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


def preparar_estado_continuo(escala_mes_anterior, funcionarios):
    """Gera estado inicial quando há escala do mês anterior."""
    if not escala_mes_anterior or "dias" not in escala_mes_anterior:
        return None

    fids_validos = {str(f["id"]) for f in funcionarios}

    consec           = {fid: 0 for fid in fids_validos}
    ultimo_turno     = {fid: None for fid in fids_validos}
    dias_trabalhados = {fid: 0 for fid in fids_validos}
    pipocacoes       = {fid: 0 for fid in fids_validos}

    dias = sorted(escala_mes_anterior["dias"], key=lambda d: d["data"])
    trabalhou_ontem = {fid: False for fid in fids_validos}
    nome_para_id = {f["nome"]: str(f["id"]) for f in funcionarios}

    for dia in dias:
        trabalhou_hoje = {fid: False for fid in fids_validos}
        for turno, pessoas in dia["turnos"].items():
            for p in pessoas:
                if isinstance(p, dict) and "funcionario_id" in p:
                    fid = str(p["funcionario_id"])
                elif isinstance(p, str):
                    fid = nome_para_id.get(p)
                else:
                    fid = None
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
