# Instruções de Desenvolvimento - Monitoramento de Efluentes ETE Evonik

Documento de referência técnica, arquitetura e diretrizes de desenvolvimento para o projeto do Hackathon Evonik + ETEC: "Automação da avaliação de efluentes e impacto no corpo receptor (Rio Piracicaba)".

---

## 1. Visão Geral e Objetivo

O objetivo do sistema é substituir o processo manual de conferência de laudos ambientais por uma solução automatizada, confiável e auditável. O sistema processa os resultados laboratoriais das campanhas mensais de monitoramento da ETE Industrial (Unidade Americana/SP) e avalia o impacto do lançamento no corpo receptor (Rio Piracicaba, Classe 2).

### Amostras Monitoradas
- **P1 (Efluente Bruto):** Entrada da Estação de Tratamento de Esgotos/Efluentes.
- **P2 (Efluente Tratado):** Ponto de lançamento após tratamento na ETE.
- **P3 (Rio à Montante):** Ponto de referência no Rio Piracicaba antes do descarte da ETE.
- **P4 (Rio à Jusante):** Ponto de monitoramento no Rio Piracicaba após a mistura do efluente.

---

## 2. Stack Tecnológico e Dependências

- **Linguagem:** Python 3.14
- **Framework Web:** Flask (rotas modulares em `app/routes.py`)
- **ORM e Banco de Dados:** Flask-SQLAlchemy com SQLite (`instance/monitoramento.db`)
- **Processamento de Planilhas:** pandas e openpyxl
- **Processamento e Leitura de PDF:** pypdf (7.1.1)
- **Geração de Relatórios PDF:** xhtml2pdf
- **Front-end e Estilização:** HTML5 semântico, Jinja2 e Tailwind CSS via CDN oficial
- **Tipografia:** Newsreader (serif editorial), Inter (sans-serif) e JetBrains Mono (código e métricas)

---

## 3. Identidade Visual e Padrões de Interface

- **Paleta de Cores:**
  - Cor primária da marca: `#971E84` (Magenta/Roxo Evonik)
  - Hover de botões primários: `#7e186e`
  - Fundo suave selecionado: `#fdf4fa` / `rgba(151, 30, 132, 0.05)`
  - Bordas de destaque: `rgba(151, 30, 132, 0.2)`
- **Layout e Estética:**
  - Fundo em tom `#fafbfc` com grade blueprint técnica (`blueprint-grid`) e cantoneiras de alinhamento (`+`).
  - Navegação superior direta e minimalista com as abas lado a lado: **Relatório de Excel** e **Leitor de PDF**.
  - Ícones vetoriais padronizados no padrão Lucide SVG com traço fino e elegante.

---

## 4. Estrutura do Projeto

```text
HACKATON/
├── app/
│   ├── __init__.py          # Inicialização do Flask e SQLAlchemy
│   ├── models.py            # Modelos relacionais do banco SQLite
│   ├── routes.py            # Rotas web (Excel, PDF, visualização e download)
│   ├── services.py          # Regras de negócio, parsers (Excel/PDF) e gerador PDF
│   └── templates/
│       ├── base.html        # Layout base com barra de navegação compartilhada
│       ├── index.html       # Página de upload e leitura de planilhas Excel
│       ├── importar_pdf.html# Página dedicada à leitura automática de laudos PDF
│       ├── relatorio.html   # Dashboard técnico e parecer de conformidade ambiental
│       └── relatorio_pdf.html # Template estruturado para geração do PDF de auditoria
├── context/
│   └── DEV-INSTRUCTIONS.md  # Este guia de diretrizes e especificações
├── instance/
│   └── monitoramento.db     # Base SQLite local persistida
├── tests/                   # Scripts e validações automatizadas
├── run.py                   # Ponto de entrada para execução da aplicação Flask
└── requirements.txt         # Dependências do projeto
```

---

## 5. Regras de Negócio e Cálculos Ambientais

### A. Eficiência de Remoção da ETE (P1 vs P2)
- **Fórmula:** `Eficiência (%) = ((P1 - P2) / P1) * 100`
- **Parâmetros de Carga Obrigatórios:**
  - DBO5,20 (Demanda Bioquímica de Oxigênio): meta legal de remoção mínima de 80% (Art. 16, CONAMA 430/2011).
  - DQO (Demanda Química de Oxigênio): controle operacional da planta.
  - SST (Sólidos Suspensos Totais): controle de sedimentação e separação física.

