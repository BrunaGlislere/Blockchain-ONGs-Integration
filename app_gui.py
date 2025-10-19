import tkinter as tk
from tkinter import messagebox
from tkinter import ttk, filedialog
import shutil
import json
import webbrowser
from pathlib import Path

from PIL import Image, ImageTk

from blockchain_ong_sim.cli import (
    ensure_dirs, emit_extract, canonicalize, build_ledger_from_extract,
    reconcile, produce_block, render_dashboards, generate_report_html,
    generate_report_pdf, INBOX, PROCESSED, CONCIL, CHAIN, OUT
)

APP_TITLE = "ONG Transparency – Local"
USERS_FILE = Path.cwd() / 'users.json'
DARK_BG = '#1f2127'
DARK_CARD = '#2a2d34'
DARK_FG = '#E6E6E6'
ACCENT = '#3B82F6'


def run_pipeline_once():
    ensure_dirs()
    src = emit_extract()
    canon = canonicalize(src)
    ledger = build_ledger_from_extract(canon)
    conc = reconcile(canon, ledger)
    chain_file = produce_block()
    render_dashboards(canon, conc)
    html = generate_report_html(canon, conc, chain_file)
    pdf = generate_report_pdf(canon, conc, chain_file)
    return html, pdf


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        # Start with small login window; main UI will maximize after login
        self.geometry("420x260")
        self.resizable(False, False)
        self.configure(bg=DARK_BG)
        self._in_main = False
        self._images_cache = {}

        # ttk dark theme
        style = ttk.Style(self)
        try:
            style.theme_use('clam')
        except Exception:
            pass
        style.configure('TFrame', background=DARK_BG)
        style.configure('Card.TFrame', background=DARK_CARD)
        style.configure('TLabel', background=DARK_BG, foreground=DARK_FG)
        style.configure('Card.TLabel', background=DARK_CARD, foreground=DARK_FG)
        style.configure('TButton', background=ACCENT, foreground='#ffffff')
        style.map('TButton', foreground=[('disabled', '#aaaaaa')])

        self.current_user = None
        self.current_role = None
        self._ensure_default_admin()
        self._build_login()

    def _clear(self):
        for w in list(self.winfo_children()):
            try:
                w.destroy()
            except Exception:
                pass

    def _build_login(self):
        self._clear()
        frm = tk.Frame(self, padx=18, pady=18, bg=DARK_BG)
        frm.pack(expand=True, fill="both")
        tk.Label(frm, text="Acesso", font=("Segoe UI", 14, "bold"), fg=DARK_FG, bg=DARK_BG).pack(pady=(0,8))
        tk.Label(frm, text="Usuário", fg=DARK_FG, bg=DARK_BG).pack(anchor="w")
        self.user_e = tk.Entry(frm, bg=DARK_CARD, fg=DARK_FG, insertbackground=DARK_FG, relief='flat')
        self.user_e.pack(fill="x", pady=(0,8))
        tk.Label(frm, text="Senha", fg=DARK_FG, bg=DARK_BG).pack(anchor="w")
        self.pass_e = tk.Entry(frm, show="*", bg=DARK_CARD, fg=DARK_FG, insertbackground=DARK_FG, relief='flat')
        self.pass_e.pack(fill="x")
        self.pass_e.bind("<Return>", lambda e: self._try_login())
        ttk.Button(frm, text="Entrar", command=self._try_login).pack(pady=12)
        tk.Label(frm, text="Dica: UserAdmin1 / Admin1234", fg="#999", bg=DARK_BG).pack()
        # Ensure small modal-like login size and center
        try:
            self.resizable(False, False)
            self._center_window(420, 260)
        except Exception:
            pass

    def _try_login(self):
        u = self.user_e.get().strip()
        p = self.pass_e.get().strip()
        users = self._load_users()
        if u in users and users[u]['password'] == p:
            self.current_user = u
            self.current_role = users[u].get('role', 'user')
            self._build_main()
        else:
            messagebox.showerror("Falha de login", "Usuário ou senha inválidos.")

    def _build_main(self):
        self._clear()
        self._in_main = True
        # Enable resizing for main UI
        self.resizable(True, True)
        top = tk.Frame(self, padx=12, pady=8, bg=DARK_CARD)
        top.pack(fill="x")
        tk.Label(top, text="Sistema Local de Transparência", font=("Segoe UI", 13, "bold"), fg=DARK_FG, bg=DARK_CARD).pack(side="left")
        ttk.Button(top, text="Logout", command=self._logout).pack(side="right", padx=(8,0))
        ttk.Button(top, text="Exportar arquivos", command=self._export_files).pack(side="right", padx=(8,0))
        ttk.Button(top, text="Executar pipeline", command=self._run_all).pack(side="right", padx=(8,0))
        ttk.Button(top, text="Atualizar visualização", command=self._refresh_views).pack(side="right")

        # Tabs
        nb = ttk.Notebook(self)
        nb.pack(expand=True, fill="both")
        self.tab_extrato = tk.Frame(nb, padx=10, pady=10, bg=DARK_BG)
        self.tab_conc = tk.Frame(nb, padx=10, pady=10, bg=DARK_BG)
        self.tab_rep = tk.Frame(nb, padx=10, pady=10, bg=DARK_BG)
        self.tab_admin = tk.Frame(nb, padx=10, pady=10, bg=DARK_BG)
        nb.add(self.tab_extrato, text="Extrato")
        nb.add(self.tab_conc, text="Conciliação")
        nb.add(self.tab_rep, text="Relatório Blockchain")
        if self.current_role == 'admin':
            nb.add(self.tab_admin, text="Admin")

        # Extrato image
        self._img_extrato_lbl = tk.Label(self.tab_extrato, bg=DARK_BG)
        self._img_extrato_lbl.pack(expand=True)

        # Conciliação image
        self._img_conc_lbl = tk.Label(self.tab_conc, bg=DARK_BG)
        self._img_conc_lbl.pack(expand=True)

        # Relatório: resumo + blocos
        rep_top = tk.Frame(self.tab_rep, bg=DARK_BG)
        rep_top.pack(fill="x")
        self._sum_lbl = tk.Label(rep_top, text="Resumo: —", fg=DARK_FG, bg=DARK_BG)
        self._sum_lbl.pack(anchor="w")
        cols = ("altura","timestamp","txs","merkle_root","block_hash")
        self._tree = ttk.Treeview(self.tab_rep, columns=cols, show="headings")
        for c in cols:
            self._tree.heading(c, text=c)
            self._tree.column(c, width=120 if c!="merkle_root" and c!="block_hash" else 220, stretch=True)
        self._tree.pack(expand=True, fill="both", pady=(6,0))

        # Admin tab (user management)
        if self.current_role == 'admin':
            self._build_admin_tab()

        # Footer
        bot = tk.Frame(self, padx=12, pady=8, bg=DARK_CARD)
        bot.pack(fill="x")
        ttk.Button(bot, text="Sair", command=self.destroy).pack(side="right")

        # Maximiza a janela para melhor visualização
        try:
            self.state('zoomed')
        except Exception:
            self.attributes('-zoomed', True)

        # Initial load
        self._refresh_views()
        # Reajusta imagens quando a janela muda de tamanho
        self.bind("<Configure>", self._on_configure)

    def _run_all(self):
        try:
            html, pdf = run_pipeline_once()
            messagebox.showinfo("Concluído", "Pipeline concluído e visualizações atualizadas dentro do sistema.")
            self._refresh_views()
        except Exception as e:
            messagebox.showerror("Erro", f"Falha ao executar pipeline: {e}")

    def _on_configure(self, event=None):
        # Avoid callbacks after logout
        if not self._in_main:
            return
        self._refresh_views()

    def _refresh_views(self):
        if not self._in_main:
            return
        # Load and show images if exist
        try:
            extrato_png = OUT / 'extrato_dashboard.png'
            if extrato_png.exists() and hasattr(self, '_img_extrato_lbl') and self._img_extrato_lbl.winfo_exists():
                img = Image.open(extrato_png)
                target_w = max(1200, min(1800, (self.winfo_width() or 1200) - 60))
                img = img.resize((int(target_w), int(img.height * target_w / img.width)), Image.LANCZOS)
                self._images_cache['extrato'] = ImageTk.PhotoImage(img)
                self._img_extrato_lbl.configure(image=self._images_cache['extrato'])
            conc_png = OUT / 'conciliacao_dashboard.png'
            if conc_png.exists() and hasattr(self, '_img_conc_lbl') and self._img_conc_lbl.winfo_exists():
                img2 = Image.open(conc_png)
                target_w = max(1200, min(1800, (self.winfo_width() or 1200) - 60))
                img2 = img2.resize((int(target_w), int(img2.height * target_w / img2.width)), Image.LANCZOS)
                self._images_cache['conc'] = ImageTk.PhotoImage(img2)
                self._img_conc_lbl.configure(image=self._images_cache['conc'])
        except Exception as e:
            messagebox.showwarning("Visualização", f"Falha ao carregar imagens: {e}")

        # Summary and blocks
        try:
            # Load latest conciliation
            concs = sorted(CONCIL.glob('*.conciliation.csv'))
            if concs:
                import pandas as pd
                dfc = pd.read_csv(concs[-1])
                matched = (dfc['status']=='matched').sum(); manual = (dfc['status']=='manual_review').sum(); unmatched = (dfc['status']=='unmatched').sum(); total = len(dfc)
                pct = (matched/total*100) if total else 0
                self._sum_lbl.config(text=f"Resumo: {matched}/{total} matched ({pct:.1f}%), {manual} revisão, {unmatched} sem correspondência.")
            # Blocks
            for i in self._tree.get_children():
                self._tree.delete(i)
            chain_file = CHAIN / 'chain.jsonl'
            if chain_file.exists():
                import json
                blocks=[]
                with chain_file.open('r', encoding='utf-8') as f:
                    for line in f:
                        blocks.append(json.loads(line))
                for b in blocks[-15:]:
                    self._tree.insert('', 'end', values=(b.get('height'), b.get('timestamp'), b.get('tx_count'), b.get('merkle_root'), b.get('block_hash')))
        except Exception as e:
            messagebox.showwarning("Relatório", f"Falha ao carregar relatório: {e}")

    def _export_files(self):
        # Seleciona pasta e copia artefatos principais
        dest_base = filedialog.askdirectory(title="Selecione a pasta de destino para exportação")
        if not dest_base:
            return
        try:
            ts = datetime.now().strftime('%Y%m%d_%H%M%S')
            dest = Path(dest_base) / f'export_{ts}'
            dest.mkdir(parents=True, exist_ok=True)
            # copia dashboards e relatórios
            for name in ['extrato_dashboard.png','conciliacao_dashboard.png','report_blockchain.html','report_blockchain.pdf']:
                src = OUT / name
                if src.exists():
                    shutil.copy2(src, dest / name)
            # copia dados mais recentes
            canons = sorted(PROCESSED.glob('*.canonical.csv'))
            concs = sorted(CONCIL.glob('*.conciliation.csv'))
            if canons:
                shutil.copy2(canons[-1], dest / canons[-1].name)
            if concs:
                shutil.copy2(concs[-1], dest / concs[-1].name)
            chain_file = CHAIN / 'chain.jsonl'
            if chain_file.exists():
                shutil.copy2(chain_file, dest / chain_file.name)
            messagebox.showinfo("Exportação", f"Arquivos exportados para: {dest}")
        except Exception as e:
            messagebox.showerror("Exportação", f"Falha ao exportar: {e}")

    # User management helpers
    def _ensure_default_admin(self):
        try:
            if not USERS_FILE.exists():
                USERS_FILE.write_text(json.dumps({
                    "UserAdmin1": {"password": "Admin1234", "role": "admin"}
                }, indent=2), encoding='utf-8')
        except Exception:
            pass

    def _load_users(self):
        try:
            return json.loads(USERS_FILE.read_text(encoding='utf-8'))
        except Exception:
            return {"UserAdmin1": {"password": "Admin1234", "role": "admin"}}

    def _save_users(self, users):
        USERS_FILE.write_text(json.dumps(users, indent=2, ensure_ascii=False), encoding='utf-8')

    def _logout(self):
        # Unbind configure to avoid callbacks on destroyed widgets
        try:
            self.unbind("<Configure>")
        except Exception:
            pass
        self._in_main = False
        self.current_user = None
        self.current_role = None
        # Clear cached images
        self._images_cache.clear()
        self._build_login()

    def _center_window(self, w: int, h: int):
        try:
            self.update_idletasks()
            sw = self.winfo_screenwidth()
            sh = self.winfo_screenheight()
            x = max(0, (sw - w) // 2)
            y = max(0, (sh - h) // 3)
            self.geometry(f"{w}x{h}+{x}+{y}")
        except Exception:
            pass

    def _build_admin_tab(self):
        frm = tk.Frame(self.tab_admin, bg=DARK_BG)
        frm.pack(fill='both', expand=True)

        # Users table
        cols = ("usuario", "role")
        self._users_tree = ttk.Treeview(frm, columns=cols, show='headings')
        for c in cols:
            self._users_tree.heading(c, text=c)
            self._users_tree.column(c, width=200, stretch=True)
        self._users_tree.pack(fill='both', expand=True, pady=(0,8))

        # Controls
        ctrl = tk.Frame(frm, bg=DARK_BG)
        ctrl.pack(fill='x')
        tk.Label(ctrl, text='Usuário', fg=DARK_FG, bg=DARK_BG).grid(row=0, column=0, sticky='w')
        self._new_user = tk.Entry(ctrl, bg=DARK_CARD, fg=DARK_FG, insertbackground=DARK_FG, relief='flat')
        self._new_user.grid(row=1, column=0, padx=(0,12), sticky='we')
        tk.Label(ctrl, text='Senha', fg=DARK_FG, bg=DARK_BG).grid(row=0, column=1, sticky='w')
        self._new_pass = tk.Entry(ctrl, show='*', bg=DARK_CARD, fg=DARK_FG, insertbackground=DARK_FG, relief='flat')
        self._new_pass.grid(row=1, column=1, padx=(0,12), sticky='we')
        tk.Label(ctrl, text='Role', fg=DARK_FG, bg=DARK_BG).grid(row=0, column=2, sticky='w')
        self._new_role = ttk.Combobox(ctrl, values=['user','admin'])
        self._new_role.set('user')
        self._new_role.grid(row=1, column=2, padx=(0,12), sticky='we')
        ttk.Button(ctrl, text='Adicionar', command=self._add_user).grid(row=1, column=3, padx=(0,12))
        ttk.Button(ctrl, text='Remover selecionado', command=self._del_user).grid(row=1, column=4)
        ctrl.grid_columnconfigure(0, weight=1)
        ctrl.grid_columnconfigure(1, weight=1)
        ctrl.grid_columnconfigure(2, weight=0)

        self._refresh_users_table()

    def _refresh_users_table(self):
        users = self._load_users()
        for i in self._users_tree.get_children():
            self._users_tree.delete(i)
        for u, meta in users.items():
            self._users_tree.insert('', 'end', values=(u, meta.get('role','user')))

    def _add_user(self):
        u = self._new_user.get().strip()
        p = self._new_pass.get().strip()
        r = self._new_role.get().strip() or 'user'
        if not u or not p:
            messagebox.showwarning('Admin', 'Informe usuário e senha.')
            return
        users = self._load_users()
        if u in users:
            messagebox.showwarning('Admin', 'Usuário já existe.')
            return
        users[u] = {"password": p, "role": r}
        self._save_users(users)
        self._new_user.delete(0, 'end'); self._new_pass.delete(0, 'end')
        self._refresh_users_table()

    def _del_user(self):
        sel = self._users_tree.selection()
        if not sel:
            return
        item = self._users_tree.item(sel[0])
        user = item['values'][0]
        if user == 'UserAdmin1':
            messagebox.showwarning('Admin', 'Não é permitido remover o administrador padrão.')
            return
        users = self._load_users()
        if user in users:
            del users[user]
            self._save_users(users)
            self._refresh_users_table()


if __name__ == "__main__":
    App().mainloop()
