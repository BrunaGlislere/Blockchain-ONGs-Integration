from __future__ import annotations
import argparse
import csv
import json
from pathlib import Path
from datetime import datetime, date, timedelta
import hashlib
import random

import pandas as pd
from PIL import Image, ImageDraw, ImageFont

try:
    # Optional PDF report generation
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image as RLImage, Table, TableStyle
    from reportlab.lib import colors
    REPORTLAB_AVAILABLE = True
except Exception:
    REPORTLAB_AVAILABLE = False

# Use the current working directory as the root so packaged executables work as expected
ROOT = Path.cwd()
DATA = ROOT / 'data'
INBOX = DATA / 'inbox'
PROCESSED = DATA / 'processed'
ANCHORS = DATA / 'anchors'
LEDGER = DATA / 'ledger'
CONCIL = DATA / 'conciliation'
CHAIN = ROOT / 'chain'
OUT = ROOT / 'out'


def ensure_dirs():
    for p in [INBOX, PROCESSED, ANCHORS, LEDGER, CONCIL, CHAIN, OUT]:
        p.mkdir(parents=True, exist_ok=True)


def emit_extract(n: int = 14) -> Path:
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    path = INBOX / f'extrato_{ts}.csv'
    rows = []
    base = date.today() - timedelta(days=n)
    balance = 10000.0
    for i in range(1, n+1):
        d = base + timedelta(days=i)
        amt = (-1)**i * round(100 + i*7.25 + random.uniform(-5,5), 2)
        balance = round(balance + amt, 2)
        rows.append({
            'date': d.isoformat(),
            'description': f'Movimento {i}',
            'amount': amt,
            'balance': balance,
            'category': 'Doação' if amt>0 else 'Pagamento',
            'counterparty': 'Parceiro X' if amt<0 else 'Doador Y',
        })
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)
    print(path)
    return path


def canonicalize(src: Path) -> Path:
    df = pd.read_csv(src)
    # Ordenar por data, normalizar campos texto
    df['date'] = pd.to_datetime(df['date']).dt.date.astype(str)
    for c in ['description','category','counterparty']:
        df[c] = df[c].astype(str).str.strip()
    df['amount'] = df['amount'].astype(float).round(2)
    df['balance'] = df['balance'].astype(float).round(2)
    df = df.sort_values(['date','amount','description']).reset_index(drop=True)
    out = PROCESSED / (src.stem + '.canonical.csv')
    df.to_csv(out, index=False)
    # Hash canônico (sha256 do CSV canônico)
    h = hashlib.sha256(out.read_bytes()).hexdigest()
    anc = {
        'kind': 'bank_extract',
        'source_file': str(src.name),
        'canonical_file': str(out.name),
        'sha256': h,
        'timestamp': datetime.utcnow().isoformat()+'Z'
    }
    anc_path = ANCHORS / (src.stem + '.anchor.json')
    anc_path.write_text(json.dumps(anc, ensure_ascii=False, separators=(',',':')))
    print(out, anc_path)
    return out


def build_ledger_from_extract(canonical_csv: Path) -> Path:
    df = pd.read_csv(canonical_csv)
    rows = []
    for i, r in enumerate(df.to_dict(orient='records'), start=1):
        desc = r['description'] + (' - ref' if i % 3 == 0 else '')
        if i % 7 == 0:
            continue
        rows.append({
            'tx_id': f"0x{i:04X}{i:04X}",
            'date': r['date'],
            'amount': r['amount'],
            'description': desc,
            'counterparty': r['counterparty']
        })
    out = LEDGER / (canonical_csv.stem + '.ledger.csv')
    with open(out, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)
    print(out)
    return out


def token_set(s: str):
    return {t.lower() for t in str(s).replace('-', ' ').replace('/', ' ').split() if t}


def jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 1.0
    inter = len(a & b)
    union = len(a | b) or 1
    return inter / union


