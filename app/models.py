import re
import unicodedata
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from app import db


def normalizar_texto(texto: str) -> str:
    """
    Padroniza strings de parametros e rotulos para comparacao no banco.
    Converte subscritos (DBO5,20), sobrescritos (Cr6+), ions (CN-, F-),
    remove acentos, espacos extras e passa tudo para minusculo.
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
    Pontos fixos de amostragem do monitoramento mensal:
    P1 (Bruto), P2 (Tratado), P3 (Montante) e P4 (Jusante).
    """
    __tablename__ = 'pontos_coleta'

    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(10), unique=True, nullable=False)
    nome = db.Column(db.String(100), nullable=False)
    matriz = db.Column(db.String(50), nullable=False)
    finalidade = db.Column(db.String(255), nullable=False)
    sinonimos = db.Column(db.String(255), nullable=True)

    def __repr__(self):
        return f"<PontoColeta {self.codigo}: {self.nome}>"


class Legislacao(db.Model):
    """
    Normas ambientais de referencia usadas nos laudos e relatorios
    (CONAMA 430/2011, Decreto SP 8.468/1976 e CONAMA 357/2005).
    """
    __tablename__ = 'legislacoes'

    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(50), unique=True, nullable=False)
    nome = db.Column(db.String(150), nullable=False)
    esfera = db.Column(db.String(50), nullable=False)
    artigo_referencia = db.Column(db.String(50), nullable=True)
    aplicacao = db.Column(db.String(100), nullable=False)
    descricao = db.Column(db.Text, nullable=True)

    def __repr__(self):
        return f"<Legislacao {self.nome}>"


