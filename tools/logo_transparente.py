"""Gera o logo Gromar em PNG com fundo transparente, a partir do JPG original.

O JPG não tem canal alfa: na legenda ele entra como um retângulo branco. Aqui o
fundo é recortado por flood fill a partir das bordas — só o branco *conectado à
borda* sai, então o miolo claro dentro das letras é preservado. As bordas ganham
alfa proporcional para não ficarem serrilhadas.

Uso:
    python tools/logo_transparente.py [--origem <jpg>] [--destino <png>]
"""

from __future__ import annotations

import argparse
import os

from PIL import Image, ImageDraw

ORIGEM = r"C:\Users\peron\GROMAR INDUSTRIA E COMERCIO LTDA\Comercial - Documentos\3 - Apresentação comercial e fotos\Logo Gromar\Logo Horizontal P.jpg"
DESTINO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "logo-gromar.png")

MARCA = (255, 0, 255)   # magenta: cor que não existe no logo, usada como marcador
TOLERANCIA = 40         # quanto o JPEG pode desviar do branco puro
LIMIAR_BORDA = 235      # acima disto o pixel é considerado quase-fundo


def recortar_fundo(origem: str, destino: str) -> tuple[int, int, float]:
    im = Image.open(origem).convert("RGB")
    marcado = im.copy()
    for canto in ((0, 0), (im.width - 1, 0), (0, im.height - 1), (im.width - 1, im.height - 1)):
        ImageDraw.floodfill(marcado, canto, MARCA, thresh=TOLERANCIA)

    saida = im.convert("RGBA")
    px_orig, px_marc, px_saida = im.load(), marcado.load(), saida.load()
    transparentes = 0
    for y in range(im.height):
        for x in range(im.width):
            if px_marc[x, y] != MARCA:
                continue
            r, g, b = px_orig[x, y]
            claro = max(r, g, b)
            if claro >= LIMIAR_BORDA:
                alfa = 0
            else:
                # anti-aliasing: quanto mais escuro, mais opaco
                alfa = int(255 * (LIMIAR_BORDA - claro) / LIMIAR_BORDA)
            px_saida[x, y] = (r, g, b, alfa)
            if alfa == 0:
                transparentes += 1

    os.makedirs(os.path.dirname(destino), exist_ok=True)
    saida.save(destino, "PNG")
    total = im.width * im.height
    return im.size[0], im.size[1], 100.0 * transparentes / total


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--origem", default=ORIGEM)
    p.add_argument("--destino", default=DESTINO)
    args = p.parse_args()

    larg, alt, pct = recortar_fundo(args.origem, args.destino)
    print(f"{args.destino}\n  {larg}x{alt} px | {pct:.1f}% do quadro virou transparente")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
