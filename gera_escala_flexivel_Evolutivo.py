import pandas as pd
import random
from datetime import datetime
import calendar
import xlsxwriter
import statistics

print("""
===============================================================
  SISTEMA EVOLUTIVO DE ESCALA — TORRE V3.1 (AGORA RANDOMIZADO!)
===============================================================
1) Escolha o MODO:
A → Balanceamento SUAVE (respeita preferências)
B → Balanceamento FORTE (igualar horas)
AMBOS → Cada tentativa escolhe A ou B aleatoriamente
===============================================================
""")

modo_global = input("Digite A, B ou AMBOS: ").strip().upper()
if modo_global not in ["A", "B", "AMBOS"]:
    print("Modo inválido. Use A, B ou AMBOS.")
    exit()

print("""
===============================================================
Quantas tentativas deseja gerar?

10   - Rápido  
50   - Qualidade boa  (padrão automático)
100  - Alta qualidade
300  - Qualidade máxima
1000 - Ultra detalhado (pode demorar)

Aperte ENTER para usar 50.
===============================================================
""")

inp = input("Digite o número: ").strip()
tentativas = int(inp) if inp.isdigit() else 50

print(f"\n→ Gerando {tentativas} tentativas...\n")

# =========== CONFIGS FIXAS ============
ANO = 2025
MES = 11
dias_no_mes = calendar.monthrange(ANO, MES)[1]
turnos = ["00H", "06H", "12H", "18H"]
horas_por_turno = 6
limite_dias_consecutivos = 6

experientes = [
    "ALLAN", "RODRIGO", "EDUARDO", "MARCO",
    "BRANCÃO", "CLEITON", "TONINHO"
]
auxiliares = [
    "THAIS", "FELIPE", "B.SELAYARAN",
    "RICHER", "GUILHERME", "B.HORNES", "teste"
]

preferencias = {
    "ALLAN": ["06H", "12H"],
    "RODRIGO": ["18H"],
    # "EDUARDO": ["00H", "06H"],
    # "MARCO": ["12H"],
    # "BRANCÃO": ["18H"],
    # "CLEITON": ["06H"],
    # "TONINHO": ["12H"],
    # "THAIS": ["00H"],
    # "FELIPE": ["06H"],
    # "B.SELAYARAN": ["12H"],
    # "RICHER": ["18H"],
    # "GUILHERME": ["12H"],
    # "B.HORNES": ["18H"]
}
restricoes = {
    "THAIS": ["18H"],
    "RODRIGO": ["00H"],
    # "FELIPE": ["00H"],
    # "GUILHERME": ["00H"]
}
plantoes_fixos = {
    "CLEITON": "06H",
    "MARCO": "12H",
    # "BRANCÃO": "18H",
    # "ALLAN": "06H"
}

# ========== FUNÇÕES AUXILIARES ==========

def pode_trabalhar(p, turno):
    return not (p in restricoes and turno in restricoes[p])

def peso_preferencia(p, turno, w_pref):
    return -w_pref if turno in preferencias.get(p, []) else 0

def peso_plantao(p, turno, w_plant):
    return -w_plant if plantoes_fixos.get(p) == turno else 0

