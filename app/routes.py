import hmac
import re
import secrets
import zipfile
from flask import render_template, request, redirect, url_for, flash, send_file, jsonify, session
from werkzeug.exceptions import HTTPException
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


def gerar_csrf_token() -> str:
    """Gera ou recupera o token CSRF vinculado a sessao do navegador."""
    token = session.get('csrf_token')
    if not token:
        token = secrets.token_hex(32)
        session['csrf_token'] = token
    return token


_MAX_XLSX_DESCOMPRIMIDO_BYTES = 50 * 1024 * 1024
_MAX_XLSX_ENTRADAS_ZIP = 500


def validar_assinatura_arquivo(arquivo, tipo: str) -> bool:
    """Confere magic bytes e estrutura interna (.xlsx seguro contra ZIP falso e zip-bomb)."""
    cabecalho = arquivo.stream.read(8)
    arquivo.stream.seek(0)
    if tipo == 'pdf':
        return cabecalho.startswith(b'%PDF-')
    if tipo == 'excel':
        if not cabecalho.startswith(b'PK\x03\x04'):
            return False
        try:
            with zipfile.ZipFile(arquivo.stream, 'r') as zf:
                infos = zf.infolist()
                if not infos or len(infos) > _MAX_XLSX_ENTRADAS_ZIP:
                    return False
                tamanho_total = sum(info.file_size for info in infos)
                if tamanho_total > _MAX_XLSX_DESCOMPRIMIDO_BYTES:
                    return False
                nomes = set(zf.namelist())
                return '[Content_Types].xml' in nomes and 'xl/workbook.xml' in nomes
        except (zipfile.BadZipFile, OSError, ValueError):
            return False
        finally:
            arquivo.stream.seek(0)
    return False


@app.context_processor
def injetar_csrf_token():
    """Disponibiliza a funcao csrf_token() em todos os templates Jinja2."""
    return {'csrf_token': gerar_csrf_token}


@app.before_request
def validar_csrf():
    """Valida o token CSRF em requisicoes que alteram estado (POST/PUT/DELETE/PATCH)."""
    if request.method not in ('POST', 'PUT', 'DELETE', 'PATCH'):
        return None
    token_sessao = session.get('csrf_token', '')
    token_enviado = request.form.get('csrf_token') or request.headers.get('X-CSRF-Token', '')
    if not token_sessao or not token_enviado or not hmac.compare_digest(token_sessao, token_enviado):
        mensagem = "Sessão expirada ou requisição inválida. Recarregue a página e tente novamente."
        if request.path.startswith('/api/'):
            return jsonify({'erro': mensagem}), 403
        flash(mensagem, "error")
        if request.path == '/importar-pdf':
            return redirect(url_for('importar_pdf'))
        if request.form.get('origem') == 'dashboard':
            return redirect(url_for('dashboard'))
        return redirect(url_for('index'))
    return None


@app.after_request
def aplicar_cabecalhos_seguranca(response):
    """Adiciona cabecalhos HTTP de seguranca (CSP, clickjacking, MIME sniffing e controle de cache)."""
    response.headers.setdefault('X-Content-Type-Options', 'nosniff')
    response.headers.setdefault('X-Frame-Options', 'DENY')
    response.headers.setdefault('Referrer-Policy', 'same-origin')
    response.headers.setdefault('Permissions-Policy', 'geolocation=(), microphone=(), camera=()')
    response.headers.setdefault(
        'Content-Security-Policy',
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com https://cdn.jsdelivr.net; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com data:; "
        "img-src 'self' data: blob:; "
        "connect-src 'self'; "
        "object-src 'none'; "
        "base-uri 'self'; "
        "frame-ancestors 'none'; "
        "form-action 'self'"
    )
    if not request.path.startswith('/static/'):
        response.headers.setdefault('Cache-Control', 'no-store')
    return response


@app.route('/')
def index():
    """Exibe a pagina inicial de importacao de planilhas Excel e as campanhas da sessao."""
    campanhas = listar_laudos_sessao(ordem_desc=True)
    return render_template('index.html', campanhas=campanhas)


