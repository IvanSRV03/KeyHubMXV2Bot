# Bot de Telegram para venta de licencias (KeyHubMx)

Bot en Python que conecta con la API del proveedor **mspidpro** para:

- Checar validez de claves antes de venderlas (`Check Keys`)
- Checar si una clave ya fue canjeada (`Check Redeem`)
- Obtener el Confirmation ID a partir del Installation ID que manda el cliente,
  ya sea escrito o en foto (`Get CID`)
- Vender el catálogo de claves del proveedor directamente a tus clientes (`Buy Key`)
- Llevar una cuenta/saldo acumulado por cada cliente de Telegram (no cobra al
  momento, solo va sumando lo que debe, igual que hacías antes)

---

## ⚠️ Antes que nada: nunca subas tokens a este repo

Los tokens (`BOT_TOKEN`, `PROVIDER_TOKEN`) van **solo** en variables de entorno:
en Railway bajo *Variables*, y en tu computadora en un archivo `.env` local que
ya está ignorado por `.gitignore`. Usa `.env.example` como plantilla.

Si alguna vez un token llega a quedar escrito en un archivo del repo, **rótalo**
(genéralo de nuevo en el panel del proveedor o con @BotFather). Borrarlo del
archivo no basta: el valor viejo sigue guardado en el historial de git y
cualquiera puede leerlo.

---

## 1. Crea tu bot de Telegram

1. Abre Telegram y busca **@BotFather**.
2. Mándale `/newbot`, ponle un nombre y un username (debe terminar en `bot`).
3. Te va a dar un **token** con este formato: `123456789:AAAA...`. Ese es tu `BOT_TOKEN`.

## 2. Consigue tu Telegram ID (para ser administrador)

1. Busca en Telegram al bot **@userinfobot** y mándale cualquier mensaje.
2. Te responde con tu ID numérico. Ese número va en `ADMIN_IDS`.
3. Si quieres que alguien más de tu equipo también tenga comandos de admin,
   pon los IDs separados por coma: `ADMIN_IDS=111111111,222222222`.

## 3. Despliega en Railway

1. Crea un proyecto nuevo en Railway y sube este código (puedes conectar un
   repo de GitHub o usar `railway up` desde esta carpeta).
2. En **Variables**, agrega:
   - `BOT_TOKEN` → el token de BotFather
   - `PROVIDER_TOKEN` → el token que te dio mspidpro (lo copias de tu panel; **nunca lo escribas en este README ni en el código**)
   - `ADMIN_IDS` → tu Telegram ID (y los de tu equipo si aplica)
   - `DB_PATH` → `/data/bot.db`
3. **Importante — agrega un Volume:** en Railway, ve a tu servicio →
   **Settings → Volumes** → crea un volumen y móntalo en `/data`. Si no
   haces esto, la base de datos (clientes, saldos, historial) se borra cada
   vez que Railway vuelve a desplegar el bot.
4. Railway va a detectar el `Procfile` y correr `python bot.py` como
   proceso tipo *worker* (no necesita dominio público, el bot funciona por
   *polling*, no por webhook).
5. Cuando termine el deploy, revisa los **Logs**: deberías ver
   `Bot iniciado, esperando mensajes...`.

## 4. Primer uso — configura el catálogo y los precios

El bot nunca inventa precios de venta: tú decides cuánto cobrarle a tus
clientes por cada producto y por cada Confirmation ID.

1. Desde tu cuenta de Telegram (la que pusiste en `ADMIN_IDS`), mándale al
   bot: `/refrescarproductos`
   Esto trae el catálogo del proveedor y lo guarda localmente.
   ⚠️ La documentación que me diste no incluye un ejemplo del JSON exacto
   que regresa `/key-products`, así que este comando intenta interpretar la
   forma más común de respuesta. Si el catálogo sale vacío o incompleto,
   mándame la respuesta cruda de esa llamada (puedes verla en los logs de
   Railway) y ajusto el parseo.
2. Para cada producto que quieras vender, asígnale un precio:
   `/precio CODIGO 25.00`
   (Solo los productos con precio asignado aparecen en `/productos` para tus clientes.)
3. Define cuánto le cobras a un cliente por generar un Confirmation ID:
   `/preciocid 2.00`
   (Si lo dejas en 0, la consulta de CID no genera cargo.)

## 5. Cómo compran tus clientes

La idea es que el cliente no tenga que aprenderse nada.

1. Manda `/productos` y ve la lista numerada, con un botón por producto.
2. Toca el botón **o** manda el número directo: `/1`, `/2`, ...
3. El bot le muestra qué es, cuánto cuesta y cómo le quedaría el saldo.
4. Un toque en ✅ y le llega la clave.

