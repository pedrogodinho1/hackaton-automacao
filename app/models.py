"""
Modelos de Dados do Domínio Ambiental (Camada Model - SQLAlchemy ORM).

Este módulo define a estrutura relacional do banco de dados SQLite para o sistema
de monitoramento ambiental da ETE e do Rio Piracicaba, integrando regras de negócio
e inteligência normativa.

Entidades principais:
1. PontoColeta: Cadastro padronizado dos 4 pontos de amostragem (P1, P2, P3 e P4).
2. Legislacao: Cadastro das normas ambientais regulatórias (CONAMA e Decretos Estaduais).
3. LimiteLegal: Tabela mestra de parâmetros químicos/físico-químicos com limites numéricos,
   textos legais e métodos de validação automática (prevalência da norma mais restritiva).
4. Laudo: Registro histórico de cada campanha mensal de monitoramento laboratorial.
5. ResultadoAnalise: Medições individuais obtidas para cada parâmetro e ponto de coleta.
6. EficienciaETE: Registro dos cálculos de taxa de remoção e eficiência da estação de tratamento.
"""

import re
import unicodedata
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from app import db


def normalizar_texto(texto: str) -> str:
    """
    Higieniza e normaliza nomes de parâmetros químicos e rótulos de coleta.

    Por que existe:
    - Laudos laboratoriais em PDF e planilhas Excel utilizam tipografia variada,
      incluindo caracteres subscritos (ex: DBO₅,₂₀), sobrescritos (ex: Cr⁶⁺),
      sinais de íons (ex: CN⁻, F⁻), acentuação gráfica e espaçamentos irregulares.
    - Esta função padroniza qualquer string para uma representação ASCII simplificada,
      permitindo que o sistema localize os parâmetros correspondentes no banco de dados
      de forma resiliente, sem falhas de busca por diferenças de digitação ou formatação.

    O que faz:
    1. Traduz numerais subscritos/sobrescritos e traços tipográficos em caracteres padrão.
    2. Decompõe acentos gráficos (NFKD) e remove diacríticos.
    3. Converte todo o texto para minúsculas e remove espaços extras.
    """
    if not texto:
        return ""
    mapa_chars = str.maketrans({
        "₀": "0", "₁": "1", "₂": "2", "₃": "3", "₄": "4",
        "₅": "5", "₆": "6", "₇": "7", "₈": "8", "₉": "9",
        "⁰": "0", "¹": "1", "²": "2", "³": "3", "⁴": "4",
        "⁵": "5", "⁶": "6", "⁷": "7", "⁸": "8", "⁹": "9",
        "⁺": "+", "⁻": "-", "−": "-", "–": "-",
    })
    t = texto.translate(mapa_chars).strip().lower()
    t = unicodedata.normalize("NFKD", t)
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"\s+", " ", t)
    return t


class PontoColeta(db.Model):
    """
    Cadastro dos Pontos de Coleta Oficiais do Monitoramento.

    Por que existe:
    - O desafio de automação divide o monitoramento mensal em exatamente quatro pontos
      que cobrem o ciclo completo da estação de tratamento até a influência no rio.
    - Esta tabela centraliza o cadastro desses pontos, sua finalidade ambiental e
      sinônimos aceitos para que a leitura de arquivos identifique automaticamente
      a qual ponto pertence cada coluna ou bloco de dados.
    """
    __tablename__ = 'pontos_coleta'

    id = db.Column(db.Integer, primary_key=True)
    # Identificador alfanumérico curto: 'P1', 'P2', 'P3' ou 'P4'
    codigo = db.Column(db.String(10), unique=True, nullable=False)
    # Nome descritivo (ex: 'Efluente Bruto (Entrada ETE)', 'Efluente Tratado (Saída ETE)')
    nome = db.Column(db.String(100), nullable=False)
    # Natureza da amostra coletada ('Efluente Líquido' ou 'Água Superficial')
    matriz = db.Column(db.String(50), nullable=False)
    # Papel da amostra no cálculo de eficiência ou avaliação de conformidade
    finalidade = db.Column(db.String(255), nullable=False)
    # Lista de termos equivalentes separados por '|' (ex: "P1|Bruto|Entrada ETE")
    sinonimos = db.Column(db.String(255), nullable=True)

    def __repr__(self):
        return f"<PontoColeta {self.codigo}: {self.nome}>"


