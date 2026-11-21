import re
from datetime import datetime, date
from decimal import Decimal, ROUND_HALF_UP
import pandas as pd
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
    # Se a planilha tiver uma aba com metadados (como Metadados_Amostras), puxa os dados do cabecalho
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
    # Procura por abas conhecidas de dados. Se nao achar, pega a primeira do arquivo
    abas = excel_file.sheet_names
    preferenciais = ['dados_importacao', 'dados', 'medicoes', 'resultados', 'laudo', 'planilha1']
    for p in preferenciais:
        for aba in abas:
            if normalizar_texto(aba) == p:
                return aba
    return abas[0]


def padronizar_dataframe_pandas(df: pd.DataFrame) -> pd.DataFrame:
    # Mapeia os cabecalhos para nomes padrao e limpa linhas em branco
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

    # Processa cada mes encontrado na planilha
    for mes in sorted(df['mes_referencia'].unique()):
        df_mes = df[df['mes_referencia'] == mes]
        data_coleta_mes = df_mes['data_coleta'].dropna().iloc[0].date() if not df_mes['data_coleta'].isna().all() else date.today()
        codigo_campanha = f"CAMP-{mes}"

        # Se ja existir a campanha daquele mes, remove antes de reinserir para evitar duplicatas
        laudo_existente = Laudo.query.filter_by(codigo_laudo=codigo_campanha).first()
        if laudo_existente:
            db.session.delete(laudo_existente)
            db.session.flush()

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