def reconcile(canonical_csv: Path, ledger_csv: Path, date_window_days=1, desc_thresh=0.4) -> Path:
    import datetime as dt
    ext = pd.read_csv(canonical_csv)
    led = pd.read_csv(ledger_csv)
    conc = []
    for _, er in ext.iterrows():
        e_date = dt.date.fromisoformat(str(er['date']))
        e_amt = float(er['amount'])
        e_desc = str(er['description'])
        e_cp = str(er['counterparty'])
        candidates = []
        for _, lr in led.iterrows():
            l_date = dt.date.fromisoformat(str(lr['date']))
            l_amt = float(lr['amount'])
            if abs((l_date - e_date).days) <= date_window_days and abs(l_amt - e_amt) < 1e-6:
                d_sim = jaccard(token_set(e_desc), token_set(lr['description']))
                candidates.append((d_sim, lr))
        if candidates:
            candidates.sort(key=lambda x: x[0], reverse=True)
            d_sim, lr = candidates[0]
            score = 0.5*1.0 + 0.3*1.0 + 0.2*float(d_sim)
            status = 'matched' if score >= 0.85 and d_sim >= desc_thresh else ('manual_review' if score >= 0.6 else 'unmatched')
            conc.append({
                'tx_id_ledger': lr['tx_id'], 'date': er['date'], 'amount': e_amt,
                'counterparty': e_cp, 'match_score': round(score, 2), 'status': status,
            })
        else:
            conc.append({
                'tx_id_ledger': '', 'date': er['date'], 'amount': e_amt,
                'counterparty': e_cp, 'match_score': 0.0, 'status': 'unmatched',
            })
    out = CONCIL / (canonical_csv.stem + '.conciliation.csv')
    with open(out, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=list(conc[0].keys()))
        w.writeheader(); w.writerows(conc)
    print(out)
    return out


def merkle_root(items: list[bytes]) -> str:
    if not items:
        return hashlib.sha256(b'').hexdigest()
    layer = [hashlib.sha256(x).digest() for x in items]
    while len(layer) > 1:
        if len(layer) % 2 == 1:
            layer.append(layer[-1])
        layer = [hashlib.sha256(layer[i] + layer[i+1]).digest() for i in range(0, len(layer), 2)]
    return layer[0].hex()


def anchor_pending() -> list[Path]:
    return sorted(ANCHORS.glob('*.anchor.json'))


def produce_block() -> Path | None:
    pend = anchor_pending()
    if not pend:
        print('NO_ANCHORS')
        return None
    txs = [json.loads(p.read_text()) for p in pend]
    tx_bytes = [json.dumps(tx, separators=(',',':'), ensure_ascii=False).encode('utf-8') for tx in txs]
    mroot = merkle_root(tx_bytes)
    prev = None
    chain_file = CHAIN / 'chain.jsonl'
    height = 0
    if chain_file.exists():
        last = None
        with chain_file.open('r', encoding='utf-8') as f:
            for line in f:
                last = json.loads(line)
        if last:
            prev = last['block_hash']
            height = last['height'] + 1
    block_header = {
        'height': height,
        'timestamp': datetime.utcnow().isoformat()+'Z',
        'prev_hash': prev,
        'merkle_root': mroot,
        'tx_count': len(txs),
    }
    block_hash = hashlib.sha256(json.dumps(block_header, separators=(',',':'), ensure_ascii=False).encode('utf-8')).hexdigest()
    block = {
        **block_header,
        'block_hash': block_hash,
        'txs': txs,
    }
    with chain_file.open('a', encoding='utf-8') as f:
        f.write(json.dumps(block, ensure_ascii=False) + '\n')
    archived_dir = ANCHORS / 'archived'
    archived_dir.mkdir(exist_ok=True)
    for p in pend:
        p.rename(archived_dir / p.name)
    print(chain_file)
    return chain_file


def draw_table_image(img, x, y, w, h, headers, rows, font):
    d = ImageDraw.Draw(img)
    d.rectangle([x, y, x+w, y+40], fill=(225,231,240), outline=(180,180,180))
    col_w = w // len(headers)
    for i, htxt in enumerate(headers):
        d.text((x + 10 + i*col_w, y + 10), str(htxt), fill=(20,20,20), font=font)
        d.line([x + (i+1)*col_w, y, x + (i+1)*col_w, y+h], fill=(200,200,200))
    d.rectangle([x, y, x+w, y+h], outline=(180,180,180))
    row_h = 34
    for r_i, row in enumerate(rows[: int((h-40)/row_h)]):
        ry = y + 40 + r_i*row_h
        if r_i % 2 == 0:
            d.rectangle([x, ry, x+w, ry+row_h], fill=(248,250,252))
        for c_i, val in enumerate(row[:len(headers)]):
            d.text((x + 10 + c_i*col_w, ry + 8), str(val), fill=(30,30,30), font=font)


