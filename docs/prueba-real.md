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

### 1. Login interactivo + cierre de Chrome + timeout — valida Parche 3

- [ ] Ejecutar el login con un perfil dedicado a la prueba:

```bash
      NLM_PROFILE=prueba-real nlm login
```

- [ ] Se abre Chrome. Iniciar sesión con la **cuenta secundaria**.
- [ ] **Observar:** en cuanto el login se completa y se extraen las cookies,
      Chrome debe **cerrarse solo** (no quedarse abierto). → confirma el cierre
      inmediato del Parche 3.
- [ ] **Prueba del timeout (opcional pero recomendable):** repetir el login y
      **no** completar el inicio de sesión; esperar al timeout configurado
      (~5 min por defecto, verificar). Chrome debe cerrarse y el comando abortar
      con mensaje claro, en vez de quedarse colgado con el puerto abierto.

### 2. Cifrado real de credenciales — valida Parche 1

- [ ] Tras el login exitoso, localizar el archivo de credenciales del perfil
      (algo como `~/.notebooklm-mcp-cli/profiles/prueba-real/cookies.json`;
      confirmar ruta real).
- [ ] **Abrirlo y verificar que NO es JSON legible**, sino un blob cifrado:

```bash
      cat ~/.notebooklm-mcp-cli/profiles/prueba-real/cookies.json
```

      → No deben verse nombres de cookies ni valores de sesión en claro.
- [ ] Confirmar que la clave está en el keyring:

```bash
      python3 -c "import keyring; print(bool(keyring.get_password('notebooklm-mcp-cli','<nombre-clave>')))"
```

      (verificar el service/username reales que usa el código).
- [ ] Confirmar permisos `0600` del archivo:

```bash
      ls -l ~/.notebooklm-mcp-cli/profiles/prueba-real/cookies.json
```

      → debe mostrar `-rw-------`.

### 3. Migración plaintext → cifrado — valida Parche 1 (migración)

> Solo si quieres probar la ruta de migración. Requiere un perfil viejo en claro.

- [ ] Si tienes (o fabricas) un perfil con credenciales en texto claro de una
      versión anterior, cargarlo una vez y verificar que **se cifra
      automáticamente** y que la versión en claro desaparece.
- [ ] Si no aplica, saltar este paso.

### 4. Aviso de plaintext y `require_encryption` — valida Parche 4

- [ ] **Caso por defecto (degrada con aviso):** simular keyring no disponible
      (p. ej. entorno sin DBus) y hacer una operación que escriba credenciales.
      → Debe **degradar a texto claro pero mostrando un aviso VISIBLE** (banner
      en el arranque del servidor MCP, no una línea perdida).
- [ ] **Caso `require_encryption=true` (falla cerrado):**

```bash
      NLM_REQUIRE_ENCRYPTION=true NLM_PROFILE=prueba-real nlm <operación>
```

      con keyring no disponible → debe **fallar con error, sin escribir en
      claro**. (Verificar nombre real de la env var.)

### 5. Los tres modos sobre un cliente MCP real — valida Parche 2

- [ ] Arrancar el servidor MCP en cada modo y comprobar el número de tools y
      la ausencia/presencia de las peligrosas. Ya verificado con mcp-scan, pero
      aquí se prueba conectándolo a un cliente MCP real (p. ej. Claude Desktop):
      - `readonly` → solo tools de lectura
      - `standard` (32 tools) → lectura + escritura normal, **sin** las 7 peligrosas
      - `full` (39 tools) → todas
- [ ] Config MCP del cliente apuntando a tu binario, con
      `NLM_TOOLS_MODE` y `NLM_PROFILE=prueba-real` en el `env`.
      (Reutilizar la estructura del `mcp-scan-config.json` que ya montamos.)

### 6. Borrado de notas/etiquetas gateado por modo — valida Parche 2 (runtime guard)

- [ ] En modo `standard`, pedir (vía el cliente MCP o CLI según corresponda)
      un borrado de nota/etiqueta → debe **bloquearse** con el mensaje del guard
      (`deletion_blocked_result`).
- [ ] En modo `full`, el mismo borrado → **permitido**.
- [ ] Confirmar que crear/listar/renombrar notas y etiquetas **sí** funciona en
      `standard` (no se bloqueó de más).

---

## Criterio de éxito

La prueba se considera superada si:

1. Chrome se cierra solo tras el login y respeta el timeout.
2. `cookies.json` está cifrado en disco, con permisos `0600` y clave en keyring.
3. El aviso de plaintext es visible; `require_encryption=true` falla cerrado.
4. Los tres modos exponen el conjunto de tools esperado sobre un cliente real.
5. El borrado de notas/etiquetas está bloqueado en `standard` y permitido en `full`.

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
