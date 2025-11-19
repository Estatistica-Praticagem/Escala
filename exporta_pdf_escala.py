from reportlab.lib.pagesizes import landscape, A4
from reportlab.pdfgen import canvas
from reportlab.platypus import Table, TableStyle, SimpleDocTemplate, Paragraph, Spacer, PageBreak
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet

def gerar_pdf_escala_completa(
    titulo, subtitulo, colunas_escala, dados_escala, 
    resumo_cols, resumo_dados, 
    legenda=None, nome_pdf="ESCALA_TORRE_PROFISSIONAL.pdf"
):
    largura, altura = landscape(A4)
    styles = getSampleStyleSheet()
    styleN = styles["Normal"]
    styleH = styles["Heading2"]

    pdf = SimpleDocTemplate(
        nome_pdf, pagesize=landscape(A4), leftMargin=25, rightMargin=25, topMargin=20, bottomMargin=20
    )
    elements = []

    # --- TÍTULO ---
    elements.append(Paragraph(f"<b>{titulo}</b>", styleH))
    elements.append(Paragraph(subtitulo, styleN))
    elements.append(Spacer(1, 10))

    # --- LEGENDA ---
    if legenda:
        t_leg = Table(legenda)
        t_leg.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (0,0), colors.yellow),
            ('BACKGROUND', (1,0), (1,0), colors.green),
            ('BACKGROUND', (2,0), (2,0), colors.orange),
            ('BACKGROUND', (3,0), (3,0), colors.red),
            ('ALIGN', (0,0), (-1,-1), 'CENTER'),
            ('FONTNAME', (0,0), (-1,-1), 'Helvetica-Bold'),
            ('GRID', (0,0), (-1,-1), 0.5, colors.black),
            ('FONTSIZE', (0,0), (-1,-1), 8)
        ]))
        elements.append(t_leg)
        elements.append(Spacer(1, 16))

    # --- TABELA DA ESCALA (pode quebrar em várias páginas se precisar) ---
    def table_style(cols):
        return TableStyle([
            ('BACKGROUND', (0,0), (len(cols)-1,0), colors.HexColor("#1F4E78")),
            ('TEXTCOLOR',(0,0),(len(cols)-1,0),colors.white),
            ('ALIGN',(0,0),(-1,-1),'CENTER'),
            ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
            ('GRID',(0,0),(-1,-1),0.4,colors.black),
            ('FONTSIZE', (0,0), (-1,-1), 7)
        ])

    # Quebrar a tabela de escala em páginas se necessário
    rows_por_pagina = 20  # Ajuste conforme fonte/tamanho de papel
    total_rows = len(dados_escala)
    for i in range(0, total_rows, rows_por_pagina):
        dados_pag = dados_escala[i:i+rows_por_pagina]
        t = Table([colunas_escala] + dados_pag, repeatRows=1)
        t.setStyle(table_style(colunas_escala))
        elements.append(t)
        elements.append(Spacer(1, 14))
        if i + rows_por_pagina < total_rows:
            elements.append(PageBreak())

    # --- SEGUNDA PÁGINA: RESUMO ESTATÍSTICO ---
    elements.append(PageBreak())
    elements.append(Paragraph("<b>RESUMO POR OPERADOR</b>", styleH))
    elements.append(Spacer(1, 8))
    t_res = Table([resumo_cols] + resumo_dados)
    t_res.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (len(resumo_cols)-1,0), colors.HexColor("#888888")),
        ('TEXTCOLOR',(0,0),(len(resumo_cols)-1,0),colors.white),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('GRID',(0,0),(-1,-1),0.4,colors.black),
        ('FONTSIZE', (0,0), (-1,-1), 9)
    ]))
    elements.append(t_res)
    pdf.build(elements)
    print(f"PDF gerado: {nome_pdf}")

# ======= COMO USAR (exemplo) =========
# 1. colunas_escala = lista com nomes das colunas da escala (como DATA, 00H_OP1, etc)
# 2. dados_escala = lista de listas, cada linha um dia, cada célula um nome
# 3. resumo_cols = ["OPERADOR", "HORAS", "00H", "06H", "12H", "18H", "DIAS", "FOLGAS"]
# 4. resumo_dados = lista de listas, cada linha um operador e seus totais
# 5. legenda = [["TROCA", "FOLGA", "ATESTADO", "FALTA"], ["AMARELO", "VERDE", "LARANJA", "VERMELHO"]]

# Exemplo de chamada no seu código principal:
# gerar_pdf_escala_completa(
#    TITULO, SUBTITULO, colunas_escala, dados_escala, 
#    resumo_cols, resumo_dados, 
#    legenda=legenda, nome_pdf="ESCALA_TORRE_PROFISSIONAL.pdf"
# )

