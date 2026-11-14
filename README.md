# Transparência de ONGs com Ethereum local

Aplicativo de prestação de contas desenvolvido para a Atividade Extensionista III de Engenharia de Software. O sistema concilia um extrato fictício com um ledger de demonstração, calcula o SHA-256 dos dois CSVs e publica a raiz de Merkle do lote no contrato EvidenceRegistry, executado no nó Ethereum Anvil.

## Executar no Windows

Abra o PowerShell na pasta do repositório. Use Python 3.12 com Tkinter e Node.js com npm para instalar o Anvil.

~~~powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\scripts\install-anvil.ps1
.\.venv\Scripts\python.exe app_gui.py
~~~

O instalador obtém o Anvil 1.7.1 para Windows x64. Também é possível apontar a variável ONG_ANVIL para um Anvil já instalado ou usar o binário no PATH.

Na interface, clique em **Executar demonstração** e examine as abas **Extrato**, **Conciliação** e **Registro Ethereum**. Use **Verificar arquivos e recibo** para recalcular a raiz e consultar a transação no nó. **Exportar evidências** salva os dois CSVs, o manifesto e uma cópia do recibo. A verificação pelo nó depende do estado que contém essa transação.

Para reproduzir pelo terminal:

~~~powershell
.\.venv\Scripts\python.exe -m blockchain_ong_sim.cli ethereum-demo
.\.venv\Scripts\python.exe -m blockchain_ong_sim.cli ethereum-verify
~~~

Cada lote contém 14 lançamentos fictícios. São esperados 10 conciliados (71,4%), dois em revisão e dois sem correspondência. A primeira execução implanta o contrato e publica uma transação de ancoragem. O recibo exibe o hash, o bloco, o nonce e o consumo de gás. A mesma raiz recupera o recibo anterior.

## Arquitetura

O programa inicia o Anvil sob demanda, restrito a 127.0.0.1, com Chain ID 31337 e contas de desenvolvimento. O acesso é feito por JSON-RPC. O contrato aceita somente o publicador que o implantou, recusa a raiz zero e impede raízes repetidas. Os CSVs ficam fora da cadeia. A leitura de confirmação verifica o estado do contrato, o evento, o recibo e a inclusão no bloco. O estado da rede fica em ethereum-state/. Para verificar os recibos no futuro, preserve essa pasta e os arquivos de evidência.

O código está em contracts/EvidenceRegistry.sol. O bytecode e a ABI são reproduzíveis com Solidity 0.8.30 e scripts/compile-contract.cjs, com o pacote solc disponível para o Node. O nó único e seu estado restaurável servem à validação técnica. Uma implantação real exigiria gestão de chaves e uma rede com governança definida.

## Conciliação e simulador anterior

| Situação | Regra |
| --- | --- |
| Conciliado | Mesmo valor, data dentro de um dia e candidato único com similaridade de descrição suficiente. |
| Em revisão | Similaridade insuficiente, empate ou mesmo ID candidato para vários lançamentos. |
| Sem correspondência | Ausência de candidato de mesmo valor dentro da janela. |

O extrato e o ledger do cenário padrão são gerados em conjunto para reproduzir o resultado. Os comandos abaixo aceitam uma amostra independente, no formato CSV UTF-8 com datas AAAA-MM-DD e ponto decimal. Campos do extrato: date, description, amount, balance, category e counterparty. Campos do ledger: tx_id, date, amount, description e counterparty. Use tx_id único.

~~~powershell
.\.venv\Scripts\python.exe -m blockchain_ong_sim.cli ingest .\meu_lote.csv
.\.venv\Scripts\python.exe -m blockchain_ong_sim.cli reconcile --ledger .\meu_ledger.csv
~~~

Os comandos run-all, anchor, verify e report pertencem à cadeia didática em JSONL, disponível também em app_gui.py --legacy. A versão atual aceita o formato CSV do simulador. A compatibilidade com OFX e com exportações do Nubank requer validação específica.

## Fluxo técnico

~~~mermaid
flowchart LR
    A["Extrato fictício"] --> B["Normalizar CSV"]
    B --> C["Conciliar com ledger"]
    B --> D["SHA-256 do extrato"]
    C --> E["SHA-256 da conciliação"]
    D --> F["Raiz de Merkle"]
    E --> F
    F --> G["Contrato EvidenceRegistry"]
    G --> H["Evento e recibo Ethereum"]
    H --> I["Verificar lote"]
~~~
