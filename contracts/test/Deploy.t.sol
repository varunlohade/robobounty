// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

import {Test} from "forge-std/Test.sol";
import {Deploy} from "../script/Deploy.s.sol";

contract DeployRolesTest is Test {
    uint256 constant ARC_TESTNET = 5042002;
    address constant ARC_USDC = 0x3600000000000000000000000000000000000000;
    address constant FOUNDRY_ONE = 0x70997970C51812dc3A010C7d01b50e0d17dc79C8;
    address company = makeAddr("company");
    address resolver = makeAddr("resolver");
    address arbiter = makeAddr("arbiter");
    address tester = makeAddr("tester");
    Deploy script = new Deploy();

    function test_fourSeparateRolesPass() public view {
        script.checkRoles(ARC_TESTNET, ARC_USDC, company, resolver, arbiter, tester);
    }

    function test_sharedRoleFails() public {
        vm.expectRevert(Deploy.RolesNotFour.selector);
        script.checkRoles(31337, ARC_USDC, company, resolver, arbiter, resolver);
        vm.expectRevert(Deploy.RolesNotFour.selector);
        script.checkRoles(31337, ARC_USDC, company, company, arbiter, tester);
    }

    function test_arcNeedsTheDocsUsdcAddress() public {
        vm.expectRevert(abi.encodeWithSelector(Deploy.NotArcUsdc.selector, address(1)));
        script.checkRoles(ARC_TESTNET, address(1), company, resolver, arbiter, tester);
    }

    function test_arcRefusesFoundryDefaultAccounts() public {
        vm.expectRevert(abi.encodeWithSelector(Deploy.DefaultTestAccount.selector, FOUNDRY_ONE));
        script.checkRoles(ARC_TESTNET, ARC_USDC, company, resolver, arbiter, FOUNDRY_ONE);
    }

    function test_localChainAllowsDefaultAccounts() public view {
        script.checkRoles(31337, address(1), company, resolver, arbiter, FOUNDRY_ONE);
    }
}
