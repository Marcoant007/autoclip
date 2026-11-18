# Mídia animada nas cenas

O editor aceita imagens estáticas PNG/JPG/WebP (15 MB) e GIF, WebP animado ou MP4 (50 MB, até 180 segundos). Todos os arquivos têm limite de 20 megapixels. O backend valida o conteúdo; extensão e MIME enviados pelo navegador não determinam o tipo.

GIFs, WebPs animados e vídeos são convertidos localmente para MP4 H.264, sem áudio, com até 1080 × 1920 e 30 fps. Uma imagem de um único quadro continua estática. A normalização mantém a proporção; a composição final preenche o quadro vertical com recorte central.

Alguns leitores de WebP animado informam duração zero no contêiner mesmo quando os quadros são válidos. Nesses casos, o upload calcula a duração a partir dos tempos dos quadros decodificados com Pillow, mantendo a validação do limite de 180 segundos e a animação na conversão.

Na renderização, o vídeo repete se for mais curto que a narração e é cortado ao terminar a fala. A voz e as legendas vêm do fluxo de narração. O áudio original do arquivo não é usado. Em modo `auto`, uma mídia enviada tem prioridade sobre um plano de cartoon salvo na mesma cena; `cartoon` e `cards` continuam sendo escolhas explícitas de renderizador.

## API compatível

O endpoint existente `POST /api/creations/{id}/images` aceita também GIF/WebP animado/MP4 e retorna:

```json
{"image_id": "0123456789abcdef", "media_type": "video"}
```

Salve os dois campos na cena. `media_type` aceita `image` ou `video` e define a prévia do editor; roteiros antigos assumem `image`. O renderizador identifica o arquivo persistido independentemente desse indicador. O identificador continua chamado `image_id` para preservar os roteiros existentes.

`GET /api/creations/{id}/images/{image_id}` entrega PNG ou MP4 com o Content-Type correspondente. `?poster=true` entrega um quadro PNG de vídeos. MP4 aceita requisições Range. Assets são vinculados ao roteiro; importar um roteiro limpa referências e exige novo envio dos arquivos.

Falhas de upload retornam `detail.message` e `detail.hint`. Arquivo vazio retorna 400; limite de tamanho/resolução, 413; formato não reconhecido, 415; falha de leitura/conversão, 422; dependência ausente, 503; tempo excedido, 504. Uma falha interna retorna 500. O terminal registra a causa original, incluindo a saída de erro do FFmpeg. Uma falha de conversão ou de gravação não é tratada como formato não suportado.

## Vozes

A lista de narração e a validação dos personagens incluem Antônio, Francisca e Thalita para português brasileiro. Thalita foi consultada no catálogo do serviço e teve síntese real verificada. O fluxo atual usa Edge TTS; arquivos MP3 de amostra não instalam novos sintetizadores.
