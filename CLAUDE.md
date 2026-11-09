# Lookdev Kit – pravidla pro Claude

Blender extension (záložka **Lookdev** v N panelu). Autor: Ota. Komunikace česky, tykání, stručně.

## Struktura
- `Lookdev Kit/__init__.py` – celý addon (jeden soubor)
- `Lookdev Kit/ding.wav` – zvuk po dokončení renderu (Render Ding)
- `Lookdev Kit/blender_manifest.toml` – metadata a verze (žádné `bl_info`)
- `.github/workflows/build.yml` – po pushi do `main` sestaví zip, index.json, Release a nasadí GitHub Pages

## Verzování
- Zvyšovat jen poslední číslo (1.0.12 → 1.0.13). Prostřední/první číslo neměnit, dokud to Ota výslovně neřekne.
- Každá změna addonu = nová verze v `blender_manifest.toml`, jinak Blender update nenabídne.
- Zip pro Otu pojmenovat s verzí a mezerami, bez podtržítek: `Lookdev Kit 1.0.13.zip` (soubory v kořeni zipu).

## Kód
- Min. Blender 4.2. ID addonu přes `ADDON_ID = __package__ or __name__` – nikdy nehardcodovat název.
- Texty v UI a v preferencích anglicky; komentáře v kódu můžou být česky.
- Layout panelů: label vlevo, hodnota vpravo (jako nativní property split v Blenderu).
- Zvuk: přehrávat přes `winsound` (Windows) / `afplay` (Mac), ne přes `aud.Device()` – praská.
- Blender se tu spustit nedá; ověřit aspoň `python3 -m py_compile` a nechat validaci na GitHub Action.

## Distribuce
Blender repo URL: `https://rrakato.github.io/lookdev-kit/index.json`
