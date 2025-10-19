# Blockchain-ONGs-Integration-Sim

Pipeline de integração “quase real” para ONG: extrato (mock/CSV) → ingestão/canonicalização → conciliação → ancoragem on-chain simulada (Merkle + blocos) → dashboards.

Sem credenciais, sem dados sensíveis. Simula coleta automatizada (emissão para `data/inbox/`), processamento e publicação de âncoras.

## Executar

1) Ativar venv (se necessário):
   `..\.venv\Scripts\Activate.ps1`

2) Rodar pipeline completo:
   `python -m blockchain_ong_sim.cli run-all`

Artefatos:
- `data/inbox/` — extratos emitidos automaticamente
- `data/processed/` — CSV canônicos
- `data/anchors/` — âncoras (hashes e metadados)
- `data/ledger/` — ledger mock
- `data/conciliation/` — conciliações
- `chain/chain.jsonl` — blockchain simulada (blocos com Merkle)
- `out/` — imagens de dashboards (PNG)

## Comandos
- `emit-extract` — cria extrato CSV no inbox (mock/Nubank sandbox)
- `ingest` — canonicaliza CSV → `processed/` e gera âncora → `anchors/`
- `reconcile` — concilia extrato canônico com ledger mock → `conciliation/`
- `anchor` — cria bloco com Merkle root e inclui âncoras pendentes → `chain.jsonl`
- `render-dashboards` — gera prints (extrato + conciliação)
- `run-all` — executa tudo na ordem

## Observações
- Blockchain simulada: blocos com `prev_hash`, `merkle_root`, `block_hash`; sem rede P2P real.
- Sem LGPD: dados sintéticos; não publicar segredos.

## Interface gráfica (GUI)
- Executável Windows: `dist/ONGTransparency.exe` (login: `UserAdmin1` / `Admin1234`).
- Rodar da fonte: `python app_gui.py` (usa Tkinter). Após login, a UI abre maximizada, com abas para visualizar Extrato, Conciliação e Relatório, além de área Admin para gerenciar usuários.

## Dependências
Instale as dependências (modo desenvolvimento):

```
pip install -r requirements.txt
```

Para empacotar o executável (opcional):

```
pyinstaller --noconsole --onefile --name ONGTransparency app_gui.py
```

## Fluxo da Regra de Negócios (Mermaid)

```mermaid
%%{init: { "theme":"base", "securityLevel":"loose" }}%%
flowchart TD

  subgraph CONFIG[Configurações]
    CFG[Parâmetros: janela_data=1 dia; desc_thresh=0.4]
  end

  A[Extrato Nubank CSVOFX (sandbox)] --> B[Ingestão  Canonicalização<br>(normaliza datasvalorestexto)]
  B --> C[Hash SHA-256 do CSV canônico]
  C --> D{Âncora já existente
}  D -- "Não" --> E[Cria âncora {sha256, origem, timestamp}]
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
  J --> K[Filtrar candidatos: mesma quantia<br>e data dentro da janela]
  CONFIG -.-> K
  K --> L[Similaridade de descrição por tokens (Jaccard)]
  CONFIG -.-> L
  L --> M[score = 0.5valor + 0.3data + 0.2descrição]

  M --> N{score  0.85 e desc  0.4
}  N -- "Sim" --> O[status = matched<br>vincular extrato  tx_id_ledger]
  N -- "Não" --> P{score  0.60
}  P -- "Sim" --> Q[status = manual_review<br>enfileirar para revisão]
  P -- "Não" --> R[status = unmatched<br>abrir backlogissue]

  Q --> S[Revisão humana  confirmação]
  S --> O
  O --> T[Ancorar evidência do loterelatório (hash) no bloco]
  T --> F

  O --> U[Dashboards &amp; Relatórios]
  Q --> U
  R --> U
  U --> V[Taxa de conciliação, tabelas e gráficos]
```

Versão PNG estática: veja `docs/fluxo_regra_negocio.png`.
