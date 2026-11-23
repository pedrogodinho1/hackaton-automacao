import io
import re
from datetime import datetime, date
from decimal import Decimal, ROUND_HALF_UP
from flask import render_template
import pandas as pd
import pypdf
from xhtml2pdf import pisa
from app import db
from app.models import (
    Laudo,
    ResultadoAnalise,
    EficienciaETE,
    LimiteLegal,
    normalizar_texto,
)

# Sinonimos para identificar nomes de colunas comuns em planilhas laboratoriais
MAPA_COLUNAS_EXCEL = {
    'id_laudo': 'id_laudo',
    'codigo_laudo': 'id_laudo',
    'laudo': 'id_laudo',
    'numero_laudo': 'id_laudo',
    'data_coleta': 'data_coleta',
    'data': 'data_coleta',
    'data_amostragem': 'data_coleta',
    'mes_referencia': 'mes_referencia',
    'campanha': 'mes_referencia',
    'mes': 'mes_referencia',
    'mes_ano': 'mes_referencia',
    'codigo_ponto': 'codigo_ponto',
    'ponto': 'codigo_ponto',
    'cod_ponto': 'codigo_ponto',
    'ponto_coleta': 'ponto_coleta',
    'ponto_amostragem': 'ponto_coleta',
    'parametro': 'parametro',
    'ensaio': 'parametro',
    'analise': 'parametro',
    'unidade': 'unidade',
    'unid': 'unidade',
    'unidade_medida': 'unidade',
    'resultado': 'resultado',
    'valor': 'resultado',
    'valor_medido': 'resultado',
    'concentracao': 'resultado',
    'metodo_analise': 'metodo_analise',
    'metodo': 'metodo_analise',
    'lq_metodo': 'lq_metodo',
    'lq': 'lq_metodo',
}


def extrair_metadados_planilha(excel_file: pd.ExcelFile) -> dict:
    """
    Busca abas auxiliares de metadados na planilha (ex: Metadados_Amostras) para
    preencher laboratorio, unidade monitorada e corpo receptor automaticamente.
    """
    metadados = {
        'laboratorio': 'Laboratório Acreditado',
        'unidade_monitorada': 'ETE Industrial, Unidade Americana/SP',
        'corpo_receptor': 'Rio Piracicaba (Classe 2)',
        'observacoes': 'Importação de dados laboratoriais via pandas.'
    }

    nomes_abas_meta = ['Metadados_Amostras', 'Metadados', 'Informacoes', 'Configuracao', 'Cadastro']
    aba_meta = next((s for s in excel_file.sheet_names if s in nomes_abas_meta), None)

    if aba_meta:
        try:
            df_meta = excel_file.parse(aba_meta)
            if df_meta.shape[1] >= 2:
                col_chave, col_valor = df_meta.columns[0], df_meta.columns[1]
                for _, row in df_meta.iterrows():
                    chave = str(row[col_chave]).strip().lower()
                    valor = str(row[col_valor]).strip()
                    if valor and valor.lower() != 'nan':
                        if 'laborat' in chave:
                            metadados['laboratorio'] = valor
                        elif 'unidade' in chave:
                            metadados['unidade_monitorada'] = valor
                        elif 'receptor' in chave or 'rio' in chave:
                            metadados['corpo_receptor'] = valor
                        elif 'observa' in chave:
                            metadados['observacoes'] = valor
        except Exception:
            pass

    return metadados


def selecionar_aba_dados(excel_file: pd.ExcelFile) -> str:
    """Seleciona a aba principal de medicoes por nomes conhecidos ou usa a primeira aba."""
    abas = excel_file.sheet_names
    preferenciais = ['dados_importacao', 'dados', 'medicoes', 'resultados', 'laudo', 'planilha1']
    for p in preferenciais:
        for aba in abas:
            if normalizar_texto(aba) == p:
                return aba
    return abas[0]


def padronizar_dataframe_pandas(df: pd.DataFrame) -> pd.DataFrame:
    """
    Normaliza os nomes das colunas via dicionario de sinonimos, limpa linhas vazias
    e extrai datas, mes de referencia e codigo do ponto de coleta (P1 a P4).
    """
    novas_colunas = {}
    for col in df.columns:
        col_limpa = normalizar_texto(str(col)).replace(' ', '_')
        novas_colunas[col] = MAPA_COLUNAS_EXCEL.get(col_limpa, col_limpa)

    df = df.rename(columns=novas_colunas).dropna(how='all')

    for obrigatoria in ['parametro', 'resultado']:
        if obrigatoria not in df.columns:
            raise ValueError(f"A planilha precisa ter a coluna '{obrigatoria}'.")

    if 'data_coleta' in df.columns:
        df['data_coleta'] = pd.to_datetime(df['data_coleta'], errors='coerce')
    else:
        df['data_coleta'] = pd.to_datetime(datetime.now().date())

    if 'mes_referencia' not in df.columns or df['mes_referencia'].isna().all():
        df['mes_referencia'] = df['data_coleta'].dt.strftime('%Y-%m')
    else:
        df['mes_referencia'] = df['mes_referencia'].astype(str).str.strip()

    # Se nao tiver codigo do ponto direto, tenta achar P1..P4 no texto da coluna
    if 'codigo_ponto' in df.columns:
        df['codigo_ponto'] = df['codigo_ponto'].astype(str).str.upper().str.strip()
    elif 'ponto_coleta' in df.columns:
        df['codigo_ponto'] = df['ponto_coleta'].astype(str).str.extract(r'(P[1-4])', flags=re.IGNORECASE)[0].str.upper()
    else:
        df['codigo_ponto'] = 'P2'

    if 'unidade' not in df.columns:
        df['unidade'] = 'mg/L'
    else:
        df['unidade'] = df['unidade'].astype(str).str.strip()

    return df


