// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

import {Script, console2} from "forge-std/Script.sol";
import {FailureBounty} from "../src/FailureBounty.sol";

interface IERC20Approve {
    function approve(address spender, uint256 amount) external returns (bool);
}

/// @notice Deploys FailureBounty and funds one bounty from the company wallet. All values come from env vars.
/// The signer comes from the command line, as a keystore: docs/SWITCH-ON.md. This file holds no key.
contract Deploy is Script {
    uint256 internal constant ARC_TESTNET = 5042002;
    address internal constant ARC_USDC = 0x3600000000000000000000000000000000000000;

    error RolesNotFour();
    error NotArcUsdc(address usdc);
    error DefaultTestAccount(address who);

    /// @dev Arc seeds a Foundry default account as blocklisted, and all ten keys are public.
    function isFoundryDefault(address who) public pure returns (bool) {
        return who == 0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266 || who == 0x70997970C51812dc3A010C7d01b50e0d17dc79C8
            || who == 0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC || who == 0x90F79bf6EB2c4f870365E785982E1f101E93b906
            || who == 0x15d34AAf54267DB7D7c367839AAf71A00a2C6A65 || who == 0x9965507D1a55bcC2695C58ba16FB37d819B0A4dc
            || who == 0x976EA74026E726554dB657fA54763abd0C3a0aa9 || who == 0x14dC79964da2C08b23698B3D3cc7Ca32193d9955
            || who == 0x23618e81E3f5cdF7f54C3d65f7FBc0aBf5B21E8f || who == 0xa0Ee7A142d267C1f36714E4a8F75612F20a79720;
    }

    function checkRoles(uint256 chainId, address usdc, address company, address resolver, address arbiter, address tester)
        public
        pure
    {
        if (
            company == resolver || company == arbiter || company == tester || resolver == arbiter || resolver == tester
                || arbiter == tester
        ) revert RolesNotFour();
        if (chainId != ARC_TESTNET) return;
        if (usdc != ARC_USDC) revert NotArcUsdc(usdc);
        if (isFoundryDefault(company)) revert DefaultTestAccount(company);
        if (isFoundryDefault(resolver)) revert DefaultTestAccount(resolver);
        if (isFoundryDefault(arbiter)) revert DefaultTestAccount(arbiter);
        if (isFoundryDefault(tester)) revert DefaultTestAccount(tester);
    }

    function run() external returns (FailureBounty bounty, uint256 bountyId) {
        address usdc = vm.envAddress("ARC_USDC_ADDRESS");
        address company = vm.envAddress("ARC_COMPANY_ADDRESS");
        address resolver = vm.envAddress("ARC_RESOLVER_ADDRESS");
        address arbiter = vm.envAddress("ARC_ARBITER_ADDRESS");
        address tester = vm.envAddress("ARC_TESTER_ADDRESS");
        checkRoles(block.chainid, usdc, company, resolver, arbiter, tester);

        uint256 cap = vm.envUint("ARC_CAP_BASE_UNITS");
        uint64 deadline = uint64(block.timestamp + vm.envUint("ARC_DEADLINE_SECONDS"));

        vm.startBroadcast(company);
        bounty = new FailureBounty(usdc);
        IERC20Approve(usdc).approve(address(bounty), cap);
        bountyId = bounty.createBounty(
            resolver,
            arbiter,
            vm.envBytes32("ARC_SPEC_HASH"),
            cap,
            vm.envUint("ARC_PER_FAILURE_BASE_UNITS"),
            vm.envUint("ARC_TOP_PRIZE_BASE_UNITS"),
            deadline,
            uint64(vm.envUint("ARC_GRACE_SECONDS")),
            uint64(vm.envUint("ARC_DISPUTE_WINDOW_SECONDS"))
        );
        vm.stopBroadcast();

        console2.log("ARC_BOUNTY_ADDRESS", address(bounty));
        console2.log("ARC_BOUNTY_ID", bountyId);
    }
}
