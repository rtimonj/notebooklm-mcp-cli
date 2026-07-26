# Cómo se hizo: bitácora de prompts

Documentación del proceso de securización del fork `notebooklm-mcp-cli`
(`github.com/rtimonj/notebooklm-mcp-cli`, rama `secure`).

Recoge, en orden cronológico, **todos los prompts enviados a Claude Code**. La
planificación, el análisis de código y la redacción de estos prompts se hicieron
en conversaciones aparte (chat de Claude.ai); la ejecución sobre la máquina real
la hizo Claude Code.

**Metodología general** — patrón repetido en cada ronda:

1. Analizar el código y decidir qué hacer (chat).
2. Redactar un prompt completo y autocontenido (chat).
3. Ejecutarlo con aprobación paso a paso (Claude Code).
4. Traer el resultado de vuelta y decidir lo siguiente (chat).

**Reglas constantes en todos los prompts:**

- Mostrar cada comando antes de ejecutarlo y esperar aprobación para
  instalaciones, cambios fuera del repo y cualquier `git push`.
- Nunca hacer push sin preguntar. Push solo a `origin` (el fork), jamás a
  `upstream`.
- Nada de `nlm login` ni credenciales reales durante el desarrollo.
- Proponer el diseño antes de implementar, en cambios no triviales.
- Añadir tests a cada cambio y pasar `pytest` + `ruff` antes del commit.
- Mostrar el diff completo y esperar aprobación antes de commitear.

---

## Índice

