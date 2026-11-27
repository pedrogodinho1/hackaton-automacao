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
- **ORM, Banco de Referência e Sessão:** Flask-SQLAlchemy com SQLite (`instance/monitoramento.db`) para normas, pontos de coleta e limites legais; armazenamento em memória isolado por sessão (`_SESSOES_LAUDOS`) para campanhas importadas (zerado ao reiniciar o servidor)
- **Processamento de Planilhas:** pandas e openpyxl
- **Processamento e Leitura de PDF:** pypdf (7.1.1)
- **Geração de Relatórios PDF:** xhtml2pdf
- **Front-end e Estilização:** HTML5 semântico, Jinja2, Tailwind CSS via CDN oficial e Chart.js
- **Tipografia:** Inter (sans-serif) e JetBrains Mono (código e métricas)

---

## 3. Identidade Visual e Padrões de Interface

- **Paleta de Cores:**
  - Cor primária da marca: `#971E84` (Magenta/Roxo Evonik)
  - Hover de botões primários: `#7e186e`
  - Fundo suave selecionado: `#fdf4fa` / `rgba(151, 30, 132, 0.05)`
  - Bordas de destaque: `rgba(151, 30, 132, 0.2)`
- **Layout e Estética:**
  - Fundo em tom `#fafbfc` com grade blueprint técnica (`blueprint-grid`).
  - Ícone vetorial próprio (`app/static/images/icon.svg`, gota com pulso de telemetria) usado tanto no cabeçalho quanto como favicon.
  - Navegação superior direta e minimalista com as abas lado a lado: **Relatório de Excel**, **Leitor de PDF** e **Dashboard Ambiental**.
  - Ícones vetoriais padronizados no padrão Lucide SVG com traço fino e elegante.
  - Gráficos dinâmicos no Dashboard Ambiental via Chart.js.

---

## 4. Estrutura do Projeto

```text
HACKATON/
├── app/
│   ├── __init__.py            # Inicialização do Flask, dotenv, limite de upload (16 MB) e SQLAlchemy
│   ├── models.py              # Modelos relacionais do banco SQLite
│   ├── routes.py              # Rotas web (Excel, PDF, Dashboard, API JSON, exclusão e download)
│   ├── services.py            # Regras de negócio, sessão em memória, parsers (Excel/PDF), dashboard e gerador PDF
│   ├── static/
│   │   ├── css/style.css      # Design system, grade blueprint, cards, tabelas e badges
│   │   ├── images/icon.svg    # Ícone principal da aplicação e favicon
│   │   └── js/app.js          # Dropzones, filtros rápidos de tabela e feedback de envio
│   └── templates/
│       ├── base.html          # Layout base com barra de navegação compartilhada e rodapé centralizado
│       ├── index.html         # Página de upload e leitura de planilhas Excel
│       ├── importar_pdf.html  # Página dedicada à leitura automática de laudos PDF
│       ├── dashboard.html     # Dashboard Ambiental com KPIs, filtros e gráficos Chart.js
│       ├── relatorio.html     # Parecer técnico completo e conformidade ambiental
│       └── relatorio_pdf.html # Template estruturado para geração do PDF de auditoria
├── context/
│   └── DEV-INSTRUCTIONS.md    # Este guia de diretrizes e especificações
├── instance/
│   └── monitoramento.db       # Base SQLite local com tabelas de referência legal
├── init_db.py                 # Seed de pontos de coleta, legislações e 22 limites legais
├── run.py                     # Ponto de entrada para execução da aplicação Flask
└── requirements.txt           # Dependências do projeto
```

---

## 5. Regras de Negócio e Cálculos Ambientais

### A. Eficiência de Remoção da ETE (P1 vs P2)
- **Fórmula:** `Eficiência (%) = ((P1 - P2) / P1) * 100`
- **Parâmetros de Carga Obrigatórios:**
  - DBO5,20 (Demanda Bioquímica de Oxigênio): meta legal de remoção mínima de 60% pela CONAMA 430/2011 (Art. 16) e limite máximo de concentração de 60,0 mg/L pelo Decreto SP 8.468/1976 (Art. 18, que prevê alternativamente remoção mínima de 80%).
  - DQO (Demanda Química de Oxigênio): controle operacional da planta.
  - SST (Sólidos Suspensos Totais): controle de sedimentação e separação física.

### B. Conformidade do Efluente Tratado (Regra da Norma Mais Restritiva)
- Cada medição em P2 é comparada simultaneamente com:
  - **CONAMA 430/2011 (Artigo 16)**
  - **Decreto Estadual SP 8.468/1976 (Artigo 18)**
- Em parâmetros onde ambas as normas estipulam limites diferentes, o sistema aplica automaticamente a norma mais rigorosa (menor valor numérico permitido).
- Exemplo: Cianeto Total tem limite de 1,00 mg/L no CONAMA 430 e 0,20 mg/L no Decreto SP 8.468. O sistema adota 0,20 mg/L como teto de conformidade.

