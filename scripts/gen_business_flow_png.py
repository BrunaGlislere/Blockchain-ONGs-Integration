from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs'
OUT.mkdir(exist_ok=True)
IMG = OUT / 'fluxo_regra_negocio.png'

def draw_diagram():
    W, H = 1800, 1100
    bg = (28, 30, 36)
    card = (42, 45, 52)
    fg = (230, 230, 230)
    acc = (59, 130, 246)

    img = Image.new('RGB', (W, H), bg)
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype('arial.ttf', 18)
        title = ImageFont.truetype('arial.ttf', 28)
        small = ImageFont.truetype('arial.ttf', 16)
    except Exception:
        font = ImageFont.load_default(); title = font; small = font

    d.text((20, 15), 'Fluxo da Regra de Negócios — Integração e Blockchain (simulada)', fill=fg, font=title)

    def box(x, y, w, h, text, fill=card):
        d.rounded_rectangle([x, y, x+w, y+h], radius=10, fill=fill, outline=(80,80,90))
        d.multiline_text((x+12, y+10), text, fill=fg, font=font)
        return (x,y,w,h)

    def arrow(ax, ay, bx, by):
        d.line([ax, ay, bx, by], fill=fg, width=3)
        # head
        hx, hy = bx, by
        d.polygon([(hx-8, hy-6),(hx, hy),(hx-8, hy+6)], fill=fg)

    # Config
    box(20, 60, 360, 80, 'Configurações\njanela_data=±1 dia; desc_thresh=0.4')

    # Ingestão e âncora
    a = box(20, 180, 320, 80, 'Extrato CSV/OFX (sandbox)')
    b = box(380, 180, 340, 100, 'Ingestão / Canonicalização\n(normaliza datas/valores/texto)')
    c = box(760, 180, 260, 80, 'Hash SHA-256\n(CSV canônico)')
    d1 = box(1060, 170, 260, 100, 'Âncora existente?')
    e = box(1360, 140, 360, 110, 'Cria âncora\n{sha256, origem, timestamp}')
    h = box(1360, 260, 360, 80, 'Reutiliza âncora anterior')
    f = box(1060, 300, 260, 80, 'Fila de Âncoras\npendentes')

    arrow(a[0]+a[2], a[1]+40, b[0], b[1]+40)
    arrow(b[0]+b[2], b[1]+40, c[0], c[1]+40)
    arrow(c[0]+c[2], c[1]+40, d1[0], d1[1]+50)
    arrow(d1[0]+d1[2], d1[1]+30, e[0], e[1]+30)
    arrow(d1[0]+d1[2], d1[1]+70, h[0], h[1]+30)
    arrow(e[0]+e[2], e[1]+40, f[0]+130, f[1])
    arrow(h[0]+h[2], h[1]+40, f[0]+130, f[1]+80)

    # Mineração
    g = box(1060, 420, 260, 80, 'Mineração de bloco')
    g1 = box(1360, 420, 360, 80, 'Empacotar transações\nde âncora')
    g2 = box(1360, 520, 360, 80, 'Calcular Merkle Root')
    g3 = box(1360, 620, 360, 100, 'Bloco: {prev_hash,\nmerkle_root, ts, txs}')
    g4 = box(1060, 640, 260, 80, 'chain.jsonl / Ledger')

    arrow(f[0]+130, f[1]+80, g[0]+130, g[1])
    arrow(g[0]+g[2], g[1]+40, g1[0], g1[1]+40)
    arrow(g1[0]+g1[2], g1[1]+40, g2[0], g2[1]+40)
    arrow(g2[0]+g2[2], g2[1]+40, g3[0], g3[1]+50)
    arrow(g3[0], g3[1]+60, g4[0]+130, g4[1]+40)

    # Conciliação
    i = box(380, 310, 340, 80, 'Gerar/obter Ledger\n(mock ou on-chain)')
    j = box(380, 420, 260, 80, 'Para cada linha do extrato')
    k = box(380, 520, 340, 100, 'Filtrar candidatos\nmesma quantia e janela de data')
    l = box(380, 640, 340, 80, 'Similaridade por tokens\n(Jaccard)')
    m = box(380, 740, 360, 80, 'score = 0.5·valor + 0.3·data + 0.2·descrição')
    n = box(780, 740, 280, 100, 'score ≥ 0.85\ne desc ≥ 0.4?')
    o = box(1060, 760, 300, 100, 'status = matched\nvincular extrato ↔ tx_id_ledger')
    p = box(780, 880, 280, 80, 'score ≥ 0.60?')
    q = box(1060, 900, 300, 80, 'status = manual_review')
    r = box(1380, 900, 300, 80, 'status = unmatched')

    arrow(b[0], b[1]+100, i[0]+170, i[1])
    arrow(i[0]+170, i[1]+80, j[0]+130, j[1])
    arrow(j[0]+130, j[1]+80, k[0]+170, k[1])
    arrow(k[0]+170, k[1]+100, l[0]+170, l[1])
    arrow(l[0]+170, l[1]+80, m[0], m[1]+40)
    arrow(m[0]+360, m[1]+40, n[0], n[1]+50)
    arrow(n[0]+280, n[1]+30, o[0], o[1]+30)
    arrow(n[0]+140, n[1]+100, p[0]+140, p[1])
    arrow(p[0]+280, p[1]+40, q[0], q[1]+20)
    arrow(p[0]+280, p[1]+40, r[0], r[1]+20)

    # Pós-conciliação
    s = box(1380, 760, 300, 80, 'Revisão humana / confirmação')
    t = box(1380, 640, 300, 80, 'Ancorar evidência do lote')
    u = box(700, 420, 300, 80, 'Dashboards & Relatórios')
    v = box(700, 520, 300, 80, 'Taxa, tabelas e gráficos')
    w = box(700, 620, 300, 80, 'Exportar/Publish (CI opcional)')

    arrow(q[0]+300, q[1]+40, s[0], s[1]+20)
    arrow(o[0]+300, o[1]+30, t[0], t[1]+40)
    arrow(t[0], t[1]+40, f[0]+130, f[1]+40)
    arrow(o[0]-20, o[1]-20, u[0]+150, u[1]+80)
    arrow(q[0], q[1], u[0]+150, u[1]+80)
    arrow(r[0], r[1], u[0]+150, u[1]+80)
    arrow(u[0]+150, u[1]+80, v[0]+150, v[1])
    arrow(v[0]+150, v[1]+80, w[0]+150, w[1])

    # LGPD & Ética
    d.rounded_rectangle([20, 900, 360, 1060], radius=10, fill=card, outline=(80,80,90))
    d.text((32, 912), 'LGPD & Ética', fill=fg, font=font)
    d.text((32, 944), '• Minimizar dados on-chain: guardar apenas hashes/refs', fill=fg, font=small)
    d.text((32, 972), '• Somente dados sintéticos / sem segredos', fill=fg, font=small)

    img.save(IMG)
    print(IMG)

if __name__ == '__main__':
    draw_diagram()