@app.route('/importar', methods=['POST'])
def importar():
    """Valida a planilha Excel enviada, executa a analise ambiental e renderiza o parecer."""
    if 'arquivo' not in request.files:
        flash("Nenhum arquivo enviado. Selecione uma planilha Excel (.xlsx).", "error")
        return redirect(url_for('index'))

    arquivo = request.files['arquivo']
    if not arquivo.filename:
        flash("Nenhum arquivo selecionado.", "error")
        return redirect(url_for('index'))

    nome_lower = arquivo.filename.lower()
    if nome_lower.endswith('.xls'):
        flash("Formato legado .xls não é suportado. Salve a planilha como .xlsx e tente novamente.", "error")
        return redirect(url_for('index'))

    if not nome_lower.endswith('.xlsx'):
        flash("Formato inválido. Envie uma planilha Excel no formato .xlsx.", "error")
        return redirect(url_for('index'))

    if not validar_assinatura_arquivo(arquivo, 'excel'):
        flash("O conteúdo do arquivo não corresponde a uma planilha Excel válida (.xlsx).", "error")
        return redirect(url_for('index'))

    try:
        resultado = importar_relatorio_excel(arquivo, nome_arquivo=arquivo.filename)
        return render_template('relatorio.html', resultado=resultado)
    except ValueError as e:
        flash(f"Não foi possível processar a planilha: {e}", "error")
        return redirect(url_for('index'))
    except Exception:
        app.logger.exception("Erro inesperado ao processar planilha Excel.")
        flash("Não foi possível processar a planilha enviada. Verifique se o arquivo está íntegro e no padrão esperado.", "error")
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

    if not validar_assinatura_arquivo(arquivo, 'pdf'):
        flash("O conteúdo do arquivo não corresponde a um documento PDF válido.", "error")
        return redirect(url_for('importar_pdf'))

    try:
        resultado = importar_relatorio_pdf(arquivo, nome_arquivo=arquivo.filename)
        return render_template('relatorio.html', resultado=resultado)
    except ValueError as e:
        flash(f"Não foi possível processar o laudo em PDF: {e}", "error")
        return redirect(url_for('importar_pdf'))
    except Exception:
        app.logger.exception("Erro inesperado ao processar laudo PDF.")
        flash("Não foi possível processar o laudo em PDF. Verifique se o arquivo está íntegro.", "error")
        return redirect(url_for('importar_pdf'))


@app.route('/dashboard')
def dashboard():
    """Exibe o Dashboard Ambiental consolidado com KPIs, graficos dinamicos e alertas."""
    campanha = request.args.get('campanha', 'todas')
    parametro = request.args.get('parametro', '')
    dados = obter_dados_dashboard(campanha_filtro=campanha, parametro_filtro=parametro)
    return render_template('dashboard.html', dados=dados)


@app.route('/api/dashboard')
def api_dashboard():
    """Endpoint JSON para atualizacao interativa dos filtros e graficos no Dashboard."""
    campanha = request.args.get('campanha', 'todas')
    parametro = request.args.get('parametro', '')
    dados = obter_dados_dashboard(campanha_filtro=campanha, parametro_filtro=parametro)
    return jsonify(dados)


@app.route('/relatorio/<path:codigo_laudo>/pdf')
def baixar_relatorio_pdf(codigo_laudo):
    """Gera o relatorio tecnico em PDF na memoria via xhtml2pdf e entrega para download."""
    try:
        contexto = obter_contexto_relatorio(codigo_laudo)
        pdf_buffer = gerar_pdf_relatorio(contexto)

        data_str = contexto['laudo'].data_coleta.strftime('%Y%m%d')
        codigo_seguro = re.sub(r'[^A-Za-z0-9._-]', '_', codigo_laudo).strip('._') or 'laudo'
        nome_arquivo = f"relatorio_efluentes_{codigo_seguro}_{data_str}.pdf"

        return send_file(
            pdf_buffer,
            mimetype="application/pdf",
            as_attachment=True,
            download_name=nome_arquivo
        )
    except HTTPException:
        raise
    except Exception:
        app.logger.exception("Erro ao gerar PDF do laudo %s.", codigo_laudo)
        flash("Não foi possível gerar o arquivo PDF no momento.", "error")
        return redirect(url_for('ver_relatorio', codigo_laudo=codigo_laudo))


