# Product Overview - Auraxis

Ultima atualizacao: 2026-02-22

## Objetivo deste documento
Este documento descreve o produto para P.O., stakeholders e alinhamento de negocio.
Status de execucao, progresso e rastreabilidade de entrega ficam exclusivamente em `TASKS.md`.

## Visao do produto
Auraxis e uma plataforma de gestao financeira pessoal com foco em planejamento e projecoes de investimento.
A proposta central e transformar dados financeiros do usuario em visibilidade de presente e clareza de futuro.

## Problema que resolvemos
1. Usuarios registram movimentacoes, mas nao conseguem transformar isso em direcao financeira pratica.
2. Metas financeiras existem no plano mental, mas faltam simulacoes objetivas de aporte x tempo.
3. Sem um perfil financeiro consistente, recomendacoes tendem a ser genricas e pouco acionaveis.

## Proposta de valor
1. Consolidar estado financeiro atual em uma base confiavel.
2. Permitir simulacoes de metas com cenarios de aporte e prazo.
3. Evoluir para recomendacoes orientativas personalizadas, com explicabilidade.

## Escopo funcional atual (visao consolidada)
1. Autenticacao e sessao com foco em seguranca de acesso.
2. Gestao de transacoes com filtros, dashboard, consultas por periodo e politica de impacto para lancamentos de cartao.
3. Gestao de carteira e operacoes de investimento com calculos de desempenho.
4. Modulo de metas com CRUD e simulacao de planejamento em REST e GraphQL.
5. Cartoes de credito com fatura/utilizacao derivadas de transacoes canonicas.
6. Arquitetura de dominio centralizada para reduzir duplicacao entre adapters REST/GraphQL.

## Principios de produto
1. Clareza: regras financeiras e simulacoes precisam ser compreensiveis para o usuario final.
2. Confianca: seguranca e consistencia de dados sao requisitos de base.
3. Evolucao incremental: cada etapa deve adicionar valor sem degradar confiabilidade.
4. Rastreabilidade: decisoes de produto devem ser convertidas em backlog tecnico no `TASKS.md`.

## Direcao de Perfil de Usuario (V1)

### Decisoes aprovadas em 2026-02-20
1. Renda mensal de referencia sera liquida (`monthly_income_net`).
2. Objetivos financeiros no perfil serao campo livre nesta fase.
3. `state_uf` sera opcional no onboarding e editavel posteriormente no perfil.
4. Perfil de investidor sera inicialmente auto declarado pelo usuario.
5. Um questionario curto sera oferecido para apoiar essa autodeclaracao, de forma indicativa (nao diagnostica).

### Taxonomia inicial de perfil de investidor
1. `conservador`
2. `explorador`
3. `entusiasta`

### Campos minimos de perfil para evolucao de personalizacao
1. `name`
2. `birth_date`
3. `monthly_income_net`
4. `state_uf`
5. `occupation`
6. `investor_profile` (auto declarado)
7. `financial_objectives` (texto livre)

### Questionario auxiliar de perfil (diretriz)
1. Deve ser curto e de baixo atrito.
2. Deve gerar uma sugestao de perfil para o usuario validar, sem substituir a autodeclaracao.
3. Deve ser tratado como apoio de produto, nao como recomendacao financeira certificada.

## Direcao futura de IA
1. Identificar padroes de gasto e oportunidades de economia.
2. Traduzir impacto de comportamento financeiro na viabilidade das metas.
3. Entregar orientacoes acionaveis com justificativas claras.

## Guardrails para recursos de IA
1. Consentimento explicito do usuario para analise automatizada.
2. Explicabilidade minima da recomendacao.
3. Privacidade, minimizacao de dados e trilha de auditoria.
4. Modo advisory-only, sem execucao automatica financeira.

## Discovery de Produto & Analise Competitiva (2026-02-20)

### Posicionamento de Mercado
O Auraxis diferencia-se de apps como **Mobills, Despezzas e Organizze** ao mover o foco do "Registro de Passado" (Fluxo de Caixa) para o "Planejamento de Futuro" (Investimentos e Metas). Enquanto os concorrentes focam em automacao de despesas, o Auraxis foca em simulacao de destino e impacto de comportamento.

