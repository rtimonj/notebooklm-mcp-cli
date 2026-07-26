# Procedimiento: sincronizar el fork con upstream

> **Qué es esto.** El guion completo para incorporar las mejoras del proyecto
> original (`jacob-bd/notebooklm-mcp-cli`) a este fork endurecido **sin perder ni
> debilitar los parches de seguridad**. Está escrito para ejecutarse con un
> asistente (Claude Code) o a mano, en el orden dado.
>
> Vive en el repo a propósito: el procedimiento no debe depender de que nadie
> recuerde una conversación concreta.
>
> Complementa a [`prueba-real.md`](./prueba-real.md), que documenta qué se validó
> y cómo instalar/desplegar el fork.

---

## Contexto

- Rama de trabajo del fork: **`secure`**. Partió de la versión **0.8.9** del upstream.
- Upstream: `jacob-bd/notebooklm-mcp-cli`, remote `upstream` (HTTPS, **solo lectura**).
  Iba por la **0.9.4** a fecha de 2026-07-26; comprueba la versión actual antes de empezar.
- **Objetivo:** incorporar las mejoras funcionales de upstream conservando intactos
  los 4 parches de seguridad, los 7 arreglos de auditoría y la corrección del
  bypass de cifrado.

**La parte importante de este procedimiento es la FASE 3 (auditoría post-merge),
no el merge en sí.** El merge lo resuelve git; lo que git no puede hacer es darse
cuenta de que upstream añadió una tool peligrosa que queda expuesta por defecto.

---

## Reglas de la sesión

- Mostrar cada comando **antes** de ejecutarlo y esperar aprobación para cualquier
  cosa que instale software, modifique archivos fuera del repo o haga `git push`.
- **Push solo a `origin`** (el fork), **nunca a `upstream`**, y con confirmación
  explícita justo antes.
- **No ejecutar `nlm login`** ni tocar los perfiles reales de `~/.notebooklm-mcp-cli`.
- Antes de implementar algo no trivial: estudiar, proponer y esperar aprobación.
- Mostrar el diff completo y esperar aprobación antes de cada commit.

---

## FASE 1 — Reconocimiento (no tocar nada todavía)

1. `git checkout secure && git status` — debe estar limpio.
2. `git fetch upstream --tags`
3. Mostrar qué ha cambiado upstream desde nuestro punto de partida:

```bash
git log --oneline HEAD..upstream/main | head -60
git diff --stat HEAD..upstream/main
```

   Y el CHANGELOG del proyecto entre 0.8.9 y la última versión.

4. Dar un **RESUMEN EJECUTIVO antes de mergear nada**:
   - Qué funcionalidades nuevas aporta upstream y **si merecen la pena**.
   - **Qué archivos tocados por nuestros parches ha cambiado también upstream**
     (previsión de conflictos):

     ```
     src/notebooklm_tools/utils/credential_store.py
     src/notebooklm_tools/utils/config.py
     src/notebooklm_tools/core/auth.py
     src/notebooklm_tools/services/auth.py
     src/notebooklm_tools/utils/cdp.py
     src/notebooklm_tools/mcp/server.py
     src/notebooklm_tools/mcp/tools/
     ```

   - Si upstream ha etiquetado **releases intermedias**, valorar si conviene
     mergear **versión a versión** (`v0.9.0`, `v0.9.1`, …) en vez de todo de golpe,
     para aislar conflictos. Recomendar una estrategia.
5. **PARAR aquí** y esperar decisión.

---

## FASE 2 — Merge (solo tras el OK)

6. Rama de trabajo dedicada — **nunca mergear directamente sobre `secure`**:

```bash
git checkout -b sync/upstream-<version>
```

7. Mergear según la estrategia acordada. En **cada conflicto**: mostrarlo,
   explicar qué quiere cada lado, y **proponer la resolución antes de aplicarla**.

> **Regla de oro en conflictos que afecten a seguridad: gana la versión
> endurecida.** Las mejoras funcionales de upstream se reincorporan **encima** del
> parche, no al revés. Si upstream reescribió una función que endurecimos, se parte
> de nuestra versión y se le añade la mejora — nunca se acepta la de upstream y se
> intenta "volver a endurecer" después.

