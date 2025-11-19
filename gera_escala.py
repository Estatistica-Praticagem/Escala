import pandas as pd
import calendar
from datetime import datetime, timedelta
import random

# ---------------------------------------------
# CONFIGURAÇÕES DA ESCALA
# ---------------------------------------------

ANO = 2025
MES = 12

# Operadores divididos em 2 categorias
experientes = [
    "ALLAN", "RODRIGO", "EDUARDO", "MARCO",
    "BRANCÃO", "CLEITON", "TONINHO"
]

auxiliares = [
    "THAIS", "FELIPE", "B.SELAYARAN", "RICHER",
    "B.HORNES", "GUILHERME"
]

# Remover Bernardo (desligado)
removidos = ["BERNARDO"]
auxiliares = [x for x in auxiliares if x not in removidos]
experientes = [x for x in experientes if x not in removidos]

# Dias de férias (exemplo do PDF)
ferias = {
    "VITORIA": (datetime(2025,12,3), datetime(2026,1,2)),
    "B.MACHADO": (datetime(2025,12,10), datetime(2025,12,30)),
}

# ---------------------------------------------
# Função para verificar se operador está em férias
# ---------------------------------------------
def em_ferias(nome, dia):
    if nome not in ferias:
        return False
    inicio, fim = ferias[nome]
    return inicio <= dia <= fim

# ---------------------------------------------
# Montar a escala diária
# ---------------------------------------------
dias_no_mes = calendar.monthrange(ANO, MES)[1]

turnos = ["00H", "06H", "12H", "18H"]
escala = []

# Índice cíclico p/ turnos (4x2 operadores)
idx_exp = 0
idx_aux = 0

for dia in range(1, dias_no_mes + 1):
    data_dia = datetime(ANO, MES, dia)

    linha = {"DATA": data_dia.strftime("%d/%m/%Y")}

    for t in turnos:

        # Buscar próximo experiente não de férias
        while em_ferias(experientes[idx_exp % len(experientes)], data_dia):
            idx_exp += 1
        
        # Buscar próximo auxiliar não de férias
        while em_ferias(auxiliares[idx_aux % len(auxiliares)], data_dia):
            idx_aux += 1

        exp = experientes[idx_exp % len(experientes)]
        aux = auxiliares[idx_aux % len(auxiliares)]

        linha[f"{t}_EXP"] = exp
        linha[f"{t}_AUX"] = aux

        idx_exp += 1
        idx_aux += 1

    escala.append(linha)

# ---------------------------------------------
# Gerar planilha Excel
# ---------------------------------------------
df = pd.DataFrame(escala)

arquivo_saida = f"ESCALA_{MES:02d}_{ANO}.xlsx"
df.to_excel(arquivo_saida, index=False)

print(f"Escala gerada com sucesso: {arquivo_saida}")
