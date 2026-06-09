<p align="center">
  <a href="README.ja.md">日本語</a> | <a href="README.zh.md">中文</a> | <a href="README.md">English</a> | <a href="README.fr.md">Français</a> | <a href="README.hi.md">हिन्दी</a> | <a href="README.it.md">Italiano</a> | <a href="README.pt-BR.md">Português (BR)</a>
</p>

<p align="center">
  <img src="app/logo.png" width="400" alt="engine-room">
</p>

<p align="center">
  <a href="https://github.com/mcp-tool-shop-org/engine-room/actions/workflows/ci.yml"><img src="https://github.com/mcp-tool-shop-org/engine-room/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue" alt="License: MIT"></a>
  <a href="https://mcp-tool-shop-org.github.io/engine-room/"><img src="https://img.shields.io/badge/landing%20page-engine--room-0a7ea4" alt="Landing page"></a>
</p>

Un **sistema de aprovisionamiento basado en recetas para motores de IA locales**. Explore un catálogo de "recetas" verificadas y medidas para motores, seleccione una y configúrela en su propio equipo con GPU: **aprovisionamiento → lanzamiento → medición**, de forma dinámica, reproducible y validada frente a una línea base de rendimiento real.

## Por qué

Los motores de IA locales son extremadamente heterogéneos para configurarlos: uno es una compilación CUDA desde el código fuente, el siguiente es un contenedor, el siguiente un paquete portátil, el siguiente un cuantificador que escribe un archivo y se cierra. Saber *cuál* motor usar es un problema (una base de conocimientos lo resuelve); en realidad, *configurarlo correctamente, de forma reproducible y medir que funciona* es otro problema diferente.
`engine-room` aborda la segunda parte.

## Arquitectura: dos artefactos, una interfaz

`engine-room` representa la mitad **activa** de una división deliberada:

- **Conocimiento:** la *receta* abstracta, verificada y con origen (qué construir, el conjunto de herramientas fijado, los objetivos de línea base medidos, los pasos de reversión declarados). Cambia cuando cambia un motor upstream. Se almacena en la base de conocimientos.
- **Acción:** este repositorio: resuelve una receta para el equipo activo, la materializa, la lanza/mide y la revierte de forma segura. Cambia cuando cambia el *equipo*.

## Obtención de la capa de recetas

`engine-room` es la mitad **activa**; no incluye las recetas. La mitad del **conocimiento** es un artefacto proporcionado por separado y verificado: la base de datos de recetas `tensor-engine-knowledge` (`engines.db`), a la que apunta `er`. Clonar este repositorio solo le proporciona el ejecutor, no el catálogo.

- **Detecte su equipo** sin ninguna base de datos de recetas: `er rig` lee únicamente el hardware activo (`nvidia-smi` + entorno), por lo que funciona desde el principio.
- **Apunte a la base de datos de recetas** para todo lo demás (`list` / `show` / `preflight` / `provision`) de dos maneras:
- establezca `ER_RECIPES_DB` en la ruta de la base de datos, o
- pase `--db <ruta>` en cualquier comando.
- Si no se establece ninguno de los dos, `er` busca `../../readouts/tensor-engine-knowledge/engines.db` en relación con el repositorio. Cuando falta la base de datos, obtiene un error claro (`no se encontró la base de datos de recetas: ... — establezca $ER_RECIPES_DB o pase --db`), no un rastreo de pila.