---

## FASE 3 — Auditoría post-merge (obligatoria)

### 8. Tools nuevas sin clasificar

Comparar el catálogo de tools MCP **antes y después** del merge. Para **cada tool
nueva** que haya traído upstream:

- Explicar qué hace y clasificarla en **readonly / standard / dangerous** con el
  criterio ya establecido: `dangerous` = compartir públicamente, invitar
  colaboradores, borrar, u operaciones **en lote**.
- **CRÍTICO — verificar si el gating es lista blanca o lista de exclusión.** Si
  fuese de exclusión, una tool nueva peligrosa quedaría **EXPUESTA por defecto** en
  `standard`. Decirlo explícitamente y clasificarla donde corresponda.

  > Estado actual: el gating es por **enumeración explícita** en `tool_groups.py`
  > (`TIER_READ` / `TIER_WRITE` / `TIER_DANGEROUS`), y hay un test
  > (`test_tiers_cover_exactly_the_registered_tools`) que **falla** si aparece una
  > tool registrada que no esté en ningún tier. Ese test es la red de seguridad:
  > si el merge trae tools nuevas, **debe fallar**. Si no falla, sospechar.

- Si alguna tool nueva tiene **sub-acciones destructivas** (como `note` / `label`
  con `action="delete"`), aplicarle el guard `deletion_blocked_result()` igual que
  a las existentes — ver `mcp/tools/notes.py` y `mcp/tools/labels.py`.

### 9. Rutas de credenciales

Grep de **todas** las escrituras a `cookies.json` / `metadata.json` / `auth.json`
y confirmar que **todas** siguen pasando por `write_secure_json`:

```bash
grep -rn "cookies\.json\|metadata\.json\|auth\.json" src/ | grep -iE "write|dump|open\(.*w"
grep -rn "\.write_text(\|json\.dump(" src/notebooklm_tools/core/auth.py \
  src/notebooklm_tools/utils/credential_store.py src/notebooklm_tools/services/auth.py
```

Si upstream ha añadido alguna ruta que escriba directamente (`json.dump`,
`write_text`), **es una fuga de texto claro: corregirla.**

### 10. Los 7 arreglos de la auditoría siguen intactos

| Arreglo | Dónde verificar | Qué debe seguir siendo verdad |
|---|---|---|
| Fail-closed CDP | `utils/cdp.py` → `_mapped_chrome_owns_profile` | `pid is None` → `return False` (**no** `True`) |
| Lock de generación de clave | `utils/credential_store.py` → `_key_lock` + `get_encryption_key` | Double-checked locking; re-lee el keyring dentro del lock |
| Escritura atómica | `utils/credential_store.py` → `write_secure_json` | temp con `O_CREAT\|O_EXCL`, 0o600, `fsync`, y `os.replace()` |
| Validación de nombre de perfil | `utils/config.py` → `validate_profile_name` | `^[A-Za-z0-9._-]+$`; llamada desde `get_profile_dir`, `get_chrome_profile_dir` y `AuthManager.__init__` |
| Redacción de CSRF en logs | `core/utils.py` → `_redact_sensitive`, usado en `core/base.py` | El log del cuerpo de respuesta pasa por `_redact_sensitive` |
| Gating del borrado | `mcp/tool_groups.py` → `deletion_allowed`; `mcp/tools/_utils.py` → `deletion_blocked_result` | Se comprueba **antes** de construir el cliente, en `note` y `label` |
| Guard test-only del cifrado | `utils/credential_store.py` → `encryption_disabled_by_env` | `NOTEBOOKLM_DISABLE_ENCRYPTION` solo se honra con `PYTEST_CURRENT_TEST` presente |

Más el Parche 4: `auth.require_encryption` / `NLM_REQUIRE_ENCRYPTION` sigue
haciendo **fail-closed** en `write_secure_json`.

### 11. Parche 3 (ventana CDP) tras el merge

Upstream podría haber reescrito esa zona. Verificar que siguen:

- El **cierre inmediato de Chrome** tras extraer cookies, y también en los caminos
  de error (`try/except` en `extract_cookies_via_cdp` + `finally` en
  `cli/main.py::login_callback`).
