# Sistema de Avaliação Ambiental - ETE Evonik

Aplicação web desenvolvida para o Hackathon Evonik + ETEC com foco na automação da análise de laudos laboratoriais de efluentes industriais e na avaliação de impacto ambiental no corpo receptor (Rio Piracicaba, Classe 2).

## Por que a aplicação foi feita

O acompanhamento mensal de uma Estação de Tratamento de Efluentes (ETE) exige cruzar dezenas de parâmetros físico-químicos contra legislações federais e estaduais que possuem limites diferentes para a mesma substância. Quando essa conferência é feita manualmente em planilhas ou PDFs, o processo fica lento e sujeito a erros de interpretação normativa.

Este sistema substitui a conferência manual por um fluxo automatizado, padronizado e auditável: basta enviar a planilha Excel ou o laudo laboratorial em PDF para que o sistema extraia os resultados, aplique automaticamente a norma mais restritiva, calcule a eficiência de remoção da ETE, avalie o impacto no rio e gere relatórios técnicos prontos para exportação em PDF.

## Pontos de monitoramento (P1 a P4)

O monitoramento ambiental acompanha quatro pontos fixos de coleta ao longo do ciclo de tratamento e lançamento:

| Ponto | Nome | Matriz | Finalidade |
| --- | --- | --- | --- |
| **P1** | Efluente Bruto (Entrada da ETE) | Efluente Líquido | Referência de carga poluidora antes do tratamento para o cálculo de eficiência da estação. |
| **P2** | Efluente Tratado (Saída da ETE) | Efluente Líquido | Ponto de lançamento após tratamento. Validado diretamente contra os limites legais de emissão e comparado com P1 para medir a remoção. |
| **P3** | Rio à Montante | Água Superficial | Condição natural do Rio Piracicaba antes do ponto de descarte da ETE. |
| **P4** | Rio à Jusante | Água Superficial | Qualidade da água após a mistura do efluente tratado. Comparado com P3 e com os padrões da Classe 2 para investigar possíveis impactos. |

## Regras ambientais e legislações aplicadas

O banco de referência local (`instance/monitoramento.db`) mantém cadastrados os 4 pontos de coleta, 3 normas ambientais e 22 parâmetros regulamentados com suporte a sinônimos e símbolos químicos:

- **Norma mais restritiva em P2:** cada medição no efluente tratado é confrontada simultaneamente com a **Resolução CONAMA 430/2011 (Art. 16)** e o **Decreto Estadual SP 8.468/1976 (Art. 18)**. Quando as duas normas divergem, prevalece automaticamente o limite mais rigoroso (por exemplo, Chumbo Total adota `0,1 mg/L` do Decreto SP em vez de `0,5 mg/L` do CONAMA 430).
- **Eficiência de remoção da ETE (P1 vs P2):** calculada pela fórmula `((P1 - P2) / P1) * 100` para parâmetros de carga (`DBO5,20`, `DQO` e `SST`), com verificação legal da meta de remoção mínima de `DBO5,20` (`>= 60%` pela CONAMA 430/2011) e concentração máxima (`<= 60,0 mg/L` pelo Decreto SP 8.468/1976).
- **Impacto no Rio Piracicaba (P3 vs P4):** confronta P4 com os limites máximos e mínimos da **Resolução CONAMA 357/2005 (Água Doce Classe 2)**, monitora variação térmica `>= 3,0 °C` na zona de mistura e dispara avisos de atenção quando há elevação igual ou superior a `20%` entre montante e jusante.

## Principais funcionalidades

