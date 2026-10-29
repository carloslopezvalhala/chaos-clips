# Chaos Clips

Herramienta local para sacar clips verticales virales (9:16, con subtítulos y hook) de directos y vídeos de YouTube, Twitch y Kick, pensada para campañas de clipping (ClipFarm, Reach / Content Rewards).

- **Directo:** graba un stream en vivo y saca clips cada pocos minutos.
- **Generador:** pega la URL de un vídeo y obtén clips ordenados por viralidad, con 10 plantillas.
- **Formato viral automático:** recorte al momento clave, cortes de silencio, tacos pitados, subtítulos palabra a palabra y encuadre que sigue la cara en cada plano.
- **Campañas:** nombre del creador y hashtags obligatorios en cada descripción.
- **Panel web** con acceso desde el móvil (contraseña + túnel de Cloudflare).

Instrucciones completas en [`pipeline/LEEME.md`](pipeline/LEEME.md).

## Requisitos
- Windows, Python 3.12, ffmpeg, yt-dlp y Node.js (lo usa yt-dlp para YouTube)
- Tarjeta gráfica NVIDIA recomendada (Whisper en GPU)
- `pip install faster-whisper opencv-python flask anthropic qrcode nvidia-cublas-cu12 "nvidia-cudnn-cu12==9.*"`
- Opcional: `cloudflared` para el acceso desde el móvil, y `ANTHROPIC_API_KEY` para hooks escritos por Claude

## Arrancar
Doble clic en `pipeline/abrir_panel.bat`.
