import pandas as pd
import random
from datetime import datetime
import calendar
import xlsxwriter
import statistics
import matplotlib.pyplot as plt
import os

from exporta_pdf_escala import gerar_pdf_escala_completa  # <-- IMPORTAÇÃO CERTA

# ============================================================
#                 CABEÇALHO / TÍTULO DA PLANILHA
# ============================================================
TITULO = "ESCALA DE TRABALHO - TORRE DE CONTROLE"
SUBTITULO = "MÊS: NOVEMBRO/2025"

# ============================================================
#          OPÇÃO DE EXPORTAÇÃO: EXCEL OU PDF
# ============================================================
print("""
===============================================================
  SISTEMA EVOLUTIVO DE ESCALA — TORRE V5
  → Excel colorido, PDF, férias, gráfico de carga horária, etc.
===============================================================
1) Escolha o tipo de arquivo a gerar:
E → Excel (.xlsx)
P → PDF (.pdf)
AMBOS → Gera os dois formatos
===============================================================
""")
tipo_export = input("Digite E, P ou AMBOS: ").strip().upper()
if tipo_export not in ["E", "P", "AMBOS"]:
    print("Tipo inválido. Use E, P ou AMBOS.")
    exit()

print("""
===============================================================
Escolha o MODO de balanceamento:
A → Balanceamento SUAVE (respeita preferências)
B → Balanceamento FORTE (igualar horas)
AMBOS → Cada tentativa escolhe A ou B aleatoriamente
===============================================================
""")
modo_global = input("Digite A, B ou AMBOS: ").strip().upper()
if modo_global not in ["A", "B", "AMBOS"]:
    print("Modo inválido. Use A, B ou AMBOS.")
    exit()

print("\nDeseja permitir duplas flexíveis? (pode ter 2 EXP ou 2 AUX) (S/N)")
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

# ============================================================
#                    CONFIGURAÇÃO BASE
# ============================================================
ANO = 2025
MES = 11
dias_no_mes = calendar.monthrange(ANO, MES)[1]
turnos = ["00H", "06H", "12H", "18H"]
horas_por_turno = 6
limite_dias_consecutivos = 6

operadores = [
    "ALLAN", "RODRIGO", "EDUARDO", "MARCO", "BRANCÃO",
    "CLEITON", "TONINHO",  # EXP
    "THAIS", "FELIPE", "B.SELAYARAN", "RICHER", "GUILHERME", "B.HORNES"  # AUX
]

perfil_operador = {
    "ALLAN": "EXP", "RODRIGO": "EXP", "EDUARDO": "EXP", "MARCO": "EXP",
    "BRANCÃO": "EXP", "CLEITON": "EXP", "TONINHO": "EXP",
    "THAIS": "AUX", "FELIPE": "AUX", "B.SELAYARAN": "AUX",
    "RICHER": "AUX", "GUILHERME": "AUX", "B.HORNES": "AUX"
}

# ============================================================
#                FÉRIAS — EXEMPLOS
# ============================================================
ferias = {
    "RODRIGO": (1, 15),        # Trabalha apenas do dia 1 ao 15
    "B.SELAYARAN": (10, 30),   # Trabalha do dia 10 ao 30
    "TONINHO": (5, 25)         # Trabalha do dia 5 ao 25
}

preferencias = {
    "ALLAN": ["06H"],
    "THAIS": ["00H"],
    "BRANCÃO": ["18H"]
}
restricoes = {
    "RODRIGO": ["00H"]   # NÃO pode trabalhar às 00H
}
plantoes_fixos = {
    "CLEITON": "06H"     # Fica preferencialmente no 06H
}

# ============================================================
#                  FUNÇÕES PRINCIPAIS
# ============================================================
def pode_trabalhar(p, turno, dia):
    if p in ferias:
        ini, fim = ferias[p]
        if dia < ini or dia > fim:
            return False
    if p in restricoes and turno in restricoes[p]:
        return False
    return True

def esta_de_ferias(p, dia):
    if p in ferias:
        ini, fim = ferias[p]
        if dia < ini or dia > fim:
            return True
    return False

def score_operador(p, turno, horas, consec, modo, w_pref, w_plant):
    base = horas[p] / 10 + consec[p] * 3
    if modo == "A":
        if turno in preferencias.get(p, []):
            base -= w_pref
        if plantoes_fixos.get(p) == turno:
            base -= w_plant
    else:
        base += horas[p] / 5
    base += random.uniform(-0.2, 0.2) * (abs(base) + 1)
    base += random.uniform(-2, 2)
    return base