class LimiteLegal(db.Model):
    """
    Cadastro de parametros fisico-quimicos com seus tetos legais no CONAMA 430,
    Decreto SP 8.468 e CONAMA 357 Classe 2, alem das metas de eficiencia da ETE.
    """
    __tablename__ = 'limites_legais'

    id = db.Column(db.Integer, primary_key=True)
    parametro = db.Column(db.String(100), unique=True, nullable=False)
    simbolo = db.Column(db.String(30), nullable=True)
    sinonimos = db.Column(db.Text, nullable=True)
    categoria = db.Column(db.String(60), nullable=True)
    unidade = db.Column(db.String(30), nullable=False)

    limite_min_conama430 = db.Column(db.Float, nullable=True)
    limite_max_conama430 = db.Column(db.Float, nullable=True)
    texto_conama430 = db.Column(db.String(60), nullable=True)

    limite_min_decreto8468 = db.Column(db.Float, nullable=True)
    limite_max_decreto8468 = db.Column(db.Float, nullable=True)
    texto_decreto8468 = db.Column(db.String(60), nullable=True)

    limite_min_restritivo = db.Column(db.Float, nullable=True)
    limite_max_restritivo = db.Column(db.Float, nullable=True)
    norma_mais_restritiva = db.Column(db.String(100), nullable=True)

    monitorado_no_rio = db.Column(db.Boolean, default=False)
    limite_min_conama357 = db.Column(db.Float, nullable=True)
    limite_max_conama357 = db.Column(db.Float, nullable=True)
    texto_conama357 = db.Column(db.String(60), nullable=True)

    calcula_eficiencia = db.Column(db.Boolean, default=False)
    eficiencia_minima_pct = db.Column(db.Float, nullable=True)
    tipo_avaliacao_eficiencia = db.Column(db.String(50), nullable=True)

    apenas_monitoramento_p2 = db.Column(db.Boolean, default=False)
    observacao_normativa = db.Column(db.Text, nullable=True)

    def avaliar_p2(self, valor_medido: float, eficiencia_pct: float = None) -> dict:
        """
        Avalia o valor medido na saida da ETE contra o CONAMA 430 e o Decreto 8.468.
        Quando as normas divergem para o mesmo parametro, prevalece o limite mais rigoroso.
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
                "alerta": "Valor medido nao informado."
            }

        violacoes = []
        detalhes = []

        atende_conama = True
        if self.limite_min_conama430 is not None and valor_medido < self.limite_min_conama430:
            atende_conama = False
            violacoes.append("CONAMA 430/2011")
            detalhes.append(f"abaixo do minimo de {self.limite_min_conama430} {self.unidade}")
        if self.limite_max_conama430 is not None and valor_medido > self.limite_max_conama430:
            atende_conama = False
            violacoes.append("CONAMA 430/2011")
            detalhes.append(f"acima do limite maximo de {self.limite_max_conama430} {self.unidade} (CONAMA 430/2011 Art. 16)")
        if self.eficiencia_minima_pct is not None and eficiencia_pct is not None:
            if eficiencia_pct < self.eficiencia_minima_pct:
                atende_conama = False
                if "CONAMA 430/2011" not in violacoes:
                    violacoes.append("CONAMA 430/2011")
                detalhes.append(f"eficiencia ({eficiencia_pct:.1f}%) abaixo do minimo de {self.eficiencia_minima_pct:.0f}%")

        atende_decreto = True
        if self.limite_min_decreto8468 is not None and valor_medido < self.limite_min_decreto8468:
            atende_decreto = False
            violacoes.append("Decreto Estadual 8.468/1976")
            detalhes.append(f"abaixo do minimo de {self.limite_min_decreto8468} {self.unidade}")
        if self.limite_max_decreto8468 is not None and valor_medido > self.limite_max_decreto8468:
            atende_decreto = False
            violacoes.append("Decreto Estadual 8.468/1976")
            if atende_conama and self.limite_max_conama430 is not None:
                detalhes.append(
                    f"atende a federal CONAMA 430/2011 (<= {self.limite_max_conama430} {self.unidade}), "
                    f"mas ultrapassa o Decreto Estadual 8.468/1976 (<= {self.limite_max_decreto8468} {self.unidade})"
                )
            else:
                detalhes.append(f"acima do limite maximo de {self.limite_max_decreto8468} {self.unidade} (Decreto 8.468/1976 Art. 18)")

        if not violacoes:
            return {
                "status_conformidade": "Conforme",
                "em_conformidade": True,
                "norma_violada": None,
                "alerta": None
            }

        alerta_msg = f"{self.parametro} ({valor_medido} {self.unidade} em P2): " + "; ".join(detalhes) + "."
        return {
            "status_conformidade": "Não Conforme",
            "em_conformidade": False,
            "norma_violada": " e ".join(violacoes),
            "alerta": alerta_msg
        }

    def avaliar_eficiencia(self, valor_p1: float, valor_p2: float) -> dict:
        """
        Calcula a remocao percentual da ETE: ((P1 - P2) / P1) * 100.
        Usa arredondamento tecnico (ROUND_HALF_UP) e valida contra a meta do parametro.
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
        Encontra o parametro no banco comparando o nome digitado,
        seu simbolo quimico ou sua lista de sinonimos.
        """
        alvo = normalizar_texto(nome_parametro)
        if not alvo:
            return None

        for item in cls.query.all():
            if normalizar_texto(item.parametro) == alvo:
                return item
            if item.simbolo and normalizar_texto(item.simbolo) == alvo:
                return item
            if item.sinonimos:
                sinonimos_lista = [normalizar_texto(s) for s in item.sinonimos.split("|")]
                if alvo in sinonimos_lista:
                    return item
        return None

    def __repr__(self):
        return f"<LimiteLegal {self.parametro} ({self.unidade})>"


# Mantido por compatibilidade com scripts legados
ParametroNorma = LimiteLegal


class Laudo(db.Model):
    """
    Agrupa as medicoes de uma campanha mensal em um unico registro historico.
    """
    __tablename__ = 'laudos'

    id = db.Column(db.Integer, primary_key=True)
    codigo_laudo = db.Column(db.String(100), unique=True, nullable=False)
    unidade_monitorada = db.Column(db.String(150), nullable=True)
    corpo_receptor = db.Column(db.String(150), nullable=True)
    campanha_mes = db.Column(db.String(20), nullable=False)
    data_coleta = db.Column(db.Date, nullable=False)
    laboratorio = db.Column(db.String(150), nullable=True)
    arquivo_origem = db.Column(db.String(255), nullable=True)
    observacoes = db.Column(db.Text, nullable=True)
    criado_em = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # Se o laudo for apagado, remove em cascata suas medicoes e eficiencias
    medicoes = db.relationship('ResultadoAnalise', backref='laudo', cascade='all, delete-orphan', lazy=True)
    eficiencias = db.relationship('EficienciaETE', backref='laudo', cascade='all, delete-orphan', lazy=True)

    def __repr__(self):
        return f"<Laudo {self.codigo_laudo} - {self.campanha_mes}>"


class ResultadoAnalise(db.Model):
    """
    Guarda uma medicao individual de um parametro em um ponto de coleta (P1 a P4).
    """
    __tablename__ = 'resultados_analise'

    id = db.Column(db.Integer, primary_key=True)
    laudo_id = db.Column(db.Integer, db.ForeignKey('laudos.id'), nullable=True)
    codigo_laudo = db.Column(db.String(100), nullable=False)
    data_coleta = db.Column(db.Date, nullable=False)
    ponto_coleta = db.Column(db.String(20), nullable=False)
    parametro_id = db.Column(db.Integer, db.ForeignKey('limites_legais.id'), nullable=True)
    parametro = db.Column(db.String(100), nullable=False)
    valor_medido = db.Column(db.Float, nullable=True)
    valor_texto = db.Column(db.String(50), nullable=True)
    unidade = db.Column(db.String(30), nullable=False)

    status_conformidade = db.Column(db.String(50), nullable=True)
    em_conformidade = db.Column(db.Boolean, nullable=True)
    norma_violada = db.Column(db.String(150), nullable=True)
    alerta = db.Column(db.Text, nullable=True)

    criado_em = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    limite_ref = db.relationship('LimiteLegal', backref='medicoes', lazy=True)

    def __repr__(self):
        return f"<Medicao {self.codigo_laudo} [{self.ponto_coleta}] {self.parametro}: {self.valor_medido} {self.unidade}>"


class EficienciaETE(db.Model):
    """
    Registra as taxas de remocao calculadas entre a entrada (P1) e a saida (P2) da ETE.
    """
    __tablename__ = 'eficiencias_ete'

    id = db.Column(db.Integer, primary_key=True)
    laudo_id = db.Column(db.Integer, db.ForeignKey('laudos.id'), nullable=True)
    codigo_laudo = db.Column(db.String(100), nullable=False)
    data_referencia = db.Column(db.Date, nullable=False)
    parametro = db.Column(db.String(100), nullable=False)
    unidade = db.Column(db.String(30), nullable=False, default='mg/L')
    entrada_p1 = db.Column(db.Float, nullable=False)
    saida_p2 = db.Column(db.Float, nullable=False)
    eficiencia_percentual = db.Column(db.Float, nullable=False)
    avaliacao = db.Column(db.String(50), nullable=False)
    atingiu_meta = db.Column(db.Boolean, nullable=True)

    criado_em = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def __repr__(self):
        return f"<Eficiencia {self.parametro}: {self.eficiencia_percentual:.1f}% ({self.avaliacao})>"
