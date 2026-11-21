"""
Script de Inicialização e Carga Mestra (Seed) do Banco de Dados SQLite.

Por que existe:
- O banco de dados SQLite ('instance/monitoramento.db') não é versionado no Git.
  Este script permite que qualquer desenvolvedor ou ambiente de testes recrie
  instantaneamente toda a estrutura relacional e popule as tabelas mestras
  com dados normativos reais do projeto.
- Cadastra os 4 pontos de coleta oficiais (P1 a P4), as 3 legislações ambientais
  aplicáveis e os 21 parâmetros químicos/físico-químicos com seus limites legais
  e regras de eficiência.
"""
from app import app, db
from app.models import PontoColeta, Legislacao, LimiteLegal, Laudo, ResultadoAnalise, EficienciaETE


def obter_pontos_coleta():
    """
    Retorna a lista de pontos padronizados de amostragem (P1, P2, P3 e P4).
    Cada ponto contém sinônimos para viabilizar o parsing automático de cabeçalhos
    em arquivos Excel ou relatórios PDF.
    """
    return [
        PontoColeta(
            codigo="P1",
            nome="Efluente Bruto (Entrada ETE)",
            matriz="Efluente Líquido",
            finalidade="Referência de carga poluidora para cálculo de eficiência.",
            sinonimos="P1|Bruto|Bruto (P1)|Efluente Bruto|Entrada ETE|Entrada (P1)"
        ),
        PontoColeta(
            codigo="P2",
            nome="Efluente Tratado (Saída ETE)",
            matriz="Efluente Líquido",
            finalidade="Verificação direta de conformidade com limites de lançamento.",
            sinonimos="P2|Tratado|Tratado (P2)|Efluente Tratado|Saída ETE|Saida ETE|Saída (P2)"
        ),
        PontoColeta(
            codigo="P3",
            nome="Rio à Montante",
            matriz="Água Superficial",
            finalidade="Condição natural do rio antes do ponto de lançamento.",
            sinonimos="P3|Montante|Montante (P3)|Rio à Montante|Rio a Montante|Rio Montante"
        ),
        PontoColeta(
            codigo="P4",
            nome="Rio à Jusante",
            matriz="Água Superficial",
            finalidade="Avaliação de possível contribuição ou impacto da ETE.",
            sinonimos="P4|Jusante|Jusante (P4)|Rio à Jusante|Rio a Jusante|Rio Jusante"
        ),
    ]


def obter_legislacoes():
    """
    Retorna o catálogo de legislações ambientais de referência utilizadas para
    fundamentar os pareceres técnicos e alertas de não conformidade emitidos pelo sistema.
    """
    return [
        Legislacao(
            codigo="CONAMA_430_2011",
            nome="Resolução CONAMA nº 430/2011",
            esfera="Federal",
            artigo_referencia="Art. 16",
            aplicacao="Efluente Tratado (P2) e Eficiência da ETE",
            descricao="Dispõe sobre as condições e padrões de lançamento de efluentes em corpos de água receptores."
        ),
        Legislacao(
            codigo="DECRETO_SP_8468_1976",
            nome="Decreto Estadual SP nº 8.468/1976",
            esfera="Estadual (SP)",
            artigo_referencia="Art. 18",
            aplicacao="Efluente Tratado (P2) e Corpo Receptor",
            descricao="Regulamenta a prevenção e o controle da poluição do meio ambiente no Estado de São Paulo."
        ),
        Legislacao(
            codigo="CONAMA_357_2005",
            nome="Resolução CONAMA nº 357/2005",
            esfera="Federal",
            artigo_referencia="Classe 2",
            aplicacao="Corpo Receptor — Rio Piracicaba (P3 e P4)",
            descricao="Dispõe sobre a classificação dos corpos de água e diretrizes ambientais para o seu enquadramento."
        ),
    ]


