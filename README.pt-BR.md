<p align="center">
  <a href="README.ja.md">日本語</a> | <a href="README.zh.md">中文</a> | <a href="README.es.md">Español</a> | <a href="README.fr.md">Français</a> | <a href="README.hi.md">हिन्दी</a> | <a href="README.it.md">Italiano</a> | <a href="README.md">English</a>
</p>

<p align="center">
  <img src="app/logo.png" width="400" alt="engine-room">
</p>

<p align="center">
  <a href="https://github.com/mcp-tool-shop-org/engine-room/actions/workflows/ci.yml"><img src="https://github.com/mcp-tool-shop-org/engine-room/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue" alt="License: MIT"></a>
  <a href="https://mcp-tool-shop-org.github.io/engine-room/"><img src="https://img.shields.io/badge/landing%20page-engine--room-0a7ea4" alt="Landing page"></a>
</p>

Um **provisionador orientado por receitas para mecanismos de IA locais.** Navegue em um catálogo de "receitas" verificadas e medidas, escolha uma e configure-a em sua própria plataforma GPU — **provisionamento → execução → medição** — dinamicamente, de forma reproduzível e validada em relação a uma linha de base de desempenho real.

## Por quê?

Os mecanismos de IA locais são extremamente heterogêneos para serem configurados: um é construído a partir do código-fonte CUDA, o próximo é um contêiner, o seguinte é um pacote portátil e o último é um quantizador que grava um arquivo e sai. Saber *qual* mecanismo usar é um problema (uma base de conhecimento resolve isso); realmente *configurá-lo corretamente, de forma reproduzível e medir se ele funciona* é outro.
O engine-room é a segunda parte.

## Arquitetura — dois artefatos, uma única interface

O engine-room é a metade **ativa** de uma divisão intencional:

- **Conhecimento** — a *receita* abstrata, verificada e com origem definida (o que construir, o conjunto de ferramentas fixado, os alvos de linha de base medidos, as etapas de reversão declaradas). Ela muda quando um mecanismo upstream é alterado. Reside na base de conhecimento.
- **Ação** — este repositório: resolução de uma receita em relação à plataforma ativa, materialização, execução/medição e reversão segura. Ele muda quando a *plataforma* muda.

## Obtendo a camada da receita

O engine-room é a metade **ativa**; ele não inclui as receitas. A metade do **conhecimento** é um artefato fornecido separadamente e verificado — o banco de dados de receitas **tensor-engine-knowledge** (`engines.db`) — para o qual você aponta o `er`. Clonar este repositório sozinho fornece apenas o executor, não o catálogo.

- **Detecte sua plataforma** sem nenhum banco de dados de receita: `er rig` lê apenas o hardware ativo (`nvidia-smi` + ambiente), portanto, funciona imediatamente.
- **Aponte para o banco de dados de receitas** para tudo o mais (`list` / `show` / `preflight` / `provision`) de duas maneiras:
- defina `ER_RECIPES_DB` para o caminho do banco de dados ou
- passe `--db <path>` em qualquer comando.
- Se nenhum dos dois for definido, `er` procura por `../../readouts/tensor-engine-knowledge/engines.db` em relação ao repositório. Quando o banco de dados está ausente, você recebe uma mensagem de erro clara (`banco de dados de receita não encontrado: … — defina $ER_RECIPES_DB ou passe --db`), e não um rastreamento de pilha.