def escolher_operador(lista, turno, modo, horas, consec, w_pref, w_plant, dia):
    validos = [p for p in lista if pode_trabalhar(p, turno, dia) and consec[p] < limite_dias_consecutivos]
    if not validos:
        return random.choice(lista)
    random.shuffle(validos)
    ordenados = sorted(validos, key=lambda p: score_operador(p, turno, horas, consec, modo, w_pref, w_plant))
    return random.choice(ordenados[:2])

def gerar_escala(modo):
    horas = {p: 0 for p in operadores}
    consec = {p: 0 for p in operadores}
    dados = []
    w_pref = random.randint(3, 7)
    w_plant = random.randint(7, 14)
    for dia in range(1, dias_no_mes + 1):
        linha = {"DATA": f"{dia:02d}/{MES:02d}/{ANO}"}
        disp = operadores.copy()
        random.shuffle(disp)
        for turno in turnos:
            exp_list = [p for p in disp if perfil_operador[p] == "EXP"]
            aux_list = [p for p in disp if perfil_operador[p] == "AUX"]
            if FLEXIBILIZAR and (len(exp_list) < 1 or len(aux_list) < 1):
                op1, op2 = random.sample(disp, 2)
            else:
                op1 = escolher_operador(exp_list, turno, modo, horas, consec, w_pref, w_plant, dia)
                op2 = escolher_operador(aux_list, turno, modo, horas, consec, w_pref, w_plant, dia)
            linha[f"{turno}_OP1"] = op1
            linha[f"{turno}_OP2"] = op2
            horas[op1] += horas_por_turno
            horas[op2] += horas_por_turno
            consec[op1] += 1
            consec[op2] += 1
            disp.remove(op1)
            disp.remove(op2)
        # reset consecutivos
        for p in operadores:
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

# ============================================================
#               MOTOR EVOLUTIVO — TENTATIVAS
# ============================================================
melhor_score = float("inf")
melhor = None
melhor_horas = None
for i in range(1, tentativas + 1):
    modo = random.choice(["A", "B"]) if modo_global == "AMBOS" else modo_global
    dados, horas = gerar_escala(modo)
    score, media, max_h, min_h = avaliar_escala(horas)
    print(f"[{i}/{tentativas}] Score: {score:.1f} | Média: {media:.1f} | Máx {max_h} | Mín {min_h}")
    if score < melhor_score:
        melhor_score = score
        melhor = dados
        melhor_horas = horas
        print(f" → NOVA MELHOR ENCONTRADA! Score {score:.1f}\n")

# ============================================================
#        EXPORTAÇÃO EXCEL COLORIDA & GRÁFICO CARGA HORÁRIA
# ============================================================
output_excel = "ESCALA_TORRE_V5.xlsx"
output_pdf = "ESCALA_TORRE_V5.pdf"

