# Lookdev Kit

Blender extension – záložka **Lookdev** v N panelu (render, output, Render Ding, ray visibility, transformace, světla, color picker).

Vyžaduje Blender 4.2+.

## Instalace přes repozitář (automatické aktualizace)
1. Edit → Preferences → Get Extensions → Repositories (šipka vpravo nahoře) → **+** → **Add Remote Repository**
2. URL: `https://rrakato.github.io/lookdev-kit/index.json`
3. Zapnout **Check for Updates on Startup**
4. V Get Extensions vyhledat „Lookdev Kit“ → Install

## Ruční instalace
Stáhnout zip z Releases → Edit → Preferences → Get Extensions → šipka → **Install from Disk**.

## Nová verze
1. Zvednout `version` v `Lookdev Kit/blender_manifest.toml`
2. Push do `main` → GitHub Action sestaví zip, index.json a Release