def score_operador(p, turno, horas, consec, modo, w_pref, w_plant):
    base = horas[p] / 10 + consec[p] * 3
    # RANDOMIZAÇÃO DO PESO DAS PREFERÊNCIAS E PLANTÕES POR GERAÇÃO
    if modo == "A":
        base += peso_preferencia(p, turno, w_pref)
        base += peso_plantao(p, turno, w_plant)
    else:
        base += (horas[p] / 5)
        base += peso_preferencia(p, turno, w_pref//2)
        base += peso_plantao(p, turno, w_plant//2)
    # Adiciona ruído randômico relativo e absoluto (ENTROPIA EVOLUTIVA!)
    base += random.uniform(-0.2, 0.2) * (abs(base)+1)
    base += random.uniform(-2, 2)
    return base

def escolher_operador(disponiveis, turno, modo, horas, consec, w_pref, w_plant):
    validos = [p for p in disponiveis if pode_trabalhar(p, turno) and consec[p] < limite_dias_consecutivos]
    if not validos:
        return random.choice(disponiveis)
    random.shuffle(validos)  # resolve empates
    ordenados = sorted(validos, key=lambda p: score_operador(p, turno, horas, consec, modo, w_pref, w_plant))
    # Escolhe um dos top 2 em caso de empate (exploração adicional)
    top_n = min(2, len(ordenados))
    return random.choice(ordenados[:top_n])

def gerar_escala(modo):
    horas = {p: 0 for p in experientes + auxiliares}
    consec = {p: 0 for p in experientes + auxiliares}
    dados = []
    # HEURÍSTICA: muda peso preferências e plantão em cada geração
    w_pref = random.randint(3,7)
    w_plant = random.randint(7,14)

    for dia in range(1, dias_no_mes + 1):
        linha = {"DATA": f"{dia:02d}/{MES:02d}/{ANO}"}
        exp_disp = experientes.copy()
        aux_disp = auxiliares.copy()
        random.shuffle(exp_disp)  # embaralha a ordem diária
        random.shuffle(aux_disp)
        for turno in turnos:
            exp = escolher_operador(exp_disp, turno, modo, horas, consec, w_pref, w_plant)
            aux = escolher_operador(aux_disp, turno, modo, horas, consec, w_pref, w_plant)
            linha[f"{turno}_EXP"] = exp
            linha[f"{turno}_AUX"] = aux
            horas[exp] += horas_por_turno
            horas[aux] += horas_por_turno
            consec[exp] += 1
            consec[aux] += 1
            exp_disp.remove(exp)
            aux_disp.remove(aux)
        # reset consecutivos de quem não trabalhou
        for p in horas:
            if p not in linha.values():
                consec[p] = 0
        dados.append(linha)
    return dados, horas

def avaliar_escala(horas):
    valores = list(horas.values())
    dif = max(valores) - min(valores)
    media = statistics.mean(valores)
    score = dif + media / 5
    return score, media, max(valores), min(valores)

# ========== MOTOR EVOLUTIVO ==========
melhor_score = float("inf")
melhor = None
melhor_horas = None

for i in range(1, tentativas + 1):
    if modo_global == "AMBOS":
        modo = random.choice(["A", "B"])
    else:
        modo = modo_global
    dados, horas = gerar_escala(modo)
    score, media, max_h, min_h = avaliar_escala(horas)
    print(f"[ Tentativa {i}/{tentativas} ] Score: {score:.1f} | Média: {media:.1f} | Máx: {max_h} | Mín: {min_h}")
    if score < melhor_score:
        melhor_score = score
        melhor = dados
        melhor_horas = horas
        print(f" → Nova melhor escala encontrada! Score {score:.1f}\n")

# ========== EXPORTAÇÃO EXCEL ==========
output = "ESCALA_TORRE_V3.xlsx"
wb = xlsxwriter.Workbook(output)
ws = wb.add_worksheet("ESCALA")
ws2 = wb.add_worksheet("RELATORIO_DE_HORAS")
header = wb.add_format({"bold": True, "bg_color": "#1F4E78", "font_color": "white", "align": "center"})
cell = wb.add_format({"align": "center", "border": 1})

df = pd.DataFrame(melhor)
for col, name in enumerate(df.columns):
    ws.write(0, col, name, header)
    ws.set_column(col, col, 14)
    for row, val in enumerate(df[name], 1):
        ws.write(row, col, val, cell)

ws2.write(0,0,"OPERADOR", header)
ws2.write(0,1,"HORAS", header)
linha = 1
for op, hrs in sorted(melhor_horas.items(), key=lambda x: x[1], reverse=True):
    ws2.write(linha, 0, op, cell)
    ws2.write(linha, 1, hrs, cell)
    linha += 1

wb.close()

# ========== RELATÓRIO FINAL ==========

valores = list(melhor_horas.values())
media_final = statistics.mean(valores)
max_h = max(valores)
min_h = min(valores)
dif = max_h - min_h
op_max = max(melhor_horas, key=lambda k: melhor_horas[k])
op_min = min(melhor_horas, key=lambda k: melhor_horas[k])

print("""
===============================================================
             RELATÓRIO FINAL DA MELHOR ESCALA
===============================================================
""")

for op, hrs in sorted(melhor_horas.items(), key=lambda x: x[1], reverse=True):
    status = "acima da média" if hrs > media_final else ("na média" if hrs == media_final else "abaixo da média")
    print(f"{op:12} → {hrs}h ({status})")

print(f"""
---------------------------------------------------------------
MÉDIA GERAL       → {media_final:.1f}h
MAIOR CARGA       → {max_h}h ({op_max})
MENOR CARGA       → {min_h}h ({op_min})
DISCREPÂNCIA      → {dif}h
SCORE DA ESCALA   → {melhor_score:.1f}
---------------------------------------------------------------

Recomendações automáticas:
""")

if min_h < media_final - 10:
    print(f"- Aumentar turnos para {op_min}")

if max_h > media_final + 10:
    print(f"- Reduzir turnos de {op_max}")

print(f"""
===============================================================
Arquivo Excel gerado: {output}
===============================================================
""")
