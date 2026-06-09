<p align="center">
  <a href="README.ja.md">日本語</a> | <a href="README.zh.md">中文</a> | <a href="README.es.md">Español</a> | <a href="README.fr.md">Français</a> | <a href="README.hi.md">हिन्दी</a> | <a href="README.md">English</a> | <a href="README.pt-BR.md">Português (BR)</a>
</p>

<p align="center">
  <img src="app/logo.png" width="400" alt="engine-room">
</p>

<p align="center">
  <a href="https://github.com/mcp-tool-shop-org/engine-room/actions/workflows/ci.yml"><img src="https://github.com/mcp-tool-shop-org/engine-room/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue" alt="License: MIT"></a>
  <a href="https://mcp-tool-shop-org.github.io/engine-room/"><img src="https://img.shields.io/badge/landing%20page-engine--room-0a7ea4" alt="Landing page"></a>
</p>

Un **sistema di provisioning basato su ricette per motori di intelligenza artificiale locali.** Esplora un catalogo di "ricette" verificate e misurate, seleziona una e implementala sulla tua infrastruttura GPU — **provisioning → avvio → misurazione** — in tempo reale, in modo riproducibile e convalidato rispetto a una base di riferimento delle prestazioni reali.

## Perché?

I motori di intelligenza artificiale locali sono estremamente eterogenei: uno è costruito da codice sorgente CUDA, il successivo è un container, quello dopo è un pacchetto portatile e l'ultimo è un quantizzatore che scrive un file ed esce. Capire *quale* motore utilizzare è un problema (una knowledge base lo risolve); in realtà, *configurarlo correttamente, in modo riproducibile e verificarne il funzionamento* è un altro problema.
`engine-room` rappresenta la seconda metà della soluzione.

## Architettura: due componenti, una singola interfaccia

`engine-room` è la parte **attiva** di una divisione intenzionale:

- **Conoscenza:** la *ricetta* verificata, con riferimento alla fonte e astratta (cosa costruire, la toolchain definita, gli obiettivi di base misurati, i passaggi di rollback dichiarati). Cambia quando il motore upstream cambia. Risiede nella knowledge base.
- **Azione:** questo repository: risolve una ricetta rispetto all'infrastruttura attiva, la materializza, la avvia/misura e la ripristina in modo sicuro. Cambia quando l'*infrastruttura* cambia.

## Ottenere il livello di ricette

`engine-room` è la parte **attiva**; non include le ricette. La parte **conoscenza** è un componente separato e verificato: il database delle ricette `tensor-engine-knowledge` (`engines.db`) a cui devi puntare `er`. Clonare solo questo repository ti fornisce l'esecutore, ma non il catalogo.

- **Rileva la tua infrastruttura** senza alcun database di ricette: `er rig` legge solo l'hardware attivo (`nvidia-smi` + variabili d'ambiente), quindi funziona immediatamente.
- **Punta al database delle ricette** per tutto il resto (`list` / `show` / `preflight` / `provision`) in uno dei due modi:
- imposta `ER_RECIPES_DB` sul percorso del database, oppure
- passa `--db <path>` a qualsiasi comando.
- Se nessuno dei due è impostato, `er` cerca `../../readouts/tensor-engine-knowledge/engines.db` rispetto al repository. Quando il database non viene trovato, ricevi un errore chiaro (`database delle ricette non trovato: ... — imposta $ER_RECIPES_DB o passa --db`), e non una traccia dello stack.

Il livello di ricette è l'input di conoscenza affidabile (vedi [Sicurezza / modello di minaccia](#security--threat-model)). Ottieni `engines.db` dalla distribuzione `tensor-engine-knowledge`; `engine-room` lo legge in **modalità sola lettura** e non lo scrive mai.

Una ricetta è **polimorfica**: quattro tipi, ciascuno con una forma diversa:

| Tipo | Cosa fa | Misurato da |
|------|--------------|-------------|
| `launchable-server` | avvia un server a lunga esecuzione su una porta | throughput (token/s, iterazioni/s) |
| `batch-producer` | esegue, scrive un artefatto ed esce | qualità dell'output + tempo di esecuzione |
| `modifier` | un overlay che può essere integrato per velocizzare un'altra ricetta | una variazione misurata |
| `router-fleet` | un frontend che indirizza ad altre ricette | stato per ogni motore upstream |

