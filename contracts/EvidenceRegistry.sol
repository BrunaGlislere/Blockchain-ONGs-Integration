// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

contract EvidenceRegistry {
    address public publisher;
    mapping(bytes32 => bool) public registered;

    error Unauthorized();
    error InvalidDigest();
    error AlreadyRegistered();

    event EvidenceAnchored(bytes32 indexed root, address indexed publisher);

    constructor() {
        publisher = msg.sender;
    }

    function anchor(bytes32 root) external {
        if (msg.sender != publisher) revert Unauthorized();
        if (root == bytes32(0)) revert InvalidDigest();
        if (registered[root]) revert AlreadyRegistered();
        registered[root] = true;
        emit EvidenceAnchored(root, msg.sender);
    }
}