class Legislacao(db.Model):
    """
    Catálogo de Normas e Legislações Ambientais de Referência.

    Por que existe:
    - Fornece rastreabilidade jurídica formal para as análises e laudos gerados pelo sistema.
    - Cada limite químico verificado precisa citar a norma competente e o artigo específico
      (ex: CONAMA 430/2011 Art. 16, Decreto SP 8.468/1976 Art. 18, CONAMA 357/2005 Classe 2).
    """
    __tablename__ = 'legislacoes'

    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(50), unique=True, nullable=False)  # Ex: CONAMA_430_2011
    nome = db.Column(db.String(150), nullable=False)
    esfera = db.Column(db.String(50), nullable=False)               # 'Federal' ou 'Estadual (SP)'
    artigo_referencia = db.Column(db.String(50), nullable=True)     # Artigo aplicável (ex: 'Art. 16', 'Art. 18')
    aplicacao = db.Column(db.String(100), nullable=False)           # 'Efluente Tratado' ou 'Corpo Receptor'
    descricao = db.Column(db.Text, nullable=True)

    def __repr__(self):
        return f"<Legislacao {self.nome}>"


class LimiteLegal(db.Model):
    """
    Tabela Mestra de Parâmetros Químicos, Limites Legais e Regras de Avaliação.

    Por que existe:
    - É o coração da inteligência de validação do sistema. Concentra em uma única
      estrutura os padrões máximos e mínimos permitidos pelas legislações federal e estadual,
      além das diretrizes para rios de Classe 2 e metas de eficiência da ETE.
    - Disponibiliza métodos para cálculo de eficiência e validação de conformidade
      aplicando a regra de prevalência da norma mais restritiva.
    """
    __tablename__ = 'limites_legais'

    id = db.Column(db.Integer, primary_key=True)
    parametro = db.Column(db.String(100), unique=True, nullable=False)
    simbolo = db.Column(db.String(30), nullable=True)               # Fórmula ou sigla (ex: DBO5,20, Fe, Cr6+, CN-)
    sinonimos = db.Column(db.Text, nullable=True)                   # Variações de nomes separadas por '|'
    categoria = db.Column(db.String(60), nullable=True)             # Ex: Físico-Químico, Metais, Nutrientes, Orgânicos
    unidade = db.Column(db.String(30), nullable=False)              # Ex: u.pH, °C, mL/L, mg/L

    # Padrões para Efluente Tratado (P2) - Resolução CONAMA nº 430/2011 (Art. 16)
    limite_min_conama430 = db.Column(db.Float, nullable=True)
    limite_max_conama430 = db.Column(db.Float, nullable=True)
    texto_conama430 = db.Column(db.String(60), nullable=True)

    # Padrões para Efluente Tratado (P2) - Decreto Estadual SP nº 8.468/1976 (Art. 18)
    limite_min_decreto8468 = db.Column(db.Float, nullable=True)
    limite_max_decreto8468 = db.Column(db.Float, nullable=True)
    texto_decreto8468 = db.Column(db.String(60), nullable=True)

    # Critério Consolidado de Maior Restrição para o Efluente Tratado
    limite_min_restritivo = db.Column(db.Float, nullable=True)
    limite_max_restritivo = db.Column(db.Float, nullable=True)
    norma_mais_restritiva = db.Column(db.String(100), nullable=True)

    # Limites para o Corpo Receptor (P3/P4 - Rio Piracicaba Classe 2) - CONAMA nº 357/2005
    monitorado_no_rio = db.Column(db.Boolean, default=False)
    limite_min_conama357 = db.Column(db.Float, nullable=True)
    limite_max_conama357 = db.Column(db.Float, nullable=True)
    texto_conama357 = db.Column(db.String(60), nullable=True)

    # Regras de Eficiência de Remoção da ETE (P1 vs P2)
    calcula_eficiencia = db.Column(db.Boolean, default=False)
    eficiencia_minima_pct = db.Column(db.Float, nullable=True)          # Meta de remoção (ex: 60% para DBO)
    tipo_avaliacao_eficiencia = db.Column(db.String(50), nullable=True)  # 'Conformidade Legal' ou 'Operacional'

    # Classificação de reporte em P2
    apenas_monitoramento_p2 = db.Column(db.Boolean, default=False)     # True para DQO e Sólidos Suspensos (Informativo)
    observacao_normativa = db.Column(db.Text, nullable=True)

    def avaliar_p2(self, valor_medido: float, eficiencia_pct: float = None) -> dict:
        """
        Avalia o resultado medido na saída da ETE (P2) contra os limites legais vigentes.

        Por que existe:
        - Aplica automaticamente a regra jurídica de prevalência da norma mais restritiva
          quando existem limites concorrentes no âmbito Federal (CONAMA 430) e Estadual (Decreto 8.468).

        O que faz:
        1. Identifica se o parâmetro é puramente informativo (ex: DQO e SST não possuem limite de lançamento).
        2. Checa violações de limites mínimos e máximos para cada norma aplicável.
        3. Verifica requisitos de eficiência acoplados (ex: remoção mínima de 60% para DBO).
        4. Retorna um dicionário estruturado com o status ('Conforme', 'Não Conforme', 'Informativo'),
           as normas violadas e a mensagem textual explicativa para emissão de alertas.
        """
        if self.apenas_monitoramento_p2:
            return {
                "status_conformidade": "Informativo",
                "em_conformidade": None,
                "norma_violada": None,
                "alerta": None
            }

        if valor_medido is None:
            return {
                "status_conformidade": "Sem Dados",
                "em_conformidade": None,
                "norma_violada": None,
                "alerta": "Valor medido não informado no laudo."
            }

        violacoes = []
        detalhes = []

        # 1. Validação frente à Resolução CONAMA 430/2011
        atende_conama = True
        if self.limite_min_conama430 is not None and valor_medido < self.limite_min_conama430:
            atende_conama = False
            violacoes.append("CONAMA 430/2011")
            detalhes.append(f"abaixo do limite mínimo de {self.limite_min_conama430} {self.unidade} (CONAMA 430/2011)")
        if self.limite_max_conama430 is not None and valor_medido > self.limite_max_conama430:
            atende_conama = False
            violacoes.append("CONAMA 430/2011")
            detalhes.append(f"acima do limite máximo de {self.limite_max_conama430} {self.unidade} (CONAMA 430/2011 Art. 16)")
        if self.eficiencia_minima_pct is not None and eficiencia_pct is not None:
            if eficiencia_pct < self.eficiencia_minima_pct:
                atende_conama = False
                if "CONAMA 430/2011" not in violacoes:
                    violacoes.append("CONAMA 430/2011")
                detalhes.append(f"eficiência de remoção ({eficiencia_pct:.1f}%) inferior ao padrão mínimo de {self.eficiencia_minima_pct:.0f}% (CONAMA 430/2011)")

        # 2. Validação frente ao Decreto Estadual SP nº 8.468/1976
        atende_decreto = True
        if self.limite_min_decreto8468 is not None and valor_medido < self.limite_min_decreto8468:
            atende_decreto = False
            violacoes.append("Decreto Estadual 8.468/1976")
            detalhes.append(f"abaixo do limite mínimo de {self.limite_min_decreto8468} {self.unidade} (Decreto 8.468/1976)")
        if self.limite_max_decreto8468 is not None and valor_medido > self.limite_max_decreto8468:
            atende_decreto = False
            violacoes.append("Decreto Estadual 8.468/1976")
            if atende_conama and self.limite_max_conama430 is not None:
                # Caso de teste específico: atende a lei federal, mas viola a norma estadual mais restritiva
                detalhes.append(
                    f"atende ao limite federal da CONAMA 430/2011 (≤ {self.limite_max_conama430} {self.unidade}), "
                    f"mas ultrapassa o padrão mais restritivo do Decreto Estadual 8.468/1976 (≤ {self.limite_max_decreto8468} {self.unidade})"
                )
            else:
                detalhes.append(f"acima do limite máximo de {self.limite_max_decreto8468} {self.unidade} (Decreto Estadual 8.468/1976 Art. 18)")

        # Caso esteja em conformidade com todas as normas
        if not violacoes:
            return {
                "status_conformidade": "Conforme",
                "em_conformidade": True,
                "norma_violada": None,
                "alerta": None
            }

        # Em caso de não conformidade, compõe o alerta circunstanciado
        alerta_msg = f"{self.parametro} ({valor_medido} {self.unidade} em P2): " + "; ".join(detalhes) + "."
        return {
            "status_conformidade": "Não Conforme",
            "em_conformidade": False,
            "norma_violada": " e ".join(violacoes),
            "alerta": alerta_msg
        }

    def avaliar_eficiencia(self, valor_p1: float, valor_p2: float) -> dict:
        """
        Calcula a eficiência percentual de remoção de carga poluente pela ETE:
        Fórmula: Eficiência (%) = [(Concentração P1 - Concentração P2) / Concentração P1] * 100

        Por que existe:
        - Avalia o desempenho operacional da estação de tratamento e valida se o processo
          atinge as metas mínimas estipuladas por lei (ex: DBO5,20 ≥ 60%).

        O que faz:
        1. Valida se as concentrações de entrada (P1) e saída (P2) são válidas e positivas.
        2. Calcula a redução percentual utilizando precisão decimal ('ROUND_HALF_UP')
           para reproduzir o arredondamento técnico padrão de relatórios laboratoriais.
        3. Compara o resultado com a meta mínima exigida pelo parâmetro, classificando
           entre 'Conforme (≥ X%)', 'Não Conforme (< X%)' ou 'Operacional'.
        """
        if valor_p1 is None or valor_p2 is None or valor_p1 <= 0:
            return {
                "eficiencia_pct": None,
                "avaliacao": "Sem Dados",
                "atingiu_meta": None
            }

        bruto = ((valor_p1 - valor_p2) / valor_p1) * 100.0
        eficiencia = float(Decimal(str(bruto)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))

        if self.eficiencia_minima_pct is not None:
            atingiu = eficiencia >= self.eficiencia_minima_pct
            status = f"Conforme (≥ {int(self.eficiencia_minima_pct)}%)" if atingiu else f"Não Conforme (< {int(self.eficiencia_minima_pct)}%)"
            return {
                "eficiencia_pct": eficiencia,
                "avaliacao": status,
                "atingiu_meta": atingiu
            }

        return {
            "eficiencia_pct": eficiencia,
            "avaliacao": "Operacional",
            "atingiu_meta": True
        }

    @classmethod
    def buscar_por_nome(cls, nome_parametro: str):
        """
        Localiza a regra de um parâmetro químico no banco através de busca resiliente.

        Por que existe:
        - Permite associar dados de colunas do Excel ou tabelas de PDF aos limites legais
          mesmo quando os documentos trazem variações textuais (ex: 'DBO', 'DBO5,20',
          'Demanda Bioquímica de Oxigênio', 'Cr(VI)', 'Cromo Hexavalente').

        O que faz:
        - Normaliza o texto buscado e compara sequencialmente contra:
          1. O nome cadastrado do parâmetro.
          2. A fórmula ou símbolo químico.
          3. Cada sinônimo registrado na lista de termos equivalentes.
        """
        alvo = normalizar_texto(nome_parametro)
        if not alvo:
            return None

        todos = cls.query.all()
        for item in todos:
            if normalizar_texto(item.parametro) == alvo:
                return item
            if item.simbolo and normalizar_texto(item.simbolo) == alvo:
                return item
            if item.sinonimos:
                lista_sin = [normalizar_texto(s) for s in item.sinonimos.split("|")]
                if alvo in lista_sin:
                    return item
        return None

    def __repr__(self):
        return f"<LimiteLegal {self.parametro} ({self.unidade})>"