- **Importação de planilhas Excel (`.xlsx` e `.xls`):** leitura via `pandas` e `openpyxl`, reconhecimento flexível de colunas e sinônimos, tratamento de valores abaixo do limite de quantificação (`< LQ`) e suporte a planilhas com múltiplas campanhas mensais.
- **Leitor automático de laudos PDF:** extração de texto via `pypdf` compatível tanto com laudos laboratoriais (independente do número fixo de páginas) quanto com relatórios técnicos gerados pelo próprio sistema, com aviso claro para PDFs escaneados sem texto selecionável.
- **Dashboard Ambiental interativo:** painel consolidado com 4 cartões de KPIs, filtros dinâmicos por campanha e por parâmetro via API JSON (`/api/dashboard`), 5 gráficos em `Chart.js` (conformidade em P2, eficiência histórica da ETE, comparativo P3 vs P4 no Rio Piracicaba, série histórica do parâmetro selecionado e ranking de não conformidades), painéis de alertas e tabela consolidada com busca rápida.
- **Parecer técnico e exportação em PDF:** visualização web detalhada por campanha (`/relatorio/<codigo_laudo>`) e geração de laudo técnico oficial em PDF diretamente em memória via `xhtml2pdf`, sem gravar arquivos temporários no disco.
- **Sessão em memória sem persistência indesejada:** as campanhas importadas ficam armazenadas apenas na memória da sessão ativa (permitindo comparar vários arquivos na mesma sessão e começando zerado ao reiniciar o servidor), enquanto o SQLite mantém apenas as tabelas de referência legal.
- **Segurança e robustez:** proteção CSRF em todos os formulários `POST`, validação real do tipo de arquivo por assinatura (Magic Bytes), limite de upload de 16 MB com tratamento HTTP 413, cabeçalhos HTTP de segurança (`X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy`), cookies de sessão `HttpOnly`/`SameSite=Lax`, páginas personalizadas de erro 404/500 e interface responsiva para desktop, tablet e celular.

## Tecnologias utilizadas

- **Back-end:** Python 3.14, Flask, Flask-SQLAlchemy, SQLAlchemy e python-dotenv
- **Banco de referência:** SQLite (`instance/monitoramento.db`)
- **Processamento de dados e documentos:** pandas, openpyxl, pypdf e xhtml2pdf
- **Front-end:** HTML5, Jinja2, Tailwind CSS, CSS customizado, JavaScript puro (Vanilla JS), Chart.js e ícones vetoriais no padrão Lucide SVG

## Estrutura do projeto

```text
HACKATON/
├── app/
│   ├── __init__.py            # Inicializacao do Flask, dotenv, limite de upload e SQLAlchemy
│   ├── models.py              # Modelos relacionais (pontos, legislacoes e limites legais)
│   ├── routes.py              # Rotas web, API JSON, protecao CSRF, magic bytes e handlers de erro
│   ├── services.py            # Regras ambientais, sessao em memoria, parsers Excel/PDF e gerador PDF
│   ├── static/
│   │   ├── css/style.css      # Design system, grade blueprint, spinner, scroll e regras responsivas
│   │   ├── images/icon.svg    # Icone principal da aplicacao e favicon
│   │   └── js/app.js          # Dropzones, filtros de tabela, alertas fechaveis e loader
│   └── templates/
│       ├── base.html          # Layout base com navegacao responsiva e rodape
│       ├── index.html         # Aba Relatorio de Excel
│       ├── importar_pdf.html  # Aba Leitor de PDF
│       ├── dashboard.html     # Aba Dashboard Ambiental
│       ├── relatorio.html     # Parecer tecnico detalhado
│       ├── relatorio_pdf.html # Template A4 para exportacao em PDF
│       └── erro.html          # Pagina personalizada para erros 404 e 500
├── context/
│   └── DEV-INSTRUCTIONS.md    # Documentacao tecnica e diretrizes do projeto
├── instance/
│   └── monitoramento.db       # Banco SQLite gerado localmente pelo init_db.py
├── init_db.py                 # Script de criacao e carga inicial das normas e limites legais
├── run.py                     # Ponto de entrada do servidor Flask
└── requirements.txt           # Dependencias Python do projeto
```

## Como executar localmente

### Pré-requisitos
- Python 3.10 ou superior instalado

### Passo a passo (Windows PowerShell)

1. Crie e ative o ambiente virtual:
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

2. Instale as dependências:
   ```powershell
   pip install -r requirements.txt
   ```

3. Inicialize o banco de referência com os pontos P1 a P4, legislações e 22 limites legais:
   ```powershell
   python init_db.py
   ```

4. Inicie o servidor:
   ```powershell
   python run.py
   ```

5. Acesse no navegador: `http://127.0.0.1:5000`

### Variáveis de ambiente opcionais (`.env`)

Você pode criar um arquivo `.env` na raiz do projeto (ignorado pelo Git) para personalizar o ambiente:

```env
SECRET_KEY=sua-chave-secreta-aqui
FLASK_DEBUG=true
SESSION_COOKIE_SECURE=false
```

## Licença

Este projeto está licenciado sob a licença MIT. Consulte o arquivo [LICENSE](LICENSE) para mais detalhes.