def calcular_eficiencias_campanha(df_mes: pd.DataFrame, laudo_id: int, codigo_laudo: str, data_ref: date) -> list:
    """
    Calcula a eficiencia ((P1 - P2) / P1) * 100 para parametros que tenham
    medicao tanto no bruto quanto no tratado naquele mes.
    """
    eficiencias_salvas = []
    df_p1 = df_mes[df_mes['codigo_ponto'] == 'P1'].set_index('parametro_normalizado')
    df_p2 = df_mes[df_mes['codigo_ponto'] == 'P2'].set_index('parametro_normalizado')

    parametros_comuns = set(df_p1.index).intersection(set(df_p2.index))

    for param_norm in parametros_comuns:
        row_p1 = df_p1.loc[param_norm]
        row_p2 = df_p2.loc[param_norm]

        v1 = float(row_p1['resultado_num'].iloc[0] if isinstance(row_p1, pd.DataFrame) else row_p1['resultado_num'])
        v2 = float(row_p2['resultado_num'].iloc[0] if isinstance(row_p2, pd.DataFrame) else row_p2['resultado_num'])
        nome_param = str(row_p1['parametro'].iloc[0] if isinstance(row_p1, pd.DataFrame) else row_p1['parametro'])
        unidade = str(row_p1['unidade'].iloc[0] if isinstance(row_p1, pd.DataFrame) else row_p1['unidade'])

        if v1 > 0:
            regra_param = LimiteLegal.buscar_por_nome(nome_param)
            # So calcula remocao para parametros de carga (DBO, DQO, SST), nao para pH ou temperatura
            if not regra_param or not regra_param.calcula_eficiencia:
                continue

            avaliacao_ef = regra_param.avaliar_eficiencia(v1, v2)

            ef_obj = EficienciaETE(
                laudo_id=laudo_id,
                codigo_laudo=codigo_laudo,
                data_referencia=data_ref,
                parametro=regra_param.parametro if regra_param else nome_param,
                unidade=unidade,
                entrada_p1=v1,
                saida_p2=v2,
                eficiencia_percentual=avaliacao_ef['eficiencia_pct'],
                avaliacao=avaliacao_ef['avaliacao'],
                atingiu_meta=avaliacao_ef['atingiu_meta']
            )
            db.session.add(ef_obj)
            eficiencias_salvas.append({
                'parametro': ef_obj.parametro,
                'entrada_p1': v1,
                'saida_p2': v2,
                'unidade': unidade,
                'eficiencia_pct': avaliacao_ef['eficiencia_pct'],
                'avaliacao': avaliacao_ef['avaliacao'],
                'atingiu_meta': avaliacao_ef['atingiu_meta']
            })

    return eficiencias_salvas


def avaliar_impacto_corpo_receptor(df_mes: pd.DataFrame) -> list:
    """
    Compara as concentracoes entre Montante (P3) e Jusante (P4) no rio.
    Se P4 ultrapassar os limites do CONAMA 357 (Classe 2) ou subir de forma
    expressiva apos o efluente tratado, gera um aviso de investigacao.
    """
    impactos = []
    df_p3 = df_mes[df_mes['codigo_ponto'] == 'P3'].set_index('parametro_normalizado')
    df_p4 = df_mes[df_mes['codigo_ponto'] == 'P4'].set_index('parametro_normalizado')
    df_p2 = df_mes[df_mes['codigo_ponto'] == 'P2'].set_index('parametro_normalizado')

    parametros_rio = set(df_p3.index).intersection(set(df_p4.index))

    for param_norm in parametros_rio:
        row_p3 = df_p3.loc[param_norm]
        row_p4 = df_p4.loc[param_norm]

        v3 = float(row_p3['resultado_num'].iloc[0] if isinstance(row_p3, pd.DataFrame) else row_p3['resultado_num'])
        v4 = float(row_p4['resultado_num'].iloc[0] if isinstance(row_p4, pd.DataFrame) else row_p4['resultado_num'])
        nome_param = str(row_p3['parametro'].iloc[0] if isinstance(row_p3, pd.DataFrame) else row_p3['parametro'])
        unidade = str(row_p3['unidade'].iloc[0] if isinstance(row_p3, pd.DataFrame) else row_p3['unidade'])

        delta = round(v4 - v3, 3)
        var_pct = round(((v4 - v3) / v3) * 100.0, 1) if v3 > 0 else 0.0

        regra = LimiteLegal.buscar_por_nome(nome_param)
        status_rio = "Normal"
        alerta_impacto = None

        if regra and regra.limite_max_conama357 is not None and v4 > regra.limite_max_conama357:
            status_rio = "Alerta de Impacto"
            alerta_impacto = (
                f"Concentração em Jusante (P4 = {v4} {unidade}) ultrapassou o limite "
                f"do CONAMA 357/2005 Classe 2 (<= {regra.limite_max_conama357} {unidade}). "
                f"Elevação de +{delta} {unidade} ({var_pct:+.1f}%) em relação a Montante (P3 = {v3} {unidade})."
            )
        elif delta > 0 and param_norm in df_p2.index:
            row_p2 = df_p2.loc[param_norm]
            v2 = float(row_p2['resultado_num'].iloc[0] if isinstance(row_p2, pd.DataFrame) else row_p2['resultado_num'])
            if var_pct >= 20.0:
                status_rio = "Atenção"
                alerta_impacto = (
                    f"Elevação de {var_pct:+.1f}% no rio após o lançamento "
                    f"(P3 = {v3} -> P4 = {v4} {unidade}). Concentração no Tratado (P2 = {v2} {unidade}). "
                    f"Recomenda-se investigar a contribuição da ETE."
                )

        impactos.append({
            'parametro': regra.parametro if regra else nome_param,
            'montante_p3': v3,
            'jusante_p4': v4,
            'diferenca': delta,
            'variacao_pct': var_pct,
            'unidade': unidade,
            'status_rio': status_rio,
            'alerta_impacto': alerta_impacto,
            'limite_classe2': regra.texto_conama357 if regra else 'Não tabelado'
        })

    return impactos


