import math
import re
import unicodedata
from decimal import Decimal, ROUND_HALF_UP
from app import db


def _numero_valido(valor) -> bool:
    """Retorna True apenas quando o valor e numerico finito (exclui None, NaN e Inf)."""
    if valor is None or isinstance(valor, bool):
        return False
    try:
        return math.isfinite(float(valor))
    except (TypeError, ValueError):
        return False


def normalizar_texto(texto: str) -> str:
    """
    Padroniza strings de parametros e rotulos para comparacao no banco.
    Converte subscritos (DBO5,20), sobrescritos (Cr6+), ions (CN-, F-),
    remove acentos, espacos extras e passa tudo para minusculo.
    """
    if texto is None or (isinstance(texto, float) and not math.isfinite(texto)):
        return ""
    texto_str = str(texto)
    if not texto_str.strip():
        return ""
    mapa_chars = str.maketrans({
        "₀": "0", "₁": "1", "₂": "2", "₃": "3", "₄": "4",
        "₅": "5", "₆": "6", "₇": "7", "₈": "8", "₉": "9",
        "⁰": "0", "¹": "1", "²": "2", "³": "3", "⁴": "4",
        "⁵": "5", "⁶": "6", "⁷": "7", "⁸": "8", "⁹": "9",
        "⁺": "+", "⁻": "-", "−": "-", "–": "-",
    })
    t = texto_str.translate(mapa_chars).strip().lower()
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

    @classmethod
    def montar_mapa_sinonimos(cls) -> dict:
        """Constroi um dicionario normalizado de sinonimos para os codigos P1 a P4."""
        mapa = {}
        for ponto in cls.query.all():
            cod = ponto.codigo.strip().upper()
            mapa[normalizar_texto(cod)] = cod
            mapa[normalizar_texto(ponto.nome)] = cod
            if ponto.sinonimos:
                for sin in ponto.sinonimos.split("|"):
                    sin_norm = normalizar_texto(sin)
                    if sin_norm:
                        mapa[sin_norm] = cod
        return mapa

    @classmethod
    def resolver_codigo(cls, texto_ponto: str, mapa_sinonimos: dict = None) -> str | None:
        """Resolve qualquer rotulo ou sinonimo de ponto de coleta para P1, P2, P3 ou P4."""
        t_norm = normalizar_texto(texto_ponto)
        if not t_norm or t_norm in ("nan", "none"):
            return None
        match_cod = re.search(r"(?<![a-z0-9])(?:p[-_\s]?|ponto[-_\s]*)([1-4])(?![a-z0-9])", t_norm)
        if match_cod:
            return f"P{match_cod.group(1)}"
        mapa = mapa_sinonimos if mapa_sinonimos is not None else cls.montar_mapa_sinonimos()
        if t_norm in mapa:
            return mapa[t_norm]
        if t_norm == "entrada":
            return "P1"
        if t_norm == "saida":
            return "P2"
        for sin_norm, cod in sorted(mapa.items(), key=lambda x: len(x[0]), reverse=True):
            if len(sin_norm) >= 4 and re.search(r"(?<![a-z0-9])" + re.escape(sin_norm) + r"(?![a-z0-9])", t_norm):
                return cod
        return None

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

        if not _numero_valido(valor_medido):
            return {
                "status_conformidade": "Sem Dados",
                "em_conformidade": None,
                "norma_violada": None,
                "alerta": "Valor medido não informado."
            }

        valor_medido = float(valor_medido)
        # Concentracoes fisicas negativas (sem limite minimo legal, exceto temperatura) sao dados invalidos
        if (
            valor_medido < 0
            and self.limite_min_conama430 is None
            and self.limite_min_decreto8468 is None
            and normalizar_texto(self.parametro) != "temperatura"
        ):
            return {
                "status_conformidade": "Sem Dados",
                "em_conformidade": None,
                "norma_violada": None,
                "alerta": f"Valor negativo inválido ({valor_medido} {self.unidade}) informado para {self.parametro}."
            }

        violacoes = []
        detalhes = []

        atende_conama = True
        if self.limite_min_conama430 is not None and valor_medido < self.limite_min_conama430:
            atende_conama = False
            violacoes.append("CONAMA 430/2011")
            detalhes.append(f"abaixo do mínimo de {self.limite_min_conama430} {self.unidade} (CONAMA 430/2011 Art. 16)")
        estrito_conama = (self.texto_conama430 or "").strip().startswith("<")
        if self.limite_max_conama430 is not None:
            excede_conama = valor_medido >= self.limite_max_conama430 if estrito_conama else valor_medido > self.limite_max_conama430
            if excede_conama:
                atende_conama = False
                if "CONAMA 430/2011" not in violacoes:
                    violacoes.append("CONAMA 430/2011")
                if estrito_conama:
                    detalhes.append(f"igual ou acima do limite de {self.limite_max_conama430} {self.unidade} (CONAMA 430/2011 Art. 16)")
                else:
                    detalhes.append(f"acima do limite máximo de {self.limite_max_conama430} {self.unidade} (CONAMA 430/2011 Art. 16)")
        if self.eficiencia_minima_pct is not None and _numero_valido(eficiencia_pct):
            ef_val = float(eficiencia_pct)
            if ef_val < self.eficiencia_minima_pct:
                atende_conama = False
                if "CONAMA 430/2011" not in violacoes:
                    violacoes.append("CONAMA 430/2011")
                detalhes.append(f"eficiência ({ef_val:.1f}%) abaixo do mínimo de {self.eficiencia_minima_pct:.0f}%")

        atende_decreto = True
        if self.limite_min_decreto8468 is not None and valor_medido < self.limite_min_decreto8468:
            atende_decreto = False
            violacoes.append("Decreto Estadual 8.468/1976")
            detalhes.append(f"abaixo do mínimo de {self.limite_min_decreto8468} {self.unidade} (Decreto 8.468/1976 Art. 18)")
        estrito_decreto = (self.texto_decreto8468 or "").strip().startswith("<")
        if self.limite_max_decreto8468 is not None:
            excede_decreto = valor_medido >= self.limite_max_decreto8468 if estrito_decreto else valor_medido > self.limite_max_decreto8468
            if excede_decreto:
                atende_decreto = False
                if "Decreto Estadual 8.468/1976" not in violacoes:
                    violacoes.append("Decreto Estadual 8.468/1976")
                if atende_conama and self.limite_max_conama430 is not None:
                    op_conama = "<" if estrito_conama else "<="
                    op_decreto = "<" if estrito_decreto else "<="
                    detalhes.append(
                        f"atende à federal CONAMA 430/2011 ({op_conama} {self.limite_max_conama430} {self.unidade}), "
                        f"mas ultrapassa o Decreto Estadual 8.468/1976 ({op_decreto} {self.limite_max_decreto8468} {self.unidade})"
                    )
                elif estrito_decreto:
                    detalhes.append(f"igual ou acima do limite de {self.limite_max_decreto8468} {self.unidade} (Decreto 8.468/1976 Art. 18)")
                else:
                    detalhes.append(f"acima do limite máximo de {self.limite_max_decreto8468} {self.unidade} (Decreto 8.468/1976 Art. 18)")

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

    @property
    def limite_max_estrito(self) -> bool:
        """Indica se o limite maximo restritivo e estritamente menor (<), como Temperatura < 40 C."""
        if self.limite_max_restritivo is None:
            return False
        estrito_c = (
            self.limite_max_conama430 == self.limite_max_restritivo
            and (self.texto_conama430 or "").strip().startswith("<")
        )
        estrito_d = (
            self.limite_max_decreto8468 == self.limite_max_restritivo
            and (self.texto_decreto8468 or "").strip().startswith("<")
        )
        return estrito_c or estrito_d

    def avaliar_eficiencia(self, valor_p1: float, valor_p2: float) -> dict:
        """
        Calcula a remocao percentual da ETE: ((P1 - P2) / P1) * 100.
        Usa arredondamento tecnico (ROUND_HALF_UP) e valida contra a meta do parametro.
        Rejeita concentracoes invalidas (P1 <= 0 ou P2 < 0).
        """
        if not _numero_valido(valor_p1) or not _numero_valido(valor_p2) or float(valor_p1) <= 0 or float(valor_p2) < 0:
            return {
                "eficiencia_pct": None,
                "avaliacao": "Sem Dados",
                "atingiu_meta": None
            }

        v1 = float(valor_p1)
        v2 = float(valor_p2)
        bruto = ((v1 - v2) / v1) * 100.0
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
            "atingiu_meta": None
        }

    @classmethod
    def montar_mapa_busca(cls) -> dict:
        """Constroi dicionario normalizado (nome, simbolo e sinonimos -> LimiteLegal) para buscas O(1)."""
        mapa = {}
        todos = cls.query.all()
        for item in todos:
            if item.sinonimos:
                for s in item.sinonimos.split("|"):
                    s_norm = normalizar_texto(s)
                    if s_norm:
                        mapa.setdefault(s_norm, item)
        for item in todos:
            if item.simbolo:
                simb_norm = normalizar_texto(item.simbolo)
                if simb_norm:
                    mapa[simb_norm] = item
        for item in todos:
            mapa[normalizar_texto(item.parametro)] = item
        return mapa

    @classmethod
    def buscar_por_nome(cls, nome_parametro: str, mapa_busca: dict = None):
        """
        Encontra o parametro no banco comparando o nome digitado,
        seu simbolo quimico ou sua lista de sinonimos.
        Aceita um mapa pre-carregado via montar_mapa_busca() para evitar consultas repetitivas.
        """
        alvo = normalizar_texto(nome_parametro)
        if not alvo:
            return None

        mapa = mapa_busca if mapa_busca is not None else cls.montar_mapa_busca()
        encontrado = mapa.get(alvo)
        if encontrado is not None:
            return encontrado

        # Fallback: remove sufixo de unidade entre parenteses (ex: 'Temperatura (°C)', 'Ferro Dissolvido (mg/L)')
        sem_unid = re.sub(r"\s*\((?:mg/l|ml/l|u\.?ph|°c|ºc|unt|%)\)\s*$", "", alvo).strip()
        if sem_unid and sem_unid != alvo:
            return mapa.get(sem_unid)
        return None

    def __repr__(self):
        return f"<LimiteLegal {self.parametro} ({self.unidade})>"


# Mantido por compatibilidade com scripts legados
ParametroNorma = LimiteLegal