### B. Conformidade do Efluente Tratado (Regra da Norma Mais Restritiva)
- Cada medição em P2 é comparada simultaneamente com:
  - **CONAMA 430/2011 (Artigo 16)**
  - **Decreto Estadual SP 8.468/1976 (Artigo 18)**
- Em parâmetros onde ambas as normas estipulam limites diferentes, o sistema aplica automaticamente a norma mais rigorosa (menor valor numérico permitido).
- Exemplo: Chumbo Total tem limite de 0,5 mg/L no CONAMA 430 e 0,1 mg/L no Decreto SP 8.468. O sistema adota 0,1 mg/L como teto de conformidade.

### C. Avaliação de Impacto no Rio Piracicaba (P3 vs P4)
- Compara a concentração a jusante (P4) com o padrão de qualidade do **CONAMA 357/2005 para corpos hídricos Classe 2**.
- Calcula o delta absoluto (`P4 - P3`) e percentual de variação.
- Dispara alerta de impacto ambiental caso P4 ultrapasse o teto da Classe 2 ou quando houver elevação igual ou superior a 20% atribuível ao lançamento da ETE.

---

## 6. Rotas e Fluxo da Aplicação

1. **`GET /` (Relatório de Excel):**
   - Apresenta a tela de seleção de planilha Excel (.xlsx e .xls) e histórico de campanhas gravadas no banco.
2. **`POST /importar`:**
   - Ingestão da planilha via pandas, execução dos cálculos, gravação no SQLite e renderização do relatório.
3. **`GET /importar-pdf` (Leitor de PDF):**
   - Apresenta a tela de seleção de arquivo PDF e histórico de laudos salvos.
4. **`POST /importar-pdf`:**
   - Extrai metadados, amostras P1 a P4, calcula eficiências, persiste de forma idempotente e exibe o parecer ambiental.
5. **`GET /relatorio/<codigo_laudo>`:**
   - Exibição visual detalhada de qualquer campanha salva no histórico.
6. **`GET /relatorio/<codigo_laudo>/pdf`:**
   - Renderização em memória e download do laudo técnico oficial em formato PDF.

---

## 7. Estágios de Evolução do Software

- [x] **Nível Básico (Concluído):**
  - Importação e validação de planilhas Excel.
  - Banco de dados relacional com 22 parâmetros regulamentados e seed automatizado.
  - Cálculo de eficiência de tratamento da ETE.
  - Comparação automatizada com a norma mais restritiva.
  - Relatório técnico interativo e exportação em PDF.

- [x] **Nível Intermediário (Fase 1 Concluída):**
  - Módulo de leitura automática de PDFs laboratoriais via `pypdf`.
  - Separação da aplicação em páginas dedicadas (Relatório de Excel vs Leitor de PDF).
  - Tratamento transacional idempotente para reprocessamento seguro de laudos.
  - *Próximos passos:* Comparativos de tendências temporais e gráficos dinâmicos no dashboard.

- [ ] **Nível Avançado (Planejado):**
  - Integração com Inteligência Artificial para parecer descritivo automatizado.
  - Alertas automáticos via e-mail para parâmetros em não conformidade.
  - Projeções de qualidade hídrica e modelos preditivos de vazão.

---

## 8. Diretrizes de Código e Comunicação

1. **Humanização da Comunicação:** Respostas e textos devem ser claros, diretos, cordiais e naturais em português brasileiro, sem jargões artificiais e sem o uso de travessões longos. Utilize hífen simples (`-`) ou pontuação convencional.
2. **Transações Seguras:** Toda escrita no banco de dados deve utilizar bloco `try/except` com `db.session.rollback()` no tratamento de exceções.
3. **Idempotência:** A reimportação de uma mesma campanha deve substituir os dados antigos de forma limpa, evitando erros de violação de chave primária ou única.
4. **Código Limpo:** Mantenha comentários descritivos em português, nomes de variáveis autoexplicativos e funções desacopladas por responsabilidade única.
