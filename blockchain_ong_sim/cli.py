from __future__ import annotations
import argparse
from collections import Counter
from contextlib import contextmanager
import csv
from html import escape
from io import StringIO
import json
import os
from pathlib import Path
from datetime import datetime, date, timedelta, timezone
import hashlib
from uuid import uuid4

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
CHAIN_FILE = CHAIN / 'chain.jsonl'
BLOCK_FIELDS = ('height', 'timestamp', 'prev_hash', 'merkle_root', 'tx_count')
EXTRACT_FIELDS = ('date', 'description', 'amount', 'balance', 'category', 'counterparty')
LEDGER_FIELDS = ('tx_id', 'date', 'amount', 'description', 'counterparty')
RECONCILIATION_FIELDS = ('tx_id_ledger', 'date', 'amount', 'counterparty', 'match_score', 'status')
DEMO_DESCRIPTIONS = (
    'Aquisição de alimentos', 'Doação para cestas', 'Material para oficinas',
    'Doação mensal', 'Transporte de insumos', 'Arrecadação da comunidade',
    'Pagamento de impressão', 'Doação para oficinas', 'Compra de material escolar',
    'Doação para transporte', 'Serviço de manutenção', 'Apoio a projeto social',
    'Pagamento de logística', 'Doação para evento',
)


def ensure_dirs():
    for p in [INBOX, PROCESSED, ANCHORS, LEDGER, CONCIL, CHAIN, OUT]:
        p.mkdir(parents=True, exist_ok=True)


def csv_bytes(fields: tuple[str, ...], rows: list[dict]) -> bytes:
    stream = StringIO(newline='')
    writer = csv.DictWriter(stream, fieldnames=fields, lineterminator='\n')
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode('utf-8')


def emit_extract(n: int = 14) -> Path:
    ts = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    path = INBOX / f'extrato_{ts}.csv'
    rows = []
    base = date(2026, 1, 1)
    balance = 10000.0
    for i in range(1, n+1):
        d = base + timedelta(days=i)
        amt = (-1)**i * (100 + i*7.25)
        balance = round(balance + amt, 2)
        rows.append({
            'date': d.isoformat(),
            'description': DEMO_DESCRIPTIONS[(i - 1) % len(DEMO_DESCRIPTIONS)],
            'amount': amt,
            'balance': balance,
            'category': 'Doação' if amt>0 else 'Pagamento',
            'counterparty': 'Parceiro X' if amt<0 else 'Doador Y',
        })
    atomic_write(path, csv_bytes(EXTRACT_FIELDS, rows))
    print(path)
    return path


def canonicalize(src: Path, *, stage_legacy=True) -> Path:
    df = pd.read_csv(src, usecols=list(EXTRACT_FIELDS), dtype=str, keep_default_na=False)
    df = df.loc[:, list(EXTRACT_FIELDS)]
    df['date'] = pd.to_datetime(df['date'], format='%Y-%m-%d').dt.strftime('%Y-%m-%d')
    for field in ('description', 'category', 'counterparty'):
        df[field] = df[field].str.strip()
    for field in ('amount', 'balance'):
        df[field] = pd.to_numeric(df[field]).round(2)
        if df[field].isin([float('inf'), float('-inf')]).any():
            raise ValueError(f'Valor inválido na coluna {field}.')
    if df[['date', 'amount', 'balance']].isna().any().any() or df['description'].eq('').any():
        raise ValueError('Informe data, valor, saldo e descrição em todos os lançamentos.')
    df = df.sort_values(list(EXTRACT_FIELDS)).reset_index(drop=True)
    out = PROCESSED / (src.stem + '.canonical.csv')
    contents = df.to_csv(index=False, lineterminator='\n', float_format='%.2f').encode('utf-8')
    save_evidence(out, contents)
    if stage_legacy:
        stage_anchor('bank_extract', src.name, out)
    print(out)
    return out


