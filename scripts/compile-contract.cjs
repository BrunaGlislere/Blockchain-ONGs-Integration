const fs = require("node:fs");
const path = require("node:path");
const solc = require("solc");

const root = path.resolve(__dirname, "..");
const sourceName = "EvidenceRegistry.sol";
const source = fs.readFileSync(path.join(root, "contracts", sourceName), "utf8");
const input = {
  language: "Solidity",
  sources: { [sourceName]: { content: source } },
  settings: {
    optimizer: { enabled: true, runs: 200 },
    evmVersion: "cancun",
    outputSelection: {
      "*": { "*": ["abi", "evm.bytecode.object", "evm.deployedBytecode.object", "evm.methodIdentifiers"] },
    },
  },
};
const output = JSON.parse(solc.compile(JSON.stringify(input)));
for (const issue of output.errors ?? []) {
  if (issue.severity === "error") throw Error(issue.formattedMessage);
}
const contract = output.contracts[sourceName].EvidenceRegistry;
const artifact = {
  compiler: solc.version(),
  abi: contract.abi,
  bytecode: "0x" + contract.evm.bytecode.object,
  deployedBytecode: "0x" + contract.evm.deployedBytecode.object,
  methods: contract.evm.methodIdentifiers,
};
fs.writeFileSync(path.join(root, "contracts", "EvidenceRegistry.json"), JSON.stringify(artifact, null, 2) + "\n");
