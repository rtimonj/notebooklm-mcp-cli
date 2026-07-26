# Prueba real del fork endurecido `notebooklm-mcp-cli`

> Documento de referencia para retomar más adelante. **No ejecutar sin repasar
> antes.** Entran credenciales reales de Google, por eso esta fase la conduces
> tú, con supervisión paso a paso.

---

## Contexto: dónde lo dejamos

Estado del fork (`github.com/rtimonj/notebooklm-mcp-cli`, rama `secure`, ya en tu GitHub):

- **Parche 1** — cifrado de credenciales en reposo (Fernet + keyring del sistema; migración automática de perfiles en claro).
- **Parche 2** — gating de herramientas por modo. En `standard` (por defecto) el borrado de notas/etiquetas está bloqueado; las 7 tools peligrosas solo en `full`.
- **Parche 3** — minimización de la ventana del puerto CDP (cierre inmediato de Chrome tras extraer cookies + timeout de login).
- **Parche 4** — opción `require_encryption` para fallar cerrado si no hay keyring.
- **Ronda de auditoría** — 7 hallazgos cerrados (fail-open CDP, race de clave, escritura atómica, validación de perfil, redacción CSRF en logs, gating de borrado, require_encryption).
- **Escaneo MCP** — `inspect` limpio; 32 tools en standard / 39 en full verificado sobre el servidor arrancado; 0 marcadores de prompt-injection/tool-poisoning.
- **Prueba real (en curso)** — bloques 1, 2 y 4 validados con cuenta secundaria; destapó un hallazgo en `NOTEBOOKLM_DISABLE_ENCRYPTION`, ya corregido. Ver [Pendiente / TODO](#pendiente--todo).

**Objetivo de esta fase:** validar con credenciales reales que el endurecimiento
funciona de verdad, no solo en los tests.

---

## ⚠️ Nota importante sobre comandos y variables

A lo largo del desarrollo hemos usado estos nombres, algunos **propuestos en los
prompts pero no verificados uno a uno** contra la instalación real:

- `NLM_PROFILE` — selección de perfil
- `NLM_TOOLS_MODE` — modo de exposición de tools (`readonly` / `standard` / `full`)
- `NLM_REQUIRE_ENCRYPTION` — forzar cifrado (fallar cerrado)
- El comando del servidor MCP (¿`nlm mcp`? binario del `.venv`?)
- El comando de login (`nlm login`)

**Antes de usar cualquiera de estos, verifícalo en tu instalación** con:

```bash
nlm --help
nlm login --help
nlm mcp --help        # o el subcomando real del servidor
```

Y confirma los nombres exactos de las env vars en el código
(`config.py` / README de tu fork). No los des por definitivos solo porque
aparezcan aquí.

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

### 1. Login interactivo + cierre de Chrome + timeout — valida Parche 3 ✅ VALIDADO

- [x] Ejecutar el login con un perfil dedicado a la prueba:

```bash
      NLM_PROFILE=prueba-real nlm login
```

- [x] Se abre Chrome. Iniciar sesión con la **cuenta secundaria**.
- [x] **Observar:** en cuanto el login se completa y se extraen las cookies,
      Chrome debe **cerrarse solo** (no quedarse abierto). → confirma el cierre
      inmediato del Parche 3. **Resultado: correcto, Chrome se cierra solo.**
- [x] **Prueba del timeout:** repetir el login y **no** completar el inicio de
      sesión; esperar al timeout. Chrome debe cerrarse y el comando abortar con
      mensaje claro, en vez de quedarse colgado con el puerto abierto.
      **Resultado: correcto, timeout de 300 s y aborta con "Error: Login timeout".**

### 2. Cifrado real de credenciales — valida Parche 1 ✅ VALIDADO

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

      **Resultado: cifrado confirmado, formato `__nlm_encrypted__`/`ciphertext`.**
- [x] Confirmar que la clave está en el keyring (service y key reales del código):

```bash
      python3 -c "import keyring; print(bool(keyring.get_password('notebooklm-mcp-cli','credentials-encryption-key')))"
```

      → debe imprimir `True`. **Resultado: clave presente en el keyring.**
- [x] Confirmar permisos `0600` del archivo:

```bash
      ls -l ~/.notebooklm-mcp-cli/profiles/prueba-real/cookies.json
```

      → debe mostrar `-rw-------`. **Resultado: permisos correctos.**

### 3. Migración plaintext → cifrado — valida Parche 1 (migración)

> Solo si quieres probar la ruta de migración. Requiere un perfil viejo en claro.

- [ ] Si tienes (o fabricas) un perfil con credenciales en texto claro de una
      versión anterior, cargarlo una vez y verificar que **se cifra
      automáticamente** y que la versión en claro desaparece.
- [ ] Si no aplica, saltar este paso.

### 4. Aviso de plaintext y `require_encryption` — valida Parche 4 ✅ VALIDADO

- [x] **Caso por defecto (degrada con aviso):** simular keyring no disponible
      (p. ej. entorno sin DBus) y hacer una operación que escriba credenciales.
      → Debe **degradar a texto claro pero mostrando un aviso VISIBLE** (banner
      en el arranque del servidor MCP, no una línea perdida).
      **Resultado: banner de aviso mostrado correctamente.**
- [x] **Caso `require_encryption=true` (falla cerrado):**

```bash
      NLM_REQUIRE_ENCRYPTION=true NLM_PROFILE=prueba-real nlm login
```

      con keyring no disponible → debe **fallar con error, sin escribir en
      claro**. **Resultado: falla cerrado y no escribe nada.**

      Nota: durante esta prueba se detectó que el error salía como traceback de
      Python en vez de error limpio del CLI. Corregido — ver
      [Pendiente / TODO](#pendiente--todo).

### 5. Los tres modos sobre un cliente MCP real — valida Parche 2 ⏳ PENDIENTE

> Parcialmente verificado: el modo `standard` expone **32/39 tools** confirmado
> sobre el servidor MCP realmente arrancado (vía `mcp-scan inspect`), y `full`
> las 39. Lo que queda es probarlo con un **cliente MCP real** conectado.

- [ ] Arrancar el servidor MCP en cada modo y comprobar el número de tools y
      la ausencia/presencia de las peligrosas. Ya verificado con mcp-scan, pero
      aquí se prueba conectándolo a un cliente MCP real (p. ej. Claude Desktop):
      - `readonly` → solo tools de lectura
      - `standard` (32 tools) → lectura + escritura normal, **sin** las 7 peligrosas
      - `full` (39 tools) → todas
- [ ] Config MCP del cliente apuntando a tu binario, con
      `NLM_TOOLS_MODE` y `NLM_PROFILE=prueba-real` en el `env`.
      (Reutilizar la estructura del `mcp-scan-config.json` que ya montamos.)

### 6. Borrado de notas/etiquetas gateado por modo — valida Parche 2 (runtime guard) ⏳ PENDIENTE

- [ ] En modo `standard`, pedir (vía el cliente MCP o CLI según corresponda)
      un borrado de nota/etiqueta → debe **bloquearse** con el mensaje del guard
      (`deletion_blocked_result`).
- [ ] En modo `full`, el mismo borrado → **permitido**.
- [ ] Confirmar que crear/listar/renombrar notas y etiquetas **sí** funciona en
      `standard` (no se bloqueó de más).

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

### Bloques de prueba que quedan

- **Bloque 5** — los tres modos sobre un cliente MCP real (Claude Desktop u otro).
  Ya confirmado a nivel de servidor arrancado (32/39 en `standard`), falta el
  cliente real.
- **Bloque 6** — borrado de notas/etiquetas gateado por modo, de extremo a extremo.
- **Bloque 3** (opcional) — migración de un perfil antiguo en texto claro.

---

## Criterio de éxito

La prueba se considera superada si:

1. ✅ Chrome se cierra solo tras el login y respeta el timeout.
2. ✅ `cookies.json` está cifrado en disco, con permisos `0600` y clave en keyring.
3. ✅ El aviso de plaintext es visible; `require_encryption=true` falla cerrado.
4. ⏳ Los tres modos exponen el conjunto de tools esperado sobre un cliente real.
5. ⏳ El borrado de notas/etiquetas está bloqueado en `standard` y permitido en `full`.

---

## Riesgo residual (recordatorio honesto)

Este endurecimiento **reduce el daño si alguien roba archivos de tu disco** y
reduce la ventana de exposición del puerto CDP. **No elimina** el riesgo
estructural de fondo: sigues entregando una sesión de Google real a APIs
internas no oficiales de NotebookLM, mediante un proyecto de terceros. Por eso
usamos una cuenta secundaria y no la principal. Mientras el puerto CDP esté
abierto (aunque ahora sea brevemente), otro proceso local de tu usuario podría
leer la sesión — es inherente al enfoque, no un bug del fork.

---

## Pasos posteriores (fuera del alcance de esta prueba)

- **Mantenimiento del fork:** `git fetch upstream && git merge upstream/main`
  periódicamente (el proyecto original se actualiza a menudo). Resolver
  conflictos — buena tarea para Claude Code.
- **Contribuir upstream (opcional):** abrir PRs al proyecto original con los
  parches de seguridad (1 y 3 especialmente). Si el mantenedor los acepta,
  dejas de necesitar mantener el fork. Decisión aparte, se revisa antes.
- **Capa Snyk Agent Scan (opcional):** si algún día quieres el guardrailing
  remoto, requiere cuenta Snyk + `SNYK_TOKEN`, o fijar una versión pre-Snyk de
  mcp-scan con endpoint público.