# Alias para preservar compatibilidade com referências legadas
ParametroNorma = LimiteLegal


class Laudo(db.Model):
    """
    Registro de Campanha Mensal de Monitoramento / Laudo Laboratorial.

    Por que existe:
    - Agrupa todas as medições de uma coleta em uma entidade histórica identificada
      (atendendo ao requisito de armazenamento do histórico no banco de dados).
    - Guarda metadados essenciais como laboratório emissor, data da coleta, mês/ano de referência,
      unidade fabril monitorada e o nome do arquivo original de importação.
    """
    __tablename__ = 'laudos'

    id = db.Column(db.Integer, primary_key=True)
    codigo_laudo = db.Column(db.String(100), unique=True, nullable=False)  # Ex: 'LAUDO-2026-001'
    unidade_monitorada = db.Column(db.String(150), nullable=True)          # Ex: 'Unidade Industrial — ETE'
    corpo_receptor = db.Column(db.String(150), nullable=True)              # Ex: 'Rio Piracicaba — Classe 2'
    campanha_mes = db.Column(db.String(20), nullable=False)                # Ex: '10/2026'
    data_coleta = db.Column(db.Date, nullable=False)
    laboratorio = db.Column(db.String(150), nullable=True)
    arquivo_origem = db.Column(db.String(255), nullable=True)              # Nome do arquivo Excel/PDF carregado
    observacoes = db.Column(db.Text, nullable=True)
    criado_em = db.Column(db.DateTime, default=datetime.utcnow)

    # Relacionamentos 1:N com exclusão em cascata (remover o laudo remove suas medições e eficiências)
    medicoes = db.relationship('ResultadoAnalise', backref='laudo', cascade='all, delete-orphan', lazy=True)
    eficiencias = db.relationship('EficienciaETE', backref='laudo', cascade='all, delete-orphan', lazy=True)

    def __repr__(self):
        return f"<Laudo {self.codigo_laudo} - {self.campanha_mes}>"