La capa de recetas es la entrada de conocimiento confiable (vea [Seguridad / modelo de amenazas](#security--threat-model)). Obtenga `engines.db` de la distribución de `tensor-engine-knowledge`; `engine-room` lo lee **solo en modo lectura** y nunca lo escribe.

Una receta es **polimórfica**: cuatro tipos, cada uno con una forma diferente:

| Tipo | Qué hace | Medido por |
|------|--------------|-------------|
| `launchable-server` | inicia un servidor de larga duración en un puerto | rendimiento (tokens/s, iteraciones/s) |
| `batch-producer` | se ejecuta, escribe un artefacto y se cierra | calidad de la salida + tiempo transcurrido |
| `modifier` | una superposición que se integra fácilmente y acelera otra receta | un delta medido |
| `router-fleet` | un front-end que enruta a otras recetas | estado por motor upstream |

## Reproducible y validado por diseño

- **Artefactos fijados y empaquetados** (un hash contra un índice curado no es suficiente cuando el índice elimina el canal; la fijación debe ser una copia con dirección de contenido).
- Las **líneas base medidas** están vinculadas al modelo y contienen una banda de compatibilidad, por lo que una actualización rutinaria del controlador no las invalida.
- Se ejecuta una **puerta de control de corrección antes de cualquier afirmación de rendimiento**, conectable por modalidad de salida.
- **Cada paso irreversible tiene un "deshacer" con nombre** con un estado honesto posterior a la reversión; los que son globales para toda la máquina requieren una aprobación humana explícita.

## Estado

El ejecutor está implementado. La CLI `er` lee la capa de recetas y resuelve una receta para el equipo activo (`rig` / `list` / `show` / `preflight`, todos sin efectos secundarios), y el sistema de aprovisionamiento ejecuta el ciclo de reconciliación: **en modo de prueba por defecto**, con una ruta `--execute` configurada que materializa los artefactos fijados, lanza un servidor local y lo mide en relación con la línea base de la receta (`provision` / `teardown` / `status`). Consulte [`executor/README.md`](executor/README.md).

La reproducibilidad es honestamente parcial hoy: las fijaciones se resuelven contra un índice, y los artefactos no fijados se aceptan; empaquetarlos en un almacén con dirección de contenido para que la `reproducibilidad` sea *ganada* es el **Objetivo 1**.

La interfaz de usuario del operador se incluye como un prototipo autónomo (datos simulados + efectos secundarios simulados por temporizador, fiel a la API JSON/WS real):

- [`app/`](app/) — el Panel de control: explore las recetas y ejecútelas, con telemetría en vivo, paradas ANDON y reversión. Diseñado a partir de [`design/ui-control-panel.claude-design-brief.md`](design/ui-control-panel.claude-design-brief.md) (el mapa completo del controlador de eventos y los requisitos de usabilidad).

## Seguridad / modelo de amenazas

La **capa de recetas** (`tensor-engine-knowledge/engines.db`) es la entrada de conocimiento confiable: las recetas verificadas y con origen que indican qué construir y qué objetivos alcanzar. `engine-room` lo trata como la fuente de verdad.

`er provision --execute` es el único comando que interactúa con el equipo. Está **protegido por un `--execute` y un `--model` explícitos**: todos los demás comandos, y `provision` sin `--execute`, son de solo lectura / modo de prueba. Cuando se ejecuta, realiza lo siguiente:

- **descarga** los artefactos fijados de la receta y **verifica su hash SHA256** *cuando la fijación contiene un hash*; actualmente se aceptan las fijaciones o hashes de marcador de posición (la brecha del Objetivo 1 mencionada anteriormente; trate la base de datos de recetas y sus URL de artefactos como confiables hasta que esto se implemente),
- **extrae** los archivos en un directorio por instancia (nunca en PATH global),
- **lanza** un servidor local (`127.0.0.1`) y puede **detenerlo**: la reversión está verificada por identidad (solo mata un PID cuyo ejecutable se encuentra en nuestro directorio de instancia, por lo que nunca mata un proceso no relacionado).

Cada paso irreversible se registra en un libro de contabilidad *antes* de que se ejecute y tiene un compensador con nombre, ordenado del más reciente al más antiguo. Para informar sobre una vulnerabilidad, consulte [`SECURITY.md`](SECURITY.md).

## Soporte

engine-room está en **mantenimiento activo**. Las correcciones de seguridad se implementan en la **última versión menor** (la línea 1.0.x); consulte [`SECURITY.md`](SECURITY.md) para ver las versiones compatibles y el canal de comunicación privado para informar sobre problemas. Envíe informes de errores y solicitudes de nuevas funciones como incidencias de GitHub.

## Licencia

MIT — consulte [LICENSE](LICENSE).

---

<p align="center">Built by <a href="https://mcp-tool-shop.github.io/">MCP Tool Shop</a>.</p>
