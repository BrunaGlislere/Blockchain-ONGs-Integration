from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from blockchain_ong_sim import cli, ethereum

BG = '#f3f5f7'
WHITE = '#ffffff'
INK = '#17242c'
MUTED = '#4b5c66'
LINE = '#d9e0e4'
GREEN = '#145d50'
TITLES = ('Visão geral', 'Extrato', 'Conciliação', 'Registro Ethereum')
STATUS = {'matched': 'Conciliado', 'manual_review': 'Em revisão', 'unmatched': 'Sem correspondência'}


def label(parent, text='', *, size=10, weight='normal', color=INK, background=WHITE):
    return tk.Label(parent, text=text, font=('Segoe UI', size, weight),
                    bg=background, fg=color, anchor='w', justify='left')


def read_table(path: Path) -> list[dict]:
    with path.open(encoding='utf-8', newline='') as stream:
        return list(csv.DictReader(stream))


class AuditDesk(tk.Tk):
    def __init__(self, *, fullscreen=False):
        super().__init__()
        self.title('Transparência ONG | Auditoria de lotes')
        self.geometry('1250x810')
        self.minsize(980, 740)
        self.configure(bg=BG)
        if fullscreen:
            self.state('zoomed')
        self.worker = ThreadPoolExecutor(max_workers=1)
        self.batch = None
        self.status = tk.StringVar(value='Ambiente de desenvolvimento • dados sintéticos')
        self.verified = tk.StringVar(value='')
        self._build()
        self.reload()
        self.protocol('WM_DELETE_WINDOW', self._close)

    def _style(self):
        style = ttk.Style(self)
        style.theme_use('clam')
        style.configure('Treeview', rowheight=34, font=('Segoe UI', 10),
                        background=WHITE, fieldbackground=WHITE, foreground=INK, borderwidth=0)
        style.configure('Treeview.Heading', background='#e8edf0', foreground=INK,
                        font=('Segoe UI', 10, 'bold'), padding=(9, 7), relief='flat')
        style.map('Treeview', background=[('selected', '#d3e9e2')], foreground=[('selected', INK)])
        style.configure('TButton', font=('Segoe UI', 10), padding=(12, 7))
        style.configure('Primary.TButton', background=GREEN, foreground=WHITE)
        style.map('Primary.TButton', background=[('active', '#0c493e'), ('disabled', '#6f817d')])
        style.configure('TNotebook', background=BG, borderwidth=0)
        style.configure('TNotebook.Tab', padding=(20, 10), background=BG,
                        font=('Segoe UI', 10), foreground=MUTED)
        style.map('TNotebook.Tab', background=[('selected', WHITE)], foreground=[('selected', GREEN)])

    def _build(self):
        self._style()
        header = tk.Frame(self, bg=WHITE, padx=26, pady=15)
        header.pack(fill='x')
        label(header, 'Transparência ONG', size=15, weight='bold').pack(side='left')
        label(header, '  /  Auditoria de lotes', color=MUTED, size=11).pack(side='left')
        self.run = ttk.Button(header, text='Executar demonstração', style='Primary.TButton', command=self.execute_demo)
        self.run.pack(side='right')
        self.export = ttk.Button(header, text='Exportar evidências', command=self.export_batch)
        self.export.pack(side='right', padx=(0, 10))
        tk.Frame(self, bg=LINE, height=1).pack(fill='x')

        intro = tk.Frame(self, bg=BG, padx=27, pady=14)
        intro.pack(fill='x')
        label(intro, 'Prestação de contas', size=24, weight='bold', background=BG).pack(anchor='w')
        self.batch_label = label(intro, background=BG, color=MUTED)
        self.batch_label.pack(anchor='w', pady=(4, 0))

        self.tabs = ttk.Notebook(self)
        self.tabs.pack(fill='both', expand=True, padx=26, pady=(0, 12))
        self.pages = {}
        for title in TITLES:
            page = tk.Frame(self.tabs, bg=WHITE, padx=18, pady=14, takefocus=False)
            self.tabs.add(page, text=title)
            self.pages[title] = page
        self.tabs.enable_traversal()

        summary = self.pages['Visão geral']
        self.metrics = tk.Frame(summary, bg=WHITE)
        self.metrics.pack(fill='x')
        self.metric_values = []
        for index, name in enumerate(('Lançamentos', 'Conciliados', 'Em revisão', 'Sem correspondência')):
            self.metrics.columnconfigure(index, weight=1, uniform='metrics')
            panel = tk.Frame(self.metrics, bg='#f1f6f4', padx=14, pady=9)
            panel.grid(row=0, column=index, sticky='ew', padx=(0, 8))
            label(panel, name, color=MUTED, background='#f1f6f4').pack(anchor='w')
            value = label(panel, '—', size=23, weight='bold', background='#f1f6f4')
            value.pack(anchor='w')
            self.metric_values.append(value)
        label(summary, 'Histórico de lotes', size=13, weight='bold').pack(anchor='w', pady=(18, 6))
        self.history = self._table(summary, [('Lote', 230), ('Registro', 110), ('Bloco', 70), ('Transação', 290)], visible_rows=3)
        self.history.bind('<<TreeviewSelect>>', self._pick_batch)

        self.extract = self._table(self.pages['Extrato'], [
            ('Data', 90), ('Descrição', 240), ('Valor (R$)', 115), ('Saldo (R$)', 115),
            ('Categoria', 105), ('Contraparte', 135)])

        conc = self.pages['Conciliação']
        filters = tk.Frame(conc, bg=WHITE)
        filters.pack(fill='x', pady=(0, 8))
        label(filters, 'Situação').pack(side='left', padx=(0, 8))
        self.status_filter = ttk.Combobox(filters, state='readonly', width=22,
                                          values=['Todos', *STATUS.values()])
        self.status_filter.set('Todos')
        self.status_filter.pack(side='left')
        self.status_filter.bind('<<ComboboxSelected>>', self._conciliation)
        self.conc = self._table(conc, [('Data', 95), ('Valor (R$)', 125), ('Contraparte', 125),
                                      ('ID no ledger', 145), ('Pontuação', 100), ('Situação', 170)])

        ledger = self.pages['Registro Ethereum']
        actions = tk.Frame(ledger, bg=WHITE)
        actions.pack(fill='x', pady=(0, 8))
        label(actions, 'Recibo da ancoragem', size=13, weight='bold').pack(side='left')
        self.verify = ttk.Button(actions, text='Verificar arquivos e recibo', command=self.verify_batch)
        self.verify.pack(side='right')
        label(ledger, 'Anvil · Ethereum local · Chain ID 31337', color=MUTED).pack(anchor='w')
        self.receipt_values = {}
        details = tk.Frame(ledger, bg=WHITE)
        details.pack(fill='x', pady=8)
        for index, (field, heading) in enumerate([
            ('status', 'Situação'), ('transaction', 'Hash da transação'), ('contract', 'Contrato'),
            ('publisher', 'Publicador'), ('block', 'Bloco'), ('block_hash', 'Hash do bloco'),
            ('gas_used', 'Gás usado'), ('nonce', 'Nonce'), ('root', 'Raiz de Merkle do lote'),
        ]):
            background = '#f5f7f9' if index % 2 == 0 else WHITE
            label(details, heading, size=9, weight='bold', background=background).grid(row=index, column=0, sticky='nsew', ipady=1, ipadx=8)
            value = tk.StringVar(value='—')
            entry = tk.Entry(details, textvariable=value, state='readonly', readonlybackground=background,
                             bd=0, fg=INK, font=('Consolas', 9), relief='flat')
            entry.grid(row=index, column=1, sticky='nsew', ipady=1, padx=(8, 0))
            self.receipt_values[field] = value
        details.columnconfigure(1, weight=1)
        outcome = label(ledger, color=GREEN, weight='bold')
        outcome.configure(textvariable=self.verified)
        outcome.pack(anchor='w', fill='x', pady=4)
        footer = label(self, color=MUTED, background=BG)
        footer.configure(textvariable=self.status, padx=27)
        footer.pack(fill='x', pady=(0, 9))

    def _table(self, parent, columns, *, visible_rows=11):
        wrapper = tk.Frame(parent, bg=WHITE)
        wrapper.pack(fill='both', expand=True)
        names = [heading for heading, _ in columns]
        table = ttk.Treeview(wrapper, columns=names, height=visible_rows, show='headings', selectmode='browse')
        scroller = ttk.Scrollbar(wrapper, orient='vertical', command=table.yview)
        table.configure(yscrollcommand=scroller.set)
        scroller.pack(side='right', fill='y')
        table.pack(fill='both', expand=True)
        for name, width in columns:
            table.heading(name, text=name, anchor='w')
            table.column(name, minwidth=64, width=width, anchor='w')
        table.tag_configure('stripe', background='#f6f8fa')
        return table

    def _fill(self, table, rows):
        table.delete(*table.get_children())
        for index, values in enumerate(rows):
            table.insert('', 'end', values=values, tags=('stripe',) if index % 2 else ())

    def reload(self, selected=None):
        self.batches = ethereum.manifests()
        self._fill(self.history, (
            (m['batch'], 'Confirmado', m['receipt']['block'],
             m['receipt']['transaction'][:22] + '…' + m['receipt']['transaction'][-8:])
            for m in self.batches
        ))
        if self.batches:
            batch = selected or self.batches[0]
            self.show_batch(batch)
        else:
            self.batch_label.configure(text='Execute a demonstração para gerar o primeiro lote.')
        self.export.configure(state='normal' if self.batch else 'disabled')
        self.verify.configure(state='normal' if self.batch else 'disabled')

    def _pick_batch(self, _event):
        item = self.history.selection()
        if item:
            self.show_batch(self.batches[self.history.index(item[0])])

    def show_batch(self, batch):
        extract, reconciliation = (cli.ROOT / row['name'] for row in batch['files'])
        try:
            entries = read_table(extract)
            self.conciliation = read_table(reconciliation)
        except (OSError, ValueError) as error:
            messagebox.showerror('Evidências', str(error), parent=self)
            return
        self.batch = batch
        dates = [datetime.fromisoformat(r['date']).strftime('%d/%m/%Y') for r in entries]
        self.batch_label.configure(text=f'Lote {batch["batch"]}   •   {dates[0]} a {dates[-1]}' if dates else batch['batch'])
        self._fill(self.extract, ((day, r['description'], cli.brl(float(r['amount'])),
                                  cli.brl(float(r['balance'])), r['category'], r['counterparty'])
                                 for day, r in zip(dates, entries)))
        for widget, count in zip(self.metric_values, (len(entries), *(sum(r['status'] == code for r in self.conciliation) for code in STATUS))):
            widget.configure(text=str(count))
        self._conciliation()
        for key, variable in self.receipt_values.items():
            value = batch['receipt'][key]
            variable.set('Confirmada no nó local' if key == 'status' and value == 1 else str(value))
        self.verified.set('')

    def _conciliation(self, _event=None):
        selected = self.status_filter.get()
        rows = ((datetime.fromisoformat(r['date']).strftime('%d/%m/%Y'), cli.brl(float(r['amount'])),
                 r['counterparty'], r['tx_id_ledger'] or '—', r['match_score'].replace('.', ','),
                 STATUS[r['status']]) for r in self.conciliation
                if selected == 'Todos' or STATUS[r['status']] == selected)
        self._fill(self.conc, rows)

    def _task(self, message, action, done):
        for button in (self.run, self.verify, self.export):
            button.configure(state='disabled')
        self.status.set(message)
        future = self.worker.submit(action)

        def poll():
            if not future.done():
                self.after(80, poll)
                return
            try:
                done(future.result())
            except Exception as error:
                self.status.set(str(error))
            finally:
                self.run.configure(state='normal')
                if self.batch:
                    self.verify.configure(state='normal')
                    self.export.configure(state='normal')

        self.after(80, poll)

    def execute_demo(self):
        def done(batch):
            self.reload(batch)
            self.tabs.select(self.pages['Visão geral'])
            self.status.set('Lote processado e transação confirmada no Ethereum local.')

        self._task('Processando extrato, conciliação e publicação no contrato…',
                   lambda: ethereum.anchor(*cli.prepare_demo()), done)

    def verify_batch(self):
        batch = self.batch
        self.verified.set('')

        def done(_receipt):
            if self.batch is batch:
                self.verified.set('Integridade confirmada • dois arquivos, raiz de Merkle e recibo Ethereum')
            self.status.set('Verificação concluída no nó local.')

        self._task('Recalculando hashes e consultando o recibo…', lambda: ethereum.verify(batch), done)

    def export_batch(self):
        batch = self.batch
        base = filedialog.askdirectory(title='Pasta de destino', parent=self)
        if not base:
            return

        def export():
            stamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')
            destination = Path(base) / f'evidencias_{stamp}'
            evidence = ethereum.verify(batch)
            for row in batch['files']:
                source = cli.ROOT / row['name']
                target = destination / row['name']
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
            (destination / 'manifesto.json').write_text(json.dumps(batch, indent=2), encoding='utf-8')
            (destination / 'recibo.json').write_text(json.dumps(evidence, indent=2), encoding='utf-8')
            return destination

        self._task('Validando e exportando os arquivos…', export,
                   lambda dest: self.status.set(f'Evidências exportadas em {dest}.'))

    def _close(self):
        self.worker.shutdown(wait=False, cancel_futures=True)
        self.destroy()


if __name__ == '__main__':
    AuditDesk().mainloop()
