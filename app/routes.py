from flask import render_template, request, redirect, url_for, flash, send_file
from app import app
from app.models import Laudo
from app.services import (
    importar_relatorio_excel,
    obter_contexto_relatorio,
    gerar_pdf_relatorio,
)


@app.route('/')
def index():
    # Tela inicial com formulario de upload e listagem das campanhas salvas
    campanhas = Laudo.query.order_by(Laudo.data_coleta.desc()).all()
    return render_template('index.html', campanhas=campanhas)


@app.route('/importar', methods=['POST'])
def importar():
    # Recebe a planilha enviada, roda a analise em pandas e exibe o relatorio
    if 'arquivo' not in request.files:
        flash("Nenhum arquivo enviado. Selecione uma planilha Excel (.xlsx ou .xls).", "error")
        return redirect(url_for('index'))

    arquivo = request.files['arquivo']
    if not arquivo.filename:
        flash("Nenhum arquivo selecionado.", "error")
        return redirect(url_for('index'))

    if not arquivo.filename.lower().endswith(('.xlsx', '.xls')):
        flash("Formato invalido. Envie uma planilha Excel (.xlsx ou .xls).", "error")
        return redirect(url_for('index'))

    try:
        resultado = importar_relatorio_excel(arquivo, nome_arquivo=arquivo.filename)
        return render_template('relatorio.html', resultado=resultado)
    except Exception as e:
        flash(f"Nao foi possivel processar a planilha: {e}", "error")
        return redirect(url_for('index'))


@app.route('/relatorio/<codigo_laudo>')
def ver_relatorio(codigo_laudo):
    # Exibe na interface HTML a campanha salva no banco
    contexto = obter_contexto_relatorio(codigo_laudo)
    return render_template('relatorio.html', **contexto)


@app.route('/relatorio/<codigo_laudo>/pdf')
def baixar_relatorio_pdf(codigo_laudo):
    # Gera o PDF em memoria via xhtml2pdf e entrega como download (attachment)
    try:
        contexto = obter_contexto_relatorio(codigo_laudo)
        pdf_buffer = gerar_pdf_relatorio(contexto)

        data_str = contexto['laudo'].data_coleta.strftime('%Y%m%d')
        nome_arquivo = f"relatorio_efluentes_{codigo_laudo}_{data_str}.pdf"

        return send_file(
            pdf_buffer,
            mimetype="application/pdf",
            as_attachment=True,
            download_name=nome_arquivo
        )
    except Exception as e:
        flash(f"Erro ao gerar o arquivo PDF: {e}", "error")
        return redirect(url_for('ver_relatorio', codigo_laudo=codigo_laudo))
