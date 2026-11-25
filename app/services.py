from collections import OrderedDict
import io
import math
import re
import secrets
import threading
from dataclasses import dataclass, field
from datetime import datetime, date
from types import SimpleNamespace
from flask import abort, has_request_context, render_template, session
import pandas as pd
import pypdf
from xhtml2pdf import pisa
from app.models import (
    LimiteLegal,
    PontoColeta,
    normalizar_texto,
)


def sanitizar_float(valor) -> float | None:
    """Converte o valor para float finito ou retorna None para None, NaN e Inf."""
    if valor is None or isinstance(valor, bool):
        return None
    try:
        num = float(valor)
        return num if math.isfinite(num) else None
    except (TypeError, ValueError):
        return None


_REGEX_LEITURA_NUMERICA = re.compile(
    r'^\s*([<>])?\s*([+-]?\d+(?:[.,]\d+)*)(?:\s*(?:mg/L|u\.pH|°C|mL/L|UNT|%))?\s*$',
    re.IGNORECASE,
)


def converter_numero_br(valor) -> tuple[float | None, str]:
    """
    Converte leituras laboratoriais para float e texto original.
    Suporta formato brasileiro com separador de milhar ('1.200,50'), decimal com virgula ('7,2'),
    formato internacional ('1200.5') e limites de quantificacao ('< 0,01' -> metade do LQ).
    Ignora observacoes textuais com numeros misturados (ex: 'ND - LQ 0,05', 'SMWW 5210').
    """
    if valor is None or isinstance(valor, bool):
        return None, "Sem Dados"
    if isinstance(valor, (int, float)):
        num_direto = sanitizar_float(valor)
        if num_direto is None:
            return None, "Sem Dados"
        return num_direto, str(valor).strip()
    try:
        if pd.isna(valor):
            return None, "Sem Dados"
    except (TypeError, ValueError):
        pass

    val_str = str(valor).strip()
    if not val_str:
        return None, "Sem Dados"

    match_num = _REGEX_LEITURA_NUMERICA.match(val_str)
    if not match_num:
        return None, val_str

    abaixo_lq = match_num.group(1) == '<'
    num_parte = match_num.group(2)

    if ',' in num_parte and '.' in num_parte:
        if num_parte.rfind(',') > num_parte.rfind('.'):
            num_parte = num_parte.replace('.', '').replace(',', '.')
        else:
            num_parte = num_parte.replace(',', '')
    elif ',' in num_parte:
        num_parte = num_parte.replace(',', '.')

    num = sanitizar_float(num_parte)
    if num is None:
        return None, val_str
    return (num / 2.0 if abaixo_lq else num), val_str


def sanitizar_codigo_laudo(codigo: str, fallback: str = "LAUDO") -> str:
    """Limpa o codigo do laudo removendo quebras, separadores de rota e caracteres inseguros para URL."""
    texto = str(codigo or '').strip()
    texto = re.sub(r'[\r\n\t]+', ' ', texto)
    texto = re.sub(r'[/\\#?%]+', '-', texto)
    texto = re.sub(r'\s+', ' ', texto)
    texto = re.sub(r'-{2,}', '-', texto)
    texto = texto.strip(' .-')
    if not texto or texto in ('.', '..'):
        return fallback
    return texto[:80]


@dataclass
class MedicaoSessao:
    """Representa uma medicao individual mantida em memoria durante a sessao do servidor."""
    codigo_laudo: str
    data_coleta: date
    ponto_coleta: str
    parametro_id: int | None
    parametro: str
    valor_medido: float | None
    valor_texto: str | None
    unidade: str
    status_conformidade: str
    em_conformidade: bool | None
    norma_violada: str | None
    alerta: str | None
    norma_mais_restritiva: str | None = None

    @property
    def limite_ref(self):
        if not self.norma_mais_restritiva:
            return None
        return SimpleNamespace(norma_mais_restritiva=self.norma_mais_restritiva)


@dataclass
class EficienciaSessao:
    """Representa uma taxa de remocao (P1 vs P2) mantida em memoria na sessao atual."""
    codigo_laudo: str
    data_referencia: date
    parametro: str
    unidade: str
    entrada_p1: float
    saida_p2: float
    eficiencia_percentual: float
    avaliacao: str
    atingiu_meta: bool | None


@dataclass
class LaudoSessao:
    """Agrupa os dados de uma campanha importada em memoria sem gravar estado no SQLite."""
    codigo_laudo: str
    unidade_monitorada: str
    corpo_receptor: str
    campanha_mes: str
    data_coleta: date
    laboratorio: str
    arquivo_origem: str
    observacoes: str
    medicoes: list = field(default_factory=list)
    eficiencias: list = field(default_factory=list)


_MAX_SESSOES_ATIVAS = 100
_MAX_LAUDOS_POR_SESSAO = 100
_SESSOES_LOCK = threading.RLock()
_SESSOES_LAUDOS: OrderedDict[str, OrderedDict[str, LaudoSessao]] = OrderedDict()


def _obter_id_sessao() -> str:
    """Identifica a sessao atual do navegador (ou '__cli__' fora de requisicao HTTP)."""
    if has_request_context():
        sid = session.get('sid')
        if not sid:
            sid = secrets.token_hex(16)
            session['sid'] = sid
        return sid
    return '__cli__'


def _obter_armazenamento_sessao(criar: bool = False) -> OrderedDict[str, LaudoSessao] | None:
    """Retorna o mapa de laudos isolado da sessao atual com limite de memoria (LRU)."""
    sid = _obter_id_sessao()
    store = _SESSOES_LAUDOS.get(sid)
    if store is None:
        if not criar:
            return None
        store = OrderedDict()
        _SESSOES_LAUDOS[sid] = store
        while len(_SESSOES_LAUDOS) > _MAX_SESSOES_ATIVAS:
            _SESSOES_LAUDOS.popitem(last=False)
    else:
        _SESSOES_LAUDOS.move_to_end(sid)
    return store


def _salvar_laudos_sessao(novos_laudos: dict[str, LaudoSessao]) -> None:
    """Grava ou atualiza laudos na sessao atual de forma thread-safe e com limite de itens."""
    with _SESSOES_LOCK:
        store = _obter_armazenamento_sessao(criar=True)
        for codigo, laudo in novos_laudos.items():
            store[codigo] = laudo
            store.move_to_end(codigo)
        while len(store) > _MAX_LAUDOS_POR_SESSAO:
            store.popitem(last=False)