Los números los asigna el bot solo, la primera vez que le pones precio a un
producto con `/precio`, y **ya no cambian** — así un cliente que se aprendió
"/3 es Office 2021" no termina comprando otra cosa cuando crezca el catálogo.

Lo demás para el cliente:

- `/cid` — su Confirmation ID (escrito o por foto)
- `/saldo` — cuánto debe y cuánto crédito le queda
- `/historial` — sus últimos movimientos
- `/reposicion` — pedir el cambio de una clave que no le sirvió
- `/comprar CODIGO CANTIDAD` — sigue funcionando, por si ya se acostumbró

### Reposiciones

Si una clave no le sirve, el cliente manda `/reposicion`, toca la compra que
falló y escribe qué pasó. A ti te llega el aviso con el motivo y dos botones:

- **✅ Aprobar** → el bot le compra otra clave al proveedor y se la manda al
  cliente **sin cobrarle nada**. El costo del proveedor lo absorbes tú, igual
  que cuando repones a mano.
- **❌ Rechazar** → se le avisa al cliente.

Con `/reposiciones` ves las que quedan pendientes. Una reposición ya resuelta
no se vuelve a surtir aunque toques el botón otra vez.

### Qué te avisa el bot

Para que no estés a ciegas, te llega un mensaje cuando:

- alguien nuevo pide acceso
- un cliente **compra** (quién, qué, cuánto, número de orden)
- un cliente **genera un CID** (quién, cuánto se le cobró, su saldo)
- un cliente pide una **reposición**
- una compra queda **sin confirmar** con el proveedor

## 6. Comandos para ti (administrador)

- `/checkkey CLAVE1 CLAVE2 ...` — revisa si las claves sirven antes de venderlas
- `/checkredeem CLAVE1 CLAVE2 ...` — revisa si ya fueron canjeadas
- `/admincid INSTALLATION_ID` — saca un CID sin cargárselo a ningún cliente
- `/refrescarproductos` — actualiza el catálogo desde el proveedor
- `/precio CODIGO PRECIO` — fija el precio de venta (y le asigna su `/1`, `/2`...)

Estos tres aceptan el **código o el número** del producto, lo que tengas más
a la mano: `/nombre 1 Office 2016` hace lo mismo que `/nombre OFF2016 Office 2016`.

- `/nombre CODIGO Nombre bonito` — cambia el nombre que ve el cliente, para que
  no lea "Win10/11 Pro OEM 1PC 97% (Warranty: 30 day)" sino "Windows 11 Pro".
  Ese nombre **no se pierde** al correr `/refrescarproductos`.
  Con `/nombre CODIGO original` regresa al del proveedor.
- `/numero CODIGO NUMERO` — le cambia el número corto. Sirve para no
  cambiarles el número a tus clientes cuando cambias de versión de un
  producto: si el `/11` era la versión OEM y ahora vendes la Retail,
  `/numero 502 11` hace que el `/11` siga siendo el mismo número.
  Si ese número lo tiene otro producto a la venta, se intercambian.
- `/ocultar CODIGO` — lo saca de `/productos` sin borrarlo. Si luego le vuelves
  a poner precio, recupera el mismo número que ya conocían tus clientes.
- `/preciocid PRECIO` — fija lo que le cobras a un cliente por un CID
- `/comprarstock CODIGO CANTIDAD` — compra al proveedor sin cargarlo a ningún cliente (para tener inventario propio)
- `/clientes` — lista de todos los clientes con su saldo
- `/cliente TELEGRAM_ID` — detalle y últimos movimientos de un cliente
### Comprobantes de transferencia

Cuando un cliente manda `/saldo` y debe algo, el bot le muestra cuánto debe,
**tus datos para transferir** y un botón «📤 Ya te transferí». Al tocarlo,
manda la foto del comprobante y a ti te llega con tres botones:

- **✅ Liquidó todo** → borra su saldo completo
- **✏️ Otro monto** → escribes el número y se abona eso nada más
- **❌ Rechazar** → no mueve nada y se le avisa

El saldo **solo** se mueve cuando tú tocas el botón: mandar el comprobante no
descuenta nada por sí solo. Un comprobante ya resuelto no se puede volver a
aplicar, y un cliente no puede aprobarse el suyo.

Con `/comprobantes` ves los que faltan por revisar, con su foto.

Tus datos bancarios se cambian sin volver a desplegar:

```
/datosbancarios BBVA — Tu Nombre / CLABE: 0121800... / Cuenta: 159...
```

(las diagonales `/` se convierten en saltos de línea). Sin argumentos te
muestra cómo los están viendo tus clientes.

### Cobrar y registrar pagos (sin escribir IDs)

