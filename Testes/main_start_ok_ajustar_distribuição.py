"""
Gerador de escalas EXP/AUX
---------------------------------
Versão revisada em 2025-12-10  (patch “start-strategy” 2025-12-15)

Regras duras PRIORITÁRIAS
    1. Respeita férias, datas e turnos proibidos
    2. Máx. 6 dias consecutivos de trabalho (3 nos 7 primeiros dias)
    3. Durante sequência (consec > 0) o funcionário deve manter o MESMO turno
    4. Após folga (consec == 0) deve seguir o ciclo 00↔12 / 06↔18
    5. Máximo 8 dias por turno/mês (parâmetro)

Regras suaves ponderadas por SOFT_WEIGHTS
Nenhum reset de ultimo_turno durante folga
Funções claramente separadas
"""

import json, calendar, random, statistics
from datetime import datetime, timedelta

# ========================
#   CONFIGURAÇÃO DE PESOS E PARÂMETROS
# ========================
START_WINDOW_DIAS          = 7     # 1ª semana
MAX_SEQ_START_WINDOW       = 3     # no start cada um só pode 3 seguidos
HORAS_POR_TURNO            = 6

# -------- HARD CONSTRAINTS --------
HARD_RULES = {
    "ferias":                   True,
    "dia_semana_proibido":      True,
    "turno_proibido":           True,
    "data_proibida":            True,
    "troca_de_turno_sem_folga": True,
    "mesmo_turno_sem_folga":    True,
    "limite_dias_consecutivos": 6,   # valor real após a 1ª semana
    "limite_dias_mesmo_turno":  8,
}

# -------- SOFT CONSTRAINTS --------
SOFT_WEIGHTS = {
    "preferencia_turno":               10,
    "balanceamento_turnos":           700,
    "penaliza_ausencia_turno":       1200,
    "dias_trabalhados":                 4,
    "desequilibrio_horas":             18,
    "troca_de_turno":                  90,
    "bonus_sequencia_mesmo_turno":     80,
    "penaliza_intercalado_trab_folga": 80,
    "bonus_folga_agrupada":            20,
    "penaliza_seq_curta":             440,
    "penaliza_seq_longa":             440,
    "bonus_seq_alvo":                 150,
}

TARGET_SEQ_MIN, TARGET_SEQ_MAX = 4, 5  # sequência ideal

# ========================
#   TURNOS E CONSTANTES
# ========================
TURNOS       = ["00H", "06H", "12H", "18H"]
CICLO_TURNOS = {"00H":"12H", "12H":"00H", "06H":"18H", "18H":"06H"}

parse_mes   = lambda m: f"{int(m):02d}"
dias_do_mes = lambda y, m: calendar.monthrange(y, m)[1]
str_data    = lambda y, m, d: f"{y}-{parse_mes(m)}-{int(d):02d}"

# ========================
#   PARSERS
# ========================
def parse_ferias(lista):
    out={}
    for f in lista or []:
        fid=str(f["funcionario_id"])
        ini=datetime.strptime(f["data_inicio"],"%Y-%m-%d").date()
        fim=datetime.strptime(f["data_fim"],"%Y-%m-%d").date()
        out.setdefault(fid,[]).append((ini,fim))
    return out

def parse_preferencias(lista):
    out={}
    for p in lista or []:
        fid=str(p["funcionario_id"])
        turnos=set(p.get("turnos_preferidos",[]))
        if p.get("turno"): turnos.add(p["turno"])
        if turnos: out.setdefault(fid,set()).update(turnos)
    return out

def parse_restricoes(lista):
    out={"dia_semana_proibido":{},"turno_proibido":{},"data_proibida":{},"turno_permitido_por_dia":{}}
    for r in lista or []:
        fid,tipo=str(r["funcionario_id"]),r["tipo"]
        if   tipo=="DIA_SEMANA_PROIBIDO":
            out["dia_semana_proibido"].setdefault(fid,set()).add(int(r["dia_semana"]))
        elif tipo=="TURNO_PROIBIDO":
            out["turno_proibido"].setdefault(fid,set()).add(r["turno"])
        elif tipo=="DATA_PROIBIDA":
            d=datetime.strptime(r["data"],"%Y-%m-%d").date()
            out["data_proibida"].setdefault(fid,set()).add(d)
        elif tipo=="TURNO_PERMITIDO_POR_DIA":
            ds=int(r["dia_semana"])
            tset=set(t.strip() for t in r["turnos_permitidos"].split(",") if t.strip())
            out["turno_permitido_por_dia"].setdefault(fid,{})[ds]=tset
    return out

