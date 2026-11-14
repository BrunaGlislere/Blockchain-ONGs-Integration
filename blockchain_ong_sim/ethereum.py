from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import gzip
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import time
from urllib.error import URLError
from urllib.request import Request, urlopen

from . import cli

PROJECT = Path(__file__).resolve().parents[1]
STATE = cli.ROOT / 'ethereum-state'
BATCHES = STATE / 'batches'
CHAIN_ID = 31337
ARTIFACT = PROJECT / 'contracts' / 'EvidenceRegistry.json'


class EthereumError(RuntimeError):
    pass


class Rpc:
    def __init__(self, port: int):
        self.url = f'http://127.0.0.1:{port}'

    def __call__(self, method: str, *params):
        payload = json.dumps(dict(jsonrpc='2.0', id=1, method=method, params=params)).encode()
        request = Request(self.url, data=payload, headers={'Content-Type': 'application/json'})
        try:
            with urlopen(request, timeout=5) as response:
                reply = json.load(response)
        except (OSError, URLError, ValueError) as error:
            raise EthereumError(f'Falha de comunicação com o nó local ({method}).') from error
        if 'error' in reply:
            raise EthereumError(f'{method} — {reply["error"]["message"]}')
        return reply['result']

    def confirmed(self, tx: dict) -> dict:
        tx_hash = self('eth_sendTransaction', tx)
        for _ in range(40):
            receipt = self('eth_getTransactionReceipt', tx_hash)
            if receipt:
                if int(receipt['status'], 16) != 1:
                    raise EthereumError(f'Transação revertida: {tx_hash}')
                return receipt
            time.sleep(.15)
        raise EthereumError(f'Recibo indisponível: {tx_hash}')