def importar_relatorio_excel(origem_arquivo, nome_arquivo: str = "relatorio.xlsx") -> dict:
    """
    Le a planilha Excel via pandas, valida as regras ambientais e salva no banco.
    Aceita tanto caminho de arquivo em disco quanto o buffer vindo do upload HTTP.
    """
    excel_file = pd.ExcelFile(origem_arquivo, engine='openpyxl')
    metadados = extrair_metadados_planilha(excel_file)

    nome_aba = selecionar_aba_dados(excel_file)
    df_bruto = excel_file.parse(nome_aba)
    df = padronizar_dataframe_pandas(df_bruto)
    df['parametro_normalizado'] = df['parametro'].apply(normalizar_texto)

    # Trata valores com limite de quantificacao (ex: "< 0,01")
    def tratar_resultado(val):
        if pd.isna(val):
            return None, "Sem Dados"
        val_str = str(val).strip()
        if val_str.startswith('<'):
            num_parte = re.sub(r'[^\d,\.]', '', val_str).replace(',', '.')
            try:
                # Usa metade do limite de quantificacao para as contas numericas
                return float(num_parte) / 2.0, val_str
            except ValueError:
                return None, val_str
        try:
            return float(str(val).replace(',', '.')), val_str
        except ValueError:
            return None, val_str

    tratados = df['resultado'].apply(tratar_resultado)
    df['resultado_num'] = [t[0] for t in tratados]
    df['resultado_txt'] = [t[1] for t in tratados]

    resultado_processamento = {
        'sucesso': True,
        'arquivo': nome_arquivo,
        'aba_lida': nome_aba,
        'total_linhas': len(df),
        'campanhas_processadas': [],
        'total_alertas': 0,
        'alertas': [],
        'eficiencias': [],
        'impactos_rio': [],
        'relatorios_por_mes': {}
    }

    try:
        # Processa cada mes encontrado na planilha
        for mes in sorted(df['mes_referencia'].unique()):
            df_mes = df[df['mes_referencia'] == mes]
            data_coleta_mes = df_mes['data_coleta'].dropna().iloc[0].date() if not df_mes['data_coleta'].isna().all() else date.today()
            codigo_campanha = f"CAMP-{mes}"

            # Se ja existir a campanha daquele mes, remove previamente com commit para garantir a limpeza no SQLite
            laudos_antigos = Laudo.query.filter_by(codigo_laudo=codigo_campanha).all()
            if laudos_antigos:
                ids_antigos = [l.id for l in laudos_antigos]
                ResultadoAnalise.query.filter(
                    (ResultadoAnalise.codigo_laudo == codigo_campanha) |
                    (ResultadoAnalise.laudo_id.in_(ids_antigos))
                ).delete(synchronize_session=False)
                EficienciaETE.query.filter(
                    (EficienciaETE.codigo_laudo == codigo_campanha) |
                    (EficienciaETE.laudo_id.in_(ids_antigos))
                ).delete(synchronize_session=False)
                for l in laudos_antigos:
                    db.session.delete(l)
                db.session.commit()

            novo_laudo = Laudo(
                codigo_laudo=codigo_campanha,
                unidade_monitorada=metadados['unidade_monitorada'],
                corpo_receptor=metadados['corpo_receptor'],
                campanha_mes=mes,
                data_coleta=data_coleta_mes,
                laboratorio=metadados['laboratorio'],
                arquivo_origem=nome_arquivo,
                observacoes=metadados['observacoes']
            )
            db.session.add(novo_laudo)
            db.session.flush()

            medicoes_mes = []
            alertas_mes = []

            for _, row in df_mes.iterrows():
                nome_param = str(row['parametro']).strip()
                ponto = str(row['codigo_ponto']).strip().upper()
                val_num = row['resultado_num']
                val_txt = row['resultado_txt']
                unidade = str(row['unidade']).strip()

                regra_param = LimiteLegal.buscar_por_nome(nome_param)

                status_conf = "Informativo"
                em_conf = None
                norma_violada = None
                alerta_texto = None

                # Avalia limites no Efluente Tratado (P2)
                if ponto == 'P2' and regra_param:
                    avaliacao = regra_param.avaliar_p2(val_num)
                    status_conf = avaliacao['status_conformidade']
                    em_conf = avaliacao['em_conformidade']
                    norma_violada = avaliacao['norma_violada']
                    alerta_texto = avaliacao['alerta']

                    if status_conf == "Não Conforme":
                        alertas_mes.append({
                            'mes': mes,
                            'ponto': ponto,
                            'parametro': regra_param.parametro,
                            'valor': val_num,
                            'unidade': unidade,
                            'norma_violada': norma_violada,
                            'mensagem': alerta_texto
                        })

                medicao = ResultadoAnalise(
                    laudo_id=novo_laudo.id,
                    codigo_laudo=codigo_campanha,
                    data_coleta=data_coleta_mes,
                    ponto_coleta=ponto,
                    parametro_id=regra_param.id if regra_param else None,
                    parametro=regra_param.parametro if regra_param else nome_param,
                    valor_medido=val_num,
                    valor_texto=val_txt,
                    unidade=unidade,
                    status_conformidade=status_conf,
                    em_conformidade=em_conf,
                    norma_violada=norma_violada,
                    alerta=alerta_texto
                )
                db.session.add(medicao)
                medicoes_mes.append(medicao)

            eficiencias_mes = calcular_eficiencias_campanha(df_mes, novo_laudo.id, codigo_campanha, data_coleta_mes)
            impactos_rio_mes = avaliar_impacto_corpo_receptor(df_mes)

            resultado_processamento['campanhas_processadas'].append(mes)
            resultado_processamento['total_alertas'] += len(alertas_mes)
            resultado_processamento['alertas'].extend(alertas_mes)
            resultado_processamento['eficiencias'].extend([{**e, 'mes': mes} for e in eficiencias_mes])
            resultado_processamento['impactos_rio'].extend([{**i, 'mes': mes} for i in impactos_rio_mes])

            resultado_processamento['relatorios_por_mes'][mes] = {
                'codigo_laudo': codigo_campanha,
                'data_coleta': data_coleta_mes.strftime('%d/%m/%Y'),
                'total_medicoes': len(medicoes_mes),
                'alertas': alertas_mes,
                'eficiencias': eficiencias_mes,
                'impactos_rio': impactos_rio_mes
            }

        db.session.commit()
        return resultado_processamento
    except Exception as e:
        db.session.rollback()
        raise e