@app.route('/relatorio/<path:codigo_laudo>')
def ver_relatorio(codigo_laudo):
    """Carrega os dados de uma campanha ja gravada na sessao e exibe o parecer em HTML."""
    contexto = obter_contexto_relatorio(codigo_laudo)
    return render_template('relatorio.html', **contexto)


@app.route('/laudo/<path:codigo_laudo>/excluir', methods=['POST'])
def excluir_laudo_rota(codigo_laudo):
    """Exclui uma campanha especifica da sessao atual."""
    origem = request.form.get('origem', 'index')
    try:
        removido = excluir_laudo(codigo_laudo)
        if removido:
            flash(f"Laudo '{codigo_laudo}' excluído com sucesso.", "success")
        else:
            flash(f"Laudo '{codigo_laudo}' não encontrado.", "error")
    except Exception:
        app.logger.exception("Erro ao excluir laudo %s.", codigo_laudo)
        flash("Não foi possível excluir o laudo.", "error")

    if origem == 'dashboard':
        return redirect(url_for('dashboard'))
    if origem == 'importar_pdf':
        return redirect(url_for('importar_pdf'))
    return redirect(url_for('index'))


@app.route('/laudos/limpar', methods=['POST'])
def limpar_laudos_rota():
    """Limpa todos os laudos importados da sessao, preservando normas e parametros de referencia."""
    origem = request.form.get('origem', 'index')
    try:
        total = limpar_todos_laudos()
        if total > 0:
            flash(f"Histórico limpo: {total} campanha(s) removida(s). Pronto para novas importações.", "success")
        else:
            flash("Não há campanhas carregadas na sessão para remover.", "success")
    except Exception:
        app.logger.exception("Erro ao limpar historico de laudos.")
        flash("Não foi possível limpar o histórico.", "error")

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


@app.errorhandler(404)
def pagina_nao_encontrada(_error):
    """Exibe pagina personalizada de erro 404 ou JSON para chamadas da API."""
    if request.path.startswith('/api/'):
        return jsonify({'erro': 'Recurso não encontrado.'}), 404
    return render_template(
        'erro.html',
        codigo=404,
        titulo='Página ou laudo não encontrado',
        descricao='O endereço solicitado não existe ou o laudo já não está carregado na sessão atual. Se o servidor foi reiniciado ou os dados foram limpos, importe o arquivo novamente.'
    ), 404


@app.errorhandler(405)
def metodo_nao_permitido(_error):
    """Exibe pagina personalizada de erro 405 ou JSON quando o metodo HTTP nao e suportado pela rota."""
    if request.path.startswith('/api/'):
        return jsonify({'erro': 'Método HTTP não permitido para este recurso.'}), 405
    return render_template(
        'erro.html',
        codigo=405,
        titulo='Ação não permitida por acesso direto',
        descricao='Esta rota aceita apenas envio de formulário pela aplicação. Utilize os botões da interface ou retorne à tela inicial.'
    ), 405


@app.errorhandler(500)
def erro_interno_servidor(error):
    """Registra falhas internas inesperadas no log e exibe tela amigavel de erro 500."""
    app.logger.exception("Erro interno não tratado: %s", error)
    if request.path.startswith('/api/'):
        return jsonify({'erro': 'Erro interno ao processar a solicitação.'}), 500
    return render_template(
        'erro.html',
        codigo=500,
        titulo='Erro interno ao processar a página',
        descricao='Ocorreu uma falha inesperada no servidor. Tente novamente ou retorne para a tela inicial.'
    ), 500