class ResultadoAnalise(db.Model):
    """
    Registro Individual de Medição Laboratorial (Tabela de Medições).

    Por que existe:
    - Armazena pontualmente o valor medido de cada substância química em determinado ponto
      de amostragem (P1 a P4) e o resultado da validação automática de conformidade.
    - Preserva tanto o valor float para computações quanto o valor em string original
      para registros com limite de detecção (ex: '< 0,01' ou 'Ausente').
    """
    __tablename__ = 'resultados_analise'

    id = db.Column(db.Integer, primary_key=True)
    laudo_id = db.Column(db.Integer, db.ForeignKey('laudos.id'), nullable=True)
    codigo_laudo = db.Column(db.String(100), nullable=False)
    data_coleta = db.Column(db.Date, nullable=False)
    ponto_coleta = db.Column(db.String(20), nullable=False)         # 'P1', 'P2', 'P3' ou 'P4'
    parametro_id = db.Column(db.Integer, db.ForeignKey('limites_legais.id'), nullable=True)
    parametro = db.Column(db.String(100), nullable=False)
    valor_medido = db.Column(db.Float, nullable=True)
    valor_texto = db.Column(db.String(50), nullable=True)           # Representação textual exata do laudo
    unidade = db.Column(db.String(30), nullable=False)

    # Resultados da avaliação automática de conformidade
    status_conformidade = db.Column(db.String(50), nullable=True)   # 'Conforme', 'Não Conforme', 'Informativo'
    em_conformidade = db.Column(db.Boolean, nullable=True)
    norma_violada = db.Column(db.String(150), nullable=True)        # Norma(s) infringida(s), se houver
    alerta = db.Column(db.Text, nullable=True)                      # Descrição detalhada do alerta emitido

    criado_em = db.Column(db.DateTime, default=datetime.utcnow)

    # Vínculo com os limites cadastrados na tabela mestra
    limite_ref = db.relationship('LimiteLegal', backref='medicoes', lazy=True)

    def __repr__(self):
        return f"<Medicao {self.codigo_laudo} [{self.ponto_coleta}] {self.parametro}: {self.valor_medido} {self.unidade} ({self.status_conformidade})>"