def render_dashboards(canonical_csv: Path, conc_csv: Path):
    OUT.mkdir(exist_ok=True)
    # Extrato
    W, H = 1400, 900
    img = Image.new('RGB', (W, H), (247,248,250))
    d = ImageDraw.Draw(img)
    try:
        title_font = ImageFont.truetype('arial.ttf', 32)
        font = ImageFont.truetype('arial.ttf', 20)
    except Exception:
        title_font = ImageFont.load_default(); font = ImageFont.load_default()
    d.rectangle([0,0,W,70], fill=(34,102,242))
    d.text((20, 18), 'Extrato — Conta ONG (sandbox)', fill=(255,255,255), font=title_font)
    df = pd.read_csv(canonical_csv)
    headers = ['date','description','amount','balance','category','counterparty']
    rows = df[headers].values.tolist()
    draw_table_image(img, 40, 120, W-80, H-180, headers, rows, font)
    img.save(OUT / 'extrato_dashboard.png')

    # Conciliação
    img2 = Image.new('RGB', (W, H), (247,248,250))
    d2 = ImageDraw.Draw(img2)
    d2.rectangle([0,0,W,70], fill=(16,130,90))
    d2.text((20, 18), 'Conciliação — Ledger x Extrato', fill=(255,255,255), font=title_font)
    cdf = pd.read_csv(conc_csv)
    headers2 = ['tx_id_ledger','date','amount','counterparty','match_score','status']
    rows2 = cdf[headers2].values.tolist()
    draw_table_image(img2, 40, 120, W-80, 520, headers2, rows2, font)
    matched = (cdf['status']=='matched').mean()*100
    d2.rectangle([40, 670, 500, 830], fill=(255,255,255), outline=(200,200,200))
    d2.text((60, 690), 'Resumo', fill=(0,0,0), font=font)
    d2.text((60, 730), f'Taxa de conciliação: {matched:.1f}%', fill=(0,0,0), font=font)
    img2.save(OUT / 'conciliacao_dashboard.png')

    print(OUT / 'extrato_dashboard.png', OUT / 'conciliacao_dashboard.png')


def generate_report_html(canonical_csv: Path, conc_csv: Path, chain_file: Path | None) -> Path:
    OUT.mkdir(exist_ok=True)
    dfc = pd.read_csv(conc_csv)
    matched = (dfc['status'] == 'matched').sum()
    manual = (dfc['status'] == 'manual_review').sum()
    unmatched = (dfc['status'] == 'unmatched').sum()
    total = len(dfc)
    pct = (matched/total*100) if total else 0.0
    blocks = []
    if chain_file and chain_file.exists():
        with chain_file.open('r', encoding='utf-8') as f:
            for line in f:
                blocks.append(json.loads(line))
    last = blocks[-1] if blocks else None
    rows_html = ''.join(
        '<tr><td>{height}</td><td>{ts}</td><td>{txs}</td><td><code>{mr}</code></td><td><code>{bh}</code></td></tr>'.format(
            height=b.get('height'), ts=b.get('timestamp'), txs=b.get('tx_count'), mr=b.get('merkle_root'), bh=b.get('block_hash')
        ) for b in blocks[-10:]
    )
    chain_name = (chain_file.name if chain_file else 'N/A')
    last_hash = (last.get('block_hash','') if last else '')
    last_block_html = ('<p><b>Último bloco:</b> ' + last_hash + '</p>') if last_hash else '<p>Sem blocos.</p>'
    html = """
<!doctype html>
<html lang=pt-br>
<meta charset=utf-8>
<title>Relatório da Blockchain (Simulada)</title>
<style>
 body{{font-family:Segoe UI,Arial;margin:24px;max-width:1100px}}
 h1,h2{{margin:6px 0}}
 .card{{background:#f7f8fa;border:1px solid #e0e0e0;padding:12px;margin:10px 0}}
 .grid{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}
 table{{border-collapse:collapse;width:100%}}
 th,td{{border:1px solid #d0d0d0;padding:6px;font-size:13px}}
 th{{background:#e5e7f0}}
 .muted{{color:#666;font-size:12px}}
 img{{max-width:100%;height:auto;border:1px solid #ddd}}
 code{{background:#f0f0f0;padding:2px 4px}}
</style>
<h1>Relatório da Blockchain (Simulada)</h1>
<div class=card>
 <b>Visão geral</b><br>
 Conciliação: {matched}/{total} matched ({pct:.1f}%), {manual} em revisão, {unmatched} sem correspondência.
</div>
<div class=grid>
 <div class=card>
  <h2>Extrato</h2>
  <img src=\"extrato_dashboard.png\" alt=\"Extrato\">
 </div>
 <div class=card>
  <h2>Conciliação</h2>
  <img src=\"conciliacao_dashboard.png\" alt=\"Conciliação\">
 </div>
</div>
<div class=card>
 <h2>Blockchain</h2>
 <p class=muted>Arquivo de cadeia: <code>{chain_name}</code></p>
 <table>
  <tr><th>Altura</th><th>Timestamp</th><th>Txs</th><th>Merkle root</th><th>Block hash</th></tr>
  {rows_html}
 </table>
 {last_block_html}
</div>
<p class=muted>Dados sintéticos; âncoras: arquivos em data/anchors (archived após mineração). Este relatório referencia imagens em out/.</p>
""".format(matched=matched, total=total, pct=pct, manual=manual, unmatched=unmatched, chain_name=chain_name, rows_html=rows_html, last_block_html=last_block_html)
    out = OUT / 'report_blockchain.html'
    out.write_text(html, encoding='utf-8')
    return out


