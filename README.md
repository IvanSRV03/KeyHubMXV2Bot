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
   - `PROVIDER_TOKEN` → `kt_5kWDPqBPBxSlZSzg1qmYUGA6mwOAi1OebM5cq93LhPE`
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

## 5. Comandos para tus clientes

- `/start` — se da de alta automáticamente
- `/productos` — ve el catálogo con precios
- `/comprar CODIGO CANTIDAD` — compra (le pide confirmación con botones antes de procesar)
- `/cid` — te pide el Installation ID (texto o foto) y te regresa el Confirmation ID
- `/saldo` — cuánto debe acumulado
- `/historial` — sus últimos movimientos

## 6. Comandos para ti (administrador)

- `/checkkey CLAVE1 CLAVE2 ...` — revisa si las claves sirven antes de venderlas
- `/checkredeem CLAVE1 CLAVE2 ...` — revisa si ya fueron canjeadas
- `/admincid INSTALLATION_ID` — saca un CID sin cargárselo a ningún cliente
- `/refrescarproductos` — actualiza el catálogo desde el proveedor
- `/precio CODIGO PRECIO` — fija el precio de venta de un producto
- `/preciocid PRECIO` — fija lo que le cobras a un cliente por un CID
- `/comprarstock CODIGO CANTIDAD` — compra al proveedor sin cargarlo a ningún cliente (para tener inventario propio)
- `/clientes` — lista de todos los clientes con su saldo
- `/cliente TELEGRAM_ID` — detalle y últimos movimientos de un cliente
- `/cobrar TELEGRAM_ID MONTO concepto` — agrega un cargo manual
- `/pagar TELEGRAM_ID MONTO` — registra que el cliente te pagó (baja su saldo)

## 7. Notas importantes

- **Lectura de fotos del Installation ID (OCR):** el bot usa `pytesseract`
  para leer los números de la foto. Es un método heurístico — funciona bien
  con fotos claras y derechas, pero puede fallar con fotos borrosas, con
  brillo o en ángulo. Si falla, el bot le pide al cliente que escriba el
  Installation ID directamente con `/cid NUMERO`. Si en la práctica falla
  seguido, dímelo y podemos cambiar a un servicio de OCR más robusto (con
  costo por imagen) o quitar la opción de foto y dejar solo texto.
- **Base de datos:** es SQLite guardado en el archivo que definas en
  `DB_PATH`. Con el Volume de Railway persiste entre despliegues. Si tu
  volumen de clientes crece mucho y quieres algo más robusto (Postgres),
  se puede migrar después.
- **Compra automática (`/comprar`):** el bot compra la clave al proveedor
  en el momento en que el cliente confirma, usando tu `PROVIDER_TOKEN`, y
  le suma el cargo a su cuenta pendiente. Asegúrate de que los precios que
  configures con `/precio` ya incluyan tu margen sobre el costo del
  proveedor.
- **Timeout del proveedor:** según su documentación, si una compra se queda
  "colgada", el proveedor puede tardar hasta 900 segundos en resolverla. Si
  eso pasa, el bot te muestra el `orderId` generado; puedo agregar un
  comando para consultar órdenes pendientes (`buy-key/order`) si te
  encuentras con este caso seguido.

## 8. Correrlo en tu computadora antes de subirlo (opcional)

```bash
python -m venv venv
source venv/bin/activate  # en Windows: venv\Scripts\activate
pip install -r requirements.txt
# instala tesseract-ocr en tu sistema (en Mac: brew install tesseract)
cp .env.example .env  # y llena los valores
export $(cat .env | xargs)  # en Windows usa otra forma de cargar variables
python bot.py
```