## Riproducibile e convalidato per progettazione

- **Artefatti definiti e inclusi** (un hash rispetto a un indice curato non è sufficiente quando l'indice elimina il canale: la definizione deve essere una copia indirizzata in base al contenuto).
- Le **basi di riferimento misurate** sono associate al modello e includono un intervallo di compatibilità, quindi un aggiornamento del driver di routine non le invalida.
- Un **gate di correttezza viene eseguito prima di qualsiasi affermazione sulle prestazioni**, ed è configurabile per ogni modalità di output.
- **Ogni passaggio irreversibile ha un annullamento denominato** con uno stato post-rollback onesto; quelli a livello globale richiedono l'approvazione esplicita dell'utente.

## Stato

L'esecutore è implementato. La CLI `er` legge il livello di ricette e risolve una ricetta rispetto all'infrastruttura attiva (`rig` / `list` / `show` / `preflight`, tutti senza effetti collaterali), e il sistema di provisioning esegue il ciclo di riconciliazione: **per impostazione predefinita, è in modalità dry-run**, con un percorso `--execute` definito che materializza gli artefatti definiti, avvia un server locale e lo misura rispetto alla base di riferimento della ricetta (`provision` / `teardown` / `status`). Vedi [`executor/README.md`](executor/README.md).

La riproducibilità è attualmente solo parziale: le definizioni vengono risolte rispetto a un indice e gli artefatti non definiti sono accettati; includerli in un archivio indirizzato in base al contenuto, in modo che la `riproducibilità` sia *ottenuta*, è l'**obiettivo numero 1**.

L'interfaccia utente dell'operatore viene fornita come prototipo autonomo (dati simulati + effetti collaterali simulati tramite timer, fedele alla vera API JSON/WS):

- [`app/`](app/) — il pannello di controllo: sfoglia le ricette ed eseguile, con telemetria in tempo reale, interruzioni ANDON e rollback. Progettato a partire da [`design/ui-control-panel.claude-design-brief.md`](design/ui-control-panel.claude-design-brief.md) (la mappa completa dei gestori di eventi e i requisiti di usabilità).

## Sicurezza / modello di minaccia

Il **livello di ricette** (`tensor-engine-knowledge/engines.db`) è l'input di conoscenza affidabile: le ricette verificate e con riferimento alla fonte che indicano cosa costruire e quali obiettivi raggiungere. `engine-room` lo tratta come la fonte della verità.

`er provision --execute` è l'unico comando che interagisce con l'infrastruttura. È **protetto da un esplicito `--execute` e `--model** — ogni altro comando, e `provision` senza `--execute`, è in sola lettura / modalità dry-run. Quando si esegue, il sistema:

- **scarica** gli artefatti definiti della ricetta e li **verifica con SHA256** *quando la definizione include un hash SHA* — le definizioni non definite o i placeholder SHA sono attualmente accettati (il divario dell'obiettivo numero 1 sopra; tratta il database delle ricette e i relativi URL degli artefatti come affidabili fino a quando ciò non sarà implementato),
- **estrae** gli archivi in una directory per istanza (mai nella PATH globale),
- **avvia** un server locale (`127.0.0.1`) e può **arrestarlo** — il ripristino è verificato tramite identità (uccide solo un PID il cui eseguibile si trova nella nostra directory di istanza, quindi non uccide mai un processo non correlato).

Ogni passaggio irreversibile viene registrato in un registro *prima* che venga eseguito e ha un compensatore denominato, con l’elenco ordinato dal più recente al meno recente. Per segnalare una vulnerabilità, consultare il file [`SECURITY.md`](SECURITY.md).

## Supporto

Il progetto engine-room è in **costante manutenzione**. Le correzioni di sicurezza vengono implementate nell’**ultima versione secondaria** (la serie 1.0.x); consultare il file [`SECURITY.md`](SECURITY.md) per le versioni supportate e il percorso per la segnalazione privata delle vulnerabilità. Segnalare bug e richiedere nuove funzionalità tramite le issue di GitHub.

## Licenza

MIT — consultare il file [LICENSE](LICENSE).

---

<p align="center">Built by <a href="https://mcp-tool-shop.github.io/">MCP Tool Shop</a>.</p>
