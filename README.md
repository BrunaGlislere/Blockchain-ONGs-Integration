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
%%{init: { "theme":"base", "securityLevel":"loose" }}%%
flowchart TD

  subgraph CONFIG[Configurações]
    CFG[Parâmetros: janela_data=1 dia; desc_thresh=0.4]
  end

  A[Extrato Nubank CSVOFX (sandbox)] --> B[Ingestão  Canonicalização<br/>(normaliza datasvalorestexto)]
  B --> C[Hash SHA-256 do CSV canônico]
  C --> D{Âncora já existente}
  D -- "Não" --> E[Cria âncora {sha256, origem, timestamp}]
  D -- "Sim" --> H[Reutiliza âncora anterior]
  E --> F[(Fila de Âncoras pendentes)]
  H --> F

  F --> G[Mineração de bloco]
  G --> G1[Empacotar transações de âncora]
  G1 --> G2[Calcular Merkle Root]
  G2 --> G3[Bloco: {prev_hash, merkle_root, ts, txs}]
  G3 --> G4[(chain.jsonl  Ledger de blocos)]

  B --> I[Gerarobter Ledger (mock ou on-chain)]
  I --> J{Para cada linha do extrato}
  J --> K[Filtrar candidatos: mesma quantia<br/>e data dentro da janela]
  CONFIG -.-> K
  K --> L[Similaridade de descrição por tokens (Jaccard)]
  CONFIG -.-> L
  L --> M[score = 0.5valor + 0.3data + 0.2descrição]

  M --> N{score >= 0.85 e desc >= 0.4}
  N -- "Sim" --> O[status = matched<br/>vincular extrato  tx_id_ledger]
  N -- "Não" --> P{score >= 0.60}
  P -- "Sim" --> Q[status = manual_review<br/>enfileirar para revisão]
  P -- "Não" --> R[status = unmatched<br/>abrir backlogissue]

  Q --> S[Revisão humana  confirmação]
  S --> O
  O --> T[Ancorar evidência do loterelatório (hash) no bloco]
  T --> F

  O --> U[Dashboards &amp; Relatórios]
  Q --> U
  R --> U
  U --> V[Taxa de conciliação, tabelas e gráficos]
```

VersÃ£o PNG estÃ¡tica: veja `docs/fluxo_regra_negocio.png`.