### C. Avaliação de Impacto no Rio Piracicaba (P3 vs P4)
- Compara a concentração a jusante (P4) com os limites máximos e mínimos do **CONAMA 357/2005 para corpos hídricos Classe 2** (incluindo mínimo de OD e faixa de pH) e variação térmica de 3 °C.
- Calcula o delta absoluto (`P4 - P3`) e percentual de variação.
- Dispara alerta de impacto ambiental caso P4 ultrapasse os limites da Classe 2 ou aviso de atenção quando houver elevação igual ou superior a 20% atribuível ao lançamento da ETE.

---

## 6. Rotas e Fluxo da Aplicação

1. **`GET /` (Relatório de Excel):**
   - Apresenta a tela de seleção de planilha Excel (.xlsx) e o histórico de campanhas carregadas na sessão atual.
2. **`POST /importar`:**
   - Ingestão da planilha via pandas, execução dos cálculos, armazenamento na sessão em memória e renderização do relatório.
3. **`GET /importar-pdf` (Leitor de PDF):**
   - Apresenta a tela de seleção de arquivo PDF e o histórico de laudos da sessão atual.
4. **`POST /importar-pdf`:**
   - Extrai metadados e amostras P1 a P4 (tanto de laudos laboratoriais quanto de relatórios PDF exportados pelo sistema), calcula eficiências, atualiza a sessão em memória de forma idempotente e exibe o parecer ambiental.
5. **`GET /dashboard` (Dashboard Ambiental):**
   - Painel consolidado com KPIs, filtros de campanha e parâmetro, 5 gráficos dinâmicos em Chart.js, listas de alertas e histórico consolidado (com cabeçalho `Cache-Control: no-store`).
6. **`GET /api/dashboard`:**
   - Endpoint JSON (`Cache-Control: no-store`) que alimenta as atualizações dinâmicas dos filtros, gráficos e listas no Dashboard Ambiental.
7. **`GET /relatorio/<codigo_laudo>`:**
   - Exibição visual detalhada de qualquer campanha carregada na sessão atual (KPIs, eficiência, monitoramento do rio e medições em P2).
8. **`GET /relatorio/<codigo_laudo>/pdf`:**
   - Renderização em memória e download do laudo técnico oficial em formato PDF.
9. **`POST /laudo/<codigo_laudo>/excluir` e `POST /laudos/limpar`:**
   - Exclusão de uma campanha específica ou limpeza completa da sessão em memória, mantendo intactas as tabelas de normas e limites legais no SQLite.

---

## 7. Estágios de Evolução do Software

- [x] **Nível Básico (Concluído):**
  - Importação e validação de planilhas Excel.
  - Banco de dados relacional com 22 parâmetros regulamentados e seed automatizado.
  - Cálculo de eficiência de tratamento da ETE.
  - Comparação automatizada com a norma mais restritiva.
  - Relatório técnico interativo e exportação em PDF.

- [x] **Nível Intermediário (Concluído):**
  - Módulo de leitura automática de PDFs laboratoriais e relatórios exportados pelo sistema via `pypdf`, independente da quantidade fixa de páginas e com detecção de PDFs escaneados.
  - Separação da aplicação em abas dedicadas (Relatório de Excel, Leitor de PDF e Dashboard Ambiental).
  - Dashboard Ambiental consolidado com filtros dinâmicos, gráficos Chart.js (conformidade, eficiência histórica, Rio Piracicaba, série de parâmetro em P2 e ranking de não conformidades).
  - Sessão em memória para campanhas importadas (sem persistir estado entre reinicializações), exclusão/limpeza sincronizada, limite de upload (16 MB) e identidade visual própria com ícone SVG e favicon.

- [ ] **Nível Avançado (Planejado):**
  - Integração com Inteligência Artificial para parecer descritivo automatizado.
  - Alertas automáticos via e-mail para parâmetros em não conformidade.
  - Projeções de qualidade hídrica e modelos preditivos de vazão.

---

## 8. Diretrizes de Código e Comunicação

1. **Humanização da Comunicação:** Respostas e textos devem ser claros, diretos, cordiais e naturais em português brasileiro, sem jargões artificiais e sem o uso de travessões longos. Utilize hífen simples (`-`) ou pontuação convencional.
2. **Transações Seguras:** Toda escrita no banco de dados (quando aplicável) deve utilizar bloco `try/except` com `db.session.rollback()` no tratamento de exceções.
3. **Idempotência:** A reimportação de uma mesma campanha deve substituir os dados anteriores de mesmo código de forma limpa na sessão.
4. **Código Limpo:** Mantenha comentários descritivos em português apenas em partes, funções e classes importantes, nomes de variáveis autoexplicativos e funções desacopladas por responsabilidade única.