@contextmanager
def local_node():
    local_binary = PROJECT / '.tools' / 'anvil.exe'
    binary = os.environ.get('ONG_ANVIL') or shutil.which('anvil')
    if not binary and local_binary.is_file():
        binary = str(local_binary)
    if not binary:
        raise EthereumError('Instale o Anvil e execute novamente. Consulte o README.')
    cli.ensure_dirs()
    STATE.mkdir(exist_ok=True)
    BATCHES.mkdir(exist_ok=True)
    # Only one operation may load and update the chain snapshot at a time.
    with cli.chain_write_lock():
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            port = listener.getsockname()[1]
        args = [binary, '--host', '127.0.0.1', '--port', str(port), '--chain-id', str(CHAIN_ID),
                '--hardfork', 'cancun', '--silent', '--accounts', '2']
        snapshot = STATE / 'anvil.json'
        if snapshot.is_file():
            args.extend(['--load-state', str(snapshot)])
        log = STATE / 'node.log'
        with log.open('wb') as stream:
            process = subprocess.Popen(args, stdout=stream, stderr=stream,
                                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        try:
            rpc = Rpc(port)
            for _ in range(40):
                if process.poll() is not None:
                    raise EthereumError(f'O nó local encerrou. Consulte {log.name}.')
                try:
                    if int(rpc('eth_chainId'), 16) == CHAIN_ID:
                        break
                except EthereumError:
                    time.sleep(.15)
            else:
                raise EthereumError('O nó Ethereum local não respondeu.')
            yield rpc
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def persist(rpc: Rpc) -> None:
    state = rpc('anvil_dumpState')
    contents = bytes.fromhex(state.removeprefix('0x'))
    if contents.startswith(b'\x1f\x8b'):
        contents = gzip.decompress(contents)
    cli.atomic_write(STATE / 'anvil.json', contents)


def contract(rpc: Rpc, *, deploy: bool) -> tuple[str, str, dict]:
    artifact = json.loads(ARTIFACT.read_text(encoding='utf-8'))
    accounts = rpc('eth_accounts')
    sender = accounts[0]
    deployment = STATE / 'contract.json'
    if deployment.exists():
        saved = json.loads(deployment.read_text(encoding='utf-8'))
        address = saved['address']
        if rpc('eth_getCode', address, 'latest').lower() != artifact['deployedBytecode'].lower():
            raise EthereumError('O contrato registrado não corresponde ao estado do nó.')
    else:
        if not deploy:
            raise EthereumError('Execute um lote para implantar o contrato local.')
        receipt = rpc.confirmed({'from': sender, 'data': artifact['bytecode'], 'gas': hex(800_000)})
        address = receipt['contractAddress']
        persist(rpc)
        cli.atomic_write(deployment, cli.json_bytes({'address': address, 'publisher': sender,
                                                    'deployment': receipt['transactionHash']}))
    return address, sender, artifact['methods']


def make_manifest(canonical: Path, reconciliation: Path) -> dict:
    files = [canonical, reconciliation]
    hashes = [cli.sha256_file(file) for file in files]
    root = cli.merkle_root([bytes.fromhex(digest) for digest in hashes])
    return {'batch': canonical.name.removesuffix('.canonical.csv'),
            'files': [{'name': file.relative_to(cli.ROOT).as_posix(), 'sha256': digest}
                      for file, digest in zip(files, hashes)],
            'root': '0x' + root}


def receipt_fields(rpc: Rpc, receipt: dict, address: str, publisher: str, root: str) -> dict:
    tx = rpc('eth_getTransactionByHash', receipt['transactionHash'])
    block = rpc('eth_getBlockByNumber', receipt['blockNumber'], False)
    if (not tx or not block or block['hash'].lower() != receipt['blockHash'].lower()
            or tx['from'].lower() != publisher.lower()
            or receipt['transactionHash'].lower() not in [h.lower() for h in block['transactions']]):
        raise EthereumError('A transação não foi localizada no bloco consultado.')
    return {
        'chain_id': CHAIN_ID, 'contract': address, 'publisher': publisher,
        'transaction': receipt['transactionHash'], 'block': int(receipt['blockNumber'], 16),
        'block_hash': receipt['blockHash'], 'gas_used': int(receipt['gasUsed'], 16),
        'status': int(receipt['status'], 16), 'nonce': int(tx['nonce'], 16),
        'timestamp': int(block['timestamp'], 16), 'root': root,
    }


def event_topic(rpc: Rpc) -> str:
    return rpc('web3_sha3', '0x' + b'EvidenceAnchored(bytes32,address)'.hex())


def event_receipt(rpc: Rpc, address: str, publisher: str, root: str, methods: dict) -> dict:
    query = {'to': address, 'data': '0x' + methods['registered(bytes32)'] + root[2:]}
    if int(rpc('eth_call', query, 'latest'), 16) != 1:
        raise EthereumError('Raiz não registrada no contrato.')
    topics = [event_topic(rpc), root, '0x' + publisher[2:].lower().rjust(64, '0')]
    logs = rpc('eth_getLogs', {'address': address, 'fromBlock': '0x0', 'toBlock': 'latest', 'topics': topics})
    if len(logs) != 1:
        raise EthereumError('Evento de ancoragem ausente ou duplicado.')
    receipt = rpc('eth_getTransactionReceipt', logs[0]['transactionHash'])
    if not receipt or int(receipt['status'], 16) != 1 or receipt['to'].lower() != address.lower():
        raise EthereumError('O recibo da ancoragem é inválido.')
    return receipt


def anchor(canonical: Path, reconciliation: Path) -> dict:
    manifest = make_manifest(canonical, reconciliation)
    root = manifest['root']
    with local_node() as rpc:
        address, publisher, methods = contract(rpc, deploy=True)
        query = {'to': address, 'data': '0x' + methods['registered(bytes32)'] + root[2:]}
        if int(rpc('eth_call', query, 'latest'), 16) == 0:
            rpc.confirmed({'from': publisher, 'to': address,
                           'data': '0x' + methods['anchor(bytes32)'] + root[2:], 'gas': hex(130_000)})
            persist(rpc)
        receipt = event_receipt(rpc, address, publisher, root, methods)
        manifest['receipt'] = receipt_fields(rpc, receipt, address, publisher, root)
        cli.atomic_write(BATCHES / (manifest['batch'] + '.json'), cli.json_bytes(manifest))
    return manifest


def verify(manifest: dict, *, evidence_root: Path = cli.ROOT) -> dict:
    paths = [evidence_root / row['name'] for row in manifest['files']]
    for path, row in zip(paths, manifest['files']):
        if not path.resolve().is_relative_to(evidence_root.resolve()):
            raise EthereumError('O caminho da evidência está fora da pasta base.')
        if not path.is_file() or cli.sha256_file(path) != row['sha256']:
            raise EthereumError(f'Evidência ausente ou alterada — {path.name}')
    computed = '0x' + cli.merkle_root(
        [bytes.fromhex(row['sha256']) for row in manifest['files']]
    )
    if computed != manifest['root']:
        raise EthereumError('Raiz do lote não corresponde aos arquivos.')
    with local_node() as rpc:
        address, publisher, methods = contract(rpc, deploy=False)
        receipt = event_receipt(rpc, address, publisher, computed, methods)
        current = receipt_fields(rpc, receipt, address, publisher, computed)
    if current != manifest['receipt']:
        raise EthereumError('Os dados locais divergem do recibo recuperado no nó.')
    return current


def manifests() -> list[dict]:
    return [json.loads(path.read_text(encoding='utf-8'))
            for path in sorted(BATCHES.glob('*.json'), reverse=True)]