### Gaps e Lacunas Identificadas
| Feature | Descricao | Impacto (0-10) | ETA Estimado |
| :--- | :--- | :---: | :---: |
| **Open Finance** | Integracao automatica com bancos para reduzir atrito de entrada de dados. | 10 | 6-8 semanas |
| **Gestao de Cartao** | Controle detalhado de faturas, limites e parcelamentos (dor central do BR). | 8 | 3-4 semanas |
| **Recorrencia Inteligente** | Previsao automatica de contas fixas no fluxo de caixa futuro. | 7 | 2 semanas |

### Oportunidades e "Oceanos Azuis"
| Feature | Descricao | Impacto (0-10) | ETA Estimado |
| :--- | :--- | :---: | :---: |
| **Sinergia Investimento x Meta** | O rendimento real da carteira atualiza automaticamente a previsao de conclusao da meta. | 9 | 3 semanas |
| **IA com Explicabilidade** | Sugestoes que explicam o "porquê" (ex: "Sugerimos X porque sua liquidez em Y permite"). | 9 | 6-10 semanas |
| **Goal Sandbox (Simulador)** | Interface em tempo real para o usuario testar cenarios "e se eu aportar mais R$ 100?". | 8 | 2 semanas |
| **Indice de Sobrevivencia** | Calculo de "Burn Rate" - quanto tempo o patrimonio sustenta o custo de vida atual. | 7 | 1 semana |

## Discovery de Ideias Futuras (2026-02-22)

### 1) Exportacao de extrato financeiro (CSV/XLSX)
Descricao:
- Exportar receitas, despesas ou ambos por periodo.
- Presets: 15, 30, 90, 180 dias, desde o inicio e range customizado.

Valor de produto:
- Facilita prestacao de contas pessoal, compartilhamento e analise externa.

Riscos principais:
- Medio: consistencia de timezone/periodo e colunas entre CSV e XLSX.
- Baixo: performance de export para volumes altos se houver pagina grande.

### 2) Importacao de relatorios de bancos + conciliacao inteligente
Descricao:
- Importar relatorios bancarios para somar ao fluxo manual.
- Categorizar, agrupar por data e refletir no balanco mensal consolidado.
- Aplicar conciliacao para detectar possiveis duplicidades (manual x importado).
- Futuramente usar LLM para sugerir classificacao, detectar duplicidades ambíguas e gerar insights.

Valor de produto:
- Reduz friccao de digitacao manual e aumenta cobertura de dados reais.

Riscos principais:
- Alto: qualidade/variacao de layout dos arquivos entre bancos.
- Alto: deduplicacao incorreta (falso positivo/falso negativo) sem trilha de revisao.
- Alto: privacidade/LGPD para fluxo com IA e dados financeiros sensiveis.

### 3) Aba "Ferramentas" de conveniencia financeira
Descricao:
- Area utilitaria com calculos recorrentes para trabalhador e vida financeira.

Sugestoes iniciais de calculadoras:
- Salario liquido (CLT) com INSS/IRRF.
- Rescisao CLT (com e sem justa causa).
- Ferias + adicional de 1/3.
- 13o salario proporcional.
- Horas extras e adicional noturno.
- FGTS acumulado e multa de 40%.
- Divisao de conta (bar/restaurante) com taxa de servico e divisao proporcional.
- Simulador simples de parcelamento (juros efetivos/custo total).

Valor de produto:
- Aumenta uso recorrente e utilidade pratica mesmo fora do fluxo de transacoes.

Riscos principais:
- Medio: manutencao de regras tributarias/trabalhistas ao longo do tempo.
- Medio: risco de interpretacao como consultoria formal se sem disclaimers.

### 4) Integracao com Open Banking/Open Finance (ultima fase)
Descricao:
- Integracao nativa de contas para ingestao automatica de transacoes.

Diretriz:
- Tratar como iniciativa de fase final, apos consolidar importacao por arquivo e conciliacao.

Riscos principais:
- Alto: requisitos de seguranca, compliance, consentimento e operacao.
- Alto: custo de integracao e dependencia de parceiros/provedores.

Sequencia recomendada de entrega:
1. Exportacao CSV/XLSX.
2. Importacao por arquivo + conciliacao manual assistida.
3. Insights com IA em modo advisory.
4. Open Finance com discovery regulatorio e tecnico dedicado.

## Governanca documental
1. `product.md`: estrategia, direcao e decisoes de produto.
2. `TASKS.md`: backlog executavel, prioridades, riscos, progresso e commits.
