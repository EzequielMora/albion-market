# Albion Market — Plan del proyecto

## 1. Objetivo

Aplicación de escritorio que, con **dos cuentas de Albion en la misma PC**, cruza en tiempo real:

- **Cuenta "Mercado Negro"** (en Caerleon): qué ítems quiere comprar el Mercado Negro y a qué precio.
- **Cuenta "Principal"** (en una ciudad real): a cuánto se venden esos mismos ítems en la ciudad.

Resultado: una **lista ordenada por % de ganancia** con nombre exacto, tier.encanto, calidad, precio en la ciudad, precio en el Mercado Negro, ganancia neta y %. **El usuario decide y compra a mano.**

## 2. Límites del proyecto (no negociables)

| La app hace | La app NO hace |
|---|---|
| Lee el tráfico de red del juego de forma pasiva | Hacer clics, escribir o presionar teclas dentro del juego |
| Calcula, ordena y avisa | Comprar o vender |
| Copia nombres al portapapeles y muestra el siguiente ítem a buscar | Modificar o inyectar paquetes |
| Guarda datos de mercado en una base local | Leer posiciones u otros datos de jugadores |
| | Subir datos a internet |

**Motivo:** automatizar la entrada del juego (clics y teclas) es lo que Sandbox detecta y banea. La lectura pasiva de datos de mercado es lo que SBI tolera ("look and analyze").

## 3. Flujo de uso

```
[Inicio] → La app detecta los 2 procesos de Albion abiertos
        → Pregunta: "¿Cuál es MERCADO NEGRO y cuál es PRINCIPAL?" (muestra el personaje de cada uno)

[Cuenta Mercado Negro]  El usuario abre la pestaña "Vender" del Mercado Negro y pasa las páginas
                        → la app captura: ítem, tier.encanto, calidad mínima, precio y cantidad
                        → los agrega a la COLA DE OBJETIVOS (ordenada por precio, filtrada)

[Cuenta Principal]      La app muestra el siguiente objetivo y copia su nombre exacto al portapapeles
                        → el usuario pega y presiona Enter en el buscador del mercado (≈2 s)
                        → la app captura las órdenes de venta de TODAS las calidades
                        → calcula con la calidad más barata que sea ≥ la calidad mínima
                        → actualiza la LISTA DE OPORTUNIDADES y pasa al siguiente objetivo

[Alerta]                Si ganancia ≥ mínimo y % ≥ mínimo → 🔔 aviso
[Seguimiento]           Si la orden del Mercado Negro desaparece o cambia → se marca en la lista
```

## 4. Arquitectura

```
┌──────────────┐   ┌───────────────┐   ┌──────────────┐   ┌────────────┐   ┌─────────────┐
│ Capturador   │──►│ Decodificador │──►│ Base local   │──►│ Motor de   │──►│ Interfaz    │
│ (Npcap, UDP  │   │ Photon →      │   │ (SQLite)     │   │ cálculo    │   │ lista,      │
│ 5056)        │   │ mensajes de   │   │              │   │            │   │ cola,       │
│ + puerto→PID │   │ mercado       │   │              │   │            │   │ alertas     │
└──────────────┘   └───────────────┘   └──────────────┘   └────────────┘   └─────────────┘
        ▲                                     ▲
  Asignación de roles                Catálogo de ítems (ID ↔ nombre exacto en español),
  por proceso                        a partir de archivos estáticos (ao-bin-dumps), sin API
```

| Módulo | Responsabilidad |
|---|---|
| **Capturador** | Escucha el tráfico UDP de Albion. Identifica qué cuenta envió cada paquete por puerto local → proceso (PID) → rol. |
| **Decodificador** | Interpreta el protocolo Photon y extrae: órdenes de compra del Mercado Negro, órdenes de venta de la ciudad e historial. |
| **Catálogo de ítems** | Traduce un ID como `T7_ARMOR_PLATE_SET3@2` a "Armadura real 7.2" con su nombre exacto en español. |
| **Base local** | Órdenes con hora de captura, para saber qué tan frescos son los datos. Se reutiliza en el modo órdenes de compra (fase 6). |
| **Motor de cálculo** | Aplica la regla de calidad ≥ mínima, impuestos configurables, filtros y ranking. |
| **Interfaz** | Asignación de roles, cola de objetivos, lista de oportunidades, configuración y alertas. |

### Fórmula

```
precio_ciudad   = mín(órdenes de venta en ciudad con mismo tier.encanto y calidad ≥ calidad_mínima)
ingreso_neto    = precio_MN × (1 − impuesto_venta)          # venta directa a orden del MN
ganancia        = ingreso_neto − precio_ciudad − costo_viaje
%               = ganancia / precio_ciudad
mostrar si      ganancia ≥ GANANCIA_MIN  y  % ≥ PORC_MIN  y  edad_dato_MN ≤ EDAD_MAX
```

### Configuración

`impuesto_venta` (según premium), `GANANCIA_MIN`, `PORC_MIN`, `PRECIO_MN_MIN` (filtro de la cola), `costo_viaje`, `EDAD_MAX` del dato del Mercado Negro y ciudad de la cuenta principal.