1. [Preparación del entorno y Parche 1 — cifrado de credenciales](#1)
2. [Parche 2 — modo solo-lectura de herramientas MCP](#2)
3. [Parche 3 — minimizar la ventana del puerto CDP](#3)
4. [Integración de los tres parches en `secure`](#4)
5. [Auditoría de seguridad independiente](#5)
6. [Cuarta ronda — correcciones de los 7 hallazgos](#6)
7. [Commits atómicos por hallazgo](#7)
8. [Integración de `feat/audit-fixes` y push](#8)
9. [Escaneo del servidor MCP con mcp-scan](#9)
10. [Documentación de la prueba real](#10)
11. [Hallazgo en producción — bypass de `NOTEBOOKLM_DISABLE_ENCRYPTION`](#11)
12. [Integración de la corrección y verificación en binario](#12)
13. [Cierre de la documentación operativa](#13)
14. [Procedimiento reutilizable de sincronización con upstream](#14)

---

<a id="1"></a>
## 1. Preparación del entorno y Parche 1 — cifrado de credenciales

**Contexto previo:** auditoría manual del proyecto original leyendo
`services/sharing.py`, `services/notebooks.py`, `services/auth.py` y
`utils/cdp.py`. Conclusión: el código estaba mejor de lo que sugería su README
(«vibe coding» declarado por el autor), pero las cookies de sesión de Google se
guardaban en **texto claro** en disco.

**Resultado:** `uv` instalado, fork clonado por SSH, línea base de tests en
verde, y cifrado Fernet + keyring implementado con migración automática.

````text
Vamos a trabajar sobre un fork mío del proyecto notebooklm-mcp-cli para 
añadirle mejoras de seguridad. Mi fork está en:
https://github.com/rtimonj/notebooklm-mcp-cli

REGLAS GENERALES PARA TODA LA SESIÓN:
- Muéstrame cada comando antes de ejecutarlo y espera mi aprobación para 
  cualquier cosa que instale software, modifique archivos fuera del repo, 
  o haga git push.
- No hagas push a GitHub en ningún momento sin preguntarme primero.
- Usa siempre la URL SSH para operaciones con mi fork (tengo el acceso a 
  GitHub configurado por SSH y verificado con ssh -T git@github.com).
- No ejecutes "nlm login" ni ningún comando que toque credenciales reales 
  de Google en esta sesión.

FASE 0 — Preparar herramientas:
1. Comprueba si tengo "uv" instalado (uv --version). Si no, consulta la 
   documentación oficial de Astral (docs.astral.sh/uv) para confirmar el 
   método de instalación actual en Linux, muéstramelo, y tras mi 
   aprobación instálalo. Verifica después que uv queda en el PATH.
2. Comprueba que tengo git configurado (git config user.name / user.email).

FASE 1 — Clonar y establecer línea base:
3. Clona mi fork usando SSH:
   git clone git@github.com:rtimonj/notebooklm-mcp-cli.git
4. Añade el repo original como remote "upstream" (solo lectura, HTTPS):
   https://github.com/jacob-bd/notebooklm-mcp-cli
5. Instala las dependencias de desarrollo (el proyecto usa uv; revisa su 
   README/CLAUDE.md para el comando exacto, debería ser algo como 
   uv pip install -e ".[dev]").
6. Ejecuta la suite completa de tests (uv run pytest) y muéstrame el 
   resultado. NO sigas a la fase 2 si hay tests fallando; en ese caso 
   analiza por qué y coméntamelo.

FASE 2 — Parche de seguridad 1: cifrado de credenciales en reposo.
Contexto: actualmente el proyecto guarda cookies de sesión de Google en 
texto claro en ~/.notebooklm-mcp-cli (profiles/<nombre>/cookies.json y el 
legacy auth.json). Objetivo: cifrarlas en reposo.

7. Crea una rama: git checkout -b feat/encrypt-credentials-at-rest
8. Estudia primero estos archivos y explícame el flujo de guardado/carga 
   antes de escribir código:
   - src/notebooklm_tools/core/auth.py (AuthManager, save/load de perfiles)
   - src/notebooklm_tools/services/auth.py (atención a 
     _update_profile_on_success, que REESCRIBE el perfil en disco tras 
     cada chequeo de salud exitoso — el cifrado debe cubrir también esa 
     ruta de escritura)
   - Cualquier otro punto del código que escriba o lea cookies.json o 
     auth.json (búscalo con grep).
9. Propónme un diseño antes de implementar. Requisitos:
   - Cifrado simétrico (Fernet, librería cryptography) con la clave 
     guardada en el keyring del sistema (librería keyring; en mi Ubuntu 
     será GNOME Keyring / Secret Service).
   - Fallback claro y explícito si no hay keyring disponible (p. ej. 
     sesión SSH sin DBus): avisar al usuario, nunca fallar silenciosamente 
     a texto claro sin avisar.
   - Migración automática: si al cargar encuentra un perfil en texto 
     claro, lo cifra y elimina la versión sin cifrar de forma segura.
   - Retrocompatibilidad con la estructura de perfiles existente y con 
     get_active_auth_mtime() (la invalidación por mtime debe seguir 
     funcionando).
   - Permisos 0o600 desde la creación del archivo (el proyecto ya lo hace 
     así en _save_port_map de utils/cdp.py — sigue ese mismo patrón).
10. Tras mi aprobación del diseño: implementa, añade tests unitarios del 
    cifrado/descifrado/migración, y ejecuta uv run pytest y 
    uv run ruff check src/ hasta que todo pase.
11. Muéstrame el diff completo (git diff) y espera mi aprobación antes 
    del commit. Mensaje de commit en inglés, estilo del proyecto.

Al terminar, resume qué se ha hecho y qué quedaría para los parches 2 
(modo solo-lectura de herramientas MCP) y 3 (minimizar ventana del puerto 
CDP), que haremos en ramas separadas.
````

> **Nota de diseño:** el punto clave del parche no era escribir el cifrado, sino
> **no dejar ninguna ruta de escritura sin cubrir**. De ahí el énfasis en
> `_update_profile_on_success`, que reescribe el perfil tras cada chequeo de
> salud: cifrar solo el login inicial habría dejado la primera verificación
> exitosa escribiendo en claro otra vez.

---

<a id="2"></a>
## 2. Parche 2 — modo solo-lectura de herramientas MCP

**Problema:** el servidor exponía ~39 herramientas, incluidas compartir
públicamente, invitar colaboradores y borrar. Un agente confundido podía hacer
público un notebook privado.

**Resultado:** tres modos (`readonly` / `standard` / `full`), con `standard` por
defecto y las 7 herramientas peligrosas solo en `full`.

````text
Continuamos con el fork de notebooklm-mcp-cli. Ya está hecho el parche 1 
(cifrado de credenciales, rama feat/encrypt-credentials-at-rest). Ahora 
vamos con el parche 2: modo solo-lectura para las herramientas MCP.

Mantén las mismas reglas de la sesión anterior: muéstrame los comandos 
antes de ejecutar acciones importantes, nada de push sin preguntar, nada 
de "nlm login" ni credenciales reales de Google.

CONTEXTO: el servidor MCP expone ~39 herramientas, incluidas varias 
destructivas o de exposición de datos: compartir notebooks públicamente 
(notebook_share o equivalente), invitar colaboradores, borrar notebooks, 
borrar fuentes/artefactos. Si un agente de IA malinterpreta una 
instrucción, podría hacer público un notebook privado o borrar datos. 
Objetivo: que por defecto el servidor arranque en modo solo-lectura y la 
escritura sea opt-in explícito.

PASOS:
1. Parte de main actualizado y crea la rama: 
   git checkout main && git checkout -b feat/readonly-mode
   (Este parche debe ser independiente del parche 1; ya los combinaremos.)
2. Estudia y explícame cómo se registran las herramientas MCP:
   - src/notebooklm_tools/mcp/server.py (facade)
   - src/notebooklm_tools/mcp/tools/ (definiciones por dominio)
   - Comprueba si el proyecto ya tiene algún mecanismo de "selective tool 
     exposure" (el README lo menciona) — si existe, propón construir 
     sobre él en vez de duplicarlo.
3. Clasifica las ~39 herramientas en tres niveles y muéstrame la tabla 
   para que yo la apruebe o ajuste:
   - LECTURA: listar, consultar, describir, estado, descargas
   - ESCRITURA NORMAL: crear/renombrar notebooks, añadir fuentes, 
     generar artefactos
   - PELIGROSAS: compartir público, invitar colaboradores, borrar 
     notebooks/fuentes/artefactos
4. Propónme un diseño antes de implementar. Requisitos:
   - Config nueva (p. ej. tools.mode en la config del proyecto, con 
     override por variable de entorno NLM_TOOLS_MODE) con tres valores: 
     "readonly" (solo LECTURA), "standard" (LECTURA + ESCRITURA NORMAL, 
     valor por defecto) y "full" (todo).
   - En modo readonly/standard, las herramientas excluidas NO deben 
     registrarse en el servidor MCP (no basta con que devuelvan error: 
     no deben aparecer en la lista de tools, para no gastar contexto ni 
     tentar al agente).
   - El CLI (nlm) NO se ve afectado: los tres modos aplican solo al 
     servidor MCP. El CLI lo maneja un humano directamente.
   - Mensaje claro en el arranque del servidor indicando el modo activo 
     y cuántas herramientas quedan expuestas.
5. Tras mi aprobación: implementa, añade tests (al menos: cada modo 
   registra exactamente las herramientas esperadas), y pasa 
   uv run pytest y uv run ruff check src/.
6. Muéstrame el diff completo y espera mi aprobación antes del commit.

Al terminar, resume y deja listo el terreno para el parche 3 (minimizar 
la ventana del puerto CDP en utils/cdp.py).
````

> **Decisiones tomadas:** el default es `standard`, no `readonly` — un default
> demasiado restrictivo haría que el MCP pareciera «roto» en el primer uso. Y
> las herramientas excluidas **no se registran** en lugar de bloquearse al
> ejecutar: mejor para seguridad y además ahorra ventana de contexto.

---

<a id="3"></a>
## 3. Parche 3 — minimizar la ventana del puerto CDP

**Problema:** mientras Chrome corre con `--remote-debugging-port`, cualquier
proceso local del mismo usuario puede leer las cookies por CDP. No se puede
eliminar; sí se puede reducir el tiempo de exposición.

**Resultado:** cierre inmediato de Chrome tras extraer cookies, timeout de login
configurable (300 s) y puerto efímero.

````text
Continuamos con el fork de notebooklm-mcp-cli. Ya están hechos el parche 1 
(cifrado de credenciales) y el parche 2 (modo solo-lectura). Ahora el 
parche 3: minimizar la ventana de exposición del puerto de Chrome 
DevTools (CDP).

Mantén las mismas reglas: comandos importantes con aprobación previa, 
nada de push sin preguntar, nada de "nlm login" real en esta sesión 
(las pruebas de este parche se harán con mocks/tests, no con mi cuenta).

CONTEXTO: la autenticación lanza Chrome con --remote-debugging-port. 
Mientras ese puerto está abierto, CUALQUIER proceso local del mismo 
usuario puede conectarse por CDP y leer las cookies de la sesión de 
Google, igual que hace la propia herramienta. El código ya tiene 
mitigaciones buenas (port map con permisos 0600, verificación de que el 
Chrome mapeado pertenece al perfil vía cmdline, fail-closed). El objetivo 
ahora es reducir al mínimo el TIEMPO que ese puerto está abierto.

PASOS:
1. Parte de main y crea la rama:
   git checkout main && git checkout -b feat/minimize-cdp-window
2. Estudia src/notebooklm_tools/utils/cdp.py completo (también la parte 
   final: extract_cookies_via_cdp, extract_cookies_via_existing_cdp, 
   run_headless_auth) y los flujos de login en cli/ que lo usan. 
   Explícame ANTES de tocar nada:
   - En el login interactivo: ¿cuánto tiempo queda Chrome abierto con el 
     puerto de debugging tras extraer las cookies? ¿Se cierra solo o 
     queda abierto indefinidamente?
   - En el refresco headless automático: ¿se termina el Chrome headless 
     inmediatamente tras extraer, o persiste?
   - ¿Hay reutilización de instancias abiertas (find_existing_nlm_chrome) 
     que prolongue la ventana?
3. Propónme un diseño antes de implementar. Requisitos:
   - Tras extraer cookies con éxito (interactivo y headless), terminar el 
     Chrome lanzado por la herramienta lo antes posible (ya existe 
     terminate_chrome con cierre graceful vía Browser.close — úsalo).
   - Timeout de login interactivo: si el usuario no completa el login de 
     Google en N minutos (configurable, p. ej. 5 por defecto), cerrar 
     Chrome y abortar con mensaje claro, en vez de dejar el puerto 
     abierto indefinidamente.
   - Usar puerto efímero/aleatorio disponible en vez de empezar siempre 
     por el 9222 predecible (ya existe find_available_port; valorar 
     arrancar desde un puerto aleatorio del rango dinámico).
   - No romper la reutilización legítima de instancias ni los flujos 
     con navegador externo ya abierto (extract_cookies_via_existing_cdp): 
     en ese caso el Chrome no es nuestro y NO debemos cerrarlo, solo 
     documentar el riesgo.
   - Añadir al README/docs una sección breve "CDP security model" que 
     documente el riesgo residual honesto: mientras el puerto esté 
     abierto, otro proceso local del usuario podría leer la sesión.
4. Tras mi aprobación: implementa, añade tests (con mocks del proceso 
   Chrome y del websocket; el proyecto ya tiene tests de cdp en los que 
   apoyarte), y pasa uv run pytest y uv run ruff check src/.
5. Muéstrame el diff completo y espera aprobación antes del commit.

Al terminar: resume los tres parches, y propónme el plan para 
combinarlos (merge de las tres ramas en una rama integradora, p. ej. 
"secure", resolución de conflictos si los hay, y suite completa de 
tests sobre el resultado combinado). NO hagas el merge todavía.
````

> **Decisión:** si el usuario tiene su propio Chrome con debugging activo y la
> herramienta se conecta a él, **no** se cierra — cerrarle el navegador al
> usuario sería peor remedio que enfermedad. Ahí solo se documenta el riesgo.

---

<a id="4"></a>
## 4. Integración de los tres parches en `secure`

**Resultado:** rama integradora `secure` con los tres parches y la suite en verde.

````text
Fase de integración del fork de notebooklm-mcp-cli. Tenemos tres ramas 
con parches de seguridad, cada una partiendo de main:
- feat/encrypt-credentials-at-rest (cifrado de credenciales)
- feat/readonly-mode (modos de exposición de herramientas MCP)
- feat/minimize-cdp-window (reducción de ventana CDP)

Mantén las reglas de siempre: comandos importantes con aprobación, nada 
de push sin preguntar, nada de "nlm login" real todavía.

PASOS:
1. Crea la rama integradora desde main: 
   git checkout main && git checkout -b secure
2. Mergea las tres ramas de una en una, en este orden (de menos a más 
   probabilidad de conflicto): feat/readonly-mode, 
   feat/minimize-cdp-window, feat/encrypt-credentials-at-rest.
   Tras CADA merge: ejecuta uv run pytest. Si hay conflictos, 
   muéstramelos y propón la resolución antes de aplicarla — especial 
   atención a solapes entre el parche 1 y el 3 (ambos tocan rutas de 
   guardado/estado en core/auth y utils/cdp).
3. Con las tres integradas: suite completa (uv run pytest), lint 
   (uv run ruff check src/), y además una revisión cruzada que te pido 
   explícitamente: verifica que el cifrado del parche 1 sigue cubriendo 
   TODAS las rutas de escritura de credenciales también después del 
   merge (grep de escrituras a cookies.json / auth.json), y que 
   get_active_auth_mtime() sigue funcionando con los archivos cifrados.
4. Instala el paquete resultante de forma local y aislada 
   (uv tool install --force .) y verifica que:
   - "nlm --version" y "nlm --help" funcionan
   - el servidor MCP arranca en modo standard y muestra el mensaje de 
     modo/número de herramientas (sin conectar a nada real: basta 
     arrancar y ver el log de inicio)
5. Muéstrame un resumen final: diff total respecto a main 
   (git diff main..secure --stat), lista de cambios funcionales, y 
   cualquier riesgo residual que veas.
6. Si te doy el OK: commit de merge si queda algo pendiente y push de 
   la rama secure a mi fork (origin, SSH). Pídeme confirmación explícita 
   justo antes del push.
````

---

<a id="5"></a>
## 5. Auditoría de seguridad independiente

**Objetivo:** revisar con ojo escéptico el resultado combinado, incluyendo los
archivos que no se habían leído a fondo (`core/client.py`, `core/auth.py`
completo, el final de `cdp.py`, todo `mcp/`).

**Resultado:** 7 hallazgos, ninguno crítico ni alto. Todas las categorías graves
(command injection, deserialización insegura, secretos hardcodeados, TLS sin
verificar, bypass del gating, fugas de cookies en requests) verificadas limpias.

````text
Auditoría de seguridad del fork notebooklm-mcp-cli, sobre la rama secure 
(que integra los tres parches: cifrado de credenciales, modo solo-lectura 
MCP, y minimización de ventana CDP).

Actúa como un revisor de seguridad independiente y escéptico. NO asumas 
que los parches que ya hicimos son correctos: tu trabajo es encontrar 
fallos en ellos y en el resto del proyecto. No hagas cambios en esta 
sesión; solo audita y repórtame hallazgos priorizados.

ALCANCE — revisa especialmente los archivos que aún no habíamos leído a 
fondo, además de los parcheados:
1. src/notebooklm_tools/core/client.py — construcción de peticiones RPC, 
   cabeceras, manejo de session_id/CSRF, y si alguna cookie o token 
   puede acabar en logs, mensajes de error o excepciones.
2. src/notebooklm_tools/core/auth.py completo — el almacén real de 
   credenciales tras nuestro parche de cifrado. Verifica que NO queda 
   ninguna ruta que escriba credenciales en claro.
3. src/notebooklm_tools/utils/cdp.py completo, incluida la parte final 
   (extract_cookies_via_cdp, run_headless_auth).
4. Todo src/notebooklm_tools/mcp/ — que el modo readonly/standard 
   realmente impide registrar las tools peligrosas, sin bypass.

BUSCA EN CONCRETO:
- Fugas de credenciales en logs/errores/excepciones (grep de logging que 
  pueda incluir cookies, tokens, o el objeto profile completo).
- Command injection en las llamadas subprocess a Chrome (¿algún argumento 
  viene de input del usuario o de config sin sanitizar?).
- Path traversal en nombres de perfil (profiles/<nombre>) — ¿puedo 
  escapar del directorio con "../" en un nombre de perfil?
- Prompt injection / tool poisoning en las DESCRIPCIONES de las tools 
  MCP (texto que el agente lee y podría ser manipulado).
- Deserialización insegura, eval, exec, pickle.
- Cualquier secreto hardcodeado.
- Manejo de errores que falle "abierto" en vez de "cerrado" en rutas 
  de seguridad.
- Race conditions / TOCTOU en la escritura de credenciales cifradas.

ENTREGABLE: una tabla de hallazgos con severidad (crítica/alta/media/baja), 
archivo:línea, descripción, y propuesta de mitigación. Ordénala por 
severidad. Si no encuentras nada en alguna categoría, dilo explícitamente 
en vez de rellenar. Al final, dime tu veredicto honesto: ¿confiarías en 
este código con una cuenta secundaria de Google? ¿Y con una principal?
````

> **Clave del prompt:** pedir explícitamente que diga «no encontré nada» en las
> categorías limpias, en vez de rellenar. Y pedir un veredicto honesto al final,
> que obliga a sintetizar en vez de enumerar.

---

<a id="6"></a>
## 6. Cuarta ronda — correcciones de los 7 hallazgos

Los hallazgos se clasificaron en tres grupos: **bugs objetivos** (#1, #3, #5),
**defensa en profundidad** (#6, #7) y **decisiones de diseño** (#2, #4), estas
últimas decididas explícitamente antes de implementar.

````text
Cuarta ronda sobre el fork notebooklm-mcp-cli: correcciones de la 
auditoría de seguridad. Trabaja sobre una rama nueva partiendo de secure.

Reglas de siempre: comandos importantes con aprobación previa, nada de 
push sin preguntar, nada de "nlm login" real. Para cada corrección añade 
o actualiza tests, y al final pasa uv run pytest y uv run ruff check src/.

1. Crea la rama: git checkout secure && git checkout -b feat/audit-fixes

CORRECCIONES OBJETIVAS (bugs):

2. [#1 — fail-open en cdp.py] En _mapped_chrome_owns_profile 
   (aprox. cdp.py:628), cambiar el caso "pid is None" para que devuelva 
   False en vez de True, alineándolo con el resto de la función 
   (fail-closed). Una entrada legítima del port map siempre trae pid 
   (lo escribe _write_port_map), así que confiar en una sin pid es un 
   fallo. Añade un test que verifique que una entrada sin pid NO se 
   reutiliza.

3. [#3 — race/TOCTOU en la generación de clave] En credential_store.py 
   (get_encryption_key, aprox. líneas 61-86), proteger la generación de 
   clave con un threading.Lock a nivel de módulo, con el patrón 
   double-checked: adquirir el lock y RE-LEER el keyring antes de generar 
   (si otro hilo ya escribió una clave, usar esa, no generar otra). El 
   proyecto ya usa este patrón en services/auth.py (get_auth_health_checker) 
   — síguelo. Añade un test que simule dos accesos concurrentes y 
   verifique que solo se genera una clave.

4. [#5 — escritura no atómica] En credential_store.py (write_secure_json, 
   aprox. líneas 149-161), escribir a un archivo temporal (path.tmp con 
   permisos 0o600 desde la creación, os.open con O_CREAT|O_EXCL|O_WRONLY) 
   y luego os.replace() atómico sobre el destino. Mantén los permisos 
   0o600 en el resultado final. Documenta en un comentario que el borrado 
   seguro del plaintext previo (en la migración) es inviable en SSD/FS con 
   journaling — es una limitación conocida, no la intentes resolver.

CORRECCIONES DE DEFENSA EN PROFUNDIDAD:

5. [#6 — validación de nombre de perfil] En AuthManager.__init__ y/o 
   get_profile_dir (config.py, aprox. líneas 111-115), validar el nombre 
   de perfil contra ^[A-Za-z0-9._-]+$ y rechazar explícitamente nombres 
   con separadores de ruta o "..". Lanza un error claro si no valida. 
   Añade un test con "../../foo" y similares.

6. [#7 — CSRF en logs DEBUG] En base.py (aprox. líneas 887-890), donde se 
   loguea el cuerpo de respuesta en modo debug, redactar los patrones de 
   token CSRF (p. ej. SNlM0e / el patrón del token) antes de escribir al 
   log, igual que ya se redacta el at= en las requests. Añade un test que 
   verifique que un CSRF en el cuerpo no aparece en claro en el log.

CAMBIOS DE DISEÑO (ya decididos):

7. [#2 — borrado fuera del modo por defecto] Mover las SUB-ACCIONES de 
   borrado de notas y etiquetas (action="delete" en las tools de 
   note/label, aprox. labels.py:130 y notes.py:67) del tier WRITE al 
   comportamiento del tier DANGEROUS, de forma que en los modos readonly 
   y standard el borrado de notas/etiquetas NO esté disponible, y solo 
   funcione en modo full. Importante: NO muevas las tools enteras (crear/
   renombrar/listar notas y etiquetas deben seguir en standard); solo la 
   capacidad de borrado. Si la arquitectura actual no permite gating por 
   sub-acción y solo por tool, dímelo y propón la mejor forma antes de 
   implementar. Añade tests que verifiquen que delete de nota/etiqueta 
   está bloqueado en standard y permitido en full.

8. [#4 — require_encryption opcional] Añadir una opción de configuración 
   require_encryption (con override por variable de entorno, p. ej. 
   NLM_REQUIRE_ENCRYPTION) que por defecto sea false (mantiene el 
   fallback actual a texto claro con warning). Cuando sea true, la 
   escritura de credenciales debe FALLAR CERRADA (lanzar error, no 
   escribir en claro) si el keyring no está disponible. Además, cuando 
   se produzca el fallback a texto claro (en modo default), eleva la 
   visibilidad del aviso: que sea un warning claramente visible en el 
   arranque del servidor MCP, no solo una línea perdida en stderr. Añade 
   tests para ambos comportamientos (default degrada con warning; 
   require_encryption=true falla cerrada).

Al terminar: muéstrame el diff completo (git diff secure..feat/audit-fixes), 
un resumen de qué se corrigió, y confirma que pytest y ruff pasan. NO 
hagas merge ni push todavía.
````

> **Resultado del #2:** Claude Code respondió que la arquitectura solo permitía
> gating por herramienta completa, y propuso un guard en runtime
> (`deletion_allowed` / `deletion_blocked_result`) comprobado antes de construir
> el cliente. Se aprobó esa alternativa. Pedirle que **consulte si no es viable**
> evitó una implementación forzada.

---

<a id="7"></a>
## 7. Commits atómicos por hallazgo

**Por qué separados:** facilita abrir PRs selectivos a upstream y permite
revertir un fix sin arrastrar los demás.

````text
Haz commits SEPARADOS por hallazgo en la rama feat/audit-fixes, en este 
orden. Antes de empezar, mira el historial reciente (git log --oneline -15) 
y si el proyecto NO usa el estilo conventional-commits, adapta estos 
mensajes a su convención y dímelo. Muéstrame git status y qué archivos 
asignas a cada commit ANTES de crear el primero; agrupa los archivos por 
hallazgo (usa git add selectivo, no git add -A). No hagas push.

Commits (mensaje + alcance):

1. fix(cdp): fail closed when chrome ownership cannot be verified
   Archivos de #1 (cdp.py + sus tests).

2. fix(credentials): prevent key generation race with double-checked lock
   Archivos de #3 (credential_store.py + test de concurrencia).

3. fix(credentials): write credential files atomically via temp + replace
   Archivos de #5 (credential_store.py write_secure_json + tests).

4. fix(config): validate profile names to prevent path traversal
   Archivos de #6 (config.py + tests/test_profile_name_validation.py).

5. fix(logging): redact CSRF tokens from debug response logs
   Archivos de #7 (core/utils.py, base.py + tests).

6. feat(mcp): gate note/label deletion behind full tools mode
   Archivos de #2 (note/label tools + deletion_allowed helper + tests).

7. feat(credentials): add require_encryption option to fail closed
   Archivos de #4 (config, credential_store, server.py banner + tests).

Si algún archivo toca varios hallazgos (p. ej. credential_store.py aparece 
en #3, #5 y #7), sepáralo por hunks con git add -p para que cada commit 
contenga solo los cambios de su hallazgo. Si eso no es limpiamente 
posible, dímelo y decidimos cómo agrupar en vez de forzarlo.

Tras cada commit no hace falta re-ejecutar toda la suite, pero al final, 
con los 7 commits hechos, corre uv run pytest una vez para confirmar que 
la rama entera sigue en verde. Muéstrame git log --oneline -8 al terminar.
````

---

<a id="8"></a>
## 8. Integración de `feat/audit-fixes` y push

````text
Integración final en el fork notebooklm-mcp-cli. La rama feat/audit-fixes 
tiene los 7 commits de correcciones de la auditoría, sobre secure. Vamos a 
integrarla en secure y subir a mi fork.

Reglas de siempre. El push es SOLO a origin (mi fork, git@github.com:
rtimonj/notebooklm-mcp-cli.git); nunca a upstream. Pídeme confirmación 
explícita justo antes de cualquier push.

PASOS:
1. Muéstrame git log --oneline secure..feat/audit-fixes para confirmar que 
   están los 7 commits esperados.
2. git checkout secure && git merge feat/audit-fixes
   Como feat/audit-fixes salió de secure y secure no ha avanzado, debería 
   ser un fast-forward sin conflictos. Si por lo que sea NO es 
   fast-forward o hay conflictos, PARA y muéstramelos antes de resolver.
3. Ejecuta la suite completa sobre secure ya integrada: uv run pytest, 
   uv run ruff check src/ y uv run ruff format --check src/ tests/. 
   Confírmame que todo pasa.
4. Muéstrame el diff acumulado total respecto a main: 
   git diff main..secure --stat (para ver el alcance completo de las 
   cuatro rondas de trabajo).
5. Si te doy el OK explícito: push de secure a origin 
   (git push origin secure). Pídeme confirmación justo antes.
6. Opcional, pregúntame: ¿quieres que suba también las ramas individuales 
   (feat/encrypt-credentials-at-rest, feat/readonly-mode, 
   feat/minimize-cdp-window, feat/audit-fixes) a origin, o solo secure? 
   Por defecto, solo secure salvo que yo diga lo contrario.

Al terminar, resume: qué quedó en origin, y recuérdame que el siguiente 
paso es (a) escanear el servidor MCP con mcp-scan y (b) la prueba real con 
la cuenta secundaria de Google.
````

---

<a id="9"></a>
## 9. Escaneo del servidor MCP con mcp-scan

**Resultado:** 32/39 tools en `standard`, 39/39 en `full`, con las 7 peligrosas
apareciendo solo en `full`. Cero hallazgos; sin caracteres de ancho cero ni bidi
en las descripciones.

**Limitación encontrada:** `mcp-scan` fue renombrado a `snyk-agent-scan` y
eliminó `--local-only`; el escaneo estático ahora exige cuenta Snyk y token. Se
omitió deliberadamente para no compartir datos con terceros. El análisis
heurístico local se hizo igualmente vía `inspect`.

````text
Vamos a escanear el servidor MCP de este proyecto (rama secure, ya con 
todas las correcciones) con mcp-scan, de forma aislada y SIN credenciales 
reales de Google. No ejecutes "nlm login" ni uses ningún perfil con 
cookies reales. Reglas de siempre: comandos importantes con aprobación.

PASO 1 — Averiguar cómo se arranca el servidor MCP:
Busca en el proyecto (pyproject.toml [project.scripts], README, docs, 
CLAUDE.md) el comando EXACTO que lanza el servidor MCP por stdio. 
Probablemente sea algo como "nlm mcp" o similar, pero NO lo asumas: 
confírmalo en el código/config y muéstrame qué comando es y de dónde lo 
has sacado. Verifícalo también con --help (p. ej. nlm --help y el 
subcomando correspondiente).

PASO 2 — Crear un config MCP aislado solo para el escaneo:
Crea un archivo temporal, p. ej. ./mcp-scan-config.json, con la estructura 
estándar de config MCP (formato mcpServers), apuntando al comando del 
paso 1. Fuerza un perfil VACÍO/inexistente para que no haya credenciales: 
usa una variable de entorno de perfil dedicada (p. ej. 
NLM_PROFILE=scan-empty) o el flag equivalente que hayamos visto en el 
código, de modo que aunque el server arranque, no cargue cookies reales. 
Muéstrame el JSON antes de seguir.

Ejemplo de estructura (ajusta command/args/env a lo real del proyecto):
{
  "mcpServers": {
    "notebooklm": {
      "command": "nlm",
      "args": ["mcp"],
      "env": { "NLM_PROFILE": "scan-empty", "NLM_TOOLS_MODE": "standard" }
    }
  }
}

PASO 3 — Inspección (local, sin arrancar guardrails remotos):
Ejecuta:
  uvx mcp-scan@latest inspect --pretty full ./mcp-scan-config.json
Cuando mcp-scan pida consentimiento (y/n) para arrancar el servidor stdio, 
muéstrame el comando exacto que va a ejecutar y espera mi OK. Enséñame la 
lista completa de tools con sus descripciones que devuelve, y confírmame 
cuántas salen en modo standard (debería reflejar el modo solo-lectura: 
sin las tools peligrosas que gateamos).

PASO 4 — Escaneo estático LOCAL (sin compartir nada con invariantlabs.ai):
Ejecuta:
  uvx mcp-scan@latest scan --local-only --pretty full ./mcp-scan-config.json
Muéstrame el informe completo: prompt injection, tool poisoning, 
cross-references, rug-pull/pinning. 

IMPORTANTE: usa SIEMPRE --local-only en este paso. NO ejecutes el escaneo 
que llama a la API de invariantlabs.ai sin preguntarme antes; quiero 
decidir yo si comparto las descripciones de las tools.

PASO 5 — Verifica también el modo full como contraste:
Repite el inspect del paso 3 pero con NLM_TOOLS_MODE=full en el env del 
config, para ver la diferencia en número de tools expuestas entre standard 
y full. Esto confirma que el gating de modo funciona de verdad a nivel de 
servidor MCP arrancado, no solo en los tests.

Al terminar: resume cuántas tools expone cada modo, y todos los hallazgos 
de seguridad de mcp-scan (o confirma que no hubo ninguno). Limpia el 
config temporal al final (o dime que lo borre).
````

> **Aviso aprendido:** ese `mcp-scan-config.json` incluía
> `NOTEBOOKLM_DISABLE_ENCRYPTION`, lo que más tarde demostró que esa variable se
> cuela en configs por caminos normales. No volver a incluirla.

---

<a id="10"></a>
## 10. Documentación de la prueba real

Prompt de creación de `docs/prueba-real.md`. El contenido del documento se
omite aquí (vive en el propio repo); solo se recoge la instrucción.

````text
Añade un documento de checklist/guía a mi fork notebooklm-mcp-cli, en la 
rama secure. Reglas de siempre; el push es solo a origin (mi fork), con 
confirmación explícita antes.

1. git checkout secure (confirma que estás en secure y limpio con git status).
2. Crea la carpeta docs/ si no existe, y dentro el archivo docs/prueba-real.md 
   con EXACTAMENTE el contenido que va entre las marcas <<<INICIO>>> y 
   <<<FIN>>> (no incluyas las marcas en el archivo).
3. Muéstrame git diff --stat y el status para confirmar que solo se añade 
   ese archivo.
4. Commit: docs: add hardening validation checklist and guide
5. Si te doy el OK, git push origin secure (pídeme confirmación justo antes).

<<<INICIO>>>
[contenido de docs/prueba-real.md — ver el archivo en el repo]
<<<FIN>>>
````

---

<a id="11"></a>
## 11. Hallazgo en producción — bypass de `NOTEBOOKLM_DISABLE_ENCRYPTION`

**Origen:** durante la prueba real apareció en un mensaje de error una variable
no vista antes, documentada en el código como *«used by the test suite»*.

**Importante:** la hipótesis inicial (que tenía precedencia sobre
`require_encryption`) resultó **falsa** — la fase de verificación previa evitó
parchear algo que no estaba roto. Pero sí había un problema distinto y real: la
variable **apagaba las dos alarmas** (bajaba el aviso de WARNING a INFO y hacía
que `plaintext_fallback_active()` devolviera `False`, silenciando el banner del
servidor). Hacía lo peligroso y encima callaba.

````text
Hallazgo de seguridad en el fork notebooklm-mcp-cli (rama secure), 
detectado durante la prueba real. Vamos a verificarlo y, si se confirma, 
corregirlo. Reglas de siempre: comandos importantes con aprobación, nada 
de push sin preguntar, no toques mis perfiles reales de 
~/.notebooklm-mcp-cli.

CONTEXTO DEL HALLAZGO:
En src/notebooklm_tools/utils/credential_store.py conviven dos controles:
- NLM_REQUIRE_ENCRYPTION / auth.require_encryption → debe FALLAR CERRADO 
  (no escribir credenciales) si no hay keyring.
- NOTEBOOKLM_DISABLE_ENCRYPTION (DISABLE_ENCRYPTION_ENV) → fuerza 
  almacenamiento en texto claro; según el docstring de la línea 17 existe 
  "used by the test suite".

Sospecha: DISABLE_ENCRYPTION_ENV tiene precedencia sobre 
require_encryption. Motivo: get_encryption_key() (~línea 75) devuelve None 
si esa env está puesta, y _require_encryption() (~línea 96) devuelve False 
si esa env está puesta. En write_secure_json eso hace que se caiga al 
else y se escriba en PLAINTEXT aunque el operador haya exigido cifrado.

FASE 1 — VERIFICAR (no cambies nada todavía):
1. Muéstrame las líneas 55-105 de credential_store.py y confírmame si la 
   sospecha es cierta o no.
2. Escribe un test que lo demuestre: con keyring no disponible, 
   require_encryption activo Y NOTEBOOKLM_DISABLE_ENCRYPTION=1, comprobar 
   qué hace write_secure_json. Ejecútalo y dime el resultado real.
3. Comprueba también si esa env afecta a la LECTURA (read_secure_json u 
   otras rutas) y si podría hacer que se ignore un archivo ya cifrado.
4. Dame tu veredicto antes de tocar código.

FASE 2 — CORREGIR (solo si se confirma):
5. Rama nueva desde secure: git checkout secure && 
   git checkout -b fix/disable-encryption-bypass
6. Diseño que quiero (propón alternativas si ves algo mejor, pero 
   justifícalo):
   a) PRECEDENCIA: require_encryption SIEMPRE gana. Si están activas las 
      dos a la vez, no se escribe en claro: lanza CredentialStoreError 
      indicando explícitamente que hay una configuración contradictoria.
   b) ACOTAR LA PUERTA DE TEST: NOTEBOOKLM_DISABLE_ENCRYPTION solo debe 
      honrarse en contexto de test. Comprueba primero cómo la usa la 
      suite (grep en tests/) y elige el guard que no rompa los tests 
      existentes: por ejemplo, exigir que exista PYTEST_CURRENT_TEST en 
      el entorno, o un guard equivalente. Si eso rompiera tests que la 
      lanzan en subproceso, dímelo y decidimos juntos en vez de forzarlo.
      Si acotarla no es viable, como mínimo que emita un WARNING bien 
      visible (no INFO) siempre que esté activa fuera de los tests.
   c) Corregir el texto del error de write_secure_json (~línea 202): 
      ahora dice "auth.require_encryption / NOTEBOOKLM_DISABLE_ENCRYPTION 
      unset", que es confuso. Redáctalo claro.
7. Tests: además del de la fase 1, cubre que require_encryption gana sobre 
   disable, que disable sigue funcionando en contexto de test, y que el 
   comportamiento normal (con keyring) no cambia.
8. Pasa uv run pytest y uv run ruff check src/. Muéstrame el diff y espera 
   mi OK antes del commit.
   Mensaje: fix(credentials): prevent NOTEBOOKLM_DISABLE_ENCRYPTION from 
   bypassing require_encryption

FASE 3 — UX del error (menor, mismo commit o commit aparte, tú eliges):
9. Cuando write_secure_json lanza CredentialStoreError durante 
   "nlm login", el CLI muestra un traceback completo de Python en vez de 
   un error limpio (el resto del CLI sí formatea bien, p. ej. 
   "Error: Login timeout"). Captura CredentialStoreError en 
   cli/main.py (login_callback, ~línea 526) y muéstralo con el mismo 
   estilo de error que el resto del CLI.

FASE 4 — DOCUMENTAR:
10. Actualiza docs/prueba-real.md:
    - Marca como completados y validados los bloques ya probados: login 
      con cierre inmediato de Chrome, timeout de 300s, cifrado en reposo 
      (formato __nlm_encrypted__/ciphertext, permisos 0600, clave en 
      keyring service "notebooklm-mcp-cli" / key 
      "credentials-encryption-key"), banner de aviso de plaintext, 
      require_encryption fallando cerrado sin escribir nada, y modo 
      standard exponiendo 32/39 tools.
    - Corrige la verificación de cifrado del documento: el chequeo 
      "si json.load() funciona → no cifrado" es ERRÓNEO, porque el 
      archivo cifrado ES un JSON válido con las claves 
      __nlm_encrypted__ y ciphertext. Sustitúyelo por la comprobación 
      correcta.
    - Añade una sección "Pendiente / TODO" con este hallazgo y su 
      resolución.
    - Deja pendientes y sin marcar los bloques 5 (tres modos sobre 
      cliente MCP real) y 6 (borrado de notas/etiquetas gateado por modo).

Al terminar: resumen de qué se corrigió, resultado de los tests, y NO 
hagas merge ni push todavía.
````

> **Lección metodológica:** separar la fase de *verificar* de la de *corregir*, y
> pedir el veredicto antes de tocar nada, evitó un parche innecesario y sacó a la
> luz el problema verdadero, que era otro.

---

<a id="12"></a>
## 12. Integración de la corrección y verificación en binario

````text
Integra la rama fix/disable-encryption-bypass en secure y sube a mi fork.
Reglas de siempre; push solo a origin, con confirmación explícita antes.

1. git log --oneline secure..fix/disable-encryption-bypass — muéstrame los 
   commits que se van a integrar.
2. git checkout secure && git merge fix/disable-encryption-bypass
   Debería ser fast-forward. Si no lo es o hay conflictos, PARA y 
   muéstramelos.
3. Suite completa sobre secure: uv run pytest, uv run ruff check src/, 
   uv run ruff format --check src/ tests/.
4. Reinstala para que mi CLI quede con la corrección: uv tool install --force .
   Verifica con nlm --version.
5. Comprobación rápida del guard ya instalado: ejecuta
   NOTEBOOKLM_DISABLE_ENCRYPTION=1 NLM_PROFILE=prueba-real notebooklm-mcp
   y confirma que ahora aparece el WARNING de que la variable se ignora 
   fuera de tests. Corta con Ctrl+C. NO uses ningún perfil que no sea 
   prueba-real y no ejecutes nlm login.
6. Si te doy el OK: git push origin secure (confirmación justo antes).
````

---

<a id="13"></a>
## 13. Cierre de la documentación operativa

Convierte `docs/prueba-real.md` de checklist de pruebas en guía operativa:
qué está validado, cómo desplegar con un cliente MCP, cómo diagnosticar los dos
fallos típicos y cómo instalar en una máquina nueva.

````text
Cierre de la prueba real del fork notebooklm-mcp-cli. Todo validado; vamos 
a dejar docs/prueba-real.md completo y utilizable para instalar el 
proyecto en otra máquina. Reglas de siempre: push solo a origin, con 
confirmación explícita antes.

1. git checkout secure && git status (debe estar limpio y en 368c4a8 o 
   posterior).
2. LEE primero docs/prueba-real.md tal como está ahora (ya lo actualizaste 
   en la ronda anterior). Reconcilia lo que ya esté hecho con lo que pido 
   abajo, sin duplicar secciones ni perder lo que ya escribiste. Si algo 
   de lo que pido ya está, déjalo como está.

CAMBIOS A APLICAR:

A) Marcar como VALIDADOS (con fecha 2026-07-26) los siguientes bloques, 
   añadiendo en cada uno la evidencia real observada:
   - Bloque 1 (Parche 3): login OK, "Closing Google Chrome..." impreso 
     antes del éxito → cierre inmediato confirmado. Timeout probado: 
     300s exactos → "Error: Login timeout" con hint claro.
   - Bloque 2 (Parche 1): cookies.json contiene SOLO las claves 
     __nlm_encrypted__ y ciphertext; permisos -rw-------; clave presente 
     en keyring con service "notebooklm-mcp-cli" y key 
     "credentials-encryption-key"; ciclo cifrar/descifrar verificado con 
     "nlm notebook list" funcionando.
   - Bloque 4 (Parche 4): banner de aviso visible al degradar (verificado 
     forzando PYTHON_KEYRING_BACKEND=keyring.backends.fail.Keyring); con 
     NLM_REQUIRE_ENCRYPTION activo → CredentialStoreError y directorio de 
     perfil VACÍO (no se escribió nada). Nota: la variable acepta 
     cualquier valor salvo "", 0, false, no, off (lista negra, falla 
     hacia el lado seguro).
   - Bloque 5 (Parche 2, parcial): modo standard verificado sobre Claude 
     Desktop como cliente MCP real → 32/39 tools expuestas, ninguna de 
     las 7 peligrosas. Los modos readonly y full quedan PENDIENTES a 
     propósito, para probar al instalar en la segunda máquina.
   - Bloque 6 (Parche 2, guard en runtime): VALIDADO end-to-end. El 
     agente envió confirm=true y aun así fue rechazado antes de llegar al 
     cliente, con el mensaje literal:
       "Note deletion is disabled in tools mode 'standard'.
        hint: Set NLM_TOOLS_MODE=full (or [tools].mode = "full") to allow 
        deletion."
     Además buscó vía alternativa (borrar el notebook entero) y no la 
     encontró: notebook_delete no está expuesta en standard. Doble capa 
     confirmada: gating de registro + guard en runtime.
   - Corrección del bypass: verificada sobre el binario instalado, emite 
     "IGNORING NOTEBOOKLM_DISABLE_ENCRYPTION: it is a test-only 
     override...".

B) NUEVA SECCIÓN: "Despliegue con un cliente MCP (requisito de entorno)".
   Explica el problema y la solución, porque es un requisito REAL que 
   aparece precisamente porque ciframos:
   - Cuando un cliente MCP (p. ej. Claude Desktop) lanza el servidor como 
     proceso hijo, puede hacerlo con un entorno reducido SIN 
     DBUS_SESSION_BUS_ADDRESS. Sin DBus no hay acceso al keyring, sin 
     keyring no hay clave, y sin clave no se puede descifrar el perfil: 
     el servidor arranca y lista tools, pero toda operación real falla 
     con "No authentication found".
   - Solución: pasar las variables explícitamente en la config del 
     cliente. Incluye este ejemplo (ajustando rutas y el valor de DBUS, 
     que se obtiene con: echo $DBUS_SESSION_BUS_ADDRESS):

     {
       "mcpServers": {
         "notebooklm": {
           "command": "/home/USUARIO/.local/bin/notebooklm-mcp",
           "env": {
             "NLM_PROFILE": "prueba-real",
             "NLM_TOOLS_MODE": "standard",
             "NLM_REQUIRE_ENCRYPTION": "1",
             "HOME": "/home/USUARIO",
             "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/UID/bus"
           }
         }
       }
     }

   - Explica POR QUÉ se recomienda NLM_REQUIRE_ENCRYPTION=1 en esta 
     config concreta: el servidor arranca en segundo plano y nadie lee 
     stderr; sin esa variable, un fallo del keyring degradaría a texto 
     claro sin que el usuario se entere.
   - Advertencia explícita: NO usar NOTEBOOKLM_COOKIES para "resolver" 
     problemas de autenticación. Eso pone cookies de sesión de Google en 
     texto claro en un archivo de configuración, que es exactamente lo 
     que estos parches evitan. (Un asistente lo sugirió durante la 
     prueba; queda documentado para no caer en ello.)
   - Advertencia: NO incluir NOTEBOOKLM_DISABLE_ENCRYPTION en ningún 
     config. Ya se ignora fuera de tests y emitiría un warning.

C) NUEVA SECCIÓN: "Diagnóstico: keyring vs credenciales caducadas".
   Los dos fallos se parecen desde fuera y se arreglan distinto. La señal 
   que los distingue es el banner de plaintext en el log del servidor:
   - Banner de "system keyring unavailable" presente → problema de 
     ENTORNO. Faltan DBUS_SESSION_BUS_ADDRESS / HOME en la config del 
     cliente. Ver sección B.
   - Sin banner, pero las operaciones fallan con "Authentication expired" 
     o refresh_auth devuelve reason "stale" → CREDENCIALES caducadas. 
     Solución: volver a ejecutar "nlm login" en una terminal (una recarga 
     desde disco no revive tokens expirados); después reiniciar el 
     cliente MCP por completo (más fiable que llamar a refresh_auth).
   - Comandos útiles de diagnóstico (adapta las rutas a la instalación):
       tail -20 ~/.config/Claude/logs/mcp-server-<nombre>.log
       env -i HOME=$HOME PATH=$PATH NLM_PROFILE=<perfil> \
         timeout 10 notebooklm-mcp < /dev/null
     (el segundo reproduce el entorno reducido del cliente)
   - Nota: cerrar sesiones de Google desde la cuenta (Gmail → "Cerrar 
     todas las demás sesiones") invalida también las cookies guardadas 
     por nlm y obliga a repetir el login. Tenerlo en cuenta al hacer 
     limpieza.

D) NUEVA SECCIÓN: "Instalación en una máquina nueva". Guía breve y 
   ordenada, con los pasos reales que seguimos, incluidos los tropiezos:
   1. Requisitos: uv instalado; sesión de escritorio con keyring activo 
      (GNOME Keyring / Secret Service); Chrome/Chromium.
   2. git clone git@github.com:rtimonj/notebooklm-mcp-cli.git && 
      git checkout secure
   3. uv tool install --force .   ← DESDE EL DIRECTORIO, con el punto. 
      AVISO IMPORTANTE: "uv tool install notebooklm-mcp-cli" (sin punto) 
      instala el paquete de PyPI SIN los parches. Nos pasó y provocó que 
      las credenciales se guardaran en texto claro. Verificar siempre 
      con: grep -rl "require_encryption" ~/.local/share/uv/tools/notebooklm-mcp-cli/
   4. NO ejecutar "uv tool upgrade notebooklm-mcp-cli": sobrescribiría el 
      fork con la versión oficial. El aviso de "Update available" que 
      muestra el CLI es esperable (el fork partió de 0.8.9) y debe 
      ignorarse.
   5. nlm login con la cuenta secundaria; verificar cifrado según 
      Bloque 2.
   6. Configurar el cliente MCP según sección B.

E) Actualizar la sección "Pendiente / TODO" para que refleje lo que queda 
   de verdad:
   - Probar modos readonly y full sobre cliente MCP real (bloque 5 
     parcial).
   - Verificar que en modo full sí funciona el borrado de nota/etiqueta 
     (que no bloqueamos de más). Nota: notebook_delete SÍ está entre las 
     7 tools de full; durante la prueba un asistente afirmó lo contrario 
     porque su servidor corría en standard.
   - Mantenimiento: git fetch upstream && git merge upstream/main 
     periódicamente (upstream ya va por 0.9.4, el fork partió de 0.8.9).
   - Opcional: contribuir upstream los parches de seguridad.

F) Revisa que la sección de "riesgo residual" siga presente y correcta.

3. Muéstrame el diff completo del documento antes de commitear.
4. Commit: docs: complete real-credentials validation and deployment guide
5. Si te doy el OK: git push origin secure (confirmación justo antes).
````

---

<a id="14"></a>
## 14. Procedimiento reutilizable de sincronización con upstream

**Prompt reutilizable.** Ejecutar cada vez que se quiera incorporar mejoras del
proyecto original sin debilitar los parches.

Los dos riesgos que justifican no hacer un `git merge` a secas:

1. **Tools nuevas sin clasificar** — si el gating es por lista de exclusión, una
   tool nueva y peligrosa quedaría expuesta en `standard` por defecto.
2. **Rutas nuevas de escritura de credenciales** — si upstream añade un punto que
   escribe cookies sin pasar por `write_secure_json`, hay fuga de texto claro.

````text
Sincronización de mi fork notebooklm-mcp-cli con upstream. Mi rama secure 
partió de la 0.8.9; upstream va por la 0.9.4. Objetivo: incorporar las 
mejoras del proyecto original SIN perder ni debilitar mis parches de 
seguridad.

Reglas de siempre: comandos importantes con aprobación, push solo a 
origin, nunca a upstream. No ejecutes nlm login ni toques mis perfiles 
reales de ~/.notebooklm-mcp-cli.

FASE 1 — RECONOCIMIENTO (no toques nada todavía):
1. git checkout secure && git status (debe estar limpio).
2. git fetch upstream --tags
3. Muéstrame qué ha cambiado upstream desde nuestro punto de partida:
   - git log --oneline HEAD..upstream/main | head -60
   - El CHANGELOG del proyecto entre 0.8.9 y la última versión.
   - git diff --stat HEAD..upstream/main
4. Dame un RESUMEN EJECUTIVO antes de mergear nada:
   - Qué funcionalidades nuevas aporta upstream y si merecen la pena.
   - Qué archivos de los que tocan MIS parches han cambiado también 
     upstream (previsión de conflictos): utils/credential_store.py, 
     utils/config.py, core/auth.py, services/auth.py, utils/cdp.py, 
     mcp/server.py, mcp/tools/.
   - Si upstream ha etiquetado releases intermedias, dime si conviene 
     mergear versión a versión (v0.9.0, v0.9.1...) en vez de todo de 
     golpe, para aislar conflictos. Recomiéndame una estrategia.
5. PARA aquí y espera mi decisión.

FASE 2 — MERGE (solo tras mi OK):
6. Crea una rama de trabajo: git checkout -b sync/upstream-<version>
   (nunca mergees directamente sobre secure).
7. Mergea según la estrategia acordada. En cada conflicto: muéstramelo, 
   explica qué quiere cada lado, y propón la resolución ANTES de 
   aplicarla. Regla de oro en conflictos que afecten a seguridad: gana 
   MI versión endurecida; las mejoras funcionales de upstream se 
   reincorporan encima, no al revés.

FASE 3 — AUDITORÍA POST-MERGE (obligatoria, esto es lo importante):
8. TOOLS NUEVAS SIN CLASIFICAR. Compara el catálogo de tools MCP antes y 
   después del merge. Para CADA tool nueva que haya traído upstream:
   - Dime qué hace y clasifícala en readonly / standard / dangerous 
     siguiendo el criterio que ya usamos (dangerous = compartir 
     públicamente, invitar colaboradores, borrar, operaciones en lote).
   - CRÍTICO: verifica si el mecanismo de gating es lista blanca o lista 
     de exclusión. Si es de exclusión, una tool nueva peligrosa quedaría 
     EXPUESTA por defecto en standard. Dímelo explícitamente y 
     clasifícala donde corresponda.
   - Si alguna tool nueva tiene sub-acciones destructivas (como note/label 
     con action="delete"), aplícale el guard deletion_allowed igual que 
     hicimos con las existentes.
9. RUTAS DE CREDENCIALES. Haz grep de todas las escrituras a cookies.json 
   / metadata.json / auth.json y confirma que TODAS siguen pasando por 
   write_secure_json. Si upstream ha añadido alguna ruta nueva que 
   escriba directamente (json.dump, write_text), es una fuga de texto 
   claro: corrígela.
10. Verifica que siguen intactos los 7 arreglos de la auditoría, en 
    especial:
    - fail-closed en _mapped_chrome_owns_profile (pid None → False)
    - el lock de get_encryption_key
    - la escritura atómica (tmp + os.replace)
    - la validación de nombre de perfil
    - la redacción del CSRF en logs debug
    - el guard test-only de NOTEBOOKLM_DISABLE_ENCRYPTION
11. Verifica que sigue el cierre inmediato de Chrome y el timeout de 
    login tras el merge (upstream podría haber reescrito esa zona).

FASE 4 — VERIFICACIÓN:
12. uv run pytest, uv run ruff check src/, uv run ruff format --check 
    src/ tests/. Si upstream trae tests nuevos que fallan por mis 
    parches, analízalo caso por caso: ¿es que mi parche rompe algo 
    legítimo, o es que el test asume el comportamiento inseguro anterior? 
    Consúltame antes de modificar cualquier test de upstream.
13. Arranca el servidor MCP y confirma el recuento de tools por modo 
    (antes del merge: 32/39 en standard). Si el número total cambió, 
    justifícalo con las tools nuevas clasificadas en la fase 3.

FASE 5 — CIERRE:
14. Muéstrame el diff de MIS archivos de seguridad respecto a antes del 
    merge, para que compruebe que nada se debilitó.
15. Resumen: qué aporta upstream, qué conflictos hubo y cómo se 
    resolvieron, qué tools nuevas se clasificaron y en qué tier.
16. Espera mi OK para mergear sync/upstream-<version> en secure y hacer 
    push a origin. Pídeme confirmación justo antes del push.
17. Actualiza docs/prueba-real.md: nota de sincronización con fecha, 
    versión de upstream incorporada, y tools nuevas con su clasificación.
````

---

## Lecciones del proceso

**Sobre los prompts:**

- **Separar verificar de corregir.** El prompt del hallazgo #11 pedía confirmar
  la sospecha *antes* de tocar código. La sospecha era falsa; sin esa fase se
  habría parcheado algo que funcionaba bien, y no se habría encontrado el
  problema real.
- **Pedir que consulte en vez de forzar.** Varias veces («si la arquitectura no
  lo permite, dímelo y decidimos»), lo que produjo alternativas mejores que la
  instrucción original.
- **Exigir el mensaje literal.** Al probar el guard de borrado, pedir la
  respuesta sin resumir fue lo que permitió distinguir «lo bloqueó el guard» de
  «falló por otra cosa».
- **Prohibir explícitamente lo peligroso.** «Nada de `nlm login`» mantuvo todo el
  desarrollo libre de credenciales reales.
- **Commits atómicos.** Separar por hallazgo permite PRs selectivos a upstream y
  revertir un fix sin arrastrar los demás.

**Sobre el trabajo con código ajeno:**

- Leer el código antes de asumir. El proyecto original estaba **mejor** asegurado
  de lo que su README sugería; parte del endurecimiento previsto ya existía.
- Los hallazgos más interesantes no fueron los buscados. El bypass de
  `NOTEBOOKLM_DISABLE_ENCRYPTION` apareció en un mensaje de error durante una
  prueba, no en la auditoría sistemática.
- Las herramientas automáticas complementan, no sustituyen. `mcp-scan` confirmó
  el gating y limpió las descripciones, pero los 7 hallazgos salieron de leer
  código.
- El endurecimiento tiene coste operativo. Cifrar credenciales introdujo una
  dependencia del keyring que rompió el despliegue vía cliente MCP hasta pasar
  `DBUS_SESSION_BUS_ADDRESS` explícitamente. Eso hay que documentarlo.

**Riesgo residual:** nada de esto elimina el riesgo estructural de entregar una
sesión de Google real a APIs internas no oficiales mediante un proyecto de
terceros. Por eso se usó una cuenta secundaria.