def obter_contexto_relatorio(codigo_laudo: str) -> dict:
    """
    Recupera os dados completos de uma campanha mensal gravada no banco de dados.
    Reaproveitado tanto para a tela HTML quanto para a geracao do relatorio em PDF.
    """
    laudo = Laudo.query.filter_by(codigo_laudo=codigo_laudo).first_or_404()
    medicoes_p2 = [m for m in laudo.medicoes if m.ponto_coleta == 'P2']
    medicoes_p3 = [m for m in laudo.medicoes if m.ponto_coleta == 'P3']
    medicoes_p4 = [m for m in laudo.medicoes if m.ponto_coleta == 'P4']
    alertas = [m for m in laudo.medicoes if m.status_conformidade == 'Não Conforme']

    # Monta o comparativo de qualidade do Rio Piracicaba (P3 vs P4)
    impactos_rio = []
    p3_map = {m.parametro: m for m in medicoes_p3}
    p4_map = {m.parametro: m for m in medicoes_p4}
    p2_map = {m.parametro: m for m in medicoes_p2}

    for param_nome, m3 in p3_map.items():
        if param_nome in p4_map:
            m4 = p4_map[param_nome]
            v3 = m3.valor_medido or 0.0
            v4 = m4.valor_medido or 0.0
            delta = round(v4 - v3, 3)
            var_pct = round(((v4 - v3) / v3) * 100.0, 1) if v3 > 0 else 0.0

            regra = m4.limite_ref or LimiteLegal.buscar_por_nome(param_nome)
            status_rio = "Normal"
            alerta_impacto = None

            if regra and regra.limite_max_conama357 is not None and v4 > regra.limite_max_conama357:
                status_rio = "Alerta de Impacto"
                alerta_impacto = (
                    f"Concentração em Jusante (P4 = {v4} {m4.unidade}) ultrapassou o limite "
                    f"do CONAMA 357/2005 Classe 2 (<= {regra.limite_max_conama357} {m4.unidade}). "
                    f"Elevação de +{delta} {m4.unidade} ({var_pct:+.1f}%) em relação a Montante (P3 = {v3} {m3.unidade})."
                )
            elif delta > 0 and param_nome in p2_map:
                m2 = p2_map[param_nome]
                v2 = m2.valor_medido or 0.0
                if var_pct >= 20.0:
                    status_rio = "Atenção"
                    alerta_impacto = (
                        f"Elevação de {var_pct:+.1f}% no rio após o lançamento "
                        f"(P3 = {v3} -> P4 = {v4} {m4.unidade}). Concentração no Tratado (P2 = {v2} {m2.unidade}). "
                        f"Recomenda-se investigar a contribuição da ETE."
                    )

            impactos_rio.append({
                'parametro': param_nome,
                'montante_p3': v3,
                'jusante_p4': v4,
                'diferenca': delta,
                'variacao_pct': var_pct,
                'unidade': m4.unidade,
                'status_rio': status_rio,
                'alerta_impacto': alerta_impacto,
                'limite_classe2': regra.texto_conama357 if regra else 'Não tabelado'
            })

    return {
        'laudo': laudo,
        'medicoes_p2': medicoes_p2,
        'eficiencias': laudo.eficiencias,
        'alertas': alertas,
        'impactos_rio': impactos_rio,
        'data_emissao': datetime.now().strftime('%d/%m/%Y às %H:%M')
    }


def gerar_pdf_relatorio(dados_contexto: dict) -> io.BytesIO:
    """
    Renderiza o template HTML dedicado (relatorio_pdf.html) e converte em PDF usando xhtml2pdf.
    Retorna um buffer em memoria io.BytesIO posicionado no inicio (seek 0), sem salvar arquivo no disco.
    Pronto para send_file no Flask ou anexo em disparos de e-mail.
    """
    html_conteudo = render_template('relatorio_pdf.html', **dados_contexto)
    # Substitui caracteres que nao existem nas fontes core do xhtml2pdf (Helvetica)
    html_conteudo = html_conteudo.replace('≥', '>=').replace('≤', '<=').replace('•', '-')
    pdf_buffer = io.BytesIO()

    pisa_status = pisa.CreatePDF(
        src=html_conteudo,
        dest=pdf_buffer,
        encoding='utf-8'
    )

    if pisa_status.err:
        raise RuntimeError(f"Ocorreu um erro ao gerar o PDF com xhtml2pdf (código de erro: {pisa_status.err})")

    pdf_buffer.seek(0)
    return pdf_buffer


