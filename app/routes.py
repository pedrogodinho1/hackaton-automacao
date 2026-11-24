from flask import render_template, request, redirect, url_for, flash, send_file, jsonify, make_response
from app import app
from app.services import (
    listar_laudos_sessao,
    importar_relatorio_excel,
    importar_relatorio_pdf,
    obter_contexto_relatorio,
    gerar_pdf_relatorio,
    obter_dados_dashboard,
    excluir_laudo,
    limpar_todos_laudos,
)


@app.route('/')
def index():
    """Exibe a pagina inicial de importacao de planilhas Excel e as campanhas da sessao."""
    campanhas = listar_laudos_sessao(ordem_desc=True)
    return render_template('index.html', campanhas=campanhas)


@app.route('/importar', methods=['POST'])
def importar():
    """Valida a planilha Excel enviada, executa a analise ambiental e renderiza o parecer."""
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


@app.route('/importar-pdf', methods=['GET', 'POST'])
def importar_pdf():
    """Exibe a tela de leitura de PDF (GET) ou extrai e analisa o laudo enviado (POST)."""
    if request.method == 'GET':
        campanhas = listar_laudos_sessao(ordem_desc=True)
        return render_template('importar_pdf.html', campanhas=campanhas)

    if 'arquivo_pdf' not in request.files:
        flash("Nenhum arquivo enviado. Selecione um laudo laboratorial em formato PDF.", "error")
        return redirect(url_for('importar_pdf'))

    arquivo = request.files['arquivo_pdf']
    if not arquivo.filename:
        flash("Nenhum arquivo selecionado.", "error")
        return redirect(url_for('importar_pdf'))

    if not arquivo.filename.lower().endswith('.pdf'):
        flash("Formato inválido. Por favor, selecione um arquivo PDF (.pdf).", "error")
        return redirect(url_for('importar_pdf'))

    try:
        resultado = importar_relatorio_pdf(arquivo, nome_arquivo=arquivo.filename)
        return render_template('relatorio.html', resultado=resultado)
    except Exception as e:
        flash(f"Não foi possível processar o laudo em PDF: {e}", "error")
        return redirect(url_for('importar_pdf'))


@app.route('/dashboard')
def dashboard():
    """Exibe o Dashboard Ambiental consolidado com KPIs, graficos dinamicos e alertas."""
    campanha = request.args.get('campanha', 'todas')
    parametro = request.args.get('parametro', '')
    dados = obter_dados_dashboard(campanha_filtro=campanha, parametro_filtro=parametro)
    resp = make_response(render_template('dashboard.html', dados=dados))
    resp.headers['Cache-Control'] = 'no-store'
    return resp


@app.route('/api/dashboard')
def api_dashboard():
    """Endpoint JSON para atualizacao interativa dos filtros e graficos no Dashboard."""
    campanha = request.args.get('campanha', 'todas')
    parametro = request.args.get('parametro', '')
    dados = obter_dados_dashboard(campanha_filtro=campanha, parametro_filtro=parametro)
    resp = make_response(jsonify(dados))
    resp.headers['Cache-Control'] = 'no-store'
    return resp


@app.route('/relatorio/<codigo_laudo>')
def ver_relatorio(codigo_laudo):
    """Carrega os dados de uma campanha ja gravada no banco e exibe o parecer em HTML."""
    contexto = obter_contexto_relatorio(codigo_laudo)
    return render_template('relatorio.html', **contexto)


@app.route('/relatorio/<codigo_laudo>/pdf')
def baixar_relatorio_pdf(codigo_laudo):
    """Gera o relatorio tecnico em PDF na memoria via xhtml2pdf e entrega para download."""
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


@app.route('/laudo/<codigo_laudo>/excluir', methods=['POST'])
def excluir_laudo_rota(codigo_laudo):
    """Exclui uma campanha especifica e suas medicoes e eficiencias associadas."""
    origem = request.form.get('origem', 'index')
    try:
        removido = excluir_laudo(codigo_laudo)
        if removido:
            flash(f"Laudo '{codigo_laudo}' excluído com sucesso.", "success")
        else:
            flash(f"Laudo '{codigo_laudo}' não encontrado.", "error")
    except Exception as e:
        flash(f"Não foi possível excluir o laudo: {e}", "error")

    if origem == 'dashboard':
        return redirect(url_for('dashboard'))
    if origem == 'importar_pdf':
        return redirect(url_for('importar_pdf'))
    return redirect(url_for('index'))


@app.route('/laudos/limpar', methods=['POST'])
def limpar_laudos_rota():
    """Limpa todos os laudos importados, preservando normas e parametros de referencia."""
    origem = request.form.get('origem', 'index')
    try:
        total = limpar_todos_laudos()
        if total > 0:
            flash(f"Histórico limpo: {total} campanha(s) removida(s). Pronto para novas importações.", "success")
        else:
            flash("Não há campanhas gravadas para remover.", "success")
    except Exception as e:
        flash(f"Não foi possível limpar o histórico: {e}", "error")

    if origem == 'dashboard':
        return redirect(url_for('dashboard'))
    if origem == 'importar_pdf':
        return redirect(url_for('importar_pdf'))
    return redirect(url_for('index'))


@app.errorhandler(413)
def arquivo_muito_grande(_error):
    """Trata uploads acima do limite configurado de 16 MB com retorno amigavel."""
    mensagem = "O arquivo enviado excede o limite máximo permitido de 16 MB."
    if request.path.startswith('/api/'):
        return jsonify({'erro': mensagem}), 413
    flash(mensagem, "error")
    if request.path == '/importar-pdf':
        return redirect(url_for('importar_pdf'))
    return redirect(url_for('index'))
