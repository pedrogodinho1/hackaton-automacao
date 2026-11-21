from flask import render_template, request, redirect, url_for, flash
from app import app, db
from app.models import Laudo, ResultadoAnalise, EficienciaETE
from app.services import importar_relatorio_excel


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
    # Abre o relatorio de uma campanha que ja esta gravada no banco
    laudo = Laudo.query.filter_by(codigo_laudo=codigo_laudo).first_or_404()
    medicoes_p2 = [m for m in laudo.medicoes if m.ponto_coleta == 'P2']
    medicoes_rio = [m for m in laudo.medicoes if m.ponto_coleta in ('P3', 'P4')]
    alertas = [m for m in laudo.medicoes if m.status_conformidade == 'Não Conforme']

    return render_template(
        'relatorio.html',
        laudo=laudo,
        medicoes_p2=medicoes_p2,
        medicoes_rio=medicoes_rio,
        eficiencias=laudo.eficiencias,
        alertas=alertas
    )