# ========================
#   REGRAS DURAS
# ========================
def limite_consecutivo(dia_corrente):
    return MAX_SEQ_START_WINDOW if dia_corrente <= START_WINDOW_DIAS else HARD_RULES["limite_dias_consecutivos"]

def restricoes_hard(fid, turno, data, info, consec, ultimo_turno, stats):
    if any(s<=data<=e for s,e in info["ferias"].get(fid,[])): return False
    rst,wd=info["restricoes"],data.weekday()
    if wd in rst["dia_semana_proibido"].get(fid,set()): return False
    if turno in rst["turno_proibido"].get(fid,set()):   return False
    if data  in rst["data_proibida"].get(fid,set()):    return False
    if wd in rst["turno_permitido_por_dia"].get(fid,{}):
        if turno not in rst["turno_permitido_por_dia"][fid][wd]: return False

    ut,cons=ultimo_turno.get(fid),consec[fid]
    if cons>0 and ut!=turno: return False
    if cons==0 and ut is not None and turno!=CICLO_TURNOS[ut]: return False
    if cons>=limite_consecutivo(data.day): return False
    if stats and stats.get(fid,{}).get(turno,0)>=HARD_RULES["limite_dias_mesmo_turno"]: return False
    return True

# ========================
#   SCORE SOFT
# ========================
def score_func(params,func,turno,horas,consec,dia,prefs,
               ultimo_turno,stats,mes_acum_horas,seq_trab=None,seq_folga=None):
    fid=str(func["id"]); s=0
    if turno not in prefs.get(fid,set()): s+=SOFT_WEIGHTS["preferencia_turno"]
    media=statistics.mean(stats[fid].values())
    if stats[fid][turno]>media+2:
        s+=SOFT_WEIGHTS["balanceamento_turnos"]*(stats[fid][turno]-media)
    s+=consec[fid]*SOFT_WEIGHTS["dias_trabalhados"]
    if mes_acum_horas and fid in mes_acum_horas:
        s+=(mes_acum_horas[fid]/10)*SOFT_WEIGHTS["desequilibrio_horas"]
    if ultimo_turno.get(fid) and ultimo_turno[fid]!=turno: s+=SOFT_WEIGHTS["troca_de_turno"]
    if stats[fid][turno]>10: s+=100*(stats[fid][turno]-10)
    if dia>20 and sum(1 for t in TURNOS if stats[fid][t]>0)<3: s+=150
    seq_atual=consec[fid]; continua=ultimo_turno.get(fid)==turno
    if continua:
        futura=seq_atual+1
        if futura<TARGET_SEQ_MIN: s+=SOFT_WEIGHTS["penaliza_seq_curta"]
        elif futura>TARGET_SEQ_MAX: s+=SOFT_WEIGHTS["penaliza_seq_longa"]
        else: s-=SOFT_WEIGHTS["bonus_seq_alvo"]
    if seq_trab and seq_folga:
        if seq_trab[fid]==1 and seq_folga[fid]==1: s+=SOFT_WEIGHTS["penaliza_intercalado_trab_folga"]
        if seq_folga[fid]>1: s-=seq_folga[fid]*SOFT_WEIGHTS["bonus_folga_agrupada"]
    if stats[fid][turno]==0 and dia>10: s+=SOFT_WEIGHTS["penaliza_ausencia_turno"]
    return s+random.uniform(-1,1)

# ========================
#   ESCOLHA DO FUNCIONÁRIO
# ========================
def escolher_func(pool,turno,horas,consec,dia,prefs,
                  ultimo_turno,stats,params,data,info,
                  mes_acum_horas,seq_trab,seq_folga):
    cand=[f for f in pool if restricoes_hard(str(f["id"]),turno,data,info,consec,ultimo_turno,stats)]
    if not cand:
        print(f"\033[91m[ALERTA] Sem opção para {turno} dia {data}: relaxando regras\033[0m")
        return random.choice(pool)

    obrig,pos_folga,livres=[],[],[]
    for f in cand:
        fid,ut,cons=str(f["id"]),ultimo_turno.get(str(f["id"])),consec[str(f["id"])]
        if cons>0:
            if ut==turno: obrig.append(f)
            elif cons>=TARGET_SEQ_MIN: livres.append(f)
            continue
        if cons==0 and ut is not None and turno==CICLO_TURNOS[ut]:
            pos_folga.append(f); continue
        livres.append(f)

    escolha=obrig or pos_folga or livres
    print(f"\033[96m[CAND {turno} {data}]\033[0m",", ".join(x["nome"] for x in escolha))
    return min(escolha,key=lambda fx:score_func(params,fx,turno,horas,consec,dia,prefs,
                                                ultimo_turno,stats,mes_acum_horas,seq_trab,seq_folga))

