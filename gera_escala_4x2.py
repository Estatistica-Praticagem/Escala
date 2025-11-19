import pandas as pd
import calendar
from datetime import datetime, timedelta

ANO = 2025
MES = 12

# ---------------------------------------------
# GRUPOS
# ---------------------------------------------
experientes = [
    "ALLAN", "RODRIGO", "EDUARDO", "MARCO", 
    "BRANCÃO", "CLEITON", "TONINHO"
]

auxiliares = [
    "THAIS", "FELIPE", "B.SELAYARAN", 
    "RICHER", "B.HORNES", "GUILHERME"
]

# Remover desligados
remover = ["BERNARDO"]
experientes = [x for x in experientes if x not in remover]
auxiliares = [x for x in auxiliares if x not in remover]

# Férias
ferias = {
    "VITORIA": (datetime(2025,12,3), datetime(2026,1,2)),
    "B.MACHADO": (datetime(2025,12,10), datetime(2025,12,30)),
}

# ---------------------------------------------
# Funções auxiliares
# ---------------------------------------------
def em_ferias(nome, dia):
    if nome not in ferias:
        return False
    ini, fim = ferias[nome]
    return ini <= dia <= fim

def gerar_ciclos(nomes):
    ciclos = {}
    base_data = datetime(ANO, MES, 1)
    ciclo_padrao = ["T","T","T","T","F","F"]  # 4x2

    for i, nome in enumerate(nomes):
        ciclos[nome] = []
        offset = i % 6  # defasagem na escala 4x2

        for d in range(1, calendar.monthrange(ANO, MES)[1] + 1):
            tipo = ciclo_padrao[(d + offset) % 6]
            ciclos[nome].append(tipo)

    return ciclos

# ---------------------------------------------
# Ciclos 4x2
# ---------------------------------------------
ciclo_exp = gerar_ciclos(experientes)
ciclo_aux = gerar_ciclos(auxiliares)

# ---------------------------------------------
# Montagem escala
# ---------------------------------------------
turnos = ["00H", "06H", "12H", "18H"]
escala = []

dias = calendar.monthrange(ANO, MES)[1]

for dia in range(1, dias + 1):
    data_dia = datetime(ANO, MES, dia)
    linha = {"DATA": data_dia.strftime("%d/%m/%Y")}

    exp_disp = [e for e in experientes if ciclo_exp[e][dia - 1] == "T" and not em_ferias(e, data_dia)]
    aux_disp = [a for a in auxiliares if ciclo_aux[a][dia - 1] == "T" and not em_ferias(a, data_dia)]

    for t in turnos:
        if not exp_disp:
            exp = "FALTA_EXP"
        else:
            exp = exp_disp.pop(0)

        if not aux_disp:
            aux = "FALTA_AUX"
        else:
            aux = aux_disp.pop(0)

        linha[f"{t}_EXP"] = exp
        linha[f"{t}_AUX"] = aux

    escala.append(linha)

df = pd.DataFrame(escala)
df.to_excel(f"ESCALA_4x2_{MES:02d}_{ANO}.xlsx", index=False)

print("ESCALA 4x2 GERADA.")