## 5. Fases

| Fase | Entregable | Criterio de éxito |
|---|---|---|
| **0. Pruebas de viabilidad** | Script de prueba | (a) Se pueden abrir 2 clientes en la misma PC. (b) Las dos cuentas reciben datos de mercado **sin cifrar**. (c) Pasar de página en el Mercado Negro genera tráfico legible, o todos los datos llegan de una vez. |
| **1. Capturador y decodificador** | Imprime en consola las órdenes que se ven en pantalla | Coinciden con lo que muestra el juego |
| **2. Catálogo y base local** | Nombres exactos en español y datos guardados | Ningún ID sin traducir |
| **3. Motor de cálculo** | Lista calculada en consola | Cálculo verificado a mano con 5 ítems |
| **4. Roles e interfaz** | App con selector de cuentas y lista ordenada | Uso completo del flujo |
| **5. Asistente de búsqueda** | Cola, portapapeles, alertas y seguimiento | Recorrer 20 objetivos en ~1 minuto |
| **6. (Opcional) Modo órdenes de compra** | Ranking del método 1 usando el historial guardado del Mercado Negro | — |

**Si la fase 0 falla:**
- Datos cifrados: se cambia a OCR.
- No se pueden abrir 2 clientes: se usa una máquina virtual o una segunda PC.

## 5b. Hallazgos de la fase 0 (2026-10-09)

- Albion usa **Photon Protocol18**. El decodificador está en `albion_market/photon.py`.
- Los datos del mercado llegan **sin cifrar** en la cuenta probada (PID 4468).
- **Op 82 = órdenes de compra del Mercado Negro** (pestaña Vender):
  - Página de 50 órdenes; el parámetro 13 de la solicitud es el offset (0, 50, 100, …).
  - Vienen ordenadas por precio **descendente**.
  - `BuyerName = "@BLACK_MARKET"`, `LocationId = null`.
  - A veces el cliente repite la misma página → deduplicar por `Id`.
- **Op 81 = órdenes de venta del mercado normal** (pestaña Comprar):
  - Página de 50 ofertas; el parámetro 13 es el offset.
  - Vienen ordenadas por precio **ascendente**.
  - La solicitud **no lleva el texto buscado**: lleva en el parámetro 8 la **lista de índices de ítems** que coinciden con la búsqueda. Ejemplo: 25 índices = 5 tiers × 5 encantamientos.
  - La respuesta mezcla tiers, encantamientos y **todas las calidades**.
- Campos de cada orden: `Id, ItemTypeId (T4_CAPEITEM_UNDEAD@2), Tier, EnchantmentLevel, QualityLevel (1–5), UnitPriceSilver (÷10000), Amount, AuctionType (offer/request), Expires`.
- **Consecuencia para la búsqueda:** hay que copiar el nombre **con tier** y elegir el **encantamiento** en el filtro, para que las 50 ofertas sean del ítem objetivo. Si la página llega llena (50) sin alcanzar la calidad pedida, la app pide pasar a la siguiente página.
- **Búsqueda por filtros (op 81 sin texto):**
  - Parámetros de la solicitud: 1 = categoría (`"weapons"`), 2 = subcategoría, 7 = tier (`"8"`), 10 = encantamiento (`"2"`), 11 = calidad (`-2` = todas), 13 = offset. Sin lista de ítems.
  - Devuelve **todos los ítems de la categoría ordenados por precio ascendente**: 8 páginas de armas T8.2 solo llegaron de 2,75M a 6,6M.
  - → Una categoría completa es lenta para ítems caros. Hay que usar **subcategoría** (espada, arco, …) o búsqueda por nombre.
- **Regla de corte:** como el orden es ascendente, cuando el precio más bajo de la página supera el ingreso neto máximo de los objetivos pendientes del grupo, ninguna página siguiente puede dar ganancia → la app avisa "detente".
- **Evento 81 = silver del jugador** (parámetro 1 ÷ 10000; parámetro 0 = id del personaje). Llega al comprar o vender. Op 83 = compra directa de una oferta.
- El catálogo `ao-bin-dumps` coincide con la versión actual del juego: los índices de la solicitud 81 corresponden al campo `Index`.
- Pendiente: probar 2 clientes a la vez, el filtro de subcategoría, si existe otro orden, y el historial de precios.

## 6. Dos cuentas en la misma PC

- **Primera opción:** dos clientes de Albion abiertos a la vez en Windows. Hay que verificar en la fase 0 si el launcher lo permite y si los Términos de Servicio permiten tener las dos cuentas conectadas al mismo tiempo.
- **Si no se puede:** máquina virtual (pesada: necesita GPU y RAM y la captura es más compleja) o una segunda PC o notebook. Con una segunda PC, cada una corre un capturador y se comunican por red local.

## 7. Decisiones pendientes

1. Lenguaje: **Python** (más simple) o **C#** (hay más librerías de Photon y Albion ya hechas).
2. ¿Premium? Define el impuesto de venta.
3. Umbrales: ganancia mínima, % mínimo y precio mínimo en el Mercado Negro.
4. Ciudad o ciudades de la cuenta principal.