def extrair_dados_pdf_laudo(origem_pdf, nome_arquivo: str = "laudo.pdf") -> dict:
    """
    Extrai metadados e resultados analiticos (P1 a P4) de arquivos PDF via pypdf.
    Identifica automaticamente tanto o laudo laboratorial original (modelo Hackathon)
    quanto relatorios tecnicos exportados pelo proprio sistema, recalculando
    eficiencias da ETE, nao conformidades em P2 e impactos no Rio Piracicaba.
    """
    reader = pypdf.PdfReader(origem_pdf)
    num_paginas = len(reader.pages)
    if num_paginas == 0:
        raise ValueError("O arquivo PDF enviado está vazio ou não possui páginas legíveis.")

    textos_paginas = []
    for p in reader.pages:
        txt = p.extract_text() or ""
        txt = txt.replace('\u2212', '-').replace('\u2014', '-').replace('\u2264', '<=').replace('\u2265', '>=')
        textos_paginas.append(txt)

    texto_completo = "\n".join(textos_paginas)
    texto_p1 = textos_paginas[0] if num_paginas >= 1 else ""
    texto_p2 = textos_paginas[1] if num_paginas >= 2 else ""
    texto_p3 = textos_paginas[2] if num_paginas >= 3 else ""

    def converter_valor(v_str):
        if not v_str:
            return None, "Sem Dados"
        v_limpo = v_str.strip()
        if v_limpo.startswith('<'):
            num_parte = re.sub(r'[^\d,\.]', '', v_limpo).replace(',', '.')
            try:
                # Adota metade do limite de quantificacao (< LQ) para calculos numericos
                return float(num_parte) / 2.0, v_limpo
            except ValueError:
                return None, v_limpo
        num_txt = v_limpo
        if ',' in num_txt and '.' in num_txt:
            num_txt = num_txt.replace('.', '').replace(',', '.')
        elif ',' in num_txt:
            num_txt = num_txt.replace(',', '.')
        try:
            return float(num_txt), v_limpo
        except ValueError:
            return None, v_limpo

    todos_limites = LimiteLegal.query.all()
    limites_ordenados = sorted(todos_limites, key=lambda l: len(l.parametro), reverse=True)

    def casar_limite_legal(texto_linha):
        t_norm = normalizar_texto(texto_linha)
        for regra in limites_ordenados:
            if normalizar_texto(regra.parametro) in t_norm:
                return regra
        for regra in limites_ordenados:
            if regra.sinonimos:
                for sin in regra.sinonimos.split('|'):
                    if normalizar_texto(sin) in t_norm:
                        return regra
        for regra in limites_ordenados:
            if regra.simbolo and len(regra.simbolo) > 1:
                if re.search(r'\b' + re.escape(normalizar_texto(regra.simbolo)) + r'\b', t_norm):
                    return regra
        return None

    medicoes_extraidas = []
    alertas_nao_conformidade = []
    impactos_rio = []

    # Detecta se o PDF enviado e um Relatorio Tecnico exportado pelo proprio sistema
    eh_relatorio_sistema = (
        "RELATÓRIO TÉCNICO DE" in texto_completo
        and "CONFORMIDADE AMBIENTAL" in texto_completo
    )

    if eh_relatorio_sistema:
        def buscar_linha_seguinte(rotulo, default=""):
            m = re.search(rf'{rotulo}:\s*\n\s*([^\n]+)', texto_completo)
            return m.group(1).strip() if m else default

        codigo_campanha = buscar_linha_seguinte('Código do Laudo', 'LAUDO-PDF')
        mes_referencia = buscar_linha_seguinte('Mês Referência', date.today().strftime('%Y-%m'))
        data_coleta_str = buscar_linha_seguinte('Data da Coleta', '')
        laboratorio = buscar_linha_seguinte('Laboratório', 'Laboratório Acreditado')
        unidade_monitorada = buscar_linha_seguinte('Unidade', 'ETE Industrial - Unidade Americana/SP')
        corpo_receptor = buscar_linha_seguinte('Corpo Receptor', 'Rio Piracicaba (Classe 2)')

        data_coleta = date.today()
        if data_coleta_str:
            for fmt in ('%d/%m/%Y', '%Y-%m-%d', '%d-%m-%Y'):
                try:
                    data_coleta = datetime.strptime(data_coleta_str, fmt).date()
                    break
                except ValueError:
                    pass

        linhas_sys = [l.strip() for l in texto_completo.splitlines() if l.strip()]
        secao_atual = None
        i = 0
        regex_val_unid = re.compile(r'^([<>]?\s*[\d,\.]+)\s+(.+)$')

        while i < len(linhas_sys):
            linha = linhas_sys[i]
            if linha.startswith('1. Eficiência de Tratamento'):
                secao_atual = 'eficiencia'
                i += 1
                continue
            elif linha.startswith('2. Avaliação do Corpo Receptor'):
                secao_atual = 'rio'
                i += 1
                continue
            elif linha.startswith('3. Resultados Analíticos'):
                secao_atual = 'p2'
                i += 1
                continue
            elif linha.startswith('Legislações aplicadas:') or linha.startswith('Documento gerado'):
                secao_atual = None
                i += 1
                continue

            # Ignora cabecalhos repetidos de tabela e linhas de aviso
            if linha in (
                'Parâmetro', 'Entrada P1 (Bruto)', 'Saída P2 (Tratado)', 'Eficiência (%)',
                'Avaliação', 'Montante (P3)', 'Jusante (P4)', 'Variação', 'Limite Classe 2',
                'Diagnóstico', 'Parâmetro Químico / Físico', 'Resultado Medido', 'Unidade',
                'Situação Legal'
            ) or linha.startswith('Aviso:') or linha.startswith('a contribuição') or linha.startswith('(+'):
                i += 1
                continue

            if secao_atual == 'eficiencia' and i + 2 < len(linhas_sys):
                m1 = regex_val_unid.match(linhas_sys[i + 1])
                m2 = regex_val_unid.match(linhas_sys[i + 2])
                if m1 and m2:
                    regra = casar_limite_legal(linha)
                    nome_param = regra.parametro if regra else linha
                    v1_num, v1_txt = converter_valor(m1.group(1))
                    unidade = m1.group(2).strip()
                    medicoes_extraidas.append({
                        'codigo_laudo': codigo_campanha,
                        'data_coleta': data_coleta,
                        'ponto_coleta': 'P1',
                        'parametro_id': regra.id if regra else None,
                        'parametro': nome_param,
                        'valor_medido': v1_num,
                        'valor_texto': v1_txt,
                        'unidade': unidade,
                        'status_conformidade': 'Informativo',
                        'em_conformidade': True,
                        'norma_violada': None,
                        'alerta': None
                    })
                    i += 3
                    continue

            elif secao_atual == 'rio' and i + 2 < len(linhas_sys):
                m3 = regex_val_unid.match(linhas_sys[i + 1])
                m4 = regex_val_unid.match(linhas_sys[i + 2])
                if m3 and m4:
                    regra = casar_limite_legal(linha)
                    nome_param = regra.parametro if regra else linha
                    v3_num, v3_txt = converter_valor(m3.group(1))
                    v4_num, v4_txt = converter_valor(m4.group(1))
                    unidade = m3.group(2).strip()

                    medicoes_extraidas.append({
                        'codigo_laudo': codigo_campanha,
                        'data_coleta': data_coleta,
                        'ponto_coleta': 'P3',
                        'parametro_id': regra.id if regra else None,
                        'parametro': nome_param,
                        'valor_medido': v3_num,
                        'valor_texto': v3_txt,
                        'unidade': unidade,
                        'status_conformidade': 'Informativo',
                        'em_conformidade': True,
                        'norma_violada': None,
                        'alerta': None
                    })
                    medicoes_extraidas.append({
                        'codigo_laudo': codigo_campanha,
                        'data_coleta': data_coleta,
                        'ponto_coleta': 'P4',
                        'parametro_id': regra.id if regra else None,
                        'parametro': nome_param,
                        'valor_medido': v4_num,
                        'valor_texto': v4_txt,
                        'unidade': unidade,
                        'status_conformidade': 'Informativo',
                        'em_conformidade': True,
                        'norma_violada': None,
                        'alerta': None
                    })

                    delta = round(v4_num - v3_num, 3) if (v4_num is not None and v3_num is not None) else 0.0
                    var_pct = round(((v4_num - v3_num) / v3_num) * 100.0, 1) if (v3_num and v3_num > 0) else 0.0
                    status_rio = "Normal"
                    alerta_impacto = None

                    if regra and regra.limite_max_conama357 is not None and v4_num is not None and v4_num > regra.limite_max_conama357:
                        status_rio = "Alerta de Impacto"
                        alerta_impacto = (
                            f"Concentração em Jusante (P4 = {v4_num} {unidade}) ultrapassou o limite "
                            f"do CONAMA 357/2005 Classe 2 (<= {regra.limite_max_conama357} {unidade}). "
                            f"Elevação de +{delta} {unidade} ({var_pct:+.1f}%) em relação a Montante (P3 = {v3_num} {unidade})."
                        )
                    elif delta > 0 and var_pct >= 20.0:
                        status_rio = "Atenção"
                        alerta_impacto = (
                            f"Elevação de {var_pct:+.1f}% no rio após o ponto de lançamento "
                            f"(P3 = {v3_num} -> P4 = {v4_num} {unidade}). Recomenda-se investigar a contribuição da ETE."
                        )

                    impactos_rio.append({
                        'parametro': nome_param,
                        'montante_p3': v3_num,
                        'jusante_p4': v4_num,
                        'diferenca': delta,
                        'variacao_pct': var_pct,
                        'unidade': unidade,
                        'status_rio': status_rio,
                        'alerta_impacto': alerta_impacto,
                        'limite_classe2': regra.texto_conama357 if regra else 'Não tabelado',
                        'mes': mes_referencia
                    })
                    i += 3
                    continue

            elif secao_atual == 'p2' and i + 2 < len(linhas_sys):
                val_cand = linhas_sys[i + 1]
                unid_cand = linhas_sys[i + 2]
                if re.match(r'^[<>]?\s*[\d,\.]+$', val_cand):
                    regra = casar_limite_legal(linha)
                    nome_param = regra.parametro if regra else linha
                    v2_num, v2_txt = converter_valor(val_cand)

                    status_p2 = "Informativo"
                    em_conf_p2 = True
                    norma_violada = None
                    alerta_p2 = None

                    if regra:
                        avaliacao = regra.avaliar_p2(v2_num)
                        status_p2 = avaliacao['status_conformidade']
                        em_conf_p2 = avaliacao['em_conformidade']
                        norma_violada = avaliacao['norma_violada']
                        alerta_p2 = avaliacao['alerta']

                        if status_p2 == "Não Conforme":
                            alertas_nao_conformidade.append({
                                'mes': mes_referencia,
                                'ponto': 'P2',
                                'parametro': nome_param,
                                'valor': v2_num,
                                'unidade': unid_cand,
                                'norma_violada': norma_violada,
                                'mensagem': alerta_p2
                            })

                    medicoes_extraidas.append({
                        'codigo_laudo': codigo_campanha,
                        'data_coleta': data_coleta,
                        'ponto_coleta': 'P2',
                        'parametro_id': regra.id if regra else None,
                        'parametro': nome_param,
                        'valor_medido': v2_num,
                        'valor_texto': v2_txt,
                        'unidade': unid_cand,
                        'status_conformidade': status_p2,
                        'em_conformidade': em_conf_p2,
                        'norma_violada': norma_violada,
                        'alerta': alerta_p2
                    })
                    i += 4
                    continue

            i += 1
    else:
        def buscar_campo(padrao, default=""):
            m = re.search(padrao, texto_completo)
            if m:
                val = m.group(1).strip()
                val = re.sub(r'^\[|\]$', '', val).strip()
                return val
            return default

        codigo_laudo_bruto = buscar_campo(r'Código do Laudo\s*\[?(.*?)\]?(?:\s+[A-Z]|$)', 'LAUDO-PDF')
        data_coleta_str = buscar_campo(r'Data da Coleta\s*\[?(.*?)\]?(?:\s+[A-Z]|$)', '')
        unidade_monitorada = buscar_campo(r'Unidade Monitorada\s*\[?(.*?)\]?(?:\s+Campanha|$)', 'ETE Industrial - Unidade Americana/SP')
        campanha_mes_str = buscar_campo(r'Campanha\s*/\s*Mês\s*\[?(.*?)\]?(?:\s+[A-Z]|$)', '')
        corpo_receptor = buscar_campo(r'Corpo Receptor\s*\[?(.*?)\]?(?:\s+Laboratório|$)', 'Rio Piracicaba (Classe 2)')
        laboratorio = buscar_campo(r'Laboratório\s*\[?(.*?)\]?(?:\s+[A-Z]|$)', 'Laboratório Acreditado')

        data_coleta = date.today()
        if data_coleta_str and not any(ph in data_coleta_str.upper() for ph in ['DD/', 'AAAA', 'MM/']):
            for fmt in ('%d/%m/%Y', '%Y-%m-%d', '%d-%m-%Y'):
                try:
                    data_coleta = datetime.strptime(data_coleta_str, fmt).date()
                    break
                except ValueError:
                    pass

        mes_referencia = data_coleta.strftime('%Y-%m')
        if campanha_mes_str and not any(ph in campanha_mes_str.upper() for ph in ['MM/', 'AAAA']):
            m_mes = re.search(r'(\d{2})[/-](\d{4})', campanha_mes_str)
            if m_mes:
                mes_referencia = f"{m_mes.group(2)}-{m_mes.group(1)}"
            elif re.match(r'^\d{4}-\d{2}$', campanha_mes_str):
                mes_referencia = campanha_mes_str

        if 'ANO' in codigo_laudo_bruto or '001' in codigo_laudo_bruto or not codigo_laudo_bruto:
            codigo_campanha = f"CAMP-{mes_referencia}"
        else:
            codigo_campanha = codigo_laudo_bruto

        t2_tratado = texto_p2
        for quebra, uniao in [
            (r'DBO\s*\n\s*5,20', 'DBO5,20'),
            (r'Materiais\s*\n\s*Sedimentáveis', 'Materiais Sedimentáveis'),
            (r'Sólidos Suspensos\s*\n\s*Totais', 'Sólidos Suspensos Totais'),
            (r'Óleos e Graxas\s*\n\s*\(Minerais\)', 'Óleos e Graxas (Minerais)'),
            (r'Nitrogênio Amoniacal\s*\n\s*Total', 'Nitrogênio Amoniacal Total'),
            (r'Ferro Dissolvido\s*\n\s*\(Fe\)', 'Ferro Dissolvido (Fe)'),
            (r'Manganês Dissolvido\s*\n\s*\(Mn\)', 'Manganês Dissolvido (Mn)'),
            (r'Cobre Dissolvido\s*\n\s*\(Cu\)', 'Cobre Dissolvido (Cu)'),
            (r'Zinco Total\s*\n\s*\(Zn\)', 'Zinco Total (Zn)'),
            (r'Cromo Hexavalente\s*\n\s*\(Cr\s*6\+\s*\)', 'Cromo Hexavalente (Cr6+)'),
            (r'Chumbo Total\s*\n\s*\(Pb\)', 'Chumbo Total (Pb)'),
            (r'Níquel Total\s*\n\s*\(Ni\)', 'Níquel Total (Ni)'),
            (r'Fluoreto Total\s*\n\s*\(F-\)', 'Fluoreto Total (F-)'),
            (r'Fenóis Totais', 'Fenóis Totais'),
            (r'Cianeto Total\s*\n\s*\(CN-\)', 'Cianeto Total (CN-)'),
            (r'Mercúrio Total\s*\n\s*\(Hg\)', 'Mercúrio Total (Hg)'),
        ]:
            t2_tratado = re.sub(quebra, uniao, t2_tratado, flags=re.IGNORECASE)

        regex_p1_p2 = r'([A-Za-zÀ-ÿ0-9\s,\-\(\)\+]+?)\s+(mg/L|u\.pH|°C|mL/L)\s+([\d,\.<]+)\s+([\d,\.<]+)'
        for raw_param, unidade, v1_str, v2_str in re.findall(regex_p1_p2, t2_tratado):
            regra = casar_limite_legal(raw_param)
            nome_param = regra.parametro if regra else ' '.join(raw_param.split()).strip()

            v1_num, v1_txt = converter_valor(v1_str)
            v2_num, v2_txt = converter_valor(v2_str)

            # Medição P1 (Efluente Bruto)
            medicoes_extraidas.append({
                'codigo_laudo': codigo_campanha,
                'data_coleta': data_coleta,
                'ponto_coleta': 'P1',
                'parametro_id': regra.id if regra else None,
                'parametro': nome_param,
                'valor_medido': v1_num,
                'valor_texto': v1_txt,
                'unidade': unidade,
                'status_conformidade': 'Informativo',
                'em_conformidade': True,
                'norma_violada': None,
                'alerta': None
            })

            # Medição P2 (Efluente Tratado) com avaliação de conformidade legal
            status_p2 = "Informativo"
            em_conf_p2 = True
            norma_violada = None
            alerta_p2 = None

            if regra:
                avaliacao = regra.avaliar_p2(v2_num)
                status_p2 = avaliacao['status_conformidade']
                em_conf_p2 = avaliacao['em_conformidade']
                norma_violada = avaliacao['norma_violada']
                alerta_p2 = avaliacao['alerta']

                if status_p2 == "Não Conforme":
                    alertas_nao_conformidade.append({
                        'mes': mes_referencia,
                        'ponto': 'P2',
                        'parametro': nome_param,
                        'valor': v2_num,
                        'unidade': unidade,
                        'norma_violada': norma_violada,
                        'mensagem': alerta_p2
                    })

            medicoes_extraidas.append({
                'codigo_laudo': codigo_campanha,
                'data_coleta': data_coleta,
                'ponto_coleta': 'P2',
                'parametro_id': regra.id if regra else None,
                'parametro': nome_param,
                'valor_medido': v2_num,
                'valor_texto': v2_txt,
                'unidade': unidade,
                'status_conformidade': status_p2,
                'em_conformidade': em_conf_p2,
                'norma_violada': norma_violada,
                'alerta': alerta_p2
            })

        # 3. Leitura do Corpo Receptor (Página 3: P3 Montante e P4 Jusante)
        t3_tratado = texto_p3
        for quebra, uniao in [
            (r'DBO\s*\n\s*5,20', 'DBO5,20'),
            (r'Oxigênio Dissolvido\s*\n\s*\(OD\)', 'Oxigênio Dissolvido (OD)'),
            (r'Nitrogênio Amoniacal\s*\n\s*Total', 'Nitrogênio Amoniacal Total'),
            (r'Fósforo Total', 'Fósforo Total'),
            (r'Ferro Dissolvido\s*\n\s*\(Fe\)', 'Ferro Dissolvido (Fe)'),
            (r'Zinco Total\s*\n\s*\(Zn\)', 'Zinco Total (Zn)'),
            (r'Cianeto Total\s*\n\s*\(CN-\)', 'Cianeto Total (CN-)'),
        ]:
            t3_tratado = re.sub(quebra, uniao, t3_tratado, flags=re.IGNORECASE)

        regex_p3_p4 = r'([A-Za-zÀ-ÿ0-9\s,\-\(\)\+]+?)\s+(mg/L|u\.pH|°C|mL/L|UNT)\s+([\d,\.<]+)\s+([\d,\.<]+)\s+([\+\-]?[\d,\.]+)'

        for raw_param, unidade, v3_str, v4_str, delta_str in re.findall(regex_p3_p4, t3_tratado):
            regra = casar_limite_legal(raw_param)
            nome_param = regra.parametro if regra else ' '.join(raw_param.split()).strip()

            v3_num, v3_txt = converter_valor(v3_str)
            v4_num, v4_txt = converter_valor(v4_str)

            medicoes_extraidas.append({
                'codigo_laudo': codigo_campanha,
                'data_coleta': data_coleta,
                'ponto_coleta': 'P3',
                'parametro_id': regra.id if regra else None,
                'parametro': nome_param,
                'valor_medido': v3_num,
                'valor_texto': v3_txt,
                'unidade': unidade,
                'status_conformidade': 'Informativo',
                'em_conformidade': True,
                'norma_violada': None,
                'alerta': None
            })

            medicoes_extraidas.append({
                'codigo_laudo': codigo_campanha,
                'data_coleta': data_coleta,
                'ponto_coleta': 'P4',
                'parametro_id': regra.id if regra else None,
                'parametro': nome_param,
                'valor_medido': v4_num,
                'valor_texto': v4_txt,
                'unidade': unidade,
                'status_conformidade': 'Informativo',
                'em_conformidade': True,
                'norma_violada': None,
                'alerta': None
            })

            # Diagnostico de impacto no rio
            delta = round(v4_num - v3_num, 3) if (v4_num is not None and v3_num is not None) else 0.0
            var_pct = round(((v4_num - v3_num) / v3_num) * 100.0, 1) if (v3_num and v3_num > 0) else 0.0

            status_rio = "Normal"
            alerta_impacto = None

            if regra and regra.limite_max_conama357 is not None and v4_num > regra.limite_max_conama357:
                status_rio = "Alerta de Impacto"
                alerta_impacto = (
                    f"Concentração em Jusante (P4 = {v4_num} {unidade}) ultrapassou o limite "
                    f"do CONAMA 357/2005 Classe 2 (<= {regra.limite_max_conama357} {unidade}). "
                    f"Elevação de +{delta} {unidade} ({var_pct:+.1f}%) em relação a Montante (P3 = {v3_num} {unidade})."
                )
            elif delta > 0 and var_pct >= 20.0:
                status_rio = "Atenção"
                alerta_impacto = (
                    f"Elevação de {var_pct:+.1f}% no rio após o ponto de lançamento "
                    f"(P3 = {v3_num} -> P4 = {v4_num} {unidade}). Recomenda-se investigar a contribuição da ETE."
                )

            impactos_rio.append({
                'parametro': nome_param,
                'montante_p3': v3_num,
                'jusante_p4': v4_num,
                'diferenca': delta,
                'variacao_pct': var_pct,
                'unidade': unidade,
                'status_rio': status_rio,
                'alerta_impacto': alerta_impacto,
                'limite_classe2': regra.texto_conama357 if regra else 'Não tabelado',
                'mes': mes_referencia
            })

    # 4. Cálculo de Eficiência da ETE (P1 vs P2)
    # Filtra pares P1 e P2 para DBO5,20, DQO e SST
    p1_map = {m['parametro']: m['valor_medido'] for m in medicoes_extraidas if m['ponto_coleta'] == 'P1'}
    p2_map = {m['parametro']: m['valor_medido'] for m in medicoes_extraidas if m['ponto_coleta'] == 'P2'}

    eficiencias_calculadas = []
    for param_carga in ['DBO5,20', 'DQO', 'Sólidos Suspensos Totais']:
        regra = casar_limite_legal(param_carga)
        nome_oficial = regra.parametro if regra else param_carga
        if nome_oficial in p1_map and nome_oficial in p2_map:
            v1 = p1_map[nome_oficial]
            v2 = p2_map[nome_oficial]
            if v1 is not None and v2 is not None and v1 > 0:
                ef_pct = round(((v1 - v2) / v1) * 100.0, 1)
                meta_atingida = True
                avaliacao = "Operacional"
                if regra and regra.eficiencia_minima_pct:
                    meta_atingida = ef_pct >= regra.eficiencia_minima_pct
                    avaliacao = f"Conforme (>= {int(regra.eficiencia_minima_pct)}%)" if meta_atingida else f"Não Conforme (< {int(regra.eficiencia_minima_pct)}%)"

                eficiencias_calculadas.append({
                    'parametro': nome_oficial,
                    'entrada_p1': v1,
                    'saida_p2': v2,
                    'unidade': 'mg/L',
                    'eficiencia_pct': ef_pct,
                    'avaliacao': avaliacao,
                    'atingiu_meta': meta_atingida,
                    'mes': mes_referencia
                })

    if not medicoes_extraidas:
        raise ValueError(
            "Nenhuma medição laboratorial (pontos P1 a P4) foi identificada neste PDF. "
            "Verifique se o arquivo enviado é um laudo laboratorial original e não um relatório já exportado pelo sistema."
        )

    return {
        'sucesso': True,
        'formato': 'pdf',
        'arquivo': nome_arquivo,
        'codigo_laudo': codigo_campanha,
        'data_coleta': data_coleta,
        'mes_referencia': mes_referencia,
        'unidade_monitorada': unidade_monitorada,
        'corpo_receptor': corpo_receptor,
        'laboratorio': laboratorio,
        'total_linhas': len(medicoes_extraidas),
        'campanhas_processadas': [mes_referencia],
        'medicoes': medicoes_extraidas,
        'total_alertas': len(alertas_nao_conformidade),
        'alertas': alertas_nao_conformidade,
        'eficiencias': eficiencias_calculadas,
        'impactos_rio': impactos_rio,
        'relatorios_por_mes': {
            mes_referencia: {
                'codigo_laudo': codigo_campanha,
                'data_coleta': data_coleta.strftime('%d/%m/%Y'),
                'total_medicoes': len(medicoes_extraidas),
                'alertas': alertas_nao_conformidade,
                'eficiencias': eficiencias_calculadas,
                'impactos_rio': impactos_rio
            }
        }
    }