class EficienciaETE(db.Model):
    """
    Registro dos Cálculos de Eficiência de Remoção da Estação de Tratamento de Efluentes.

    Por que existe:
    - Permite comparar a carga de poluentes entre a entrada da ETE (P1 - Bruto)
      e a saída (P2 - Tratado) e consolidar os indicadores de desempenho exigidos
      pelas auditorias e órgãos ambientais (CETESB/CONAMA).
    """
    __tablename__ = 'eficiencias_ete'

    id = db.Column(db.Integer, primary_key=True)
    laudo_id = db.Column(db.Integer, db.ForeignKey('laudos.id'), nullable=True)
    codigo_laudo = db.Column(db.String(100), nullable=False)
    data_referencia = db.Column(db.Date, nullable=False)
    parametro = db.Column(db.String(100), nullable=False)           # Ex: 'DBO5,20', 'DQO', 'Sólidos Suspensos Totais'
    unidade = db.Column(db.String(30), nullable=False, default='mg/L')
    entrada_p1 = db.Column(db.Float, nullable=False)                # Concentração no Efluente Bruto
    saida_p2 = db.Column(db.Float, nullable=False)                  # Concentração no Efluente Tratado
    eficiencia_percentual = db.Column(db.Float, nullable=False)     # Percentual calculado: ((P1 - P2) / P1) * 100
    avaliacao = db.Column(db.String(50), nullable=False)            # Ex: 'Conforme (≥ 60%)', 'Operacional'
    atingiu_meta = db.Column(db.Boolean, nullable=True)

    criado_em = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<Eficiencia {self.parametro}: {self.eficiencia_percentual:.1f}% ({self.avaliacao})>"