# ========================
#   PARECER / RELATÓRIO
# ========================
def gerar_parecer_escala(dias,funcionarios):
    p={str(f["id"]):{"funcionario_id":f["id"],
                     "nome":f.get("nome"),
                     "dias_trabalhados":0,"dias_folga":0,
                     "total_horas":0,
                     "vezes_00h":0,"vezes_06h":0,"vezes_12h":0,"vezes_18h":0,
                     "maior_seq_dias_trab":0,"menor_seq_dias_mesmo_turno":None,
                     "trocas_de_turno":0} for f in funcionarios}
    ult={str(f["id"]):None for f in funcionarios}
    seq_trab=seq_t_mesmo={fid:0 for fid in p}
    for dia in dias:
        trabalhou={str(f["id"]):False for f in funcionarios}
        for turno,dupla in dia["turnos"].items():
            for nome in dupla:
                fid=next((str(f["id"]) for f in funcionarios if f["nome"]==nome),None)
                if fid is None: continue
                pr=p[fid]
                if not trabalhou[fid]: pr["dias_trabalhados"]+=1
                trabalhou[fid]=True
                pr["total_horas"]+=HORAS_POR_TURNO
                pr[f"vezes_{turno.lower()}"]+=1
                if ult[fid]==turno: seq_t_mesmo[fid]+=1
                else:
                    if seq_t_mesmo[fid]:
                        pr["menor_seq_dias_mesmo_turno"]=min(filter(None,[pr["menor_seq_dias_mesmo_turno"],seq_t_mesmo[fid]]))
                    seq_t_mesmo[fid]=1
                    if ult[fid] is not None: pr["trocas_de_turno"]+=1
                ult[fid]=turno
        for f in funcionarios:
            fid=str(f["id"])
            if trabalhou[fid]:
                seq_trab[fid]+=1
                p[fid]["maior_seq_dias_trab"]=max(p[fid]["maior_seq_dias_trab"],seq_trab[fid])
            else:
                if seq_t_mesmo[fid]:
                    p[fid]["menor_seq_dias_mesmo_turno"]=min(filter(None,[p[fid]["menor_seq_dias_mesmo_turno"],seq_t_mesmo[fid]]))
                seq_trab[fid]=seq_t_mesmo[fid]=0
    for fid,pr in p.items():
        pr["dias_folga"]=len(dias)-pr["dias_trabalhados"]
        if pr["menor_seq_dias_mesmo_turno"] is None: pr["menor_seq_dias_mesmo_turno"]=1
    return list(p.values())