- `/pagar` — a secas. El bot te muestra quién te debe, con botones. Tocas al
  cliente y eliges **Liquidó todo** o **Otro monto**. Si es otro monto, solo
  escribes el número (`250.50` o `$250.50`, da igual).
- `/cobrar` — igual, pero para agregar un cargo manual.

Los dos siguen aceptando la forma larga (`/pagar 123456 250`) si la prefieres.
Cuando registras un pago, al cliente le llega el aviso con su saldo nuevo.

### Control de acceso (quién puede comprarte)

El bot **no le vende a cualquiera**. Cuando alguien nuevo manda `/start`, queda
en estado *pendiente* y no puede comprar ni pedir CIDs hasta que tú lo
apruebes. A ti te llega un aviso por Telegram con su ID.

- `/pendientes` — solicitudes de acceso sin resolver
- `/aprobar TELEGRAM_ID` — le das acceso (y el bot le avisa)
- `/bloquear TELEGRAM_ID` — le quitas el acceso (te advierte si aún te debe)

### Órdenes al proveedor

Cada compra se registra **antes** de llamar al proveedor, así que si la
llamada se cuelga (su documentación dice que puede tardar hasta 900s) la
orden no se pierde.

- `/ordenes` — órdenes que quedaron sin confirmar
- `/ordenes todas` — las últimas 30, en cualquier estado
- `/orden ORDER_ID` — le pregunta al proveedor qué pasó con esa orden

Cuando una compra falla, al cliente **no se le cobra** y a ti te llega un
aviso. Si después resulta que el proveedor sí la surtió, `/orden` te lo dice
y te deja listo el `/cobrar` para cobrárselo tú.

### Límites de crédito

Como el bot le compra la clave al proveedor **con tu dinero** y solo le suma la
deuda al cliente, cada cliente tiene un tope de cuánto puede deber.

- `/limiteglobal MONTO` — tope que aplica a todos por defecto (arranca en $1000)
- `/limite TELEGRAM_ID MONTO` — tope propio para un cliente de confianza
- `/limite TELEGRAM_ID global` — lo regresa al tope general
- `/maxcantidad NUMERO` — máximo de unidades por compra (arranca en 5)

Si una compra hace que el cliente pase su límite, el bot la rechaza y le dice
cuánto tiene disponible. El límite se revisa dos veces: al pedir la compra y
otra vez al confirmarla.

## 7. Notas importantes

- **Lectura de fotos del Installation ID:** el proveedor **no recibe
  imágenes** — sus tres endpoints (`get-cid`, `check-keys`, `redeem-keys`)
  esperan texto. Convertir la foto en dígitos es trabajo del bot, y es la
  parte frágil del flujo.

  El lector prueba la foto en varias versiones (más grande, con contraste,
  con la iluminación emparejada para quitar sombras, invertida por si la
  pantalla está en modo oscuro) y se queda con la primera lectura que forme
  un ID válido de 54 o 63 dígitos. Medido contra pantallas de prueba, pasó
  de leer 4 de 13 a 11 de 13; falla todavía con fotos muy en ángulo o muy
  movidas.

  Por eso **nunca manda al proveedor una lectura dudosa**: le muestra al
  cliente lo que leyó y le pide confirmar con un botón. Si la lectura salió
  incompleta, le pide otra foto en vez de gastar una consulta del cupo.

  El cliente ya no necesita mandar `/cid` antes: puede mandar la foto de una,
  o pegar el Installation ID escrito y el bot lo reconoce solo.

- **Base de datos:** es SQLite guardado en el archivo que definas en
  `DB_PATH`. Con el Volume de Railway persiste entre despliegues. Si tu
  volumen de clientes crece mucho y quieres algo más robusto (Postgres),
  se puede migrar después.
- **Compra automática (`/comprar`):** el bot compra la clave al proveedor
  en el momento en que el cliente confirma, usando tu `PROVIDER_TOKEN`, y
  le suma el cargo a su cuenta pendiente. Asegúrate de que los precios que
  configures con `/precio` ya incluyan tu margen sobre el costo del
  proveedor.
- **Timeout del proveedor:** si una compra se queda "colgada", el proveedor
  puede tardar hasta 900 segundos en resolverla. El bot ya no se queda
  congelado mientras tanto (las llamadas corren en un hilo aparte) y la
  orden queda guardada para consultarla con `/orden`.

## 9. Pruebas antes de desplegar

Railway despliega solo en cuanto cambia `main`, así que conviene correr las
pruebas antes de hacer merge:

```bash
python tests/correr_todas.py
```

No tocan la red ni la base de producción: usan un proveedor simulado y una
base temporal. Cubren la migración de la base, el flujo de compra (doble
clic, proveedor caído, límite de crédito) y que la app arranque con todos
sus handlers.
