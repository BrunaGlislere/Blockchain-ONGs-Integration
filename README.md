# Blockchain-ONGs-Integration-Sim

Pipeline de integraÃ§Ã£o â€œquase realâ€ para ONG: extrato (mock/CSV) â†’ ingestÃ£o/canonicalizaÃ§Ã£o â†’ conciliaÃ§Ã£o â†’ ancoragem on-chain simulada (Merkle + blocos) â†’ dashboards.

Sem credenciais, sem dados sensÃ­veis. Simula coleta automatizada (emissÃ£o para `data/inbox/`), processamento e publicaÃ§Ã£o de Ã¢ncoras.

## Executar

1) Ativar venv (se necessÃ¡rio):
   `..\.venv\Scripts\Activate.ps1`

2) Rodar pipeline completo:
   `python -m blockchain_ong_sim.cli run-all`

Artefatos:
- `data/inbox/` â€” extratos emitidos automaticamente
- `data/processed/` â€” CSV canÃ´nicos
- `data/anchors/` â€” Ã¢ncoras (hashes e metadados)
- `data/ledger/` â€” ledger mock
- `data/conciliation/` â€” conciliaÃ§Ãµes
- `chain/chain.jsonl` â€” blockchain simulada (blocos com Merkle)
- `out/` â€” imagens de dashboards (PNG)

## Comandos
- `emit-extract` â€” cria extrato CSV no inbox (mock/Nubank sandbox)
- `ingest` â€” canonicaliza CSV â†’ `processed/` e gera Ã¢ncora â†’ `anchors/`
- `reconcile` â€” concilia extrato canÃ´nico com ledger mock â†’ `conciliation/`
- `anchor` â€” cria bloco com Merkle root e inclui Ã¢ncoras pendentes â†’ `chain.jsonl`
- `render-dashboards` â€” gera prints (extrato + conciliaÃ§Ã£o)
- `run-all` â€” executa tudo na ordem

## ObservaÃ§Ãµes
- Blockchain simulada: blocos com `prev_hash`, `merkle_root`, `block_hash`; sem rede P2P real.
- Sem LGPD: dados sintÃ©ticos; nÃ£o publicar segredos.

## Interface grÃ¡fica (GUI)
- ExecutÃ¡vel Windows: `dist/ONGTransparency.exe` (login: `UserAdmin1` / `Admin1234`).
- Rodar da fonte: `python app_gui.py` (usa Tkinter). ApÃ³s login, a UI abre maximizada, com abas para visualizar Extrato, ConciliaÃ§Ã£o e RelatÃ³rio, alÃ©m de Ã¡rea Admin para gerenciar usuÃ¡rios.

## DependÃªncias
Instale as dependÃªncias (modo desenvolvimento):

```
pip install -r requirements.txt
```

Para empacotar o executÃ¡vel (opcional):

```
pyinstaller --noconsole --onefile --name ONGTransparency app_gui.py
```

## Fluxo da Regra de NegÃ³cios (Mermaid)

```mermaid
flowchart TD
 subgraph CONFIG["Configuracoes"]
        CFG["Parametros: janela_data=+- 1 dia; desc_thresh=0.4"]
  end
    A["Extrato Nubank CSVOFX (sandbox)"] --> B["Ingestao  Canonicalizacao (normaliza datasvalorestexto)"]
    B --> C["Hash SHA-256 do CSV canonico"] & I["Gerarobter Ledger (mock ou on-chain)"]
    C --> D{"Ancora ja existente"}
    D -- Nao --> E["Cria ancora {sha256, origem, timestamp}"]
    D -- Sim --> H["Reutiliza ancora anterior"]
    E --> F[("Fila de Ancoras pendentes")]
    H --> F
    F --> G["Mineracao de bloco"]
    G --> G1["Empacotar transacoes de ancora"]
    G1 --> G2["Calcular Merkle Root"]
    G2 --> G3["Bloco: {prev_hash, merkle_root, ts, txs}"]
    G3 --> G4[("chain.jsonl  Ledger de blocos")]
    I --> J{"Para cada linha do extrato"}
    J --> K["Filtrar candidatos: mesma quantia e data dentro da janela"]
    CONFIG -.-> K & L["Similaridade de descricao por tokens (Jaccard)"]
    K --> L
    L --> M["score = 0.5*valor + 0.3*data + 0.2*descricao"]
    M --> N{"score >= 0.85 e desc >= 0.4"}
    N -- Sim --> O["status = matched (vincular extrato &lt;-&gt; tx_id_ledger)"]
    N -- Nao --> P{"score >= 0.60"}
    P -- Sim --> Q["status = manual_review (enfileirar para revisao)"]
    P -- Nao --> R["status = unmatched (abrir backlogissue)"]
    Q --> S["Revisao humana  confirmacao"] & U["Dashboards & Relatorios"]
    S --> O
    O --> T["Ancorar evidencia do loterelatorio (hash) no bloco"] & U
    T --> F
    R --> U
    U --> V["Taxa de conciliacao, tabelas e graficos"]
```

VersÃ£o PNG estÃ¡tica: veja `docs/fluxo_regra_negocio.png`.