# ========================
#   GERADOR DE ESCALA (MÊS)
# ========================
def gerar_escala_mes(ano,mes,funcionarios,params,info,
                     estado_acumulado=None,FLEXIBILIZAR=True,tentativas=50,
                     perfis=None,mes_acum_horas=None):
    dias_no_mes=dias_do_mes(ano,mes)
    if perfis is None:
        perfis={"EXP":[], "AUX":[]}
        for f in funcionarios: perfis[f["perfil"]].append(f)

    horas = dict(estado_acumulado["horas"]) if estado_acumulado else {str(f["id"]):0 for f in funcionarios}
    dias_trab = dict(estado_acumulado["dias_trab"]) if estado_acumulado else {str(f["id"]):0 for f in funcionarios}

    melhor_score=float("inf"); melhor_dias=None; melhor_outros={}
    for tentativa in range(tentativas):
        c={str(f["id"]):0 for f in funcionarios}
        u_turno={str(f["id"]):None for f in funcionarios}
        stats={str(f["id"]):{t:0 for t in TURNOS} for f in funcionarios}
        h_local=dict(horas); d_local=dict(dias_trab)
        seq_trab={str(f["id"]):0 for f in funcionarios}
        seq_folga={str(f["id"]):0 for f in funcionarios}
        dias_mes=[]
        for dia in range(1,dias_no_mes+1):
            data_atual=datetime(ano,mes,dia).date()
            linha={"data":str_data(ano,mes,dia),"turnos":{}}
            disp=funcionarios.copy(); random.shuffle(disp)
            for turno in TURNOS:
                exp_pool=[f for f in disp if f["perfil"]=="EXP"]
                aux_pool=[f for f in disp if f["perfil"]=="AUX"]
                if FLEXIBILIZAR and (len(exp_pool)<1 or len(aux_pool)<1):
                    print(f"\033[93m[WARN] Flex {turno} {data_atual}\033[0m")
                    op1,op2=random.sample(disp,2)
                else:
                    op1=escolher_func(exp_pool,turno,h_local,c,dia,info["preferencias"],
                                      u_turno,stats,params,data_atual,info,
                                      mes_acum_horas,seq_trab,seq_folga)
                    op2=escolher_func(aux_pool,turno,h_local,c,dia,info["preferencias"],
                                      u_turno,stats,params,data_atual,info,
                                      mes_acum_horas,seq_trab,seq_folga)
                linha["turnos"][turno]=[op1,op2]
                for op in (op1,op2):
                    fid=str(op["id"])
                    h_local[fid]+=HORAS_POR_TURNO; c[fid]+=1
                    stats[fid][turno]+=1; u_turno[fid]=turno; d_local[fid]+=1
                    disp.remove(op)
            ids_trab={str(e["id"]) for t in TURNOS for e in linha["turnos"][t]}
            for f in funcionarios:
                fid=str(f["id"])
                if fid in ids_trab: seq_trab[fid]+=1; seq_folga[fid]=0
                else: seq_trab[fid]=0; seq_folga[fid]+=1; c[fid]=0
            dias_mes.append(linha)
        valores=h_local.values()
        score=(max(valores)-min(valores))+statistics.mean(valores)/5
        if score<melhor_score:
            melhor_score,melhor_dias=score,dias_mes
            melhor_outros={"horas":h_local,"stats":stats,"dias_trab":d_local}
    dias_out=[{"data":d["data"],
               "turnos":{t:[f["nome"] for f in dupla] for t,dupla in d["turnos"].items()}}
              for d in melhor_dias]
    parecer=gerar_parecer_escala(dias_out,funcionarios)
    print(f"\033[92mMelhor score {ano}-{parse_mes(mes)}: {melhor_score:.2f}\033[0m")
    return {"dias":dias_out,**melhor_outros,"score":melhor_score,"parecer":parecer}

# ========================
#   GERADOR DE ESCALA (ANO)
# ========================
def gerar_escala_ano(ano,mes_inicio,funcionarios,params,info,
                     FLEXIBILIZAR=True,tentativas=50):
    resultados={}; estado=None
    for m in range(int(mes_inicio),13):
        print(f"\033[94mGerando escala para {ano}-{parse_mes(m)}\033[0m")
        res=gerar_escala_mes(ano,m,funcionarios,params,info,estado,
                             FLEXIBILIZAR,tentativas,mes_acum_horas=estado["horas"] if estado else None)
        resultados[f"{ano}-{parse_mes(m)}"]=res
        estado={"horas":res["horas"],"dias_trab":res["dias_trab"]}
    return {"ano":ano,"mes_inicio":parse_mes(mes_inicio),"escala":resultados}

# ========================
#   HANDLER WEB
# ========================
def main(request):
    try:
        if request.method=="OPTIONS": return ("",204,_cors_headers())
        if request.method!="POST":    return _json({"erro":"Use POST"},405)
        payload=request.get_json(force=True)
        ano,mes_inicio=int(payload["ano"]),int(payload["mes_inicio"])
        funcionarios=payload["funcionarios"]
        params=payload.get("parametros",{})
        tentativas=int(params.get("quantidade_escalas",50))
        FLEX=bool(params.get("permite_dupla_exp",True) and params.get("permite_dupla_aux",True))
        info={"ferias":parse_ferias(payload.get("ferias")),
              "preferencias":parse_preferencias(payload.get("preferencias")),
              "restricoes":parse_restricoes(payload.get("restricoes"))}
        if payload.get("tipo","ano")=="mes":
            res=gerar_escala_mes(ano,mes_inicio,funcionarios,params,info,
                                 FLEXIBILIZAR=FLEX,tentativas=tentativas)
            return _json(res)
        res=gerar_escala_ano(ano,mes_inicio,funcionarios,params,info,
                             FLEXIBILIZAR=FLEX,tentativas=tentativas)
        return _json(res)
    except Exception as e:
        print("\033[91m[ERRO]\033[0m",e)
        return _json({"erro":"Falha inesperada","detalhe":str(e)},500)

# ========================
#   HELPERS HTTP
# ========================
def _cors_headers():
    return {"Access-Control-Allow-Origin":"*",
            "Access-Control-Allow-Methods":"POST,OPTIONS",
            "Access-Control-Allow-Headers":"Content-Type"}

def _json(obj,status=200):
    return (json.dumps(obj,ensure_ascii=False,indent=2),status,
            {"Content-Type":"application/json",**_cors_headers()})