def importar_relatorio_pdf(origem_pdf, nome_arquivo: str = "laudo.pdf") -> dict:
    """
    Executa a leitura automática do PDF e persiste a campanha e suas medições
    no banco de dados SQLite, com proteção transacional contra chaves duplicadas.
    """
    dados = extrair_dados_pdf_laudo(origem_pdf, nome_arquivo)
    codigo_campanha = dados['codigo_laudo']
    mes_referencia = dados['mes_referencia']
    data_coleta = dados['data_coleta']

    try:
        # Limpeza prévia para garantir idempotência caso o laudo do mês já exista
        laudos_antigos = Laudo.query.filter_by(codigo_laudo=codigo_campanha).all()
        if laudos_antigos:
            ids_antigos = [l.id for l in laudos_antigos]
            ResultadoAnalise.query.filter(
                (ResultadoAnalise.codigo_laudo == codigo_campanha) |
                (ResultadoAnalise.laudo_id.in_(ids_antigos))
            ).delete(synchronize_session=False)
            EficienciaETE.query.filter(
                (EficienciaETE.codigo_laudo == codigo_campanha) |
                (EficienciaETE.laudo_id.in_(ids_antigos))
            ).delete(synchronize_session=False)
            for l in laudos_antigos:
                db.session.delete(l)
            db.session.commit()

        novo_laudo = Laudo(
            codigo_laudo=codigo_campanha,
            unidade_monitorada=dados['unidade_monitorada'],
            corpo_receptor=dados['corpo_receptor'],
            campanha_mes=mes_referencia,
            data_coleta=data_coleta,
            laboratorio=dados['laboratorio'],
            arquivo_origem=nome_arquivo,
            observacoes="Laudo importado automaticamente via módulo de extração PDF."
        )
        db.session.add(novo_laudo)
        db.session.flush()

        for m in dados['medicoes']:
            medicao = ResultadoAnalise(
                laudo_id=novo_laudo.id,
                codigo_laudo=codigo_campanha,
                data_coleta=data_coleta,
                ponto_coleta=m['ponto_coleta'],
                parametro_id=m['parametro_id'],
                parametro=m['parametro'],
                valor_medido=m['valor_medido'],
                valor_texto=m['valor_texto'],
                unidade=m['unidade'],
                status_conformidade=m['status_conformidade'],
                em_conformidade=m['em_conformidade'],
                norma_violada=m['norma_violada'],
                alerta=m['alerta']
            )
            db.session.add(medicao)

        for ef in dados['eficiencias']:
            ef_obj = EficienciaETE(
                laudo_id=novo_laudo.id,
                codigo_laudo=codigo_campanha,
                data_referencia=data_coleta,
                parametro=ef['parametro'],
                unidade=ef['unidade'],
                entrada_p1=ef['entrada_p1'],
                saida_p2=ef['saida_p2'],
                eficiencia_percentual=ef['eficiencia_pct'],
                avaliacao=ef['avaliacao'],
                atingiu_meta=ef['atingiu_meta']
            )
            db.session.add(ef_obj)

        db.session.commit()
        return dados
    except Exception as e:
        db.session.rollback()
        raise e
