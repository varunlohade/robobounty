// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

import {Test} from "forge-std/Test.sol";
import {FailureBounty} from "../src/FailureBounty.sol";
import {MockUSDC} from "./Mocks.sol";

/// Random sequence of every action, across two bounties, with its own money ledger.
contract Handler is Test {
    uint256 constant CAP = 100e6;
    uint256 constant PER_FAILURE = 10e6;
    uint256 constant TOP = 40e6;
    uint64 constant WINDOW = 1 hours;
    uint64 constant GRACE = 2 days;

    FailureBounty public immutable fb;
    MockUSDC public immutable usdc;
    address public constant COMPANY = address(0xC0);
    address public constant RESOLVER = address(0xA1);
    address public constant ARBITER = address(0xA2);
    address public constant WINNER = address(0xA3);

    uint256 public totalFunded;
    uint256 public totalPaid;
    uint256 public totalRefunded;
    uint256[2] public ids;
    bytes32[] internal fingerprints;

    constructor(FailureBounty fb_, MockUSDC usdc_) {
        fb = fb_;
        usdc = usdc_;
        usdc.mint(COMPANY, 2 * CAP);
        vm.startPrank(COMPANY);
        usdc.approve(address(fb), 2 * CAP);
        uint64 deadline = uint64(block.timestamp + 7 days);
        ids[0] = fb.createBounty(RESOLVER, ARBITER, keccak256("a"), CAP, PER_FAILURE, TOP, deadline, GRACE, WINDOW);
        ids[1] = fb.createBounty(RESOLVER, ARBITER, keccak256("b"), CAP, PER_FAILURE, TOP, deadline, GRACE, WINDOW);
        vm.stopPrank();
        totalFunded = 2 * CAP;
        for (uint256 i; i < 16; i++) {
            fingerprints.push(keccak256(abi.encode("fp", i)));
        }
    }

    function _id(uint256 seed) internal view returns (uint256) {
        return ids[seed % 2];
    }

    function _fp(uint256 seed) internal view returns (bytes32) {
        return fingerprints[seed % fingerprints.length];
    }

    function warp(uint32 by) external {
        vm.warp(block.timestamp + bound(by, 1, 3 days));
    }

    function propose(uint256 a, uint256 b, bool top) external {
        vm.prank(RESOLVER);
        try fb.propose(_id(a), WINNER, _fp(b), keccak256("r"), top) {} catch {}
    }

    function reject(uint256 a, uint256 b) external {
        vm.prank(ARBITER);
        try fb.reject(_id(a), _fp(b), bytes32(0)) {} catch {}
    }

    function finalize(uint256 a, uint256 b) external {
        try fb.finalize(_id(a), _fp(b)) {} catch {}
    }

    function claim(uint256 a, uint256 b) external {
        uint256 before = usdc.balanceOf(WINNER);
        vm.prank(WINNER);
        try fb.claim(_id(a), _fp(b)) {
            totalPaid += usdc.balanceOf(WINNER) - before;
        } catch {}
    }

    function refund(uint256 a) external {
        uint256 before = usdc.balanceOf(COMPANY);
        vm.prank(COMPANY);
        try fb.refund(_id(a)) {
            totalRefunded += usdc.balanceOf(COMPANY) - before;
        } catch {}
    }

    /// Money the contract still owes: every open proposal plus every untouched balance.
    function owed() external view returns (uint256 sum) {
        for (uint256 i; i < 2; i++) {
            (,,,,,, uint256 available,,,,) = fb.bounties(ids[i]);
            sum += available;
            for (uint256 j; j < fingerprints.length; j++) {
                (, uint256 amount,,,, FailureBounty.Status status) = fb.failures(ids[i], fingerprints[j]);
                if (status == FailureBounty.Status.Pending || status == FailureBounty.Status.Finalized) sum += amount;
            }
        }
    }
}

contract FailureBountyInvariantTest is Test {
    FailureBounty fb;
    MockUSDC usdc;
    Handler handler;

    function setUp() public {
        usdc = new MockUSDC(6);
        fb = new FailureBounty(address(usdc));
        handler = new Handler(fb, usdc);
        targetContract(address(handler));
    }

    function invariant_contractHoldsExactlyWhatItOwes() public view {
        assertEq(usdc.balanceOf(address(fb)), handler.owed());
    }

    function invariant_moneyIsConserved() public view {
        assertEq(
            handler.totalFunded(),
            handler.totalPaid() + handler.totalRefunded() + usdc.balanceOf(address(fb))
        );
    }

    function invariant_noNativeBalance() public view {
        assertEq(address(fb).balance, 0);
    }
}
