# ===============================================================
#  ESCALA TORRE — VERSÃO PROFISSIONAL V2.0 (XlsxWriter)
# ===============================================================

import pandas as pd
from datetime import datetime
import calendar
import xlsxwriter

print("""
===============================================================
    SISTEMA DE ESCALA TORRE — V2.0 PROFISSIONAL
===============================================================
Escolha o modo de balanceamento:

A → Balanceamento SUAVE (respeita mais preferências)
B → Balanceamento FORTE (foca em igualar horas)
===============================================================
""")

modo = input("Digite A ou B para escolher o modo: ").strip().upper()
if modo not in ["A", "B"]:
    print("Modo inválido. Use A ou B.")
    exit()

print(f"\n→ MODO SELECIONADO: {modo}\n")

# ===============================================================
#  CONFIGURAÇÕES INICIAIS
# ===============================================================

ANO = 2025
MES = 12
dias_no_mes = calendar.monthrange(ANO, MES)[1]

turnos = ["00H", "06H", "12H", "18H"]
horas_por_turno = 6
limite_dias_consecutivos = 6

# ===============================================================
#  OPERADORES
# ===============================================================

experientes = [
    "ALLAN", "RODRIGO", "EDUARDO", "MARCO",
    "BRANCÃO", "CLEITON", "TONINHO"
]

auxiliares = [
    "THAIS", "FELIPE", "B.SELAYARAN",
    "RICHER", "GUILHERME", "B.HORNES"
]

# ===============================================================
#  PREFERÊNCIAS
# ===============================================================

preferencias = {
    "ALLAN": ["06H", "12H"],
    "RODRIGO": ["18H"],
    "EDUARDO": ["00H", "06H"],
    "MARCO": ["12H"],
    "BRANCÃO": ["18H"],
    "CLEITON": ["06H"],
    "TONINHO": ["12H"],
    "THAIS": ["00H"],
    "FELIPE": ["06H"],
    "B.SELAYARAN": ["12H"],
    "RICHER": ["18H"],
    "GUILHERME": ["12H"],
    "B.HORNES": ["18H"]
}

# ===============================================================
#  RESTRIÇÕES
# ===============================================================

restricoes = {
    "THAIS": ["18H"],
    "RODRIGO": ["00H"],
    "FELIPE": ["00H"],
    "GUILHERME": ["00H"]
}

# ===============================================================
#  PLANTÕES FIXOS
# ===============================================================

plantoes_fixos = {
    "CLEITON": "06H",
    "MARCO": "12H",
    "BRANCÃO": "18H",
    "ALLAN": "06H"
}

# ===============================================================
# CONTROLES INTERNOS
# ===============================================================

cont_consec = {p: 0 for p in experientes + auxiliares}
horas_total = {p: 0 for p in experientes + auxiliares}

# ===============================================================
#  FUNÇÕES AUXILIARES
# ===============================================================

def pode_trabalhar(pessoa, turno):
    """Restrições obrigatórias."""
    return not (pessoa in restricoes and turno in restricoes[pessoa])

def peso_preferencia(pessoa, turno):
    return -5 if pessoa in preferencias and turno in preferencias[pessoa] else 0

def peso_plantao(pessoa, turno):
    return -10 if pessoa in plantoes_fixos and plantoes_fixos[pessoa] == turno else 0

def peso_carga(pessoa):
    """Usado no balanceamento automatico."""
    return horas_total[pessoa] / 10

def peso_consecutivos(pessoa):
    return cont_consec[pessoa] * 3

def calcular_prioridade(pessoa, turno, modo):
    score = 0

    # MODO A — suave (preferências pesam mais)
    if modo == "A":
        score += peso_preferencia(pessoa, turno)
        score += peso_plantao(pessoa, turno)
        score += peso_carga(pessoa)
        score += peso_consecutivos(pessoa)

    # MODO B — forte (igualar horas é prioridade)
    elif modo == "B":
        score += peso_carga(pessoa) * 2
        score += peso_consecutivos(pessoa)
        score += peso_preferencia(pessoa, turno) // 2
        score += peso_plantao(pessoa, turno) // 2

    return score

def ordenar_disponiveis(lista, turno, modo):
    return sorted(lista, key=lambda p: calcular_prioridade(p, turno, modo))

# ===============================================================
#  MOTOR PRINCIPAL (ALOCAÇÃO)
# ===============================================================

def escolher_operador(lista, turno, modo):
    candidatos = [p for p in lista if 
                  pode_trabalhar(p, turno) and 
                  cont_consec[p] < limite_dias_consecutivos]

    if not candidatos:
        return lista[0]  # fallback

    ordenados = ordenar_disponiveis(candidatos, turno, modo)
    return ordenados[0]



# ===============================================================
#  GERAÇÃO DA TABELA DE ESCALA
# ===============================================================

dados = []

for dia in range(1, dias_no_mes + 1):

    data = datetime(ANO, MES, dia)
    linha = {"DATA": data.strftime("%d/%m/%Y")}

    exp_disp = experientes.copy()
    aux_disp = auxiliares.copy()

    for turno in turnos:

        exp = escolher_operador(exp_disp, turno, modo)
        aux = escolher_operador(aux_disp, turno, modo)

        linha[f"{turno}_EXP"] = exp
        linha[f"{turno}_AUX"] = aux

        cont_consec[exp] += 1
        cont_consec[aux] += 1

        horas_total[exp] += horas_por_turno
        horas_total[aux] += horas_por_turno

        exp_disp.remove(exp)
        aux_disp.remove(aux)

    # reset de quem não trabalhou no dia
    for p in horas_total:
        if p not in linha.values():
            cont_consec[p] = 0

    dados.append(linha)

df = pd.DataFrame(dados)


# ===============================================================
#  EXPORTAÇÃO EXCEL — XlsxWriter (cores profissionais)
# ===============================================================

output = "ESCALA_TORRE_V2_PROFISSIONAL.xlsx"
writer = pd.ExcelWriter(output, engine="xlsxwriter")
df.to_excel(writer, sheet_name="ESCALA", index=False)

workbook  = writer.book
worksheet = writer.sheets["ESCALA"]

# formatos
header_fmt = workbook.add_format({
    "bold": True,
    "bg_color": "#1F4E78",
    "font_color": "white",
    "align": "center"
})

cell_fmt = workbook.add_format({
    "align": "center",
    "border": 1
})

# aplica formatação
for col_num, value in enumerate(df.columns.values):
    worksheet.write(0, col_num, value, header_fmt)
    worksheet.set_column(col_num, col_num, 14, cell_fmt)

# ===============================================================
#  ABA DE RELATÓRIO DE HORAS
# ===============================================================

ws2 = workbook.add_worksheet("RELATORIO_DE_HORAS")

ws2.write(0,0,"OPERADOR", header_fmt)
ws2.write(0,1,"HORAS", header_fmt)

linha = 1
for operador, horas in horas_total.items():
    ws2.write(linha, 0, operador, cell_fmt)
    ws2.write(linha, 1, horas, cell_fmt)
    linha += 1

writer.close()

# ===============================================================
#  RELATÓRIO FINAL NO TERMINAL
# ===============================================================

print("\n================ RELATÓRIO FINAL ================\n")
for op, hrs in sorted(horas_total.items(), key=lambda x: x[1]):
    print(f"{op:12} → {hrs} horas")

print("\nArquivo gerado:", output)
print("=================================================\n")


