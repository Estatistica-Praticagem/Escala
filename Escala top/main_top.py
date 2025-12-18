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


# ---------- MOTOR PRINCIPAL (AJUSTADO PARA 4x1 / 4x2 / 4x3 + blocos fixos 4 dias) ----------
def motor_gerar_dias_mes(ano, mes, funcionarios, params, info,
                         estado_acumulado=None, estado_continuo=None,
                         FLEXIBILIZAR=True, tentativas=50, perfis=None,
                         mes_acum_horas=None):
    """
    Motor gerador puro: devolve grade crua + métricas.

    PRINCÍPIO NOVO (esqueletos 4x1 / 4x2 / 4x3):
      - Todo bloco de TRABALHO é FIXO: 4 dias no mesmo turno.
      - Ao terminar o bloco, entra em FOLGA (2 ou 3 dias) definida no INÍCIO do ciclo.
      - Ao terminar folga, avança turno no CICLO: 00 -> 18 -> 12 -> 06 -> 00.
      - O MODELO (4x1/4x2/4x3) é escolhido POR SEMANA, baseado em ATIVOS reais.
      - Se mudar disponibilidade na semana: só afeta QUEM VAI INICIAR NOVO CICLO.
        Quem já está em ciclo (work_left>0 ou off_left>0) continua até terminar.

    4x1: demanda menor no 00H (1 vaga); demais turnos 2 vagas; folga=2
    4x2: demanda cheia 2 vagas/turno; folga=2
    4x3: demanda cheia 2 vagas/turno; folga=3

    Observação:
      - Mantém as estruturas de retorno esperadas por gerar_escala_mes/ano.
      - Não depende de score complexo; só usa heurística leve para balancear.
    """
    # -------------------------
    # Helpers locais (auto-contido)
    # -------------------------
    MODELOS = {
        "4x1": {"folga": 2, "demanda": {"00H": 1, "06H": 2, "12H": 2, "18H": 2}},
        "4x2": {"folga": 2, "demanda": {"00H": 2, "06H": 2, "12H": 2, "18H": 2}},
        "4x3": {"folga": 3, "demanda": {"00H": 2, "06H": 2, "12H": 2, "18H": 2}},
    }

    def _em_ferias(fid, data_):
        return any(ini <= data_ <= fim for ini, fim in info["ferias"].get(fid, []))

    def contar_ativos_semana(funcs, ferias_map, monday, sunday):
        """Ativos = não ausente a semana inteira (férias cobrindo de segunda a domingo)."""
        ativos = 0
        for f in funcs:
            fid = str(f["id"])
            ausente_semana = False
            for ini, fim in ferias_map.get(fid, []):
                if ini <= monday and fim >= sunday:
                    ausente_semana = True
                    break
            if not ausente_semana:
                ativos += 1
        return max(0, ativos)

    def escolher_modelo_semana(ativos):
        """
        Heurística simples (ajuste depois se quiser):
          - >= 14 ativos => 4x3 (folga 3)
          - >= 12 ativos => 4x2 (folga 2)
          - <  12 ativos => 4x1 (reduz madrugada) (folga 2)
        """
        if ativos >= 14:
            return "4x3"
        if ativos >= 12:
            return "4x2"
        return "4x1"

    def _pick_melhor(candidatos, d_local, h_local):
        """Escolha leve: menos dias no mês, depois menos horas, depois ruído."""
        if not candidatos:
            return None
        return min(
            candidatos,
            key=lambda f: (
                d_local.get(str(f["id"]), 0),
                h_local.get(str(f["id"]), 0),
                random.random(),
            ),
        )

    def _pick_por_perfil(cands, perfil, d_local, h_local):
        prefer = [f for f in cands if f.get("perfil") == perfil]
        return _pick_melhor(prefer or cands, d_local, h_local)

    def _iniciar_bloco(fid, turno, work_left, off_len_atual, turno_atual, folga_prox):
        """Início de ciclo travado: trabalho 4 dias fixos + folga (2/3) definida agora."""
        turno_atual[fid] = turno
        work_left[fid] = 4
        off_len_atual[fid] = int(folga_prox)

    # -------------------------
    # Setup base
    # -------------------------
    funcionarios = [f for f in funcionarios if f.get("perfil") in ("EXP", "AUX")]
    dias_no_mes = dias_do_mes(ano, mes)

    if perfis is None:
        perfis = {"EXP": [], "AUX": []}
        for f in funcionarios:
            perfis[f["perfil"]].append(f)

    horas = dict(estado_acumulado["horas"]) if estado_acumulado else {str(f["id"]): 0 for f in funcionarios}
    dias_trab = dict(estado_acumulado["dias_trab"]) if estado_acumulado else {str(f["id"]): 0 for f in funcionarios}

    melhor_score, melhor_dias, melhor_outros = float("inf"), None, {}

    # cache semanal: week_id -> {"modelo","folga","demanda","ativos"}
    week_cfg_cache = {}

    for _ in range(tentativas):
        # -------------------------
        # Estados (por tentativa)
        # -------------------------
        h_local = dict(horas)
        d_local = dict(dias_trab)

        stats = {str(f["id"]): {t: 0 for t in TURNOS} for f in funcionarios}
        dias_trab_mes = {str(f["id"]): 0 for f in funcionarios}
        dias_semana = {str(f["id"]): {} for f in funcionarios}

        # Mantemos esses estados antigos só para compatibilidade interna (não é o motor principal)
        c = {str(f["id"]): estado_continuo["consec"].get(str(f["id"]), 0) if estado_continuo else 0 for f in funcionarios}
        u_turno = {str(f["id"]): estado_continuo["ultimo_turno"].get(str(f["id"])) if estado_continuo else None for f in funcionarios}

        # -------------------------
        # NOVO: estado do ciclo (4 trabalho + 2/3 folga)
        # -------------------------
        turno_atual = {str(f["id"]): None for f in funcionarios}   # turno do ciclo (onde ele trabalha nos blocos)
        work_left   = {str(f["id"]): 0    for f in funcionarios}   # dias restantes do bloco de trabalho
        off_left    = {str(f["id"]): 0    for f in funcionarios}   # dias restantes de folga
        off_len_atual = {str(f["id"]): None for f in funcionarios} # folga do ciclo atual (fixada no início)

        # Controle de entrada em férias para não “avançar turno” todo dia
        em_ferias_ontem = {str(f["id"]): False for f in funcionarios}

        # Continuidade do mês anterior: preserva turno e completa o bloco de 4
        if estado_continuo:
            for fid, cons in estado_continuo["consec"].items():
                if cons and estado_continuo["ultimo_turno"].get(fid):
                    turno_atual[fid] = estado_continuo["ultimo_turno"][fid]
                    # completa bloco 4 se ainda estava dentro
                    if cons < 4:
                        work_left[fid] = 4 - cons
                        off_left[fid] = 0
                    else:
                        # se já passou de 4, começamos mês em folga padrão 2
                        work_left[fid] = 0
                        off_left[fid] = 2
                        off_len_atual[fid] = 2

        dias_mes = []

        # -------------------------
        # Loop diário
        # -------------------------
        for dia in range(1, dias_no_mes + 1):
            data_atual = datetime(ano, mes, dia).date()
            week_year, week_num, _ = data_atual.isocalendar()
            week_id = f"{week_year}-{week_num:02d}"

            # Escolhe modelo por semana com base em ativos (férias cobrindo a semana inteira)
            if week_id not in week_cfg_cache:
                monday = datetime.fromisocalendar(week_year, week_num, 1).date()
                sunday = monday + timedelta(days=6)
                ativos = contar_ativos_semana(funcionarios, info["ferias"], monday, sunday)
                modelo = escolher_modelo_semana(ativos)
                cfg = MODELOS[modelo]
                week_cfg_cache[week_id] = {
                    "modelo": modelo,
                    "folga": cfg["folga"],
                    "demanda": cfg["demanda"],
                    "ativos": ativos,
                }

            cfg_semana = week_cfg_cache[week_id]
            demanda = cfg_semana["demanda"]
            folga_prox = cfg_semana["folga"]

            linha = {"data": str_data(ano, mes, dia), "turnos": {}}
            alocados_hoje = set()

            # marca férias hoje
            em_ferias_hoje = {str(f["id"]): _em_ferias(str(f["id"]), data_atual) for f in funcionarios}

            # Disponíveis hoje: não está de folga e não está de férias hoje
            disp = [
                f for f in funcionarios
                if off_left[str(f["id"])] == 0
                and not em_ferias_hoje[str(f["id"])]
            ]
            random.shuffle(disp)

            # -------------------------
            # Preenche turno a turno com demanda variável (4x1)
            # -------------------------
            for turno in TURNOS:
                vagas = int(demanda.get(turno, 2))
                aloc = []

                def candidatos_base():
                    """Base: disponíveis hoje e ainda não alocados no dia."""
                    return [f for f in disp if str(f["id"]) not in alocados_hoje]

                def cand_em_ciclo(turno_):
                    return [
                        f for f in candidatos_base()
                        if turno_atual.get(str(f["id"])) == turno_
                        and work_left.get(str(f["id"]), 0) > 0
                    ]

                def cand_para_iniciar(turno_):
                    return [
                        f for f in candidatos_base()
                        if turno_atual.get(str(f["id"])) == turno_
                        and work_left.get(str(f["id"]), 0) == 0
                        and off_left.get(str(f["id"]), 0) == 0
                    ]

                def cand_sem_turno():
                    return [
                        f for f in candidatos_base()
                        if turno_atual.get(str(f["id"])) is None
                        and work_left.get(str(f["id"]), 0) == 0
                        and off_left.get(str(f["id"]), 0) == 0
                    ]

                while len(aloc) < vagas:
                    # prioridade: continuar bloco já em andamento no turno
                    base = cand_em_ciclo(turno)

                    # se não houver, tenta iniciar novo bloco no turno "correto" do usuário
                    if not base:
                        base = cand_para_iniciar(turno)

                    # se ainda não houver, tenta encaixar quem ainda não tem turno (primeiro encaixe do mês)
                    if not base:
                        base = cand_sem_turno()

                    # último recurso (FLEX): qualquer disponível hoje (pode quebrar alinhamento do turno_atual)
                    if not base and FLEXIBILIZAR:
                        base = candidatos_base()

                    if not base:
                        break

                    # Regra de perfil (quando vagas == 2): tenta EXP + AUX
                    if vagas == 2:
                        if len(aloc) == 0:
                            escolhido = _pick_por_perfil(base, "EXP", d_local, h_local) or _pick_melhor(base, d_local, h_local)
                        else:
                            primeiro = aloc[0].get("perfil")
                            alvo = "AUX" if primeiro == "EXP" else "EXP"
                            escolhido = _pick_por_perfil(base, alvo, d_local, h_local) or _pick_melhor(base, d_local, h_local)
                    else:
                        # vaga única (4x1 madrugada): prefere EXP
                        escolhido = _pick_por_perfil(base, "EXP", d_local, h_local) or _pick_melhor(base, d_local, h_local)

                    if not escolhido:
                        break

                    fid = str(escolhido["id"])

                    # se não tinha turno definido ainda, fixa agora no turno que ele está sendo alocado
                    if turno_atual[fid] is None:
                        turno_atual[fid] = turno

                    # se está livre (não em bloco e não em folga), iniciar bloco com folga da semana ATUAL
                    if work_left[fid] == 0 and off_left[fid] == 0:
                        _iniciar_bloco(fid, turno_atual[fid], work_left, off_len_atual, turno_atual, folga_prox)

                    aloc.append(escolhido)
                    alocados_hoje.add(fid)

                linha["turnos"][turno] = aloc

                # stats + ultimo turno do dia
                for op in aloc:
                    fid = str(op["id"])
                    stats[fid][turno] += 1
                    u_turno[fid] = turno  # usado pelo parecer/continuidade
                    # c (consec) será atualizado abaixo

            # -------------------------
            # Consolida quem trabalhou hoje
            # -------------------------
            ids_trab = {str(e["id"]) for t in TURNOS for e in linha["turnos"].get(t, [])}

            # Horas/dias acumulados
            for fid in ids_trab:
                h_local[fid] += HORAS_POR_TURNO
                d_local[fid] += 1
                dias_trab_mes[fid] += 1
                dias_semana[fid][week_id] = dias_semana[fid].get(week_id, 0) + 1

            # -------------------------
            # UPDATE do ciclo 4 dias + folga 2/3
            # -------------------------
            # 1) Quem trabalhou hoje consome 1 dia do bloco (work_left)
            for fid in ids_trab:
                if work_left[fid] <= 0:
                    # fallback: se entrou sem iniciar bloco (não deveria), corrige
                    _iniciar_bloco(fid, turno_atual.get(fid) or u_turno.get(fid) or "00H",
                                   work_left, off_len_atual, turno_atual, folga_prox)

                work_left[fid] = max(0, work_left[fid] - 1)

                # terminou bloco -> entra em folga (fixada no início do bloco)
                if work_left[fid] == 0:
                    off_left[fid] = int(off_len_atual[fid] or folga_prox)

                # atualiza c (consec antigo) para compatibilidade com estado_continuo
                c[fid] = c.get(fid, 0) + 1

            # 2) Quem não trabalhou hoje:
            for f in funcionarios:
                fid = str(f["id"])
                if fid in ids_trab:
                    continue

                # Se entrou em férias HOJE (transição), quebra ciclo e avança turno uma vez (preserva rotação)
                if em_ferias_hoje[fid] and not em_ferias_ontem.get(fid, False):
                    if turno_atual.get(fid):
                        turno_atual[fid] = CICLO_TURNOS[turno_atual[fid]]
                    work_left[fid] = 0
                    off_left[fid] = 0
                    off_len_atual[fid] = None
                    c[fid] = 0
                    continue

                # Se continua de férias, congela (não avança nem consome)
                if em_ferias_hoje[fid]:
                    c[fid] = 0
                    continue

                # Se estava em folga, consome 1 dia
                if off_left[fid] > 0:
                    off_left[fid] = max(0, off_left[fid] - 1)
                    c[fid] = 0
                    # terminou folga -> avança turno pro próximo (CICLO)
                    if off_left[fid] == 0 and turno_atual.get(fid):
                        turno_atual[fid] = CICLO_TURNOS[turno_atual[fid]]
                        off_len_atual[fid] = None  # próxima folga será aplicada no início do próximo ciclo
                    continue

                # Se NÃO estava em folga mas estava em bloco e ficou sem escalar (por falta de vaga/restrições),
                # quebra o bloco e força folga mínima (não emenda automaticamente)
                if work_left[fid] > 0:
                    work_left[fid] = 0
                    off_left[fid] = int(off_len_atual[fid] or 2)
                    off_len_atual[fid] = off_left[fid]
                    c[fid] = 0
                    continue

                # totalmente livre e não trabalhou hoje
                c[fid] = 0

            # atualiza mapa "ontem"
            em_ferias_ontem = em_ferias_hoje

            dias_mes.append(linha)

        # -------------------------
        # Score simples (equilíbrio de horas) + guarda melhor tentativa
        # -------------------------
        valores = list(h_local.values())
        if not valores:
            continue

        score = (max(valores) - min(valores)) + statistics.mean(valores) / 5

        if score < melhor_score:
            melhor_score = score
            melhor_dias = dias_mes
            melhor_outros = {"horas": h_local, "stats": stats, "dias_trab": d_local}

    return {
        "dias": melhor_dias,
        **melhor_outros,
        "score": melhor_score,
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