def obter_limites_legais():
    """
    Retorna todos os 21 parâmetros químicos e físico-químicos mapeados nos documentos
    do projeto (Tabela 2: Efluentes P1/P2, Tabela 3: Rio P3/P4 e Tabela 4: Eficiência da ETE).
    """
    return [
        # 1. pH
        LimiteLegal(
            parametro="pH",
            simbolo="pH",
            sinonimos="pH|Potencial Hidrogeniônico|Potencial Hidrogenionico",
            categoria="Físico-Químico",
            unidade="u.pH",
            limite_min_conama430=5.0,
            limite_max_conama430=9.0,
            texto_conama430="5,0 a 9,0",
            limite_min_decreto8468=5.0,
            limite_max_decreto8468=9.0,
            texto_decreto8468="5,0 a 9,0",
            limite_min_restritivo=5.0,
            limite_max_restritivo=9.0,
            norma_mais_restritiva="CONAMA 430/2011 e Decreto 8.468/1976",
            monitorado_no_rio=True,
            limite_min_conama357=6.0,
            limite_max_conama357=9.0,
            texto_conama357="6,0 a 9,0",
            calcula_eficiencia=False,
            apenas_monitoramento_p2=False,
            observacao_normativa="Faixa de pH permitida entre 5,0 e 9,0 para efluentes e entre 6,0 e 9,0 para rios Classe 2."
        ),
        # 2. Temperatura
        LimiteLegal(
            parametro="Temperatura",
            simbolo="T",
            sinonimos="Temperatura|Temp|Temperatura da Amostra",
            categoria="Físico-Químico",
            unidade="°C",
            limite_max_conama430=40.0,
            texto_conama430="< 40,0",
            limite_max_decreto8468=40.0,
            texto_decreto8468="< 40,0",
            limite_max_restritivo=40.0,
            norma_mais_restritiva="CONAMA 430/2011 e Decreto 8.468/1976",
            monitorado_no_rio=True,
            texto_conama357="Variação < 3°C",
            calcula_eficiencia=False,
            apenas_monitoramento_p2=False,
            observacao_normativa="Inferior a 40°C no lançamento, não devendo exceder variação de 3°C na zona de mistura do rio."
        ),
        # 3. Materiais Sedimentáveis
        LimiteLegal(
            parametro="Materiais Sedimentáveis",
            simbolo="MSed",
            sinonimos="Materiais Sedimentáveis|Materiais Sedimentaveis|Sólidos Sedimentáveis|Solidos Sedimentaveis",
            categoria="Sólidos",
            unidade="mL/L",
            limite_max_conama430=1.0,
            texto_conama430="≤ 1,0",
            limite_max_decreto8468=1.0,
            texto_decreto8468="≤ 1,0",
            limite_max_restritivo=1.0,
            norma_mais_restritiva="CONAMA 430/2011 e Decreto 8.468/1976",
            monitorado_no_rio=False,
            calcula_eficiencia=False,
            apenas_monitoramento_p2=False,
            observacao_normativa="Até 1,0 mL/L em teste de 1 hora em cone Imhoff."
        ),
        # 4. DBO5,20
        LimiteLegal(
            parametro="DBO5,20",
            simbolo="DBO",
            sinonimos="DBO5,20|DBO 5,20|DBO|DBO5|Demanda Bioquímica de Oxigênio|Demanda Bioquimica de Oxigenio|DBO5,20 (mg/L)",
            categoria="Matéria Orgânica",
            unidade="mg/L",
            texto_conama430="Remoção ≥ 60%",
            limite_max_decreto8468=60.0,
            texto_decreto8468="≤ 60,0",
            limite_max_restritivo=60.0,
            norma_mais_restritiva="Decreto 8.468/1976 (≤ 60,0 mg/L) e CONAMA 430/2011 (Remoção ≥ 60%)",
            monitorado_no_rio=True,
            limite_max_conama357=5.0,
            texto_conama357="≤ 5,0",
            calcula_eficiencia=True,
            eficiencia_minima_pct=60.0,
            tipo_avaliacao_eficiencia="Conformidade Legal",
            apenas_monitoramento_p2=False,
            observacao_normativa="Exige concentração ≤ 60,0 mg/L pelo Decreto 8.468/1976 e eficiência mínima de remoção de 60% pela CONAMA 430/2011."
        ),
        # 5. DQO
        LimiteLegal(
            parametro="DQO",
            simbolo="DQO",
            sinonimos="DQO|Demanda Química de Oxigênio|Demanda Quimica de Oxigenio|DQO (mg/L)",
            categoria="Matéria Orgânica",
            unidade="mg/L",
            texto_conama430="Monitoramento",
            texto_decreto8468="Monitoramento",
            norma_mais_restritiva="Monitoramento Operacional",
            monitorado_no_rio=False,
            calcula_eficiencia=True,
            eficiencia_minima_pct=None,
            tipo_avaliacao_eficiencia="Operacional",
            apenas_monitoramento_p2=True,
            observacao_normativa="Parâmetro informativo para acompanhamento de carga orgânica e eficiência operacional da ETE."
        ),
        # 6. Sólidos Suspensos Totais
        LimiteLegal(
            parametro="Sólidos Suspensos Totais",
            simbolo="SST",
            sinonimos="Sólidos Suspensos Totais|Solidos Suspensos Totais|SST|Sólidos em Suspensão Totais|Sólidos Suspensos Totais (mg/L)",
            categoria="Sólidos",
            unidade="mg/L",
            texto_conama430="Monitoramento",
            texto_decreto8468="Monitoramento",
            norma_mais_restritiva="Monitoramento Operacional",
            monitorado_no_rio=False,
            calcula_eficiencia=True,
            eficiencia_minima_pct=None,
            tipo_avaliacao_eficiencia="Operacional",
            apenas_monitoramento_p2=True,
            observacao_normativa="Parâmetro informativo para acompanhamento da retenção de sólidos e eficiência operacional da ETE."
        ),
        # 7. Óleos e Graxas (Minerais)
        LimiteLegal(
            parametro="Óleos e Graxas (Minerais)",
            simbolo="O&G",
            sinonimos="Óleos e Graxas (Minerais)|Oleos e Graxas (Minerais)|Óleos e Graxas|Oleos e Graxas|Óleos Minerais",
            categoria="Óleos e Graxas",
            unidade="mg/L",
            limite_max_conama430=20.0,
            texto_conama430="≤ 20,0",
            limite_max_decreto8468=100.0,
            texto_decreto8468="≤ 100,0*",
            limite_max_restritivo=20.0,
            norma_mais_restritiva="CONAMA 430/2011",
            monitorado_no_rio=False,
            texto_conama357="Virtualmente ausentes",
            calcula_eficiencia=False,
            apenas_monitoramento_p2=False,
            observacao_normativa="No Decreto Estadual nº 8.468/1976 (Art. 18, inciso IV), o limite refere-se a Substâncias Solúveis em Hexano (até 100 mg/L). Na CONAMA nº 430/2011, óleos minerais têm limite de 20 mg/L (mais restritivo)."
        ),
        # 8. Nitrogênio Amoniacal Total
        LimiteLegal(
            parametro="Nitrogênio Amoniacal Total",
            simbolo="N-NH3",
            sinonimos="Nitrogênio Amoniacal Total|Nitrogenio Amoniacal Total|Nitrogênio Amoniacal|Nitrogenio Amoniacal|N-Amoniacal",
            categoria="Nutrientes",
            unidade="mg/L",
            limite_max_conama430=20.0,
            texto_conama430="≤ 20,0",
            limite_max_decreto8468=None,
            texto_decreto8468="Não aplicável",
            limite_max_restritivo=20.0,
            norma_mais_restritiva="CONAMA 430/2011",
            monitorado_no_rio=True,
            limite_max_conama357=3.7,
            texto_conama357="≤ 3,7 (pH ≤ 7,5)",
            calcula_eficiencia=False,
            apenas_monitoramento_p2=False,
            observacao_normativa="Limite máximo de 20,0 mg/L pela CONAMA 430/2011 (Art. 16). Monitorado também no rio (Montante vs Jusante) para investigação de impacto."
        ),
        # 9. Ferro Dissolvido (Fe)
        LimiteLegal(
            parametro="Ferro Dissolvido (Fe)",
            simbolo="Fe",
            sinonimos="Ferro Dissolvido (Fe)|Ferro Dissolvido|Ferro",
            categoria="Metais",
            unidade="mg/L",
            limite_max_conama430=15.0,
            texto_conama430="≤ 15,0",
            limite_max_decreto8468=15.0,
            texto_decreto8468="≤ 15,0",
            limite_max_restritivo=15.0,
            norma_mais_restritiva="CONAMA 430/2011 e Decreto 8.468/1976",
            monitorado_no_rio=True,
            limite_max_conama357=0.30,
            texto_conama357="≤ 0,30",
            calcula_eficiencia=False,
            apenas_monitoramento_p2=False,
            observacao_normativa="Limite de 15,0 mg/L para efluente tratado e 0,30 mg/L para rio Classe 2 (CONAMA 357/2005)."
        ),
        # 10. Manganês Dissolvido (Mn)
        LimiteLegal(
            parametro="Manganês Dissolvido (Mn)",
            simbolo="Mn",
            sinonimos="Manganês Dissolvido (Mn)|Manganes Dissolvido (Mn)|Manganês Dissolvido|Manganes Dissolvido|Manganês",
            categoria="Metais",
            unidade="mg/L",
            limite_max_conama430=1.0,
            texto_conama430="≤ 1,0",
            limite_max_decreto8468=1.0,
            texto_decreto8468="≤ 1,0",
            limite_max_restritivo=1.0,
            norma_mais_restritiva="CONAMA 430/2011 e Decreto 8.468/1976",
            monitorado_no_rio=False,
            limite_max_conama357=0.10,
            texto_conama357="≤ 0,10",
            calcula_eficiencia=False,
            apenas_monitoramento_p2=False,
            observacao_normativa="Limite máximo de 1,0 mg/L em ambas as legislações."
        ),
        # 11. Cobre Dissolvido (Cu)
        LimiteLegal(
            parametro="Cobre Dissolvido (Cu)",
            simbolo="Cu",
            sinonimos="Cobre Dissolvido (Cu)|Cobre Dissolvido|Cobre",
            categoria="Metais",
            unidade="mg/L",
            limite_max_conama430=1.0,
            texto_conama430="≤ 1,0",
            limite_max_decreto8468=1.0,
            texto_decreto8468="≤ 1,0",
            limite_max_restritivo=1.0,
            norma_mais_restritiva="CONAMA 430/2011 e Decreto 8.468/1976",
            monitorado_no_rio=False,
            limite_max_conama357=0.009,
            texto_conama357="≤ 0,009",
            calcula_eficiencia=False,
            apenas_monitoramento_p2=False,
            observacao_normativa="Limite máximo de 1,0 mg/L em ambas as legislações."
        ),
        # 12. Zinco Total (Zn)
        LimiteLegal(
            parametro="Zinco Total (Zn)",
            simbolo="Zn",
            sinonimos="Zinco Total (Zn)|Zinco Total|Zinco",
            categoria="Metais",
            unidade="mg/L",
            limite_max_conama430=5.0,
            texto_conama430="≤ 5,0",
            limite_max_decreto8468=5.0,
            texto_decreto8468="≤ 5,0",
            limite_max_restritivo=5.0,
            norma_mais_restritiva="CONAMA 430/2011 e Decreto 8.468/1976",
            monitorado_no_rio=True,
            limite_max_conama357=0.18,
            texto_conama357="≤ 0,18",
            calcula_eficiencia=False,
            apenas_monitoramento_p2=False,
            observacao_normativa="Limite de 5,0 mg/L no efluente tratado e 0,18 mg/L no corpo receptor Classe 2."
        ),
        # 13. Cromo Hexavalente (Cr6+)
        LimiteLegal(
            parametro="Cromo Hexavalente (Cr6+)",
            simbolo="Cr6+",
            sinonimos="Cromo Hexavalente (Cr6+)|Cromo Hexavalente (Cr⁶⁺)|Cromo Hexavalente|Cr6+|Cr⁶⁺",
            categoria="Metais",
            unidade="mg/L",
            limite_max_conama430=0.10,
            texto_conama430="≤ 0,10",
            limite_max_decreto8468=0.10,
            texto_decreto8468="≤ 0,10",
            limite_max_restritivo=0.10,
            norma_mais_restritiva="CONAMA 430/2011 e Decreto 8.468/1976",
            monitorado_no_rio=False,
            limite_max_conama357=0.05,
            texto_conama357="≤ 0,05 (Cr Total)",
            calcula_eficiencia=False,
            apenas_monitoramento_p2=False,
            observacao_normativa="Limite máximo de 0,10 mg/L em ambas as legislações."
        ),
        # 14. Chumbo Total (Pb)
        LimiteLegal(
            parametro="Chumbo Total (Pb)",
            simbolo="Pb",
            sinonimos="Chumbo Total (Pb)|Chumbo Total|Chumbo",
            categoria="Metais",
            unidade="mg/L",
            limite_max_conama430=0.50,
            texto_conama430="≤ 0,50",
            limite_max_decreto8468=0.50,
            texto_decreto8468="≤ 0,50",
            limite_max_restritivo=0.50,
            norma_mais_restritiva="CONAMA 430/2011 e Decreto 8.468/1976",
            monitorado_no_rio=False,
            limite_max_conama357=0.01,
            texto_conama357="≤ 0,01",
            calcula_eficiencia=False,
            apenas_monitoramento_p2=False,
            observacao_normativa="Limite máximo de 0,50 mg/L em ambas as legislações."
        ),
        # 15. Níquel Total (Ni)
        LimiteLegal(
            parametro="Níquel Total (Ni)",
            simbolo="Ni",
            sinonimos="Níquel Total (Ni)|Niquel Total (Ni)|Níquel Total|Niquel Total|Níquel",
            categoria="Metais",
            unidade="mg/L",
            limite_max_conama430=2.0,
            texto_conama430="≤ 2,0",
            limite_max_decreto8468=2.0,
            texto_decreto8468="≤ 2,0",
            limite_max_restritivo=2.0,
            norma_mais_restritiva="CONAMA 430/2011 e Decreto 8.468/1976",
            monitorado_no_rio=False,
            limite_max_conama357=0.025,
            texto_conama357="≤ 0,025",
            calcula_eficiencia=False,
            apenas_monitoramento_p2=False,
            observacao_normativa="Limite máximo de 2,0 mg/L em ambas as legislações."
        ),
        # 16. Fluoreto Total (F-)
        LimiteLegal(
            parametro="Fluoreto Total (F-)",
            simbolo="F-",
            sinonimos="Fluoreto Total (F-)|Fluoreto Total (F⁻)|Fluoreto Total|Fluoreto|Fluoretos",
            categoria="Inorgânicos",
            unidade="mg/L",
            limite_max_conama430=10.0,
            texto_conama430="≤ 10,0",
            limite_max_decreto8468=10.0,
            texto_decreto8468="≤ 10,0",
            limite_max_restritivo=10.0,
            norma_mais_restritiva="CONAMA 430/2011 e Decreto 8.468/1976",
            monitorado_no_rio=False,
            limite_max_conama357=1.4,
            texto_conama357="≤ 1,4",
            calcula_eficiencia=False,
            apenas_monitoramento_p2=False,
            observacao_normativa="Limite máximo de 10,0 mg/L em ambas as legislações."
        ),
        # 17. Fenóis Totais
        LimiteLegal(
            parametro="Fenóis Totais",
            simbolo="Fenóis",
            sinonimos="Fenóis Totais|Fenois Totais|Fenóis|Fenois|Índice de Fenóis",
            categoria="Orgânicos Tóxicos",
            unidade="mg/L",
            limite_max_conama430=0.50,
            texto_conama430="≤ 0,50",
            limite_max_decreto8468=0.50,
            texto_decreto8468="≤ 0,50",
            limite_max_restritivo=0.50,
            norma_mais_restritiva="CONAMA 430/2011 e Decreto 8.468/1976",
            monitorado_no_rio=False,
            limite_max_conama357=0.003,
            texto_conama357="≤ 0,003",
            calcula_eficiencia=False,
            apenas_monitoramento_p2=False,
            observacao_normativa="Substâncias que reagem com 4-aminoantipirina: limite máximo de 0,50 mg/L."
        ),
        # 18. Cianeto Total (CN-)
        LimiteLegal(
            parametro="Cianeto Total (CN-)",
            simbolo="CN-",
            sinonimos="Cianeto Total (CN-)|Cianeto Total (CN⁻)|Cianeto Total|Cianeto|CN-",
            categoria="Inorgânicos Tóxicos",
            unidade="mg/L",
            limite_max_conama430=1.00,
            texto_conama430="≤ 1,00",
            limite_max_decreto8468=0.20,
            texto_decreto8468="≤ 0,20",
            limite_max_restritivo=0.20,
            norma_mais_restritiva="Decreto Estadual 8.468/1976",
            monitorado_no_rio=True,
            limite_max_conama357=0.005,
            texto_conama357="≤ 0,005 (CN Livre)",
            calcula_eficiencia=False,
            apenas_monitoramento_p2=False,
            observacao_normativa="Prevalece o padrão mais restritivo do Decreto Estadual nº 8.468/1976 (≤ 0,20 mg/L) sobre a CONAMA nº 430/2011 (≤ 1,00 mg/L)."
        ),
        # 19. Mercúrio Total (Hg)
        LimiteLegal(
            parametro="Mercúrio Total (Hg)",
            simbolo="Hg",
            sinonimos="Mercúrio Total (Hg)|Mercurio Total (Hg)|Mercúrio Total|Mercurio Total|Mercúrio",
            categoria="Metais",
            unidade="mg/L",
            limite_max_conama430=0.010,
            texto_conama430="≤ 0,010",
            limite_max_decreto8468=0.010,
            texto_decreto8468="≤ 0,010",
            limite_max_restritivo=0.010,
            norma_mais_restritiva="CONAMA 430/2011 e Decreto 8.468/1976",
            monitorado_no_rio=False,
            limite_max_conama357=0.0002,
            texto_conama357="≤ 0,0002",
            calcula_eficiencia=False,
            apenas_monitoramento_p2=False,
            observacao_normativa="Limite máximo de 0,010 mg/L em ambas as legislações."
        ),
        # 20. Oxigênio Dissolvido (OD) - Específico Corpo Receptor (P3 e P4)
        LimiteLegal(
            parametro="Oxigênio Dissolvido (OD)",
            simbolo="OD",
            sinonimos="Oxigênio Dissolvido (OD)|Oxigenio Dissolvido (OD)|Oxigênio Dissolvido|Oxigenio Dissolvido|OD",
            categoria="Físico-Químico (Corpo Receptor)",
            unidade="mg/L",
            texto_conama430="Não aplicável",
            texto_decreto8468="Não aplicável",
            norma_mais_restritiva="CONAMA 357/2005 (Corpo Receptor)",
            monitorado_no_rio=True,
            limite_min_conama357=5.0,
            texto_conama357="≥ 5,0",
            calcula_eficiencia=False,
            apenas_monitoramento_p2=True,
            observacao_normativa="Em qualquer amostra no corpo receptor (Classe 2), o Oxigênio Dissolvido não deve ser inferior a 5,0 mg/L (CONAMA 357/2005)."
        ),
        # 21. Fósforo Total - Específico Corpo Receptor (P3 e P4)
        LimiteLegal(
            parametro="Fósforo Total",
            simbolo="P",
            sinonimos="Fósforo Total|Fosforo Total|Fósforo|Fosforo|P Total",
            categoria="Nutrientes (Corpo Receptor)",
            unidade="mg/L",
            texto_conama430="Não aplicável",
            texto_decreto8468="Não aplicável",
            norma_mais_restritiva="CONAMA 357/2005 (Corpo Receptor)",
            monitorado_no_rio=True,
            limite_max_conama357=0.10,
            texto_conama357="≤ 0,10 (Ambiente Lótico)",
            calcula_eficiencia=False,
            apenas_monitoramento_p2=True,
            observacao_normativa="Monitorado no corpo receptor (Montante P3 vs Jusante P4) para avaliar aporte de nutrientes e risco de eutrofização."
        ),
    ]


