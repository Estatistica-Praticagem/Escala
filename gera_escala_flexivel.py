import pandas as pd
import calendar
from datetime import datetime

ANO = 2025
MES = 12

experientes = [
    "ALLAN", "RODRIGO", "EDUARDO", "MARCO",
    "BRANCÃO", "CLEITON", "TONINHO"
]

auxiliares = [
    "THAIS", "FELIPE", "B.SELAYARAN",
    "RICHER", "B.HORNES", "GUILHERME"
]

ferias = {
    "VITORIA": (datetime(2025,12,3), datetime(2026,1,2)),
    "B.MACHADO": (datetime(2025,12,10), datetime(2025,12,30)),
}

remover = ["BERNARDO"]
experientes = [x for x in experientes if x not in remover]
auxiliares = [x for x in auxiliares if x not in remover]

def em_ferias(nome, dia):
    if nome not in ferias:
        return False
    i, f = ferias[nome]
    return i <= dia <= f

dias = calendar.monthrange(ANO, MES)[1]
turnos = ["00H", "06H", "12H", "18H"]

escala = []

cont_trabalho = {n: 0 for n in experientes + auxiliares}

for dia in range(1, dias + 1):
    data_dia = datetime(ANO, MES, dia)
    linha = {"DATA": data_dia.strftime("%d/%m/%Y")}

    exp_disponiveis = [e for e in experientes if not em_ferias(e, data_dia)]
    aux_disponiveis = [a for a in auxiliares if not em_ferias(a, data_dia)]

    for t in turnos:
        exp = None
        aux = None

        exp_candidates = [e for e in exp_disponiveis if cont_trabalho[e] < 6]
        aux_candidates = [a for a in aux_disponiveis if cont_trabalho[a] < 6]

        if exp_candidates:
            exp = exp_candidates[0]
        elif exp_disponiveis:
            exp = exp_disponiveis[0]

        if aux_candidates:
            aux = aux_candidates[0]
        elif aux_disponiveis:
            aux = aux_disponiveis[0]

        # Se faltar um grupo → usar exceção
        if exp is None and aux is not None:
            exp = aux
        if aux is None and exp is not None:
            aux = exp

        linha[f"{t}_EXP"] = exp
        linha[f"{t}_AUX"] = aux

        if exp:
            cont_trabalho[exp] += 1
        if aux and aux != exp:
            cont_trabalho[aux] += 1

    escala.append(linha)

df = pd.DataFrame(escala)
df.to_excel(f"ESCALA_FLEXIVEL_{MES:02d}_{ANO}.xlsx", index=False)

print("ESCALA FLEXÍVEL GERADA.")