def exportar_excel(melhor, melhor_horas):
    wb = xlsxwriter.Workbook(output_excel)
    ws = wb.add_worksheet("ESCALA")
    wsl = wb.add_worksheet("RESUMO")
    header = wb.add_format({"bold": True, "bg_color": "#1F4E78", "font_color": "white", "align": "center", "border": 1})
    cell = wb.add_format({"align": "center", "border": 1})
    cell_ferias = wb.add_format({"align": "center", "bg_color": "#FFE699", "border": 1})
    cell_folga = wb.add_format({"align": "center", "bg_color": "#FFC7CE", "border": 1})  # vermelho claro
    # título
    ws.merge_range(0, 0, 0, 15, TITULO, wb.add_format({"bold": True, "font_size": 14, "align": "center"}))
    ws.write(1, 0, SUBTITULO, wb.add_format({"bold": True, "font_size": 12}))
    linha_excel = 3
    df = pd.DataFrame(melhor)
    # largura bonita
    for col, name in enumerate(df.columns):
        ws.write(linha_excel, col, name, header)
        ws.set_column(col, col, 15)
        for row, val in enumerate(df[name], linha_excel + 1):
            dia_num = int(df.iloc[row - (linha_excel + 1), 0].split('/')[0])
            # Destaca férias do operador
            if (col > 0 and esta_de_ferias(val, dia_num)):
                ws.write(row, col, val, cell_ferias)
            else:
                ws.write(row, col, val, cell)
    # =========== TABELA LATERAL (ao lado da escala) ==========
    col_escala_fim = len(df.columns) + 2  # 2 colunas de espaço
    ws.write(linha_excel, col_escala_fim + 0, "NOME", header)
    for i, t in enumerate(turnos):
        ws.write(linha_excel, col_escala_fim + 1 + i, t, header)
    ws.write(linha_excel, col_escala_fim + 1 + len(turnos), "DIAS", header)
    ws.write(linha_excel, col_escala_fim + 2 + len(turnos), "FOLGA", header)
    # Coleta stats
    stats = {p: {t: 0 for t in turnos} for p in operadores}
    dias_trab = {p: 0 for p in operadores}
    for dia in melhor:
        nomes_dia = set()
        for turno in turnos:
            op1 = dia[f"{turno}_OP1"]
            op2 = dia[f"{turno}_OP2"]
            stats[op1][turno] += 1
            stats[op2][turno] += 1
            nomes_dia.add(op1)
            nomes_dia.add(op2)
        for n in nomes_dia:
            dias_trab[n] += 1
    # Linhas da lateral
    for idx, p in enumerate(operadores, 1):
        ws.write(linha_excel + idx, col_escala_fim + 0, p, cell)
        for i, t in enumerate(turnos):
            ws.write(linha_excel + idx, col_escala_fim + 1 + i, stats[p][t], cell)
        ws.write(linha_excel + idx, col_escala_fim + 1 + len(turnos), dias_trab[p], cell)
        # Folga colorida se maior ou igual a 10 (ajuste se quiser)
        folgas = dias_no_mes - dias_trab[p]
        if folgas >= 10:
            ws.write(linha_excel + idx, col_escala_fim + 2 + len(turnos), folgas, cell_folga)
        else:
            ws.write(linha_excel + idx, col_escala_fim + 2 + len(turnos), folgas, cell)
    # =========== ABA DE RESUMO GERAL ==============
    wsl.write(0, 0, "OPERADOR", header)
    wsl.write(0, 1, "HORAS", header)
    for idx, op in enumerate(sorted(melhor_horas, key=lambda x: -melhor_horas[x]), 1):
        wsl.write(idx, 0, op, cell)
        wsl.write(idx, 1, melhor_horas[op], cell)
    # =========== GRÁFICO DE CARGA HORÁRIA =========
    plt.figure(figsize=(8, 5))
    plt.bar(list(melhor_horas.keys()), list(melhor_horas.values()))
    plt.xticks(rotation=45, ha='right')
    plt.title('Carga Horária por Operador')
    plt.xlabel('Operador')
    plt.ylabel('Horas no mês')
    plt.tight_layout()
    plt.savefig('grafico_carga_horaria.png', dpi=150)
    wsl.insert_image(2, 3, 'grafico_carga_horaria.png', {'x_scale': 0.7, 'y_scale': 0.7})
    wb.close()
    os.remove('grafico_carga_horaria.png')
    print(f"Arquivo Excel gerado: {output_excel}")

# ============================================================
#                EXPORTAÇÃO PDF (ATUALIZADO)
# ============================================================
def exportar_pdf(df, melhor_horas, stats, dias_trab, titulo, subtitulo, output_pdf):
    resumo_cols = ["OPERADOR", "HORAS", "00H", "06H", "12H", "18H", "DIAS", "FOLGAS"]
    resumo_dados = []
    for op in sorted(melhor_horas, key=lambda x: -melhor_horas[x]):
        linha = [
            op,
            melhor_horas[op],
            stats[op]["00H"],
            stats[op]["06H"],
            stats[op]["12H"],
            stats[op]["18H"],
            dias_trab[op],
            dias_no_mes - dias_trab[op],
        ]
        resumo_dados.append(linha)
    legenda = [
        ["TROCA", "FOLGA", "ATESTADO", "FALTA"],
        ["AMARELO", "VERDE", "LARANJA", "VERMELHO"]
    ]
    gerar_pdf_escala_completa(
        titulo, subtitulo,
        df.columns.tolist(), df.values.tolist(),
        resumo_cols, resumo_dados,
        legenda=legenda, nome_pdf=output_pdf
    )

# ============================================================
#           EXECUTA EXPORTAÇÃO CONFORME ESCOLHA
# ============================================================
df = pd.DataFrame(melhor)
# Para stats e dias_trab
stats = {p: {t: 0 for t in turnos} for p in operadores}
dias_trab = {p: 0 for p in operadores}
for dia in melhor:
    nomes_dia = set()
    for turno in turnos:
        op1 = dia[f"{turno}_OP1"]
        op2 = dia[f"{turno}_OP2"]
        stats[op1][turno] += 1
        stats[op2][turno] += 1
        nomes_dia.add(op1)
        nomes_dia.add(op2)
    for n in nomes_dia:
        dias_trab[n] += 1

if tipo_export in ["E", "AMBOS"]:
    exportar_excel(melhor, melhor_horas)
if tipo_export in ["P", "AMBOS"]:
    exportar_pdf(df, melhor_horas, stats, dias_trab, TITULO, SUBTITULO, output_pdf)

print("\n===============================================================")
print("Processo concluído!")
print("===============================================================\n")