def generate_report_pdf(canonical_csv: Path, conc_csv: Path, chain_file: Path | None) -> Path | None:
    if not REPORTLAB_AVAILABLE:
        return None
    ss = getSampleStyleSheet()
    ss.add(ParagraphStyle(name='TitleBig', parent=ss['Title'], fontSize=16, leading=20, spaceAfter=6))
    ss.add(ParagraphStyle(name='Body', parent=ss['BodyText'], fontSize=10.5, leading=14))
    pdf = OUT / 'report_blockchain.pdf'
    story = []
    story += [Paragraph('Relatório da Blockchain (Simulada)', ss['TitleBig'])]
    dfc = pd.read_csv(conc_csv)
    matched = (dfc['status']=='matched').sum(); manual = (dfc['status']=='manual_review').sum(); unmatched = (dfc['status']=='unmatched').sum(); total = len(dfc)
    pct = (matched/total*100) if total else 0
    story += [Paragraph(f'Conciliação: {matched}/{total} matched ({pct:.1f}%), {manual} revisão, {unmatched} sem correspondência.', ss['Body']), Spacer(1,6)]
    if (OUT/'extrato_dashboard.png').exists():
        story += [RLImage(str(OUT/'extrato_dashboard.png'), width=480, height=280)]
    if (OUT/'conciliacao_dashboard.png').exists():
        story += [Spacer(1,6), RLImage(str(OUT/'conciliacao_dashboard.png'), width=480, height=280)]
    blocks = []
    if chain_file and chain_file.exists():
        with chain_file.open('r', encoding='utf-8') as f:
            for line in f:
                blocks.append(json.loads(line))
    if blocks:
        data = [["Altura","Timestamp","Txs","Merkle root","Block hash"]]
        for b in blocks[-10:]:
            data.append([b.get('height'), b.get('timestamp'), b.get('tx_count'), b.get('merkle_root'), b.get('block_hash')])
        t = Table(data, colWidths=[40, 120, 30, 180, 180])
        t.setStyle(TableStyle([
            ('GRID', (0,0), (-1,-1), 0.5, colors.grey),
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#E5E7F0')),
            ('FONTSIZE', (0,0), (-1,-1), 8.5),
        ]))
        story += [Spacer(1,6), t]
    doc = SimpleDocTemplate(str(pdf), pagesize=A4, rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36)
    doc.build(story)
    return pdf


def run_all():
    ensure_dirs()
    src = emit_extract()
    canon = canonicalize(src)
    ledger = build_ledger_from_extract(canon)
    conc = reconcile(canon, ledger)
    chain_file = produce_block()
    render_dashboards(canon, conc)
    html = generate_report_html(canon, conc, chain_file)
    pdf = generate_report_pdf(canon, conc, chain_file)
    print(html)
    if pdf:
        print(pdf)


def main():
    parser = argparse.ArgumentParser(description='Blockchain ONG Integration Simulator')
    sub = parser.add_subparsers(dest='cmd')
    sub.add_parser('emit-extract')
    sub.add_parser('ingest')
    sub.add_parser('reconcile')
    sub.add_parser('anchor')
    sub.add_parser('render-dashboards')
    sub.add_parser('report')
    sub.add_parser('run-all')
    args = parser.parse_args()
    ensure_dirs()
    if args.cmd == 'emit-extract':
        emit_extract()
    elif args.cmd == 'ingest':
        files = sorted(INBOX.glob('extrato_*.csv'))
        if not files:
            print('NO_INBOX')
            return
        canonicalize(files[-1])
    elif args.cmd == 'reconcile':
        canons = sorted(PROCESSED.glob('*.canonical.csv'))
        if not canons:
            print('NO_CANON')
            return
        ledger = build_ledger_from_extract(canons[-1])
        reconcile(canons[-1], ledger)
    elif args.cmd == 'anchor':
        produce_block()
    elif args.cmd == 'render-dashboards':
        canons = sorted(PROCESSED.glob('*.canonical.csv'))
        conz = sorted(CONCIL.glob('*.conciliation.csv'))
        if not (canons and conz):
            print('NO_DATA')
            return
        render_dashboards(canons[-1], conz[-1])
    elif args.cmd == 'report':
        canons = sorted(PROCESSED.glob('*.canonical.csv'))
        conz = sorted(CONCIL.glob('*.conciliation.csv'))
        chain_file = CHAIN / 'chain.jsonl'
        if not (canons and conz and chain_file.exists()):
            print('NO_DATA')
            return
        html = generate_report_html(canons[-1], conz[-1], chain_file)
        pdf = generate_report_pdf(canons[-1], conz[-1], chain_file)
        print(html)
        if pdf:
            print(pdf)
    else:
        run_all()

if __name__ == '__main__':
    main()
