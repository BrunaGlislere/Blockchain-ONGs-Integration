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

Versão PNG estática: veja `docs/fluxo_regra_negocio.png`.