- El **timeout de login** configurable (`--login-timeout` / `NLM_LOGIN_TIMEOUT`,
  default 300 s).
- El **puerto efímero aleatorio** en `find_available_port`.
- Que **no** se cierra un navegador reutilizado o externo (`reused_existing`, CDP
  de terceros).

---

## FASE 4 — Verificación

12. Suite y linters:

```bash
uv run pytest
uv run ruff check src/
uv run ruff format --check src/ tests/
```

> Si upstream trae **tests nuevos que fallan** por nuestros parches, analizar
> **caso por caso**: ¿el parche rompe algo legítimo, o el test asume el
> comportamiento **inseguro** anterior? **Consultar antes de modificar cualquier
> test de upstream.** Adaptar un test para que vuelva a pasar puede ser
> exactamente lo contrario de lo que hay que hacer.

13. Arrancar el servidor MCP y confirmar el recuento de tools por modo. Baseline
    antes del merge: **readonly 15 / standard 32 / full 39**. Si el total cambió,
    justificarlo con las tools nuevas clasificadas en la fase 3.

```bash
for m in readonly standard full; do
  NLM_TOOLS_MODE=$m timeout 10 notebooklm-mcp </dev/null 2>&1 | grep "tools mode"
done
```

---

## FASE 5 — Cierre

14. Mostrar el **diff de los archivos de seguridad** respecto a antes del merge,
    para comprobar que nada se debilitó:

```bash
git diff secure..HEAD -- \
  src/notebooklm_tools/utils/credential_store.py \
  src/notebooklm_tools/utils/config.py \
  src/notebooklm_tools/utils/cdp.py \
  src/notebooklm_tools/core/auth.py \
  src/notebooklm_tools/core/utils.py \
  src/notebooklm_tools/core/base.py \
  src/notebooklm_tools/mcp/
```

15. **Resumen:** qué aporta upstream, qué conflictos hubo y cómo se resolvieron,
    qué tools nuevas se clasificaron y en qué tier.
16. Esperar el OK para mergear `sync/upstream-<version>` en `secure` y hacer push
    a `origin`. **Pedir confirmación justo antes del push.**
17. Actualizar [`prueba-real.md`](./prueba-real.md): nota de sincronización con
    fecha, versión de upstream incorporada, y tools nuevas con su clasificación.

---

## Apéndice: datos de referencia

Para que este documento sea autosuficiente. **Verifica los números contra el código
antes de fiarte de ellos** — están a fecha de 2026-07-26.

### Recuento de tools por tier

| Tier | Nº | Modo que las expone |
|---|---|---|
| `TIER_READ` | 15 | `readonly`, `standard`, `full` |
| `TIER_WRITE` | 17 | `standard`, `full` |
| `TIER_DANGEROUS` | 7 | solo `full` |
| **Total** | **39** | |

Modos acumulativos: `readonly` = 15, `standard` (por defecto) = 32, `full` = 39.

### Las 7 tools `dangerous`

```
batch                    notebook_share_batch     source_delete
notebook_delete          notebook_share_invite    studio_delete
notebook_share_public
```

### Comprobación rápida de coherencia de tiers

```bash
uv run python -c "
from notebooklm_tools.mcp import tool_groups as t
print('READ', len(t.TIER_READ), '| WRITE', len(t.TIER_WRITE),
      '| DANGEROUS', len(t.TIER_DANGEROUS), '| TOTAL', len(t.ALL_TOOLS))"
```

Y el test que detecta tools sin clasificar:

```bash
uv run pytest tests/test_tools_mode.py::test_tiers_cover_exactly_the_registered_tools -v
```

### Recordatorios operativos

- **Nunca `uv tool upgrade notebooklm-mcp-cli`**: sustituiría el fork por la versión
  oficial de PyPI, sin parches. Reinstalar siempre con `uv tool install --force .`
  desde el directorio del fork (**con el punto**).
- El aviso *"Update available"* del CLI es **esperable** y hay que ignorarlo: el
  fork partió de 0.8.9 y upstream sigue publicando.