def inicializar_banco(recriar=True):
    """
    Executa o provisionamento das tabelas e a inserção dos dados mestres na base SQLite.

    Parâmetros:
    - recriar (bool): Se True, descarta tabelas existentes (db.drop_all) e recria
      a estrutura do zero, garantindo um estado limpo e consistente para testes.
    """
    with app.app_context():
        if recriar:
            db.drop_all()
        db.create_all()

        # 1. Popula Pontos de Coleta (P1 a P4)
        if PontoColeta.query.count() == 0:
            pontos = obter_pontos_coleta()
            db.session.add_all(pontos)
            print(f"[OK] {len(pontos)} pontos de coleta padronizados (P1 a P4) cadastrados.")

        # 2. Popula Legislações Ambientais
        if Legislacao.query.count() == 0:
            leis = obter_legislacoes()
            db.session.add_all(leis)
            print(f"[OK] {len(leis)} legislações ambientais cadastradas.")

        # 3. Popula Parâmetros Químicos e Limites Legais
        if LimiteLegal.query.count() == 0:
            limites = obter_limites_legais()
            db.session.add_all(limites)
            print(f"[OK] {len(limites)} parâmetros químicos e limites legais cadastrados.")

        db.session.commit()
        print("\nBanco de dados populado e pronto como referência para leitura de laudos e emissão de relatórios!")


if __name__ == '__main__':
    inicializar_banco(recriar=True)
