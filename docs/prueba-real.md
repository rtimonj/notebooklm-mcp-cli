# Prueba real del fork endurecido `notebooklm-mcp-cli`

> **Prueba real completada el 2026-07-26** con una cuenta secundaria de Google.
> Este documento sirve ahora para dos cosas: (1) registro de qué se validó y con
> qué evidencia, y (2) **guía para instalar y desplegar el fork en otra máquina**
> — ver [Instalación en una máquina nueva](#instalación-en-una-máquina-nueva).
>
> Entran credenciales reales de Google: los pasos de login los conduces tú.

---

## Contexto: dónde lo dejamos

Estado del fork (`github.com/rtimonj/notebooklm-mcp-cli`, rama `secure`, ya en tu GitHub):

- **Parche 1** — cifrado de credenciales en reposo (Fernet + keyring del sistema; migración automática de perfiles en claro).
- **Parche 2** — gating de herramientas por modo. En `standard` (por defecto) el borrado de notas/etiquetas está bloqueado; las 7 tools peligrosas solo en `full`.
- **Parche 3** — minimización de la ventana del puerto CDP (cierre inmediato de Chrome tras extraer cookies + timeout de login).
- **Parche 4** — opción `require_encryption` para fallar cerrado si no hay keyring.
- **Ronda de auditoría** — 7 hallazgos cerrados (fail-open CDP, race de clave, escritura atómica, validación de perfil, redacción CSRF en logs, gating de borrado, require_encryption).
- **Escaneo MCP** — `inspect` limpio; 32 tools en standard / 39 en full verificado sobre el servidor arrancado; 0 marcadores de prompt-injection/tool-poisoning.
- **Prueba real (2026-07-26)** — bloques 1, 2, 4 y 6 validados y bloque 5 parcial, con cuenta secundaria. Destapó un hallazgo en `NOTEBOOKLM_DISABLE_ENCRYPTION`, ya corregido, y un requisito de entorno al desplegar con un cliente MCP. Ver [Pendiente / TODO](#pendiente--todo).

**Objetivo de esta fase:** validar con credenciales reales que el endurecimiento
funciona de verdad, no solo en los tests. **Conseguido.**

---

## Comandos y variables (verificados)

Todos estos nombres están **confirmados** contra la instalación real:

| Nombre | Qué hace |
|---|---|
| `nlm` | CLI (entry point `notebooklm_tools.cli.main:cli_main`) |
| `notebooklm-mcp` | **Servidor MCP** (entry point `notebooklm_tools.mcp.server:main`), stdio por defecto. **No existe** un subcomando `nlm mcp` |
| `nlm login` | Login interactivo vía CDP. Acepta `--login-timeout` (default 300 s) |
| `NLM_PROFILE` | Perfil activo. Solo `[A-Za-z0-9._-]+` (validado; sin `..` ni separadores) |
| `NLM_TOOLS_MODE` | `readonly` / `standard` (default) / `full` |
| `NLM_REQUIRE_ENCRYPTION` | Fallar cerrado si no hay keyring |
| `NLM_LOGIN_TIMEOUT` | Equivalente en env de `--login-timeout` |
| `NOTEBOOKLM_MCP_CLI_PATH` | Redirige el directorio de almacenamiento (útil para aislar) |
| `NOTEBOOKLM_DISABLE_ENCRYPTION` | ⛔ **Solo tests.** Se ignora fuera de pytest y avisa. No usar |

Comprobación rápida en cualquier instalación:

```bash
nlm --help
nlm login --help
notebooklm-mcp --help
```

**Detalle de `NLM_REQUIRE_ENCRYPTION`:** se interpreta con lista negra — cualquier
valor activa el modo estricto **salvo** `""`, `0`, `false`, `no`, `off`
(insensible a mayúsculas). Es decir, un valor con typo como `NLM_REQUIRE_ENCRYPTION=flase`
**activa** el cifrado obligatorio en vez de desactivarlo: falla hacia el lado seguro.

---

## Checklist de preparación (antes de empezar)

- [ ] **Cuenta secundaria de Google lista** (NO tu cuenta principal). Ya la tienes creada.
- [ ] Decidir si esa cuenta tendrá 2FA y tenerlo accesible durante el login.
- [ ] **Keyring del sistema operativo funcionando.** En tu Ubuntu es GNOME Keyring / Secret Service. Comprobar que hay una sesión de escritorio con DBus activo (no una sesión SSH pelada), porque el cifrado depende de él. Verificación rápida:

```bash
      echo $DBUS_SESSION_BUS_ADDRESS      # no debe estar vacío
      python3 -c "import keyring; print(keyring.get_keyring())"
```

- [ ] **Fork actualizado en local**, rama `secure` con todo integrado y la instalación hecha:

```bash
      cd ruta/al/notebooklm-mcp-cli
      git checkout secure
      git log --oneline -3          # confirmar que están las correcciones
      uv tool install --force .
      nlm --version
```

- [ ] **Backup mental / nota**: si algo va mal con el cifrado, el remedio es borrar el perfil y volver a loguear. No hay datos irremplazables en juego (es una cuenta secundaria), pero tenlo presente.
- [ ] Tener a mano un notebook de prueba desechable en esa cuenta de NotebookLM (o crear uno durante la prueba), para no tocar contenido que te importe.
- [ ] Sesión con tiempo y sin prisa (el login interactivo tiene timeout; si te interrumpen a media prueba, mejor repetir).

---

## Guía paso a paso

Cada bloque indica **qué probamos**, **qué parche valida** y **qué esperar**.
Marca el resultado a medida que avances.

### 1. Login interactivo + cierre de Chrome + timeout — valida Parche 3 ✅ VALIDADO (2026-07-26)

- [x] Ejecutar el login con un perfil dedicado a la prueba:

```bash
      NLM_PROFILE=prueba-real nlm login
```

- [x] Se abre Chrome. Iniciar sesión con la **cuenta secundaria**.
- [x] **Observar:** en cuanto el login se completa y se extraen las cookies,
      Chrome debe **cerrarse solo** (no quedarse abierto).

      **Evidencia:** el CLI imprime `Closing Google Chrome...` **antes** del
      mensaje de éxito, y la ventana desaparece en ese momento → cierre inmediato
      confirmado, el puerto de debugging no sobrevive al login.
- [x] **Prueba del timeout:** repetir el login y **no** completar el inicio de
      sesión; esperar al timeout. Chrome debe cerrarse y el comando abortar.

      **Evidencia:** aborta a los **300 s exactos** con `Error: Login timeout` y
      un hint claro, en vez de quedarse colgado con el puerto abierto.

### 2. Cifrado real de credenciales — valida Parche 1 ✅ VALIDADO (2026-07-26)

- [x] Tras el login exitoso, localizar el archivo de credenciales del perfil:
      `~/.notebooklm-mcp-cli/profiles/prueba-real/cookies.json`.
- [x] **Verificar que está cifrado.**

      ⚠️ **Ojo con la comprobación:** un archivo cifrado **SÍ es JSON válido** —
      es un "envelope" con las claves `__nlm_encrypted__` y `ciphertext`. Por eso
      "si `json.load()` funciona, no está cifrado" es una prueba **ERRÓNEA**: daría
      falso negativo siempre. La comprobación correcta es buscar el marcador:

```bash
      python3 -c "
      import json,sys
      d=json.load(open('$HOME/.notebooklm-mcp-cli/profiles/prueba-real/cookies.json'))
      print('CIFRADO' if isinstance(d,dict) and d.get('__nlm_encrypted__')==1 else 'EN CLARO')
      print('claves:', list(d) if isinstance(d,dict) else type(d))"
```

      → debe imprimir `CIFRADO` y `claves: ['__nlm_encrypted__', 'ciphertext']`.
      Además, un `grep` de un nombre de cookie no debe encontrar nada:

```bash
      grep -c SAPISID ~/.notebooklm-mcp-cli/profiles/prueba-real/cookies.json   # → 0
```

      **Evidencia:** el archivo contiene **solo** las claves `__nlm_encrypted__`
      y `ciphertext`; ningún nombre ni valor de cookie aparece en claro.
- [x] Confirmar que la clave está en el keyring (service y key reales del código):

```bash
      python3 -c "import keyring; print(bool(keyring.get_password('notebooklm-mcp-cli','credentials-encryption-key')))"
```

      → debe imprimir `True`. **Evidencia:** clave presente en el keyring, con
      service `notebooklm-mcp-cli` y key `credentials-encryption-key`.
- [x] Confirmar permisos `0600` del archivo:

```bash
      ls -l ~/.notebooklm-mcp-cli/profiles/prueba-real/cookies.json
```

      → debe mostrar `-rw-------`. **Evidencia:** permisos correctos.
- [x] **Verificar el ciclo completo cifrar → descifrar**, que es lo que demuestra
      que el cifrado no solo escribe, también se usa:

```bash
      NLM_PROFILE=prueba-real nlm notebook list
```

      **Evidencia:** lista los notebooks correctamente → las credenciales se
      descifran desde el keyring y funcionan contra la API real.

### 3. Migración plaintext → cifrado — valida Parche 1 (migración)

> Solo si quieres probar la ruta de migración. Requiere un perfil viejo en claro.

- [ ] Si tienes (o fabricas) un perfil con credenciales en texto claro de una
      versión anterior, cargarlo una vez y verificar que **se cifra
      automáticamente** y que la versión en claro desaparece.
- [ ] Si no aplica, saltar este paso.

### 4. Aviso de plaintext y `require_encryption` — valida Parche 4 ✅ VALIDADO (2026-07-26)

- [x] **Caso por defecto (degrada con aviso):** simular keyring no disponible y
      hacer una operación que escriba credenciales. La forma limpia de forzarlo,
      sin tocar tu keyring real, es el backend `fail` de la librería `keyring`:

```bash
      PYTHON_KEYRING_BACKEND=keyring.backends.fail.Keyring \
        NLM_PROFILE=prueba-real notebooklm-mcp
```

      **Evidencia:** aparece el banner de aviso visible en el arranque del
      servidor (no una línea perdida en INFO), avisando de que las credenciales
      se guardarían en texto claro.
- [x] **Caso `require_encryption` activo (falla cerrado):**

```bash
      PYTHON_KEYRING_BACKEND=keyring.backends.fail.Keyring \
        NLM_REQUIRE_ENCRYPTION=1 NLM_PROFILE=prueba-real nlm login
```

      **Evidencia:** lanza `CredentialStoreError` y el directorio del perfil queda
      **VACÍO** — no se escribió absolutamente nada, ni en claro ni a medias.
      Confirmado el fail-closed.

      Nota sobre cómo se interpreta la variable: cualquier valor activa el modo
      estricto **salvo** `""`, `0`, `false`, `no`, `off`. Es una lista negra, así
      que un typo (`flase`) **activa** el cifrado obligatorio: falla hacia el lado
      seguro.

      Nota: durante esta prueba se detectó que el error salía como traceback de
      Python en vez de error limpio del CLI. Corregido — ver
      [Pendiente / TODO](#pendiente--todo).

- [x] **Corrección del bypass de `NOTEBOOKLM_DISABLE_ENCRYPTION`**, verificada
      sobre el binario ya instalado:

```bash
      NOTEBOOKLM_DISABLE_ENCRYPTION=1 NLM_PROFILE=prueba-real notebooklm-mcp
```

      **Evidencia:** emite
      `IGNORING NOTEBOOKLM_DISABLE_ENCRYPTION: it is a test-only override...`
      y **no** aparece el banner de plaintext (el keyring sigue usándose), o sea
      que la variable ya no puede forzar texto claro ni silenciar los avisos.

### 5. Los tres modos sobre un cliente MCP real — valida Parche 2 ⚠️ PARCIAL (2026-07-26)

- [x] **Modo `standard` sobre Claude Desktop** como cliente MCP real.

      **Evidencia:** el cliente lista **32/39 tools**, y **ninguna** de las 7
      peligrosas (`notebook_delete`, `source_delete`, `studio_delete`,
      `notebook_share_public`, `notebook_share_invite`, `notebook_share_batch`,
      `batch`). Coincide exactamente con lo medido antes vía `mcp-scan inspect`,
      así que el gating se sostiene también con un cliente real de por medio.
- [ ] **Modos `readonly` y `full`** — pendientes **a propósito**: se dejan para
      probarlos al instalar en la segunda máquina, y así validar de paso la guía
      de instalación desde cero.
      - `readonly` → solo tools de lectura
      - `full` (39 tools) → todas, incluidas las 7 peligrosas
- [x] Config MCP del cliente apuntando a tu binario, con `NLM_TOOLS_MODE` y
      `NLM_PROFILE=prueba-real` en el `env`. **Ojo:** hace falta pasar también
      `HOME` y `DBUS_SESSION_BUS_ADDRESS` — ver
      [Despliegue con un cliente MCP](#despliegue-con-un-cliente-mcp-requisito-de-entorno).

### 6. Borrado de notas/etiquetas gateado por modo — valida Parche 2 (runtime guard) ✅ VALIDADO (2026-07-26)

- [x] En modo `standard`, pedir vía el cliente MCP el borrado de una nota →
      **bloqueado**.

      **Evidencia:** el agente envió `confirm=true` y aun así fue rechazado
      **antes de llegar al cliente de la API**, con el mensaje literal:

      ```
      Note deletion is disabled in tools mode 'standard'.
      hint: Set NLM_TOOLS_MODE=full (or [tools].mode = "full") to allow deletion.
      ```

      Es decir: el `confirm=true` no sirve de nada, que era justo el punto — la
      premisa del parche es que un agente confundido lo pone.
- [x] **Doble capa confirmada.** Al verse bloqueado, el agente buscó una vía
      alternativa (borrar el notebook entero) y **no la encontró**: `notebook_delete`
      no está expuesta en `standard`. Las dos capas funcionan de forma
      independiente y se refuerzan:
      1. **Gating en el registro** — la tool peligrosa no existe para el agente.
      2. **Guard en runtime** — la sub-acción peligrosa de una tool que sí existe
         se rechaza al invocarse.
- [ ] En modo `full`, el mismo borrado → **permitido**. Pendiente junto con el
      resto del bloque 5.
- [x] Crear/listar/renombrar notas y etiquetas **sí** funciona en `standard`
      (no se bloqueó de más).

---

## Instalación en una máquina nueva

Pasos reales, incluidos los tropiezos que tuvimos.

**1. Requisitos**

- `uv` instalado.
- **Sesión de escritorio con keyring activo** (GNOME Keyring / Secret Service).
  El cifrado depende de él. Comprobar:

```bash
echo $DBUS_SESSION_BUS_ADDRESS      # no debe estar vacío
python3 -c "import keyring; print(keyring.get_keyring())"
```

- Chrome o Chromium instalado (para el login por CDP).

**2. Clonar el fork y situarse en la rama correcta**

```bash
git clone git@github.com:rtimonj/notebooklm-mcp-cli.git
cd notebooklm-mcp-cli
git checkout secure
```

**3. Instalar — desde el directorio, con el punto**

```bash
uv tool install --force .
```

> ⛔ **AVISO IMPORTANTE.** `uv tool install notebooklm-mcp-cli` (**sin** el punto)
> instala el paquete **de PyPI**, que es el proyecto oficial **SIN los parches de
> seguridad**. Nos pasó, y el resultado fue que las credenciales se guardaron en
> **texto claro**. El punto final no es un detalle cosmético: es la diferencia
> entre tener cifrado o no tenerlo.
>
> Verificar siempre que lo instalado es el fork parcheado:
>
> ```bash
> grep -rl "require_encryption" ~/.local/share/uv/tools/notebooklm-mcp-cli/
> ```
>
> Si no devuelve ninguna ruta, has instalado la versión oficial: repite la
> instalación con `--force .` desde el directorio del fork.

**4. No actualizar con `uv tool upgrade`**

```bash
# ⛔ NO hacer esto: sobrescribe el fork con la versión oficial de PyPI
# uv tool upgrade notebooklm-mcp-cli
```

El CLI mostrará un aviso de tipo *"Update available"* — es **esperable** y hay que
**ignorarlo**: el fork partió de la 0.8.9 y el upstream ha seguido publicando
versiones. Para actualizar el fork, se hace merge del upstream (ver
[Pendiente / TODO](#pendiente--todo)), nunca `uv tool upgrade`.

**5. Login con la cuenta secundaria**

```bash
NLM_PROFILE=prueba-real nlm login
```

Verificar el cifrado según el [Bloque 2](#2-cifrado-real-de-credenciales--valida-parche-1--validado-2026-07-26).

**6. Configurar el cliente MCP**

Según la sección siguiente — **no te la saltes**: tiene un requisito de entorno
que, si falta, hace que todo falle con "No authentication found".

---

## Despliegue con un cliente MCP (requisito de entorno)

**El problema.** Cuando un cliente MCP (Claude Desktop, por ejemplo) lanza el
servidor como proceso hijo, puede hacerlo con un **entorno reducido**, sin
`DBUS_SESSION_BUS_ADDRESS`. Y sin DBus no hay acceso al keyring; sin keyring no
hay clave; sin clave **no se puede descifrar el perfil**. El síntoma es
desconcertante: el servidor arranca bien y lista las tools, pero **cualquier
operación real falla** con `No authentication found`.

Es un requisito que aparece **precisamente porque ciframos**: antes, con las
credenciales en texto claro, el servidor no necesitaba el keyring para nada.

**La solución.** Pasar las variables explícitamente en la config del cliente.
Obtén el valor de DBUS con `echo $DBUS_SESSION_BUS_ADDRESS` y ajusta rutas, tu
usuario y tu UID:

```json
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
```

**Por qué `NLM_REQUIRE_ENCRYPTION=1` justo en esta config.** El servidor MCP
arranca en segundo plano y **nadie está leyendo su stderr**. Sin esa variable, un
fallo del keyring degradaría silenciosamente a texto claro: el banner de aviso se
emitiría, sí, pero a un log que nadie mira. Con `require_encryption` activo el
fallo es **ruidoso e imposible de ignorar** — las operaciones fallan en vez de
guardar cookies en claro a tus espaldas. Es el escenario para el que se diseñó
esa opción.

### Dos cosas que NO hacer

- ⛔ **No uses `NOTEBOOKLM_COOKIES`** para "resolver" problemas de autenticación.
  Eso mete las cookies de sesión de Google **en texto claro dentro de un archivo
  de configuración** — exactamente lo que estos parches existen para evitar, y
  además en un sitio que se sincroniza y se comparte con más facilidad que
  `~/.notebooklm-mcp-cli`. Durante la prueba un asistente lo sugirió como
  atajo; queda documentado para no caer en ello. Si la autenticación falla, el
  arreglo está en la sección de diagnóstico, no en pegar cookies.
- ⛔ **No incluyas `NOTEBOOKLM_DISABLE_ENCRYPTION`** en ningún config. Fuera de
  los tests ya se ignora, y lo único que consigues es un warning en el log.

---

## Diagnóstico: keyring vs credenciales caducadas

Los dos fallos **se parecen desde fuera** (todo falla con errores de
autenticación) pero se arreglan de forma distinta. La señal que los distingue es
**el banner de plaintext en el log del servidor**:

| Señal | Diagnóstico | Solución |
|---|---|---|
| Banner de *"system keyring unavailable"* **presente** | Problema de **ENTORNO**: el servidor no alcanza el keyring | Faltan `DBUS_SESSION_BUS_ADDRESS` / `HOME` en la config del cliente → ver [sección anterior](#despliegue-con-un-cliente-mcp-requisito-de-entorno) |
| **Sin** banner, pero las operaciones fallan con *"Authentication expired"*, o `refresh_auth` devuelve reason `stale` | **CREDENCIALES caducadas** | Volver a ejecutar `nlm login` en una terminal, y **reiniciar el cliente MCP por completo** |

Detalle importante del segundo caso: **una recarga desde disco no revive tokens
expirados**. Por eso `refresh_auth` no basta y hay que rehacer el login; y
reiniciar el cliente entero resulta más fiable que confiar en `refresh_auth`.

**Comandos útiles** (adapta rutas a tu instalación):

```bash
# 1) Ver el log del servidor MCP tal como lo ve el cliente
tail -20 ~/.config/Claude/logs/mcp-server-<nombre>.log

# 2) Reproducir el entorno REDUCIDO del cliente, que es donde aparece el fallo
env -i HOME=$HOME PATH=$PATH NLM_PROFILE=<perfil> \
  timeout 10 notebooklm-mcp < /dev/null
```

El segundo comando es el más útil de los dos: `env -i` arranca con un entorno
casi vacío, igual que hace el cliente MCP, así que **reproduce el problema de
DBus** que no se ve al lanzar el servidor desde tu terminal normal.

> **Nota sobre cerrar sesiones de Google.** Si desde la cuenta haces
> Gmail → *"Cerrar todas las demás sesiones"*, eso **invalida también las cookies
> guardadas por `nlm`** y obliga a repetir el login. Tenlo en cuenta si haces
> limpieza de sesiones y de repente el fork deja de funcionar: no está roto.

---

## Pendiente / TODO

### Hallazgos de la prueba real — RESUELTOS

**1. `NOTEBOOKLM_DISABLE_ENCRYPTION` era una puerta a texto claro sin guard**
*(severidad media — corregido en la rama `fix/disable-encryption-bypass`)*

Detectado al revisar la convivencia de los dos controles de cifrado. La sospecha
inicial era que esa variable puenteaba `require_encryption`; **eso no se
confirmó** (`require_encryption` ya ganaba y lanzaba `CredentialStoreError` sin
escribir). Pero sí se confirmó un problema real y distinto: la variable

- se honraba en **cualquier** contexto, pese a documentarse como hook de test;
- bajaba el aviso de degradación de **WARNING a INFO** (invisible por defecto); y
- hacía que `plaintext_fallback_active()` devolviera `False`, **silenciando el
  banner de aviso** del servidor MCP.

O sea: ponía las cookies en claro **y apagaba las dos alarmas** diseñadas para
avisarlo. Trivial de activar por accidente (de hecho estaba puesta en el
`mcp-scan-config.json` que usamos para el escaneo).

Corrección aplicada:

- Solo se honra bajo pytest (`PYTEST_CURRENT_TEST` presente); fuera de un test se
  **ignora** y emite un WARNING visible.
- El banner y el nivel de log dejan de poder silenciarse.
- `require_encryption` + esa variable a la vez → error explícito de
  **configuración contradictoria**, sin escribir nada.
- Mensajes de error reescritos (el anterior decía
  "auth.require_encryption / NOTEBOOKLM_DISABLE_ENCRYPTION unset", que confundía).

Efecto colateral asumido: quien tenga keyring funcionando y ponga esa variable
para forzar texto claro, pasará a tener las credenciales **cifradas**.

**2. La ruta de lectura NO era vulnerable** — verificado. El marcador
`__nlm_encrypted__` se detecta independientemente de la variable, así que un
archivo cifrado siempre se reconoce; leerlo sin keyring falla cerrado y deja el
archivo intacto.

**3. Traceback de Python en el CLI** *(corregido)*. `CredentialStoreError` no
hereda de `NLMError`, así que al fallar `nlm login` con `require_encryption`
activo salía un traceback crudo en vez de un error limpio. Ahora se captura y se
formatea con el estilo del resto del CLI.

**4. Requisito de entorno al desplegar con un cliente MCP** *(documentado, no es
un bug)*. Al cifrar, el servidor pasa a necesitar el keyring, y los clientes MCP
lanzan el proceso hijo con un entorno reducido sin `DBUS_SESSION_BUS_ADDRESS`.
Solución en [Despliegue con un cliente MCP](#despliegue-con-un-cliente-mcp-requisito-de-entorno).

### Lo que queda por probar

- **Modos `readonly` y `full` sobre un cliente MCP real** (bloque 5 parcial).
  Reservado a propósito para la instalación en la segunda máquina.
- **Verificar que en modo `full` sí funciona** el borrado de nota/etiqueta, es
  decir que el guard **no bloquea de más**. Los tests lo cubren, falta la
  comprobación end-to-end.

  > Aclaración para evitar una confusión que ya ocurrió: **`notebook_delete` SÍ
  > está entre las 7 tools que expone `full`**. Durante la prueba un asistente
  > afirmó lo contrario, pero era porque su propio servidor corría en `standard`,
  > donde esa tool no existe. No es un fallo del gating: es exactamente el gating
  > funcionando.
- **Bloque 3** (opcional) — migración de un perfil antiguo en texto claro.

### Mantenimiento y opcionales

- **Sincronizar con upstream, periódicamente:**

```bash
  git fetch upstream && git merge upstream/main
```

  El upstream ya va por **0.9.4** y el fork partió de **0.8.9**, así que hay
  bastante que integrar. Recuerda: **nunca** `uv tool upgrade`, que sustituiría el
  fork por la versión oficial sin parches.

  > **No improvises este merge.** El procedimiento completo, con la auditoría
  > post-merge que evita que una tool nueva de upstream quede expuesta por defecto,
  > está en [`sincronizar-upstream.md`](./sincronizar-upstream.md).
- **Contribuir upstream (opcional):** abrir PRs al proyecto original con los
  parches de seguridad (el 1 y el 3 especialmente). Si el mantenedor los acepta,
  dejas de necesitar mantener el fork. Decisión aparte, se revisa antes.
- **Capa Snyk Agent Scan (opcional):** si algún día quieres el guardrailing
  remoto, requiere cuenta Snyk + `SNYK_TOKEN`, o fijar una versión pre-Snyk de
  mcp-scan con endpoint público. El `inspect` local ya se pasó y salió limpio.

---

## Criterio de éxito

La prueba se considera superada si:

1. ✅ Chrome se cierra solo tras el login y respeta el timeout (300 s exactos).
2. ✅ `cookies.json` está cifrado en disco, con permisos `0600` y clave en keyring,
   y el ciclo cifrar/descifrar funciona contra la API real.
3. ✅ El aviso de plaintext es visible; `require_encryption` falla cerrado sin
   escribir nada.
4. ⚠️ Los tres modos exponen el conjunto de tools esperado sobre un cliente real.
   **`standard` validado (32/39 en Claude Desktop); `readonly` y `full` pendientes**
   para la segunda máquina.
5. ✅ El borrado de notas/etiquetas está bloqueado en `standard` — incluso con
   `confirm=true` — y sin vía alternativa disponible. Queda por comprobar
   end-to-end que en `full` sí se permite.

**Veredicto: el endurecimiento funciona con credenciales reales.** Los puntos 1,
2, 3 y 5 están validados; del 4 falta solo el contraste de los otros dos modos,
que se hará al instalar en la segunda máquina.

---

## Riesgo residual (recordatorio honesto)

Este endurecimiento **reduce el daño si alguien roba archivos de tu disco** y
reduce la ventana de exposición del puerto CDP. **No elimina** el riesgo
estructural de fondo: sigues entregando una sesión de Google real a APIs
internas no oficiales de NotebookLM, mediante un proyecto de terceros. Por eso
usamos una cuenta secundaria y no la principal. Mientras el puerto CDP esté
abierto (aunque ahora sea brevemente), otro proceso local de tu usuario podría
leer la sesión — es inherente al enfoque, no un bug del fork.

Lo que la prueba real **sí** confirmó es que las tres defensas hacen su trabajo:
las credenciales en disco ya no son legibles sin el keyring, la ventana del puerto
CDP se cierra sola, y un agente con `confirm=true` no puede borrar ni compartir
nada en el modo por defecto.

> El mantenimiento del fork y la posible contribución upstream están en
> [Pendiente / TODO](#pendiente--todo).