A camada da receita é a entrada confiável de conhecimento (veja [Segurança / modelo de ameaças](#security--threat-model)). Obtenha `engines.db` da distribuição tensor-engine-knowledge; o engine-room o lê em **modo somente leitura** e nunca o grava.

Uma receita é **polimórfica** — quatro tipos, cada um com uma forma diferente:

| Tipo | O que faz | Medido por |
|------|--------------|-------------|
| `launchable-server` | inicia um servidor de longa duração em uma porta | taxa de transferência (tok/s, it/s) |
| `batch-producer` | executa, grava um artefato e sai | qualidade da saída + tempo decorrido |
| `modifier` | uma sobreposição que pode ser inserida para acelerar outra receita | um delta medido |
| `router-fleet` | uma interface que encaminha para outras receitas | saúde por upstream |

## Reproduzível e validado por design

- Artefatos **fixados e fornecidos** (um hash em relação a um índice selecionado não é suficiente quando o índice remove o canal — o fixo deve ser uma cópia endereçada pelo conteúdo).
- As **linhas de base medidas** são vinculadas ao modelo e carregam uma faixa de compatibilidade, para que uma atualização de driver de rotina não as invalide.
- Um **gate de correção é executado antes de qualquer afirmação de desempenho**, plugável por modalidade de saída.
- **Cada etapa irreversível tem um desfazimento nomeado** com um estado honesto pós-reversão; as etapas globais da máquina exigem aprovação humana explícita.

## Status

O executor foi implementado. O CLI `er` lê a camada da receita e resolve uma receita em relação à plataforma ativa (`rig` / `list` / `show` / `preflight`, todos sem efeitos colaterais), e o provisionador executa o loop de reconciliação — **execução simulada por padrão**, com um caminho `--execute` definido que materializa os artefatos fixados, inicia um servidor local e mede em relação à linha de base da receita (`provision` / `teardown` / `status`). Veja [`executor/README.md`](executor/README.md).

A reprodutibilidade é honestamente parcial hoje: os fixos são resolvidos em relação a um índice, e artefatos não fixados são aceitos — incluí-los em um armazenamento endereçado por conteúdo para que `reproduzível` seja *conquistado* é o **Objetivo 1**.

A interface do usuário do operador é fornecida como um protótipo autocontido (dados simulados + efeitos colaterais simulados pelo temporizador, fiel à API JSON/WS real):

- [`app/`](app/) — o Painel de Controle: navegue pelas receitas e execute-as, com telemetria ao vivo, interrupções ANDON e reversão. Projetado a partir de [`design/ui-control-panel.claude-design-brief.md`](design/ui-control-panel.claude-design-brief.md) (o mapa completo do manipulador de eventos e os requisitos de usabilidade).

## Segurança / modelo de ameaças

A **camada da receita** (`tensor-engine-knowledge/engines.db`) é a entrada confiável de conhecimento: as receitas verificadas e com origem definida que dizem o que construir e quais alvos atingir. O engine-room a trata como a fonte da verdade.

`er provision --execute` é o único comando que afeta a plataforma. Ele é **protegido por um `--execute` e `--model` explícitos** — todos os outros comandos, e `provision` sem `--execute`, são somente leitura / execução simulada. Quando você executa, ele:

- **baixa** os artefatos fixados da receita e **verifica o hash SHA256 deles** *quando o fixo carrega um SHA* — hashes não fixados / espaços reservados são atualmente aceitos (a lacuna do Objetivo 1 acima; trate o banco de dados de receitas e seus URLs de artefato como confiáveis até que isso seja implementado),
- **extrai** arquivos em um diretório por instância (nunca no PATH global),
- **inicia** um servidor local (`127.0.0.1`) e pode **pará-lo** — a desativação é verificada pela identidade (ele apenas mata um PID cujo executável está localizado em nosso diretório de instância, para que nunca mate um processo não relacionado).

Cada etapa irreversível é registada num livro de registo *antes* de ser executada e tem um compensador com nome, organizado por ordem cronológica inversa (do mais recente para o mais antigo). Para reportar uma vulnerabilidade, consulte [`SECURITY.md`](SECURITY.md).

## Suporte

O projeto engine-room está em **manutenção ativa**. As correções de segurança são implementadas na **versão mais recente** (a linha 1.0.x); consulte [`SECURITY.md`](SECURITY.md) para obter informações sobre as versões suportadas e o canal de comunicação para relatar avisos confidenciais. Registe erros e pedidos de funcionalidades como problemas no GitHub.

## Licença

MIT — consulte [LICENSE](LICENSE).

---

<p align="center">Built by <a href="https://mcp-tool-shop.github.io/">MCP Tool Shop</a>.</p>