def listar_laudos_sessao(ordem_desc: bool = True) -> list:
    """Retorna as campanhas importadas na sessao atual ordenadas por data de coleta."""
    with _SESSOES_LOCK:
        store = _obter_armazenamento_sessao(criar=False)
        if not store:
            return []
        laudos = list(store.values())
    return sorted(
        laudos,
        key=lambda l: (l.data_coleta, l.campanha_mes, l.codigo_laudo),
        reverse=ordem_desc,
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


_ABAS_METADADOS_NORM = {
    'metadados_amostras',
    'metadados',
    'informacoes',
    'configuracao',
    'cadastro',
}


def extrair_metadados_planilha(excel_file: pd.ExcelFile) -> dict:
    """
    Busca abas auxiliares de metadados na planilha (ex: Metadados_Amostras) para
    preencher laboratorio, unidade monitorada e corpo receptor automaticamente.
    """
    metadados = {
        'laboratorio': 'Laboratório Acreditado',
        'unidade_monitorada': 'ETE Industrial',
        'corpo_receptor': 'Rio Piracicaba (Classe 2)',
        'observacoes': 'Importação de dados laboratoriais via pandas.'
    }

    aba_meta = next(
        (s for s in excel_file.sheet_names if normalizar_texto(s).replace(' ', '_') in _ABAS_METADADOS_NORM),
        None,
    )

    if aba_meta:
        try:
            df_meta = pd.read_excel(excel_file, sheet_name=aba_meta)
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
    """Seleciona a aba principal de medicoes ignorando abas de metadados e validando cabecalhos."""
    abas = excel_file.sheet_names
    preferenciais = ['dados_importacao', 'dados', 'medicoes', 'resultados', 'laudo', 'planilha1']
    for p in preferenciais:
        for aba in abas:
            if normalizar_texto(aba).replace(' ', '_') == p:
                return aba

    candidatas = [
        aba for aba in abas
        if normalizar_texto(aba).replace(' ', '_') not in _ABAS_METADADOS_NORM
    ]
    for aba in candidatas:
        try:
            cols = pd.read_excel(excel_file, sheet_name=aba, nrows=0).columns
            cols_canonicas = {
                MAPA_COLUNAS_EXCEL.get(normalizar_texto(str(c)).replace(' ', '_'), '')
                for c in cols
            }
            if {'parametro', 'resultado'}.issubset(cols_canonicas):
                return aba
        except Exception:
            continue

    return candidatas[0] if candidatas else abas[0]


def padronizar_dataframe_pandas(df: pd.DataFrame) -> pd.DataFrame:
    """
    Normaliza os nomes das colunas via dicionario de sinonimos, consolida colunas duplicadas,
    remove linhas sem parametro e resolve datas, mes de referencia e pontos P1 a P4.
    """
    df = df.dropna(how='all').copy()

    # Consolida colunas que mapeiam para o mesmo nome canonico (priorizando o nome exato)
    colunas_consolidadas = {}
    prioridade_exata = {}
    for idx, col in enumerate(df.columns):
        col_limpa = normalizar_texto(str(col)).replace(' ', '_')
        alvo = MAPA_COLUNAS_EXCEL.get(col_limpa, col_limpa) or f"col_{idx}"
        serie = df.iloc[:, idx]
        eh_exata = col_limpa == alvo
        if alvo not in colunas_consolidadas:
            colunas_consolidadas[alvo] = serie
            prioridade_exata[alvo] = eh_exata
        elif eh_exata and not prioridade_exata[alvo]:
            colunas_consolidadas[alvo] = serie.combine_first(colunas_consolidadas[alvo])
            prioridade_exata[alvo] = True
        else:
            colunas_consolidadas[alvo] = colunas_consolidadas[alvo].combine_first(serie)

    df = pd.DataFrame(colunas_consolidadas)

    for obrigatoria in ['parametro', 'resultado']:
        if obrigatoria not in df.columns:
            raise ValueError(f"A planilha precisa ter a coluna '{obrigatoria}'.")

    # Remove linhas de rodape/observacao onde a coluna parametro esta vazia
    param_limpo = df['parametro'].map(lambda v: str(v).strip() if pd.notna(v) else '')
    df = df[param_limpo.ne('') & param_limpo.str.lower().ne('nan')].copy()

    if df.empty:
        raise ValueError("A planilha não possui linhas de medições preenchidas.")

    df['parametro'] = df['parametro'].map(lambda v: str(v).strip())

    if 'data_coleta' in df.columns:
        datas_brutas = df['data_coleta']
        datas_iso = pd.to_datetime(datas_brutas, format='%Y-%m-%d', errors='coerce')
        datas_br = pd.to_datetime(datas_brutas, format='%d/%m/%Y', errors='coerce')
        datas_parseadas = datas_iso.fillna(datas_br)
        faltantes = datas_parseadas.isna() & datas_brutas.notna()
        if faltantes.any():
            datas_parseadas.loc[faltantes] = pd.to_datetime(
                datas_brutas.loc[faltantes], errors='coerce', dayfirst=True
            )
        df['data_coleta'] = datas_parseadas
    else:
        df['data_coleta'] = pd.to_datetime(datetime.now().date())

    mes_fallback = df['data_coleta'].dt.strftime('%Y-%m').fillna(date.today().strftime('%Y-%m'))
    if 'mes_referencia' not in df.columns or df['mes_referencia'].isna().all():
        df['mes_referencia'] = mes_fallback
    else:
        mes_series = df['mes_referencia'].where(df['mes_referencia'].notna(), None)
        mes_limpo = mes_series.map(lambda v: str(v).strip() if v is not None else '')
        mes_limpo = mes_limpo.replace({'': None, 'nan': None, 'None': None, 'NaT': None})
        df['mes_referencia'] = mes_limpo.fillna(mes_fallback).astype(str).str.strip()

    # Resolve P1 a P4 usando tanto codigos diretos quanto sinonimos cadastrados em pontos_coleta
    mapa_pontos = PontoColeta.montar_mapa_sinonimos()
    if 'codigo_ponto' in df.columns or 'ponto_coleta' in df.columns:
        serie_ponto = (
            df['codigo_ponto'].combine_first(df['ponto_coleta'])
            if ('codigo_ponto' in df.columns and 'ponto_coleta' in df.columns)
            else (df['codigo_ponto'] if 'codigo_ponto' in df.columns else df['ponto_coleta'])
        )
        df['codigo_ponto'] = serie_ponto.map(
            lambda v: PontoColeta.resolver_codigo(v, mapa_sinonimos=mapa_pontos) or ''
        )
    else:
        df['codigo_ponto'] = 'P2'

    if 'unidade' not in df.columns:
        df['unidade'] = ''
    else:
        df['unidade'] = df['unidade'].map(
            lambda v: '' if (pd.isna(v) or str(v).strip().lower() in ('', 'nan', 'none')) else str(v).strip()
        )

    return df


def calcular_eficiencias_campanha(df_mes: pd.DataFrame, codigo_laudo: str, data_ref: date) -> tuple:
    """
    Calcula a eficiencia ((P1 - P2) / P1) * 100 para parametros que tenham
    medicao tanto no bruto quanto no tratado naquele mes.
    """
    eficiencias_dicts = []
    eficiencias_objs = []
    df_p1 = df_mes[df_mes['codigo_ponto'] == 'P1'].set_index('parametro_normalizado')
    df_p2 = df_mes[df_mes['codigo_ponto'] == 'P2'].set_index('parametro_normalizado')

    parametros_comuns = set(df_p1.index).intersection(set(df_p2.index))

    for param_norm in parametros_comuns:
        row_p1 = df_p1.loc[param_norm]
        row_p2 = df_p2.loc[param_norm]

        v1 = sanitizar_float(row_p1['resultado_num'].iloc[0] if isinstance(row_p1, pd.DataFrame) else row_p1['resultado_num'])
        v2 = sanitizar_float(row_p2['resultado_num'].iloc[0] if isinstance(row_p2, pd.DataFrame) else row_p2['resultado_num'])
        nome_param = str(row_p1['parametro'].iloc[0] if isinstance(row_p1, pd.DataFrame) else row_p1['parametro'])
        unidade_raw = str(row_p1['unidade'].iloc[0] if isinstance(row_p1, pd.DataFrame) else row_p1['unidade']).strip()

        if v1 is not None and v2 is not None and v1 > 0:
            regra_param = LimiteLegal.buscar_por_nome(nome_param)
            # So calcula remocao para parametros de carga (DBO, DQO, SST), nao para pH ou temperatura
            if not regra_param or not regra_param.calcula_eficiencia:
                continue

            unidade = unidade_raw or regra_param.unidade or 'mg/L'
            avaliacao_ef = regra_param.avaliar_eficiencia(v1, v2)
            if avaliacao_ef['eficiencia_pct'] is None:
                continue

            ef_obj = EficienciaSessao(
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
            eficiencias_objs.append(ef_obj)
            eficiencias_dicts.append({
                'parametro': ef_obj.parametro,
                'entrada_p1': v1,
                'saida_p2': v2,
                'unidade': unidade,
                'eficiencia_pct': avaliacao_ef['eficiencia_pct'],
                'avaliacao': avaliacao_ef['avaliacao'],
                'atingiu_meta': avaliacao_ef['atingiu_meta']
            })

    return eficiencias_dicts, eficiencias_objs


def classificar_impacto_rio(regra, nome_param: str, v3: float, v4: float, unidade: str, v2: float = None) -> dict:
    """
    Avalia o impacto ambiental no Rio Piracicaba comparando Montante (P3) e Jusante (P4).
    Verifica limites maximos e minimos do CONAMA 357/2005 (Classe 2), variacao termica
    de 3 graus Celsius e elevacoes >= 20% atribuiveis ao lancamento da ETE.
    """
    v3_val = sanitizar_float(v3)
    v4_val = sanitizar_float(v4)
    v2_val = sanitizar_float(v2)

    param_oficial = regra.parametro if regra else nome_param
    if v3_val is None or v4_val is None:
        return {
            'parametro': param_oficial,
            'montante_p3': v3_val,
            'jusante_p4': v4_val,
            'diferenca': None,
            'variacao_pct': None,
            'unidade': unidade,
            'status_rio': 'Sem Dados',
            'alerta_impacto': None,
            'limite_classe2': regra.texto_conama357 if regra else 'Não tabelado',
            'limite_max_classe2': regra.limite_max_conama357 if regra else None,
            'limite_min_classe2': regra.limite_min_conama357 if regra else None,
        }

    delta = round(v4_val - v3_val, 3)
    var_pct = round(((v4_val - v3_val) / v3_val) * 100.0, 1) if v3_val > 0 else 0.0

    param_norm = normalizar_texto(param_oficial)
    status_rio = "Normal"
    alerta_impacto = None

    if regra and regra.limite_max_conama357 is not None and v4_val > regra.limite_max_conama357:
        status_rio = "Alerta de Impacto"
        alerta_impacto = (
            f"Concentração em Jusante (P4 = {v4_val} {unidade}) ultrapassou o limite "
            f"do CONAMA 357/2005 Classe 2 (<= {regra.limite_max_conama357} {unidade}). "
            f"Variação de {delta:+g} {unidade} ({var_pct:+.1f}%) em relação a Montante (P3 = {v3_val} {unidade})."
        )
    elif regra and regra.limite_min_conama357 is not None and v4_val < regra.limite_min_conama357:
        status_rio = "Alerta de Impacto"
        alerta_impacto = (
            f"Valor em Jusante (P4 = {v4_val} {unidade}) ficou abaixo do mínimo "
            f"exigido pelo CONAMA 357/2005 Classe 2 (>= {regra.limite_min_conama357} {unidade}). "
            f"Variação de {delta:+g} {unidade} ({var_pct:+.1f}%) em relação a Montante (P3 = {v3_val} {unidade})."
        )
    elif param_norm == 'temperatura' and abs(delta) >= 3.0:
        status_rio = "Alerta de Impacto"
        alerta_impacto = (
            f"Variação térmica de {delta:+.1f} {unidade} entre Montante (P3 = {v3_val} {unidade}) "
            f"e Jusante (P4 = {v4_val} {unidade}) atingiu ou superou o limite de 3,0 °C na zona de mistura."
        )
    elif delta > 0 and var_pct >= 20.0 and 'oxigenio dissolvido' not in param_norm:
        status_rio = "Atenção"
        if v2_val is not None:
            alerta_impacto = (
                f"Elevação de {var_pct:+.1f}% no rio após o lançamento "
                f"(P3 = {v3_val} -> P4 = {v4_val} {unidade}). Concentração no Tratado (P2 = {v2_val} {unidade}). "
                f"Recomenda-se investigar a contribuição da ETE."
            )
        else:
            alerta_impacto = (
                f"Elevação de {var_pct:+.1f}% no rio após o ponto de lançamento "
                f"(P3 = {v3_val} -> P4 = {v4_val} {unidade}). Recomenda-se investigar a contribuição da ETE."
            )

    return {
        'parametro': param_oficial,
        'montante_p3': v3_val,
        'jusante_p4': v4_val,
        'diferenca': delta,
        'variacao_pct': var_pct,
        'unidade': unidade,
        'status_rio': status_rio,
        'alerta_impacto': alerta_impacto,
        'limite_classe2': regra.texto_conama357 if regra else 'Não tabelado',
        'limite_max_classe2': regra.limite_max_conama357 if regra else None,
        'limite_min_classe2': regra.limite_min_conama357 if regra else None,
    }


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

    for param_norm in sorted(parametros_rio):
        row_p3 = df_p3.loc[param_norm]
        row_p4 = df_p4.loc[param_norm]

        v3 = sanitizar_float(row_p3['resultado_num'].iloc[0] if isinstance(row_p3, pd.DataFrame) else row_p3['resultado_num'])
        v4 = sanitizar_float(row_p4['resultado_num'].iloc[0] if isinstance(row_p4, pd.DataFrame) else row_p4['resultado_num'])
        if v3 is None or v4 is None:
            continue

        nome_param = str(row_p3['parametro'].iloc[0] if isinstance(row_p3, pd.DataFrame) else row_p3['parametro'])
        unidade_raw = str(row_p3['unidade'].iloc[0] if isinstance(row_p3, pd.DataFrame) else row_p3['unidade']).strip()

        v2 = None
        if param_norm in df_p2.index:
            row_p2 = df_p2.loc[param_norm]
            v2_raw = row_p2['resultado_num'].iloc[0] if isinstance(row_p2, pd.DataFrame) else row_p2['resultado_num']
            v2 = sanitizar_float(v2_raw)

        regra = LimiteLegal.buscar_por_nome(nome_param)
        unidade = unidade_raw or (regra.unidade if regra else 'mg/L')
        impactos.append(classificar_impacto_rio(regra, nome_param, v3, v4, unidade, v2=v2))

    return impactos


def importar_relatorio_excel(origem_arquivo, nome_arquivo: str = "relatorio.xlsx") -> dict:
    """
    Le a planilha Excel via pandas, valida as regras ambientais e salva no banco.
    Aceita tanto caminho de arquivo em disco quanto o buffer vindo do upload HTTP.
    """
    try:
        excel_file = pd.ExcelFile(origem_arquivo, engine='openpyxl')
    except Exception as exc:
        raise ValueError("A planilha .xlsx está corrompida ou em um formato incompatível.") from exc
    metadados = extrair_metadados_planilha(excel_file)

    nome_aba = selecionar_aba_dados(excel_file)
    df_bruto = pd.read_excel(excel_file, sheet_name=nome_aba)
    df = padronizar_dataframe_pandas(df_bruto)

    # Resolve sinonimos para o nome canonico do LimiteLegal antes de parear P1/P2 e P3/P4
    cache_regras = {}
    def _chave_canonica_parametro(nome_bruto: str) -> str:
        norm = normalizar_texto(nome_bruto)
        if norm not in cache_regras:
            cache_regras[norm] = LimiteLegal.buscar_por_nome(nome_bruto)
        regra = cache_regras[norm]
        return normalizar_texto(regra.parametro) if regra else norm

    df['parametro_normalizado'] = df['parametro'].apply(_chave_canonica_parametro)

    tratados = df['resultado'].apply(converter_numero_br)
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

    novos_laudos = {}
    meses_ordenados = sorted(df['mes_referencia'].unique())

    # Evita colisao quando a mesma planilha multi-mes repete o mesmo id_laudo em meses diferentes
    codigos_brutos_por_mes = {}
    for mes in meses_ordenados:
        df_m = df[df['mes_referencia'] == mes]
        cod_bruto = None
        if 'id_laudo' in df_m.columns:
            ids_validos = [
                str(v).strip()
                for v in df_m['id_laudo'].dropna().tolist()
                if str(v).strip() and str(v).strip().lower() not in ('nan', 'none')
            ]
            if ids_validos:
                cod_bruto = sanitizar_codigo_laudo(ids_validos[0], fallback='')
        codigos_brutos_por_mes[mes] = cod_bruto or None

    contagem_codigos = {}
    for cod in codigos_brutos_por_mes.values():
        if cod:
            contagem_codigos[cod] = contagem_codigos.get(cod, 0) + 1

    for mes in meses_ordenados:
        df_mes = df[df['mes_referencia'] == mes]
        data_coleta_mes = df_mes['data_coleta'].dropna().iloc[0].date() if not df_mes['data_coleta'].isna().all() else date.today()
        codigo_base = codigos_brutos_por_mes[mes]
        if codigo_base and contagem_codigos.get(codigo_base, 0) > 1:
            codigo_candidato = f"{codigo_base}-{mes}"
        elif codigo_base:
            codigo_candidato = codigo_base
        else:
            codigo_candidato = f"CAMP-{mes}"
        codigo_campanha = sanitizar_codigo_laudo(
            codigo_candidato,
            fallback=sanitizar_codigo_laudo(f"CAMP-{mes}", fallback="CAMP-SESSAO"),
        )
        if codigo_campanha in novos_laudos:
            codigo_campanha = sanitizar_codigo_laudo(f"{codigo_campanha}-{mes}", fallback=f"CAMP-{len(novos_laudos) + 1}")

        eficiencias_mes, eficiencias_objs = calcular_eficiencias_campanha(df_mes, codigo_campanha, data_coleta_mes)
        eficiencias_map = {e['parametro']: e['eficiencia_pct'] for e in eficiencias_mes}

        medicoes_mes = []
        alertas_mes = []

        for _, row in df_mes.iterrows():
            nome_param = str(row['parametro']).strip()
            ponto = str(row['codigo_ponto']).strip().upper()
            val_num = sanitizar_float(row['resultado_num'])
            val_txt = row['resultado_txt']
            regra_param = LimiteLegal.buscar_por_nome(nome_param)
            unidade = str(row['unidade']).strip() or (regra_param.unidade if regra_param else 'mg/L')

            status_conf = "Informativo"
            em_conf = None
            norma_violada = None
            alerta_texto = None

            # Avalia limites no Efluente Tratado (P2), incluindo eficiencia de remocao quando aplicavel
            if ponto == 'P2' and regra_param:
                ef_param = eficiencias_map.get(regra_param.parametro)
                avaliacao = regra_param.avaliar_p2(val_num, eficiencia_pct=ef_param)
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

            medicao = MedicaoSessao(
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
                alerta=alerta_texto,
                norma_mais_restritiva=regra_param.norma_mais_restritiva if regra_param else None,
            )
            medicoes_mes.append(medicao)

        novos_laudos[codigo_campanha] = LaudoSessao(
            codigo_laudo=codigo_campanha,
            unidade_monitorada=metadados['unidade_monitorada'][:150],
            corpo_receptor=metadados['corpo_receptor'][:150],
            campanha_mes=str(mes).strip()[:32],
            data_coleta=data_coleta_mes,
            laboratorio=metadados['laboratorio'][:150],
            arquivo_origem=str(nome_arquivo)[:255],
            observacoes=metadados['observacoes'][:500],
            medicoes=medicoes_mes,
            eficiencias=eficiencias_objs,
        )

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

    _salvar_laudos_sessao(novos_laudos)
    return resultado_processamento


def _mapear_primeira_medicao(medicoes: list) -> dict:
    """Mapeia cada parametro mantendo sempre a primeira medicao (alinhado ao iloc[0] da importacao)."""
    mapa = {}
    for m in medicoes:
        mapa.setdefault(m.parametro, m)
    return mapa


def obter_contexto_relatorio(codigo_laudo: str) -> dict:
    """
    Recupera os dados completos de uma campanha carregada na sessao atual.
    Reaproveitado tanto para a tela HTML quanto para a geracao do relatorio em PDF.
    """
    with _SESSOES_LOCK:
        store = _obter_armazenamento_sessao(criar=False)
        laudo = store.get(codigo_laudo) if store else None
    if not laudo:
        abort(404)
    medicoes_p2 = [m for m in laudo.medicoes if m.ponto_coleta == 'P2']
    medicoes_p3 = [m for m in laudo.medicoes if m.ponto_coleta == 'P3']
    medicoes_p4 = [m for m in laudo.medicoes if m.ponto_coleta == 'P4']
    alertas = [m for m in laudo.medicoes if m.status_conformidade == 'Não Conforme']

    # Monta o comparativo de qualidade do Rio Piracicaba (P3 vs P4)
    impactos_rio = []
    p3_map = _mapear_primeira_medicao(medicoes_p3)
    p4_map = _mapear_primeira_medicao(medicoes_p4)
    p2_map = _mapear_primeira_medicao(medicoes_p2)

    for param_nome, m3 in p3_map.items():
        if param_nome in p4_map:
            m4 = p4_map[param_nome]
            v3 = sanitizar_float(m3.valor_medido)
            v4 = sanitizar_float(m4.valor_medido)
            if v3 is None or v4 is None:
                continue
            v2 = sanitizar_float(p2_map[param_nome].valor_medido) if param_nome in p2_map else None

            regra = LimiteLegal.buscar_por_nome(param_nome)
            impactos_rio.append(classificar_impacto_rio(regra, param_nome, v3, v4, m4.unidade, v2=v2))

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


def separar_secoes_pdf(texto_completo: str, textos_paginas: list) -> tuple:
    """
    Localiza as secoes de Efluentes (P1/P2) e Corpo Receptor (P3/P4) pelos titulos
    no texto completo, evitando dependencia do numero fixo de paginas.
    """
    padrao_efluente = re.compile(
        r'(?:RESULTADOS?\s+DE\s+EFLUENTES?|EFLUENTES?\s*\(?P1|EFLUENTE\s+BRUTO[^\n]*TRATADO|P1\s*BRUTO[^\n]*P2)',
        re.IGNORECASE
    )
    padrao_rio = re.compile(
        r'(?:CORPO\s+RECEPTOR[^\n]*(?:P3|P4|MONTANTE|JUSANTE)|(?:MONITORAMENTO|AVALIA[ÇC][ÃA]O|RESULTADOS?)[^\n]*(?:CORPO\s+RECEPTOR|RIO\s+PIRACICABA)|P3\s*(?:\(?MONTANTE\)?)?[^\n]*(?:P4|JUSANTE))',
        re.IGNORECASE
    )

    m_efl = padrao_efluente.search(texto_completo)
    m_rio = padrao_rio.search(texto_completo)

    if m_efl and m_rio:
        if m_efl.start() < m_rio.start():
            return texto_completo[m_efl.start():m_rio.start()], texto_completo[m_rio.start():]
        return texto_completo[m_efl.start():], texto_completo[m_rio.start():m_efl.start()]

    if m_rio:
        return texto_completo[:m_rio.start()], texto_completo[m_rio.start():]

    if m_efl:
        return texto_completo[m_efl.start():], ""

    texto_p2 = textos_paginas[1] if len(textos_paginas) >= 2 else texto_completo
    texto_p3 = textos_paginas[2] if len(textos_paginas) >= 3 else ""
    return texto_p2, texto_p3


def extrair_dados_pdf_laudo(origem_pdf, nome_arquivo: str = "laudo.pdf") -> dict:
    """
    Extrai metadados e resultados analiticos (P1 a P4) de arquivos PDF via pypdf.
    Identifica automaticamente tanto o laudo laboratorial original (modelo Hackathon)
    quanto relatorios tecnicos exportados pelo proprio sistema, recalculando
    eficiencias da ETE, nao conformidades em P2 e impactos no Rio Piracicaba.
    """
    try:
        reader = pypdf.PdfReader(origem_pdf)
    except pypdf.errors.PdfReadError as exc:
        raise ValueError("O arquivo PDF está corrompido ou incompleto e não pôde ser lido.") from exc

    if reader.is_encrypted:
        try:
            if not reader.decrypt(""):
                raise ValueError("O arquivo PDF está protegido por senha. Envie uma versão desbloqueada do laudo.")
        except ValueError:
            raise
        except Exception:
            raise ValueError("O arquivo PDF está protegido por senha. Envie uma versão desbloqueada do laudo.")

    num_paginas = len(reader.pages)
    if num_paginas == 0:
        raise ValueError("O arquivo PDF enviado está vazio ou não possui páginas legíveis.")

    textos_paginas = []
    for p in reader.pages:
        try:
            txt = p.extract_text() or ""
        except pypdf.errors.FileNotDecryptedError:
            raise ValueError("O arquivo PDF está protegido por senha. Envie uma versão desbloqueada do laudo.")
        except pypdf.errors.PdfReadError as exc:
            raise ValueError("O arquivo PDF está corrompido ou incompleto e não pôde ser lido.") from exc
        txt = (
            txt.replace('\u2212', '-')
            .replace('\u2014', '-')
            .replace('\u2264', '<=')
            .replace('\u2265', '>=')
            .replace('\u00baC', '°C')
            .replace('\u00bac', '°C')
        )
        textos_paginas.append(txt)

    texto_completo = "\n".join(textos_paginas)
    if not texto_completo.strip():
        raise ValueError(
            "O PDF enviado não possui texto legível (possivelmente é um arquivo escaneado ou imagem). "
            "Envie um laudo em PDF com texto selecionável."
        )

    texto_efluentes, texto_rio = separar_secoes_pdf(texto_completo, textos_paginas)
    converter_valor = converter_numero_br

    todos_limites = LimiteLegal.query.all()
    limites_ordenados = sorted(todos_limites, key=lambda l: len(l.parametro), reverse=True)
    sinonimos_ordenados = []
    for regra in limites_ordenados:
        if regra.sinonimos:
            for sin in regra.sinonimos.split('|'):
                sin_norm = normalizar_texto(sin)
                if sin_norm:
                    sinonimos_ordenados.append((sin_norm, regra))
    sinonimos_ordenados.sort(key=lambda item: len(item[0]), reverse=True)

    def _contem_termo(termo_norm: str, texto_norm: str) -> bool:
        if not termo_norm or not texto_norm:
            return False
        return bool(re.search(r'(?<![a-z0-9])' + re.escape(termo_norm) + r'(?![a-z0-9])', texto_norm))

    def casar_limite_legal(texto_linha):
        t_norm = normalizar_texto(texto_linha)
        if not t_norm:
            return None
        for regra in limites_ordenados:
            if _contem_termo(normalizar_texto(regra.parametro), t_norm):
                return regra
        for sin_norm, regra in sinonimos_ordenados:
            if _contem_termo(sin_norm, t_norm):
                return regra
        for regra in limites_ordenados:
            if regra.simbolo and len(regra.simbolo) > 1:
                if _contem_termo(normalizar_texto(regra.simbolo), t_norm):
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
            m = re.search(rf'{rotulo}:\s*([^\n]+)', texto_completo)
            if not m:
                return default
            val = m.group(1).strip()
            if not val or val.endswith(':'):
                return default
            return val

        codigo_campanha = sanitizar_codigo_laudo(buscar_linha_seguinte('Código do Laudo', 'LAUDO-PDF'), fallback='LAUDO-PDF')
        mes_referencia = buscar_linha_seguinte('Mês Referência', date.today().strftime('%Y-%m'))[:32]
        data_coleta_str = buscar_linha_seguinte('Data da Coleta', '')
        laboratorio = buscar_linha_seguinte('Laboratório', 'Laboratório Acreditado')[:150]
        unidade_monitorada = buscar_linha_seguinte('Unidade', 'ETE Industrial')[:150]
        corpo_receptor = buscar_linha_seguinte('Corpo Receptor', 'Rio Piracicaba (Classe 2)')[:150]

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
        regex_val_unid = re.compile(r'^([<>]?\s*[+-]?[\d,\.]+)\s+(.+)$')

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
                        'em_conformidade': None,
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
                        'em_conformidade': None,
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
                        'em_conformidade': None,
                        'norma_violada': None,
                        'alerta': None
                    })

                    if v3_num is not None and v4_num is not None:
                        item_impacto = classificar_impacto_rio(regra, nome_param, v3_num, v4_num, unidade)
                        item_impacto['mes'] = mes_referencia
                        impactos_rio.append(item_impacto)
                    i += 3
                    continue

            elif secao_atual == 'p2' and i + 2 < len(linhas_sys):
                val_cand = linhas_sys[i + 1]
                unid_cand = linhas_sys[i + 2]
                if re.match(r'^[<>]?\s*[+-]?[\d,\.]+$', val_cand) or normalizar_texto(val_cand) == 'sem dados':
                    regra = casar_limite_legal(linha)
                    nome_param = regra.parametro if regra else linha
                    v2_num, v2_txt = converter_valor(val_cand)

                    status_p2 = "Informativo"
                    em_conf_p2 = None
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
                val = re.sub(r'^\[|\]$', '', val).strip(' :')
                return val or default
            return default

        prox_campo = r'(?=\s+(?:Código do Laudo|Data da Coleta|Unidade Monitorada|Campanha\s*/\s*Mês|Corpo Receptor|Laboratório)\b|\r?\n|$)'
        codigo_laudo_bruto = buscar_campo(rf'Código do Laudo\s*:?\s*\[?(.*?)\]?{prox_campo}', 'LAUDO-PDF')
        data_coleta_str = buscar_campo(rf'Data da Coleta\s*:?\s*\[?(.*?)\]?{prox_campo}', '')
        unidade_monitorada = buscar_campo(rf'Unidade Monitorada\s*:?\s*\[?(.*?)\]?{prox_campo}', 'ETE Industrial')
        campanha_mes_str = buscar_campo(rf'Campanha\s*/\s*Mês\s*:?\s*\[?(.*?)\]?{prox_campo}', '')
        corpo_receptor = buscar_campo(rf'Corpo Receptor\s*:?\s*\[?(.*?)\]?{prox_campo}', 'Rio Piracicaba (Classe 2)')
        laboratorio = buscar_campo(rf'Laboratório\s*:?\s*\[?(.*?)\]?{prox_campo}', 'Laboratório Acreditado')

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

        eh_placeholder_codigo = (
            not codigo_laudo_bruto
            or bool(re.search(r'\b(ANO|XXXX|NNNN|MODELO)\b', codigo_laudo_bruto, re.IGNORECASE))
            or codigo_laudo_bruto.upper() in ('LAUDO-ANO-001', 'LAUDO-001', 'LAUDO-PDF')
        )
        if eh_placeholder_codigo:
            codigo_campanha = sanitizar_codigo_laudo(f"CAMP-{mes_referencia}", fallback="CAMP-PDF")
        else:
            codigo_campanha = sanitizar_codigo_laudo(codigo_laudo_bruto, fallback=f"CAMP-{mes_referencia}")

        t2_tratado = texto_efluentes
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

        regex_p1_p2 = r'([A-Za-zÀ-ÿ0-9\s,\-\(\)\+]+?)\s+(mg/L|u\.pH|°C|mL/L)\s+((?:[<>]\s*)?[\d,\.]+)\s+((?:[<>]\s*)?[\d,\.]+)'
        pares_efluente = []
        for raw_param, unidade, v1_str, v2_str in re.findall(regex_p1_p2, t2_tratado):
            regra = casar_limite_legal(raw_param)
            nome_param = regra.parametro if regra else ' '.join(raw_param.split()).strip()
            v1_num, v1_txt = converter_valor(v1_str)
            v2_num, v2_txt = converter_valor(v2_str)
            pares_efluente.append((regra, nome_param, unidade, v1_num, v1_txt, v2_num, v2_txt))

        eficiencias_pre_map = {}
        for regra, nome_param, _, v1_num, _, v2_num, _ in pares_efluente:
            if regra and regra.calcula_eficiencia and v1_num is not None and v2_num is not None and v1_num > 0:
                eficiencias_pre_map[nome_param] = regra.avaliar_eficiencia(v1_num, v2_num)['eficiencia_pct']

        p2_valores_map = {}
        for regra, nome_param, unidade, v1_num, v1_txt, v2_num, v2_txt in pares_efluente:
            p2_valores_map[nome_param] = v2_num

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
                'em_conformidade': None,
                'norma_violada': None,
                'alerta': None
            })

            # Medição P2 (Efluente Tratado) com avaliação de conformidade legal e eficiência
            status_p2 = "Informativo"
            em_conf_p2 = None
            norma_violada = None
            alerta_p2 = None

            if regra:
                avaliacao = regra.avaliar_p2(v2_num, eficiencia_pct=eficiencias_pre_map.get(nome_param))
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
        t3_tratado = texto_rio
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

        regex_p3_p4 = r'([A-Za-zÀ-ÿ0-9\s,\-\(\)\+]+?)\s+(mg/L|u\.pH|°C|mL/L|UNT)\s+((?:[<>]\s*)?[\d,\.]+)\s+((?:[<>]\s*)?[\d,\.]+)\s+([\+\-]?[\d,\.]+)'

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
                'em_conformidade': None,
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
                'em_conformidade': None,
                'norma_violada': None,
                'alerta': None
            })

            if v3_num is not None and v4_num is not None:
                item_impacto = classificar_impacto_rio(
                    regra,
                    nome_param,
                    v3_num,
                    v4_num,
                    unidade,
                    v2=p2_valores_map.get(nome_param)
                )
                item_impacto['mes'] = mes_referencia
                impactos_rio.append(item_impacto)

    # 4. Cálculo de Eficiência da ETE (P1 vs P2)
    # Filtra pares P1 e P2 para DBO5,20, DQO e SST mantendo sempre a primeira ocorrencia
    p1_map = {}
    p2_map = {}
    for m in medicoes_extraidas:
        if m['ponto_coleta'] == 'P1':
            p1_map.setdefault(m['parametro'], m['valor_medido'])
        elif m['ponto_coleta'] == 'P2':
            p2_map.setdefault(m['parametro'], m['valor_medido'])

    eficiencias_calculadas = []
    for param_carga in ['DBO5,20', 'DQO', 'Sólidos Suspensos Totais']:
        regra = casar_limite_legal(param_carga)
        nome_oficial = regra.parametro if regra else param_carga
        if nome_oficial in p1_map and nome_oficial in p2_map:
            v1 = p1_map[nome_oficial]
            v2 = p2_map[nome_oficial]
            if v1 is not None and v2 is not None and v1 > 0:
                if regra:
                    avaliacao_ef = regra.avaliar_eficiencia(v1, v2)
                    ef_pct = avaliacao_ef['eficiencia_pct']
                    avaliacao = avaliacao_ef['avaliacao']
                    meta_atingida = avaliacao_ef['atingiu_meta']
                else:
                    ef_pct = round(((v1 - v2) / v1) * 100.0, 1)
                    avaliacao = "Operacional"
                    meta_atingida = True

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

                # No modo de reimportacao do PDF do proprio sistema, reavalia P2 caso haja meta de eficiencia
                if eh_relatorio_sistema and regra and regra.eficiencia_minima_pct is not None:
                    for m in medicoes_extraidas:
                        if m['ponto_coleta'] == 'P2' and m['parametro'] == nome_oficial:
                            reav = regra.avaliar_p2(v2, eficiencia_pct=ef_pct)
                            if reav['status_conformidade'] == 'Não Conforme':
                                alerta_existente = next(
                                    (a for a in alertas_nao_conformidade if a['parametro'] == nome_oficial and a['ponto'] == 'P2'),
                                    None,
                                )
                                if alerta_existente:
                                    alerta_existente['norma_violada'] = reav['norma_violada']
                                    alerta_existente['mensagem'] = reav['alerta']
                                else:
                                    alertas_nao_conformidade.append({
                                        'mes': mes_referencia,
                                        'ponto': 'P2',
                                        'parametro': nome_oficial,
                                        'valor': v2,
                                        'unidade': m['unidade'],
                                        'norma_violada': reav['norma_violada'],
                                        'mensagem': reav['alerta']
                                    })
                            m['status_conformidade'] = reav['status_conformidade']
                            m['em_conformidade'] = reav['em_conformidade']
                            m['norma_violada'] = reav['norma_violada']
                            m['alerta'] = reav['alerta']

    if not medicoes_extraidas:
        raise ValueError(
            "Nenhuma medição laboratorial (pontos P1 a P4) foi identificada neste PDF. "
            "Verifique se o documento contém as tabelas de resultados com valores e unidades."
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
    Executa a leitura automatica do PDF e carrega a campanha na sessao em memoria,
    substituindo eventual leitura anterior de mesmo codigo sem gravar estado em disco.
    """
    dados = extrair_dados_pdf_laudo(origem_pdf, nome_arquivo)
    codigo_campanha = dados['codigo_laudo']
    mes_referencia = dados['mes_referencia']
    data_coleta = dados['data_coleta']

    regras_por_id = {r.id: r.norma_mais_restritiva for r in LimiteLegal.query.all()}

    medicoes_objs = [
        MedicaoSessao(
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
            alerta=m['alerta'],
            norma_mais_restritiva=regras_por_id.get(m['parametro_id']),
        )
        for m in dados['medicoes']
    ]

    eficiencias_objs = [
        EficienciaSessao(
            codigo_laudo=codigo_campanha,
            data_referencia=data_coleta,
            parametro=ef['parametro'],
            unidade=ef['unidade'],
            entrada_p1=ef['entrada_p1'],
            saida_p2=ef['saida_p2'],
            eficiencia_percentual=ef['eficiencia_pct'],
            avaliacao=ef['avaliacao'],
            atingiu_meta=ef['atingiu_meta'],
        )
        for ef in dados['eficiencias']
    ]

    _salvar_laudos_sessao({
        codigo_campanha: LaudoSessao(
            codigo_laudo=codigo_campanha,
            unidade_monitorada=str(dados['unidade_monitorada'] or 'ETE Industrial')[:150],
            corpo_receptor=str(dados['corpo_receptor'] or 'Rio Piracicaba (Classe 2)')[:150],
            campanha_mes=str(mes_referencia or '')[:32],
            data_coleta=data_coleta,
            laboratorio=str(dados['laboratorio'] or 'Laboratório Acreditado')[:150],
            arquivo_origem=str(nome_arquivo)[:255],
            observacoes="Laudo importado automaticamente via módulo de extração PDF.",
            medicoes=medicoes_objs,
            eficiencias=eficiencias_objs,
        )
    })
    return dados


def obter_dados_dashboard(campanha_filtro: str = None, parametro_filtro: str = None) -> dict:
    """
    Agrega os indicadores ambientais das campanhas carregadas na sessao em memoria
    para alimentar o Dashboard Ambiental (KPIs, graficos dinamicos e painel de alertas).
    """
    todos_laudos = listar_laudos_sessao(ordem_desc=False)

    if not todos_laudos:
        return {
            'possui_dados': False,
            'filtros': {
                'campanhas_disponiveis': [],
                'parametros_p2_disponiveis': [],
                'campanha_selecionada': 'todas',
                'parametro_selecionado': '',
            },
            'kpis': {
                'total_campanhas': 0,
                'total_medicoes_p2': 0,
                'total_avaliadas_p2': 0,
                'total_conformes_p2': 0,
                'total_nao_conformes_p2': 0,
                'total_informativos_p2': 0,
                'total_sem_dados_p2': 0,
                'taxa_conformidade_pct': None,
                'total_alertas_rio': 0,
                'total_atencao_rio': 0,
                'eficiencia_media_dbo': None,
                'eficiencia_media_dqo': None,
                'eficiencia_media_sst': None,
            },
            'graficos': {},
            'alertas_p2': [],
            'investigacoes_rio': [],
            'resumo_campanhas': [],
        }

    campanhas_disponiveis = [
        {
            'codigo_laudo': l.codigo_laudo,
            'campanha_mes': l.campanha_mes,
            'data_coleta': l.data_coleta.strftime('%d/%m/%Y'),
            'laboratorio': l.laboratorio or 'Laboratório Acreditado',
            'arquivo_origem': l.arquivo_origem or '',
        }
        for l in todos_laudos
    ]

    campanha_selecionada = campanha_filtro if (campanha_filtro and campanha_filtro != 'todas') else 'todas'
    if campanha_selecionada != 'todas':
        laudos_filtrados = [l for l in todos_laudos if l.codigo_laudo == campanha_selecionada]
        if not laudos_filtrados:
            laudos_filtrados = todos_laudos
            campanha_selecionada = 'todas'
    else:
        laudos_filtrados = todos_laudos

    parametros_p2_set = set()
    for l in todos_laudos:
        for m in l.medicoes:
            if m.ponto_coleta == 'P2':
                parametros_p2_set.add(m.parametro)
    parametros_p2_disponiveis = sorted(parametros_p2_set)

    if parametro_filtro and parametro_filtro in parametros_p2_set:
        parametro_selecionado = parametro_filtro
    elif 'DBO5,20' in parametros_p2_set:
        parametro_selecionado = 'DBO5,20'
    elif parametros_p2_disponiveis:
        parametro_selecionado = parametros_p2_disponiveis[0]
    else:
        parametro_selecionado = ''

    total_conformes_p2 = 0
    total_nao_conformes_p2 = 0
    total_informativos_p2 = 0
    total_sem_dados_p2 = 0
    total_medicoes_p2 = 0
    total_alertas_rio = 0
    total_atencao_rio = 0

    alertas_p2 = []
    investigacoes_rio = []
    contagem_violacoes_param = {}
    ef_valores_por_param = {'DBO5,20': [], 'DQO': [], 'Sólidos Suspensos Totais': []}
    resumo_campanhas = []

    codigos_filtrados = {l.codigo_laudo for l in laudos_filtrados}
    impactos_por_laudo = {}

    for l in todos_laudos:
        medicoes_p2 = [m for m in l.medicoes if m.ponto_coleta == 'P2']
        medicoes_p3 = [m for m in l.medicoes if m.ponto_coleta == 'P3']
        medicoes_p4 = [m for m in l.medicoes if m.ponto_coleta == 'P4']

        p2_map = _mapear_primeira_medicao(medicoes_p2)
        p3_map = _mapear_primeira_medicao(medicoes_p3)
        p4_map = _mapear_primeira_medicao(medicoes_p4)

        impactos_l = []
        for param_nome in sorted(set(p3_map.keys()).intersection(set(p4_map.keys()))):
            m3 = p3_map[param_nome]
            m4 = p4_map[param_nome]
            v3 = sanitizar_float(m3.valor_medido)
            v4 = sanitizar_float(m4.valor_medido)
            if v3 is None or v4 is None:
                continue
            v2 = sanitizar_float(p2_map[param_nome].valor_medido) if param_nome in p2_map else None
            regra = LimiteLegal.buscar_por_nome(param_nome)
            imp = classificar_impacto_rio(regra, param_nome, v3, v4, m4.unidade, v2=v2)
            impactos_l.append(imp)
        impactos_por_laudo[l.codigo_laudo] = impactos_l

        conf_l = sum(1 for m in medicoes_p2 if m.status_conformidade == 'Conforme')
        nconf_l = sum(1 for m in medicoes_p2 if m.status_conformidade == 'Não Conforme')
        sem_dados_l = sum(1 for m in medicoes_p2 if m.status_conformidade == 'Sem Dados')
        info_l = sum(1 for m in medicoes_p2 if m.status_conformidade not in ('Conforme', 'Não Conforme', 'Sem Dados'))
        rio_imp_l = sum(1 for i in impactos_l if i['status_rio'] == 'Alerta de Impacto')
        rio_ate_l = sum(1 for i in impactos_l if i['status_rio'] == 'Atenção')

        ef_dbo_l = next((sanitizar_float(e.eficiencia_percentual) for e in l.eficiencias if e.parametro == 'DBO5,20'), None)

        resumo_campanhas.append({
            'codigo_laudo': l.codigo_laudo,
            'campanha_mes': l.campanha_mes,
            'data_coleta': l.data_coleta.strftime('%d/%m/%Y'),
            'laboratorio': l.laboratorio or 'Laboratório Acreditado',
            'conformes': conf_l,
            'nao_conformes': nconf_l,
            'alertas_rio': rio_imp_l,
            'atencao_rio': rio_ate_l,
            'eficiencia_dbo': ef_dbo_l,
            'selecionada': l.codigo_laudo in codigos_filtrados,
        })

        if l.codigo_laudo not in codigos_filtrados:
            continue

        total_medicoes_p2 += len(medicoes_p2)
        total_conformes_p2 += conf_l
        total_nao_conformes_p2 += nconf_l
        total_informativos_p2 += info_l
        total_sem_dados_p2 += sem_dados_l
        total_alertas_rio += rio_imp_l
        total_atencao_rio += rio_ate_l

        for m in medicoes_p2:
            if m.status_conformidade == 'Não Conforme':
                contagem_violacoes_param[m.parametro] = contagem_violacoes_param.get(m.parametro, 0) + 1
                alertas_p2.append({
                    'codigo_laudo': l.codigo_laudo,
                    'campanha_mes': l.campanha_mes,
                    'parametro': m.parametro,
                    'valor_texto': m.valor_texto or str(m.valor_medido),
                    'valor_medido': m.valor_medido,
                    'unidade': m.unidade,
                    'norma_violada': m.norma_violada or 'Norma aplicável',
                    'alerta': m.alerta or 'Parâmetro fora do limite legal.',
                })

        for imp in impactos_l:
            if imp['status_rio'] in ('Alerta de Impacto', 'Atenção'):
                investigacoes_rio.append({
                    'codigo_laudo': l.codigo_laudo,
                    'campanha_mes': l.campanha_mes,
                    **imp,
                })

        for e in l.eficiencias:
            ef_val = sanitizar_float(e.eficiencia_percentual)
            if e.parametro in ef_valores_por_param and ef_val is not None:
                ef_valores_por_param[e.parametro].append(ef_val)

    total_avaliadas_p2 = total_conformes_p2 + total_nao_conformes_p2
    taxa_conformidade_pct = round((total_conformes_p2 / total_avaliadas_p2) * 100.0, 1) if total_avaliadas_p2 > 0 else None

    def media_arredondada(valores):
        validos = [v for v in valores if sanitizar_float(v) is not None]
        return round(sum(validos) / len(validos), 1) if validos else None

    # As series temporais mantem todas as campanhas em ordem cronologica, mesmo com filtro ativo
    meses_labels = [l.campanha_mes for l in todos_laudos]
    series_eficiencia = {
        'DBO5,20': [],
        'DQO': [],
        'Sólidos Suspensos Totais': [],
    }
    for l in todos_laudos:
        ef_map = {e.parametro: sanitizar_float(e.eficiencia_percentual) for e in l.eficiencias}
        for p_nome in series_eficiencia:
            series_eficiencia[p_nome].append(ef_map.get(p_nome))

    laudo_rio_ref = laudos_filtrados[-1]
    impactos_ref = impactos_por_laudo.get(laudo_rio_ref.codigo_laudo, [])
    rio_comparativo = {
        'codigo_laudo': laudo_rio_ref.codigo_laudo,
        'campanha_mes': laudo_rio_ref.campanha_mes,
        'parametros': [i['parametro'] for i in impactos_ref],
        'montante_p3': [i['montante_p3'] for i in impactos_ref],
        'jusante_p4': [i['jusante_p4'] for i in impactos_ref],
        'limites_max': [i['limite_max_classe2'] for i in impactos_ref],
        'limites_min': [i['limite_min_classe2'] for i in impactos_ref],
        'unidades': [i['unidade'] for i in impactos_ref],
        'status': [i['status_rio'] for i in impactos_ref],
    }

    regra_param_sel = LimiteLegal.buscar_por_nome(parametro_selecionado) if parametro_selecionado else None
    valores_p2_serie = []
    valores_p1_serie = []
    unidade_param_sel = regra_param_sel.unidade if regra_param_sel else ''

    for l in todos_laudos:
        m_p2 = next((m for m in l.medicoes if m.ponto_coleta == 'P2' and m.parametro == parametro_selecionado), None)
        m_p1 = next((m for m in l.medicoes if m.ponto_coleta == 'P1' and m.parametro == parametro_selecionado), None)
        valores_p2_serie.append(sanitizar_float(m_p2.valor_medido) if m_p2 else None)
        valores_p1_serie.append(sanitizar_float(m_p1.valor_medido) if m_p1 else None)
        if not unidade_param_sel and m_p2:
            unidade_param_sel = m_p2.unidade

    evolucao_parametro_p2 = {
        'parametro': parametro_selecionado,
        'unidade': unidade_param_sel,
        'meses': meses_labels,
        'valores_p2': valores_p2_serie,
        'valores_p1': valores_p1_serie,
        'limite_max_restritivo': regra_param_sel.limite_max_restritivo if regra_param_sel else None,
        'limite_min_restritivo': regra_param_sel.limite_min_restritivo if regra_param_sel else None,
        'norma_restritiva': regra_param_sel.norma_mais_restritiva if regra_param_sel else 'Monitoramento',
    }

    ranking_ordenado = sorted(contagem_violacoes_param.items(), key=lambda x: (-x[1], x[0]))

    alertas_p2.reverse()
    investigacoes_rio.reverse()
    resumo_campanhas.reverse()

    rosca_labels = ['Conforme', 'Não Conforme', 'Informativo']
    rosca_valores = [total_conformes_p2, total_nao_conformes_p2, total_informativos_p2]
    if total_sem_dados_p2 > 0:
        rosca_labels.append('Sem Dados')
        rosca_valores.append(total_sem_dados_p2)

    return {
        'possui_dados': True,
        'filtros': {
            'campanhas_disponiveis': list(reversed(campanhas_disponiveis)),
            'parametros_p2_disponiveis': parametros_p2_disponiveis,
            'campanha_selecionada': campanha_selecionada,
            'parametro_selecionado': parametro_selecionado,
        },
        'kpis': {
            'total_campanhas': len(laudos_filtrados),
            'total_medicoes_p2': total_medicoes_p2,
            'total_avaliadas_p2': total_avaliadas_p2,
            'total_conformes_p2': total_conformes_p2,
            'total_nao_conformes_p2': total_nao_conformes_p2,
            'total_informativos_p2': total_informativos_p2,
            'total_sem_dados_p2': total_sem_dados_p2,
            'taxa_conformidade_pct': taxa_conformidade_pct,
            'total_alertas_rio': total_alertas_rio,
            'total_atencao_rio': total_atencao_rio,
            'eficiencia_media_dbo': media_arredondada(ef_valores_por_param['DBO5,20']),
            'eficiencia_media_dqo': media_arredondada(ef_valores_por_param['DQO']),
            'eficiencia_media_sst': media_arredondada(ef_valores_por_param['Sólidos Suspensos Totais']),
        },
        'graficos': {
            'conformidade_rosca': {
                'labels': rosca_labels,
                'valores': rosca_valores,
            },
            'eficiencia_temporal': {
                'meses': meses_labels,
                'series': series_eficiencia,
                'meta_dbo': 60.0,
            },
            'rio_comparativo': rio_comparativo,
            'evolucao_parametro_p2': evolucao_parametro_p2,
            'nao_conformidades_por_parametro': {
                'parametros': [item[0] for item in ranking_ordenado],
                'contagens': [item[1] for item in ranking_ordenado],
            },
        },
        'alertas_p2': alertas_p2,
        'investigacoes_rio': investigacoes_rio,
        'resumo_campanhas': resumo_campanhas,
    }


def excluir_laudo(codigo_laudo: str) -> bool:
    """Remove uma campanha especifica da sessao atual em memoria."""
    with _SESSOES_LOCK:
        store = _obter_armazenamento_sessao(criar=False)
        if not store:
            return False
        return store.pop(codigo_laudo, None) is not None


def limpar_todos_laudos() -> int:
    """Limpa todas as campanhas carregadas na sessao atual em memoria."""
    with _SESSOES_LOCK:
        store = _obter_armazenamento_sessao(criar=False)
        if not store:
            return 0
        total = len(store)
        store.clear()
        return total