def json_bytes(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode('utf-8')


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def stage_anchor(kind: str, source_name: str, evidence: Path) -> None:
    anchor = {
        'kind': kind,
        'source_file': source_name,
        'canonical_file': evidence.name,
        'sha256': sha256_file(evidence),
        'timestamp': utc_timestamp(),
    }
    identifier = hashlib.sha256(json_bytes(anchor_key(anchor))).hexdigest()
    name = f'{identifier}.anchor.json'
    with chain_write_lock():
        atomic_write(ANCHORS / name, json_bytes(anchor))


def atomic_write(path: Path, contents: bytes) -> None:
    temporary = path.with_name(f'.{path.name}.{uuid4().hex}.tmp')
    try:
        temporary.write_bytes(contents)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def save_evidence(path: Path, contents: bytes) -> None:
    with chain_write_lock():
        if path.exists():
            if path.read_bytes() != contents:
                raise ValueError(f'Já existe uma evidência com o nome {path.name}. Use outro nome de lote.')
        else:
            atomic_write(path, contents)


def build_ledger_from_extract(canonical_csv: Path) -> Path:
    df = pd.read_csv(canonical_csv, keep_default_na=False)
    rows = []
    for i, r in enumerate(df.to_dict(orient='records'), start=1):
        if i % 7 == 0:
            continue
        desc = 'Registro interno' if i % 5 == 0 else r['description']
        ledger_date = date.fromisoformat(r['date']) + timedelta(days=int(i % 3 == 0))
        rows.append({
            'tx_id': f"0x{i:04X}{i:04X}",
            'date': ledger_date.isoformat(),
            'amount': r['amount'],
            'description': desc,
            'counterparty': r['counterparty']
        })
    out = LEDGER / (canonical_csv.stem + '.ledger.csv')
    atomic_write(out, csv_bytes(LEDGER_FIELDS, rows))
    print(out)
    return out


def token_set(s: str):
    return set(str(s).lower().replace('-', ' ').replace('/', ' ').split())


def jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 1.0
    inter = len(a & b)
    union = len(a | b) or 1
    return inter / union


def reconcile(canonical_csv: Path, ledger_csv: Path, date_window_days=1, desc_thresh=0.4, *, stage_legacy=True) -> Path:
    ext = pd.read_csv(canonical_csv, keep_default_na=False)
    led = pd.read_csv(ledger_csv, dtype={'tx_id': str}, keep_default_na=False)
    ledger_rows = list(led.itertuples(index=False))
    if led['tx_id'].str.strip().eq('').any() or led['tx_id'].duplicated().any():
        raise ValueError('O ledger precisa de identificadores únicos e preenchidos.')
    conc = []
    for er in ext.itertuples(index=False):
        e_date = date.fromisoformat(er.date)
        e_tokens = token_set(er.description)
        candidates = []
        for lr in ledger_rows:
            l_date = date.fromisoformat(lr.date)
            if abs((l_date - e_date).days) <= date_window_days and abs(lr.amount - er.amount) < 1e-6:
                candidates.append((jaccard(e_tokens, token_set(lr.description)), lr.tx_id))
        tx_id, score, status = '', 0.0, 'unmatched'
        if candidates:
            similarity = max(sim for sim, _ in candidates)
            best_ids = [candidate for sim, candidate in candidates if sim == similarity]
            score = 0.8 + 0.2 * similarity
            if len(best_ids) == 1:
                tx_id = best_ids[0]
            status = 'matched' if tx_id and score >= 0.85 and similarity >= desc_thresh else 'manual_review'
        conc.append({
            'tx_id_ledger': tx_id, 'date': er.date, 'amount': er.amount,
            'counterparty': er.counterparty, 'match_score': round(score, 2), 'status': status,
        })
    uses = Counter(row['tx_id_ledger'] for row in conc if row['tx_id_ledger'])
    for row in conc:
        if uses[row['tx_id_ledger']] > 1:
            row['tx_id_ledger'] = ''
            row['status'] = 'manual_review'
    out = CONCIL / (canonical_csv.stem + '.conciliation.csv')
    save_evidence(out, csv_bytes(RECONCILIATION_FIELDS, conc))
    if stage_legacy:
        stage_anchor('conciliation', canonical_csv.name, out)
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


def read_blocks(path: Path) -> list[dict]:
    with path.open(encoding='utf-8') as stream:
        return [json.loads(line) for line in stream]


def verify_blocks(blocks: list[dict]) -> None:
    previous = None
    for height, block in enumerate(blocks):
        if not isinstance(block, dict):
            raise ValueError(f'Bloco {height} inválido.')
        if block.get('height') != height or block.get('prev_hash') != previous:
            raise ValueError(f'Encadeamento inválido no bloco {height}.')
        txs = block.get('txs')
        if not isinstance(txs, list) or not txs or block.get('tx_count') != len(txs):
            raise ValueError(f'Transações inválidas no bloco {height}.')
        if block.get('merkle_root') != merkle_root([json_bytes(tx) for tx in txs]):
            raise ValueError(f'Raiz de Merkle inválida no bloco {height}.')
        header = {field: block.get(field) for field in BLOCK_FIELDS}
        previous = hashlib.sha256(json_bytes(header)).hexdigest()
        if block.get('block_hash') != previous:
            raise ValueError(f'Hash inválido no bloco {height}.')


def verify_chain(chain_file: Path = CHAIN_FILE, *, check_files: bool = True) -> tuple[int, int]:
    blocks = read_blocks(chain_file)
    if not blocks:
        raise ValueError('A cadeia está vazia.')
    verify_blocks(blocks)
    anchors = [anchor for block in blocks for anchor in block['txs']]
    if check_files:
        data_root = chain_file.resolve().parent.parent / 'data'
        for anchor in anchors:
            evidence = data_root / evidence_path(anchor)
            if not evidence.is_file() or sha256_file(evidence) != anchor['sha256']:
                raise ValueError(f'Evidência ausente ou alterada: {evidence.name}.')
    return len(blocks), len(anchors)


def evidence_path(anchor: dict) -> Path:
    folders = {'bank_extract': 'processed', 'conciliation': 'conciliation'}
    folder = folders.get(anchor['kind'])
    name = anchor['canonical_file']
    if folder is None or not isinstance(name, str) or not name or Path(name).name != name or name in ('.', '..'):
        raise ValueError('Referência de arquivo inválida em uma âncora.')
    return Path(folder) / name


@contextmanager
def chain_write_lock():
    with (CHAIN / '.writer.lock').open('a+b') as lock:
        lock.seek(0)
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        yield


def anchor_key(anchor: dict) -> tuple[str, str, str]:
    return anchor['kind'], anchor['canonical_file'], anchor['sha256']


def produce_block() -> Path | None:
    with chain_write_lock():
        pend = anchor_pending()
        blocks = read_blocks(CHAIN_FILE) if CHAIN_FILE.exists() else []
        verify_blocks(blocks)
        archived_dir = ANCHORS / 'archived'
        archived_dir.mkdir(exist_ok=True)
        known = {anchor_key(tx) for block in blocks for tx in block['txs']}
        txs = []
        for path in pend:
            tx = json.loads(path.read_text(encoding='utf-8'))
            key = anchor_key(tx)
            if key not in known:
                txs.append(tx)
                known.add(key)
        if txs:
            blocks.append(make_block(blocks, txs))
            atomic_write(CHAIN_FILE, b''.join(json_bytes(block) + b'\n' for block in blocks))
        for path in pend:
            path.replace(archived_dir / path.name)
    if blocks:
        print(CHAIN_FILE)
        return CHAIN_FILE
    print('NO_ANCHORS')
    return None


def make_block(blocks: list[dict], txs: list[dict]) -> dict:
    block_header = {
        'height': len(blocks),
        'timestamp': utc_timestamp(),
        'prev_hash': blocks[-1]['block_hash'] if blocks else None,
        'merkle_root': merkle_root([json_bytes(tx) for tx in txs]),
        'tx_count': len(txs),
    }
    return {
        **block_header,
        'block_hash': hashlib.sha256(json_bytes(block_header)).hexdigest(),
        'txs': txs,
    }


def draw_table_image(img, x, y, h, columns, rows, font):
    d = ImageDraw.Draw(img)
    w = sum(width for _, width in columns)
    d.rectangle([x, y, x+w, y+40], fill=(225,231,240), outline=(180,180,180))
    row_h = 34
    for index, _ in enumerate(rows):
        ry = y + 40 + index * row_h
        if index % 2 == 0:
            d.rectangle([x, ry, x+w, ry+row_h], fill=(248,250,252))
    left = x
    for index, (heading, width) in enumerate(columns):
        d.text((left + 10, y + 10), heading, fill=(20, 20, 20), font=font)
        for row_index, row in enumerate(rows):
            value = str(row[index])
            if d.textlength(value, font=font) > width - 20:
                while d.textlength(value + '…', font=font) > width - 20:
                    value = value[:-1]
                value += '…'
            d.text((left + 10, y + 48 + row_index * row_h), value, fill=(30, 30, 30), font=font)
        left += width
        d.line([left, y, left, y+h], fill=(200, 200, 200))
    d.rectangle([x, y, x+w, y+h], outline=(180,180,180))


def brl(value: float) -> str:
    return f'{value:.2f}'.replace('.', ',')


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
    d.text((20, 18), 'Extrato da ONG fictícia', fill=(255,255,255), font=title_font)
    df = pd.read_csv(canonical_csv, keep_default_na=False)
    columns = [('Data', 155), ('Descrição', 365), ('Valor (R$)', 175), ('Saldo (R$)', 175), ('Categoria', 190), ('Contraparte', 260)]
    displayed = df.assign(amount=df['amount'].map(brl), balance=df['balance'].map(brl))
    rows = displayed[list(EXTRACT_FIELDS)].head(14).values.tolist()
    draw_table_image(img, 40, 120, 520, columns, rows, font)
    d.text((40, 674), f'Exibição de {len(rows)} de {len(df)} lançamentos. Consulte o CSV para ver o lote completo.', fill=(30,30,30), font=font)
    img.save(OUT / 'extrato_dashboard.png')

    # Conciliação
    img2 = Image.new('RGB', (W, H), (247,248,250))
    d2 = ImageDraw.Draw(img2)
    d2.rectangle([0,0,W,70], fill=(16,130,90))
    d2.text((20, 18), 'Conciliação entre extrato e ledger simulado', fill=(255,255,255), font=title_font)
    cdf = pd.read_csv(conc_csv, keep_default_na=False)
    labels = {'matched': 'Conciliado', 'manual_review': 'Em revisão', 'unmatched': 'Sem correspondência'}
    columns = [('ID no ledger', 180), ('Data', 155), ('Valor (R$)', 170), ('Contraparte', 210), ('Pontuação', 155), ('Situação', 450)]
    displayed = cdf.assign(status=cdf['status'].map(labels), amount=cdf['amount'].map(brl))
    rows2 = displayed[list(RECONCILIATION_FIELDS)].head(14).values.tolist()
    draw_table_image(img2, 40, 120, 520, columns, rows2, font)
    matched = (cdf['status']=='matched').mean()*100 if len(cdf) else 0.0
    percentage = f'{matched:.1f}'.replace('.', ',')
    d2.text((40, 674), f'Taxa de conciliação: {percentage}%. Exibição de {len(rows2)} de {len(cdf)} lançamentos.', fill=(30,30,30), font=font)
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
            height=escape(str(b.get('height'))), ts=escape(str(b.get('timestamp'))), txs=escape(str(b.get('tx_count'))),
            mr=escape(str(b.get('merkle_root'))), bh=escape(str(b.get('block_hash')))
        ) for b in blocks[-10:]
    )
    chain_name = (chain_file.name if chain_file else 'N/A')
    last_hash = (last.get('block_hash','') if last else '')
    last_block_html = ('<p><b>Último bloco:</b> ' + escape(last_hash) + '</p>') if last_hash else '<p>Sem blocos.</p>'
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
 code{{background:#f0f0f0;padding:2px 4px;overflow-wrap:anywhere}}
 @media (max-width:760px){{.grid{{grid-template-columns:1fr}}}}
</style>
<h1>Relatório da Blockchain (Simulada)</h1>
<div class=card>
 <b>Visão geral</b><br>
 Lote: {batch}<br>
 Conciliação: {matched}/{total} conciliados ({pct:.1f}%), {manual} em revisão, {unmatched} sem correspondência.
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
""".format(matched=matched, total=total, pct=pct, manual=manual, unmatched=unmatched, chain_name=escape(chain_name),
           rows_html=rows_html, last_block_html=last_block_html, batch=escape(canonical_csv.name))
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
    story += [Paragraph(f'Lote: {escape(canonical_csv.name)}', ss['Body']),
              Paragraph(f'Conciliação: {matched}/{total} conciliados ({pct:.1f}%), {manual} em revisão, {unmatched} sem correspondência.', ss['Body']),
              Paragraph('Ambiente de demonstração com extrato e ledger simulados.', ss['Body']), Spacer(1, 6)]
    if (OUT/'extrato_dashboard.png').exists():
        story += [RLImage(str(OUT/'extrato_dashboard.png'), width=440, height=440 * 900 / 1400)]
    if (OUT/'conciliacao_dashboard.png').exists():
        story += [Spacer(1,6), RLImage(str(OUT/'conciliacao_dashboard.png'), width=440, height=440 * 900 / 1400)]
    blocks = []
    if chain_file and chain_file.exists():
        with chain_file.open('r', encoding='utf-8') as f:
            for line in f:
                blocks.append(json.loads(line))
    if blocks:
        data = [["Altura","Timestamp","Txs","Merkle root","Block hash"]]
        hash_style = ParagraphStyle(name='Hash', fontName='Courier', fontSize=7, leading=9)
        for b in blocks[-10:]:
            hashes = [str(b[key]) for key in ('merkle_root', 'block_hash')]
            cells = [Paragraph(f'{escape(value[:32])}<br/>{escape(value[32:])}', hash_style) for value in hashes]
            data.append([b['height'], str(b['timestamp'])[:19] + 'Z', b['tx_count'], *cells])
        t = Table(data, colWidths=[35, 106, 28, 164, 164], repeatRows=1)
        t.setStyle(TableStyle([
            ('GRID', (0,0), (-1,-1), 0.5, colors.grey),
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#E5E7F0')),
            ('FONTSIZE', (0,0), (-1,-1), 8.5),
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ]))
        story += [Spacer(1,6), t]
    doc = SimpleDocTemplate(str(pdf), pagesize=A4, rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36)
    doc.build(story)
    return pdf


def run_all() -> tuple[Path, Path | None]:
    canon, conc = prepare_demo(stage_legacy=True)
    chain_file = produce_block()
    render_dashboards(canon, conc)
    html = generate_report_html(canon, conc, chain_file)
    pdf = generate_report_pdf(canon, conc, chain_file)
    print(html)
    if pdf:
        print(pdf)
    return html, pdf


def prepare_demo(*, stage_legacy=False) -> tuple[Path, Path]:
    ensure_dirs()
    src = emit_extract()
    canon = canonicalize(src, stage_legacy=stage_legacy)
    ledger = build_ledger_from_extract(canon)
    conc = reconcile(canon, ledger, stage_legacy=stage_legacy)
    return canon, conc


def latest_reconciled_batch() -> tuple[Path, Path] | None:
    for conciliation in sorted(CONCIL.glob('*.conciliation.csv'), key=lambda p: (p.stat().st_mtime_ns, p.name), reverse=True):
        canonical = PROCESSED / (conciliation.name.removesuffix('.conciliation.csv') + '.csv')
        if canonical.is_file():
            return canonical, conciliation
    return None


def main():
    parser = argparse.ArgumentParser(description='Blockchain ONG Integration Simulator')
    sub = parser.add_subparsers(dest='cmd')
    sub.add_parser('emit-extract')
    ingest = sub.add_parser('ingest')
    ingest.add_argument('csv', nargs='?', type=Path, help='CSV no formato canônico do simulador')
    reconciliation = sub.add_parser('reconcile')
    reconciliation.add_argument('--ledger', type=Path, help='CSV de lançamentos fictícios independentes')
    sub.add_parser('anchor')
    sub.add_parser('render-dashboards')
    sub.add_parser('report')
    sub.add_parser('run-all')
    sub.add_parser('ethereum-demo', help='Concilia um lote fictício e ancora na EVM local')
    sub.add_parser('ethereum-verify', help='Confere o lote Ethereum mais recente pelo nó local')
    verify = sub.add_parser('verify')
    verify.add_argument('chain', nargs='?', type=Path, default=CHAIN_FILE)
    verify.add_argument('--chain-only', action='store_true', help='Verifica os blocos sem abrir os CSVs')
    args = parser.parse_args()
    ensure_dirs()
    if args.cmd == 'emit-extract':
        emit_extract()
    elif args.cmd == 'ingest':
        files = sorted(INBOX.glob('extrato_*.csv'))
        if args.csv is None and not files:
            print('NO_INBOX')
            return
        canonicalize(args.csv if args.csv else files[-1])
    elif args.cmd == 'reconcile':
        canons = sorted(PROCESSED.glob('*.canonical.csv'), key=lambda path: (path.stat().st_mtime_ns, path.name))
        if not canons:
            print('NO_CANON')
            return
        ledger = args.ledger if args.ledger else build_ledger_from_extract(canons[-1])
        reconcile(canons[-1], ledger)
    elif args.cmd == 'anchor':
        produce_block()
    elif args.cmd in ('render-dashboards', 'report'):
        batch = latest_reconciled_batch()
        if batch is None:
            print('NO_DATA')
            return
        render_dashboards(*batch)
        if args.cmd == 'report':
            print(generate_report_html(*batch, CHAIN_FILE))
            pdf = generate_report_pdf(*batch, CHAIN_FILE)
            if pdf:
                print(pdf)
    elif args.cmd == 'verify':
        try:
            blocks, anchors = verify_chain(args.chain, check_files=not args.chain_only)
        except (ValueError, OSError, KeyError, TypeError) as error:
            parser.exit(1, f'Falha de integridade: {error}\n')
        print(f'Integridade verificada: {blocks} bloco(s), {anchors} âncora(s).')
    elif args.cmd in ('ethereum-demo', 'ethereum-verify'):
        from . import ethereum

        try:
            if args.cmd == 'ethereum-demo':
                manifest = ethereum.anchor(*prepare_demo())
            else:
                batches = ethereum.manifests()
                if not batches:
                    raise ValueError('Execute ethereum-demo para gerar o primeiro lote.')
                manifest = batches[0]
            print(json.dumps(ethereum.verify(manifest), indent=2))
        except (ValueError, OSError, ethereum.EthereumError) as error:
            parser.exit(1, f'{error}\n')
    else:
        run_all()

if __name__ == '__main__':
    main()
