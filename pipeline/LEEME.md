# Clipper automático: Favorited Mansion

Graba el directo, detecta los mejores momentos y deja un clip vertical listo cada hora, con subtítulos, hook y el logo de Favorited siempre visible.

## Arrancar (recomendado: el panel)
Haz doble clic en **`abrir_panel.bat`**. Se abre el panel en el navegador (http://127.0.0.1:8765). Desde ahí puedes:
- **Iniciar y parar el directo**, y ver lo que está haciendo.
- **Sacar clips de un VOD** (enlace de YouTube con desde/hasta) o de un vídeo de tu PC.
- **Ver los clips** en tres pestañas: *Listos para subir*, *En cola* y *Descartados*.
- **Editar el hook**: al guardar, el vídeo se vuelve a montar solo en unos 10 segundos.
- **Editar la descripción** y copiarla con un clic.
- **Mover clips a listos, descartarlos o recuperarlos**, y abrir su carpeta.
- **Cambiar los ajustes** (cada cuánto sale un clip, diseño, duración, hashtags…).

Deja abierta la ventana negra del panel. Si la cierras, se apaga el panel; el directo sigue funcionando y lo puedes parar desde el panel cuando lo vuelvas a abrir.

## Directo: cualquier stream
En la pestaña **Directo**:
1. Pega la URL del directo: YouTube (`…/@canal/live` o el enlace del vídeo), Twitch o Kick.
2. Elige la plantilla y el idioma. **Modo:** "General" para cualquier stream; "Campaña Favorited" usa los hooks y hashtags de esa campaña.
3. Pulsa **Iniciar**. Si el directo aún no ha empezado, el programa espera y empieza solo.

## Usarlo desde el móvil
El procesado se hace en tu PC (necesita la tarjeta gráfica), así que **el PC tiene que estar encendido con el panel abierto**. El móvil se conecta a él por un túnel seguro de Cloudflare.
1. En el panel del PC, tarjeta **Acceso desde el móvil**: crea una contraseña (mínimo 8 caracteres).
2. Pulsa **Activar acceso móvil**. Aparecen una dirección `https://….trycloudflare.com` y un código QR.
3. Escanea el QR con el móvil y entra con tu contraseña. La sesión dura 30 días.
4. Para que parezca una app: en el navegador del móvil, **Añadir a pantalla de inicio**.

Seguridad:
- Desde fuera siempre se pide contraseña; tras 8 fallos se bloquea 15 minutos.
- La contraseña y el túnel solo se pueden cambiar desde el propio PC.
- **La dirección cambia cada vez que activas el túnel**: vuelve a escanear el QR. Para una dirección fija haría falta una cuenta de Cloudflare con un dominio propio.
- Pulsa **Desactivar** cuando no lo uses.

## Campañas
En el generador y en el directo puedes elegir una **campaña**. Cada clip lleva entonces el nombre del creador en la descripción ("IShowSpeed: …") y sus hashtags obligatorios delante. Al elegir la campaña se selecciona también su plantilla recomendada.

Ya vienen configuradas:
- **IShowSpeed × Expedia:** #IShowSpeed #Expedia, plantilla Fondo desenfocado para que no se corte la maleta amarilla.
- **Kai Cenat:** #KaiCenat.
- **Lacy:** #Lacy.

En el generador, despliega **"Gestionar campañas"** para añadir, editar o quitar campañas (nombre, creador, hashtags, plantilla y notas). Se guardan en `campanas.json`.

Recuerda: **cada clip cuenta solo para su campaña**, y algunas reglas no las puede comprobar el programa. Por ejemplo, que se vea la maleta amarilla o que la descripción diga bien el destino en la de Speed: revísalo antes de subir.

## Generador: clips de cualquier vídeo de YouTube
En el panel, pestaña **Generador** (http://127.0.0.1:8765/generador):
1. Pega el enlace de YouTube. Opcional: un tramo (desde/hasta) para ir más rápido.
2. Elige el número de clips, la duración, el idioma (automático, inglés o español) y si quieres censurar los tacos.
3. Elige una plantilla o personalízala combinando diseño, subtítulos y hook.
4. Pulsa **Generar clips**. Los clips van apareciendo a la derecha **ordenados por viralidad** (#1 = el mejor).

En cada clip puedes editar el hook (se vuelve a montar solo), cambiarle la plantilla, descargarlo, copiar la descripción o descartarlo.

**Plantillas:** Clásico viral, Karaoke amarillo, Pantalla partida, Podcast dos caras, Pop palabra a palabra, Fondo desenfocado, Minimalista, Estilo Hormozi, Documental y Gaming/streamer.
- **5 diseños:** pantalla completa, pantalla partida, fondo desenfocado, podcast y automático.
- **5 estilos de subtítulos:** karaoke, Hormozi, pop, caja negra y minimalista.
- **4 estilos de hook:** caja blanca, caja negra, amarillo y ninguno.

**Formato viral automático** (en el generador, el directo y al rehacer clips):
- **Inicio y final:** el clip empieza donde arranca la acción (se quitan frases de relleno como "yeah… okay… my bad bro") y acaba en el remate, sin la cola de despedidas.
- **Quitar silencios:** corta las pausas de más de 0,8 s (cortes rápidos) y los subtítulos se ajustan solos.
- **Pitar tacos:** además de censurarlos en pantalla, se pitan en el audio, para evitar restricciones de edad.
- **Hooks sin tacos:** sin API, el hook y la descripción usan frases sin palabrotas siempre que haya alguna.
- Cada clip muestra **⚠ N tacos** si tiene muchas palabrotas.
- Los dos primeros se pueden desactivar: en el generador con sus casillas, y en el directo en Ajustes.

**Detalles:**
- El encuadre sigue la cara en cada plano: si el vídeo cambia de cámara, se vuelve a encuadrar.
- Al descargar un vídeo entero se quitan los anuncios de patrocinadores (SponsorBlock).
- Sin API key, el hook es la frase más llamativa del clip y la viralidad se calcula por volumen, reacciones y ritmo al hablar. Con API key, Claude escribe el hook y puntúa cada clip, y el ranking mejora mucho.
- Se guarda todo en `proyectos/<id del vídeo>/`. Un vídeo de 1 hora tarda unos 5–10 minutos.
- También por consola: `python run.py generar URL --clips 20 --plantilla viral`
- **Directos muy largos (VOD de 3–10 h):** `python run.py escanear URL --top 8` descarga solo el audio, lo analiza entero y te da los mejores momentos con su hora. Luego genera solo esos tramos con "desde/hasta" (deja un minuto de margen a cada lado), sin bajar horas de vídeo.

Sin panel: doble clic en **`iniciar_directo.bat`** y déjalo abierto mientras dure el stream. Ctrl+C para parar.

Cada hora suena un aviso y aparece una carpeta nueva en `listos/` con:
- `clip.mp4`, el vídeo listo para subir
- `texto_post.txt`, la descripción con hashtags (ya copiada al portapapeles)

Súbelo a YouTube Shorts, TikTok, Instagram y X, pega la descripción y listo.

## Qué hace por dentro
1. **Graba** el directo en trozos de 5 minutos (`segmentos/`, se borran solos a las 3 h).
2. **Transcribe** cada trozo con Whisper en la GPU.
3. **Detecta momentos** por picos de volumen (gritos, sustos, risas) y por palabras como "oh my god", "run" o "what the".
4. **Monta el vertical**:
   - Diseño A, cuando detecta una cara: plano entero arriba y zoom a la cara abajo.
   - Diseño B, cuando no la detecta: plano entero centrado sobre un fondo desenfocado.
   - En los dos diseños el plano entero lleva el logo "fav.com", así que nunca se corta.
5. **Escribe el hook** (ver abajo) y lo deja en la cola (`cola/`).
6. **Cada 60 min** pasa a `listos/` el mejor clip de la cola. Descarta los clips de más de 6 h porque ya no son noticia.

## Hooks con IA (recomendado)
Sin configurar nada, los hooks salen de plantillas genéricas. Para que los escriba Claude a partir de lo que se dice en el clip (nombres, invitados como DDG, etc.):
1. Crea una API key en https://console.anthropic.com
2. En PowerShell: `setx ANTHROPIC_API_KEY "tu-clave"` y abre una consola nueva.

Cuesta en torno a 1 céntimo por clip.

## Otros modos
```
python run.py video ruta\al\video.mp4          clips de un vídeo ya descargado
python run.py vod URL --desde 1:00:00 --hasta 2:00:00   descarga un trozo del VOD y lo procesa
python run.py publicar                          suelta ya el mejor clip de la cola
```

## Ajustes (`config.json`)
- `publish_every_minutes`: cada cuánto sale un clip (60 por defecto).
- `clips_per_segment`: candidatos por cada trozo de 5 min.
- `layout`: `"auto"`, `"A"` o `"B"`.
- `hook_seconds`: 0 = el hook se ve todo el clip; 3 = solo los 3 primeros segundos.
- `clip_min_seconds` / `clip_max_seconds`: duración de los clips.

## Antes de subir, revisa 10 segundos
Una persona de ClipFarm revisa cada clip antes de pagarlo. Antes de subirlo, comprueba que el momento tiene gracia y que el hook encaja. Si no, borra la carpeta y ejecuta `python run.py publicar` para sacar el siguiente.

Para cobrar: post publicado 30 días, likes visibles y un 40% de vistas desde EE. UU., Reino Unido, Canadá o Australia.
