import pandas as pd
import random
from datetime import datetime
import calendar
import xlsxwriter
import statistics

# ------------- TÍTULO & CONFIGURAÇÕES DE SAÍDA -------------
TITULO = "ESCALA DE TRABALHO - TORRE DE CONTROLE"
SUBTITULO = "MÊS: NOVEMBRO/2025"

# ------------ ENTRADA INICIAL: MODO E FLEXIBILIDADE -------------
print("""
===============================================================
  SISTEMA EVOLUTIVO DE ESCALA — TORRE V4 (com férias e tabela lateral)
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

print("\nDeseja permitir duplas flexíveis (pode ser 2 experientes ou 2 auxiliares em situações especiais)? (S/N)")
FLEXIBILIZAR = input().strip().upper().startswith("S")

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

# ------------ LISTAS DE OPERADORES E FÉRIAS -------------
operadores = [
    "ALLAN", "RODRIGO", "EDUARDO", "MARCO", "BRANCÃO", "CLEITON", "TONINHO",
    "THAIS", "FELIPE", "B.SELAYARAN", "RICHER", "GUILHERME", "B.HORNES"
]

# Definir se cada operador é 'EXP' ou 'AUX'
perfil_operador = {
    "ALLAN": "EXP", "RODRIGO": "EXP", "EDUARDO": "EXP", "MARCO": "EXP",
    "BRANCÃO": "EXP", "CLEITON": "EXP", "TONINHO": "EXP",
    "THAIS": "AUX", "FELIPE": "AUX", "B.SELAYARAN": "AUX",
    "RICHER": "AUX", "GUILHERME": "AUX", "B.HORNES": "AUX"
}

# Exemplo de restrição de férias:
ferias = {
    # 'OPERADOR': (dia_que_pode_começar, dia_que_pode_trabalhar_ate)
    # Exemplo: "B.HORNES": (10, 25)   # só pode trabalhar do dia 10 ao 25
    # "TONINHO": (1, 20)
}

# ------------ OUTRAS CONFIGS OPCIONAIS -------------
preferencias = {}   # Preencher se desejar
restricoes = {}     # Preencher se desejar
plantoes_fixos = {} # Preencher se desejar

# ========== FUNÇÕES AUXILIARES ==========

def pode_trabalhar(p, turno, dia):
    # Respeita restrição de férias!
    if p in ferias:
        inicio, fim = ferias[p]
        if dia < inicio or dia > fim:
            return False
    if p in restricoes and turno in restricoes[p]:
        return False
    return True

def score_operador(p, turno, horas, consec, modo, w_pref, w_plant):
    base = horas[p] / 10 + consec[p] * 3
    if modo == "A":
        base += -w_pref if turno in preferencias.get(p, []) else 0
        base += -w_plant if plantoes_fixos.get(p) == turno else 0
    else:
        base += (horas[p] / 5)
        base += (-w_pref//2) if turno in preferencias.get(p, []) else 0
        base += (-w_plant//2) if plantoes_fixos.get(p) == turno else 0
    base += random.uniform(-0.2, 0.2) * (abs(base)+1)
    base += random.uniform(-2, 2)
    return base

def escolher_operador(disponiveis, turno, modo, horas, consec, w_pref, w_plant, dia):
    validos = [p for p in disponiveis if pode_trabalhar(p, turno, dia) and consec[p] < limite_dias_consecutivos]
    if not validos:
        return random.choice(disponiveis)
    random.shuffle(validos)
    ordenados = sorted(validos, key=lambda p: score_operador(p, turno, horas, consec, modo, w_pref, w_plant))
    top_n = min(2, len(ordenados))
    return random.choice(ordenados[:top_n])

def gerar_escala(modo):
    horas = {p: 0 for p in operadores}
    consec = {p: 0 for p in operadores}
    dados = []
    w_pref = random.randint(3,7)
    w_plant = random.randint(7,14)
    for dia in range(1, dias_no_mes + 1):
        linha = {"DATA": f"{dia:02d}/{MES:02d}/{ANO}"}
        disp = operadores.copy()
        random.shuffle(disp)
        for turno in turnos:
            # Garante pelo menos 1 EXP e 1 AUX, exceto se FLEXIBILIZAR
            exps = [p for p in disp if perfil_operador[p] == "EXP"]
            auxs = [p for p in disp if perfil_operador[p] == "AUX"]
            op1, op2 = None, None
            if FLEXIBILIZAR and (len(exps) < 2 or len(auxs) < 2):
                # Pode formar dupla livre
                escolhe = random.sample(disp, 2)
                op1, op2 = escolhe[0], escolhe[1]
            else:
                # Normal: pega 1 EXP e 1 AUX para o turno
                op1 = escolher_operador(exps, turno, modo, horas, consec, w_pref, w_plant, dia)
                op2 = escolher_operador(auxs, turno, modo, horas, consec, w_pref, w_plant, dia)
            linha[f"{turno}_OPERADOR 1"] = op1
            linha[f"{turno}_OPERADOR 2"] = op2
            horas[op1] += horas_por_turno
            horas[op2] += horas_por_turno
            consec[op1] += 1
            consec[op2] += 1
            disp.remove(op1)
            disp.remove(op2)
        # Zera consecutivos de quem não trabalhou no dia
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

# ========== EXPORTAÇÃO EXCEL AVANÇADA ==========
output = "ESCALA_TORRE_V4.xlsx"
wb = xlsxwriter.Workbook(output)
ws = wb.add_worksheet("ESCALA")
ws2 = wb.add_worksheet("RESUMO")

header = wb.add_format({"bold": True, "bg_color": "#1F4E78", "font_color": "white", "align": "center"})
cell = wb.add_format({"align": "center", "border": 1})

# Escreve o título no topo da planilha (ESCALA)
ws.merge_range(0, 0, 0, len(turnos)*2, TITULO, wb.add_format({"bold": True, "font_size": 14, "align": "center"}))
ws.write(1, 0, SUBTITULO, wb.add_format({"bold": True, "font_size": 12, "align": "center"}))
linha_excel = 3

df = pd.DataFrame(melhor)
for col, name in enumerate(df.columns):
    ws.write(linha_excel, col, name, header)
    ws.set_column(col, col, 14)
    for row, val in enumerate(df[name], linha_excel+1):
        ws.write(row, col, val, cell)

# Gera a TABELA LATERAL de turnos/dias/folgas
# Coleta contagem de turnos/dias por operador
stats = {p: {t:0 for t in turnos} for p in operadores}
dias_trab = {p: 0 for p in operadores}

for dia in melhor:
    nomes_dia = set()
    for turno in turnos:
        op1 = dia[f"{turno}_OPERADOR 1"]
        op2 = dia[f"{turno}_OPERADOR 2"]
        stats[op1][turno] += 1
        stats[op2][turno] += 1
        nomes_dia.add(op1)
        nomes_dia.add(op2)
    for n in nomes_dia:
        dias_trab[n] += 1

# Folgas = dias_no_mes - dias_trab
ws2.write(0,0,"NOME", header)
for i, t in enumerate(turnos, 1):
    ws2.write(0,i, t, header)
ws2.write(0,5,"DIAS", header)
ws2.write(0,6,"FOLGA", header)

for idx, p in enumerate(operadores, 1):
    ws2.write(idx,0, p, cell)
    for i, t in enumerate(turnos, 1):
        ws2.write(idx,i, stats[p][t], cell)
    ws2.write(idx,5, dias_trab[p], cell)
    ws2.write(idx,6, dias_no_mes-dias_trab[p], cell)

# Gera também um resumo geral na folha RESUMO
ws2.write(len(operadores)+2,0,"MÉDIA DIAS", header)
ws2.write(len(operadores)+2,1, statistics.mean(list(dias_trab.values())), cell)
ws2.write(len(operadores)+3,0,"MÍNIMO", header)
ws2.write(len(operadores)+3,1, min(list(dias_trab.values())), cell)
ws2.write(len(operadores)+4,0,"MÁXIMO", header)
ws2.write(len(operadores)+4,1, max(list(dias_trab.values())), cell)

wb.close()

print(f"\n===============================================================")
print(f"Arquivo Excel gerado: {output}")
print(f"===============================================================\n")
