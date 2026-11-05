// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

import {Test} from "forge-std/Test.sol";
import {FailureBounty} from "../src/FailureBounty.sol";
import {
    AttackWallet, FalseReturnToken, FeeToken, HookToken, MockUSDC, NoDecimalsToken, NoReturnToken
} from "./Mocks.sol";

contract FailureBountyTest is Test {
    uint256 constant USDC = 1e6;
    uint256 constant CAP = 100 * USDC;
    uint256 constant PER_FAILURE = 10 * USDC;
    uint256 constant TOP = 40 * USDC;
    uint64 constant WINDOW = 1 hours;
    uint64 constant GRACE = 2 days;
    bytes32 constant SPEC = keccak256("limits and world schema v3");
    bytes32 constant RESULT = keccak256("result");
    bytes32 constant FP1 = keccak256("policy-v1|bucket-a|seal-leak");
    bytes32 constant FP2 = keccak256("policy-v1|bucket-b|wind-slip");
    bytes32 constant FP3 = keccak256("policy-v1|bucket-c|battery");

    address company = makeAddr("company");
    address resolver = makeAddr("resolver");
    address arbiter = makeAddr("arbiter");
    address alice = makeAddr("alice");
    address bob = makeAddr("bob");
    address stranger = makeAddr("stranger");

    MockUSDC usdc;
    FailureBounty fb;
    uint64 deadline;

    function setUp() public {
        usdc = new MockUSDC(6);
        fb = new FailureBounty(address(usdc));
        deadline = uint64(block.timestamp + 7 days);
        usdc.mint(company, 1000 * USDC);
        vm.prank(company);
        usdc.approve(address(fb), type(uint256).max);
    }

    function _create() internal returns (uint256) {
        vm.prank(company);
        return fb.createBounty(resolver, arbiter, SPEC, CAP, PER_FAILURE, TOP, deadline, GRACE, WINDOW);
    }

    function _propose(uint256 id, address who, bytes32 fp) internal {
        vm.prank(resolver);
        fb.propose(id, who, fp, RESULT, false);
    }

    function _status(uint256 id, bytes32 fp) internal view returns (FailureBounty.Status status) {
        (,,,,, status) = fb.failures(id, fp);
    }

    function _available(uint256 id) internal view returns (uint256 available) {
        (,,,,,, available,,,,) = fb.bounties(id);
    }

    // Happy path

    function test_HappyPath_fundProposeFinalizeClaim() public {
        uint256 id = _create();
        assertEq(usdc.balanceOf(address(fb)), CAP);

        _propose(id, alice, FP1);
        assertEq(uint8(_status(id, FP1)), uint8(FailureBounty.Status.Pending));
        assertEq(_available(id), CAP - PER_FAILURE);

        vm.warp(block.timestamp + WINDOW);
        vm.prank(stranger);
        fb.finalize(id, FP1);

        vm.prank(alice);
        fb.claim(id, FP1);
        assertEq(usdc.balanceOf(alice), PER_FAILURE);
        assertEq(usdc.balanceOf(address(fb)), CAP - PER_FAILURE);
        assertEq(uint8(_status(id, FP1)), uint8(FailureBounty.Status.Claimed));
    }

    function test_SpecHashAndRolesAreStored() public {
        uint256 id = _create();
        (address c, address r, address a, bytes32 spec,,,,,,,) = fb.bounties(id);
        assertEq(c, company);
        assertEq(r, resolver);
        assertEq(a, arbiter);
        assertEq(spec, SPEC);
    }

    function test_TopPrize_paysTopAmountOnceAndFreesOnReject() public {
        uint256 id = _create();
        vm.prank(resolver);
        fb.propose(id, alice, FP1, RESULT, true);
        assertEq(_available(id), CAP - TOP);

        vm.prank(resolver);
        vm.expectRevert(FailureBounty.TopPrizeUnavailable.selector);
        fb.propose(id, bob, FP2, RESULT, true);

        vm.prank(arbiter);
        fb.reject(id, FP1, bytes32(0));
        assertEq(_available(id), CAP);

        vm.prank(resolver);
        fb.propose(id, bob, FP2, RESULT, true);
        vm.warp(block.timestamp + WINDOW);
        fb.finalize(id, FP2);
        vm.prank(bob);
        fb.claim(id, FP2);
        assertEq(usdc.balanceOf(bob), TOP);
    }

    function test_TopPrize_unavailableWhenBountyHasNone() public {
        vm.prank(company);
        uint256 id = fb.createBounty(resolver, arbiter, SPEC, CAP, PER_FAILURE, 0, deadline, GRACE, WINDOW);
        vm.prank(resolver);
        vm.expectRevert(FailureBounty.TopPrizeUnavailable.selector);
        fb.propose(id, alice, FP1, RESULT, true);
    }

    // Dispute

    function test_Dispute_arbiterRejectBlocksClaimAndFreesMoney() public {
        uint256 id = _create();
        _propose(id, alice, FP1);

        vm.prank(arbiter);
        fb.reject(id, FP1, keccak256("flaky"));
        assertEq(_available(id), CAP);

        vm.warp(block.timestamp + WINDOW);
        vm.expectRevert(FailureBounty.WrongStatus.selector);
        fb.finalize(id, FP1);
        vm.prank(alice);
        vm.expectRevert(FailureBounty.WrongStatus.selector);
        fb.claim(id, FP1);
        assertEq(usdc.balanceOf(alice), 0);
    }

    function test_Dispute_finalizeBlockedInWindow_rejectBlockedAfter() public {
        uint256 id = _create();
        _propose(id, alice, FP1);

        vm.warp(block.timestamp + WINDOW - 1);
        vm.expectRevert(FailureBounty.DisputeWindowOpen.selector);
        fb.finalize(id, FP1);

        vm.warp(block.timestamp + 1);
        vm.prank(arbiter);
        vm.expectRevert(FailureBounty.DisputeWindowClosed.selector);
        fb.reject(id, FP1, bytes32(0));
        fb.finalize(id, FP1);
    }

    function test_Dispute_cannotClaimBeforeFinalize() public {
        uint256 id = _create();
        _propose(id, alice, FP1);
        vm.warp(block.timestamp + WINDOW);
        vm.prank(alice);
        vm.expectRevert(FailureBounty.WrongStatus.selector);
        fb.claim(id, FP1);
    }

    // Duplicate fingerprint

    function test_Duplicate_blockedWhilePendingFinalizedAndClaimed() public {
        uint256 id = _create();
        _propose(id, alice, FP1);

        vm.prank(resolver);
        vm.expectRevert(FailureBounty.DuplicateFingerprint.selector);
        fb.propose(id, bob, FP1, RESULT, false);

        vm.warp(block.timestamp + WINDOW);
        fb.finalize(id, FP1);
        vm.prank(resolver);
        vm.expectRevert(FailureBounty.DuplicateFingerprint.selector);
        fb.propose(id, bob, FP1, RESULT, false);

        vm.prank(alice);
        fb.claim(id, FP1);
        vm.prank(resolver);
        vm.expectRevert(FailureBounty.DuplicateFingerprint.selector);
        fb.propose(id, bob, FP1, RESULT, false);
    }

    function test_Duplicate_doubleClaimBlocked() public {
        uint256 id = _create();
        _propose(id, alice, FP1);
        vm.warp(block.timestamp + WINDOW);
        fb.finalize(id, FP1);
        vm.startPrank(alice);
        fb.claim(id, FP1);
        vm.expectRevert(FailureBounty.WrongStatus.selector);
        fb.claim(id, FP1);
        vm.stopPrank();
        assertEq(usdc.balanceOf(alice), PER_FAILURE);
    }

    function test_Duplicate_sameFingerprintAllowedInOtherBounty() public {
        uint256 first = _create();
        uint256 second = _create();
        _propose(first, alice, FP1);
        _propose(second, bob, FP1);
        assertEq(_available(second), CAP - PER_FAILURE);
    }

    function test_Duplicate_rejectedFingerprintCanGoToTheRightSubmitter() public {
        uint256 id = _create();
        _propose(id, alice, FP1);
        vm.prank(arbiter);
        fb.reject(id, FP1, bytes32(0));

        _propose(id, bob, FP1);
        vm.warp(block.timestamp + WINDOW);
        fb.finalize(id, FP1);
        vm.prank(alice);
        vm.expectRevert(FailureBounty.NotSubmitter.selector);
        fb.claim(id, FP1);
        vm.prank(bob);
        fb.claim(id, FP1);
        assertEq(usdc.balanceOf(bob), PER_FAILURE);
    }

    // Cap

    function test_CapHit_blocksProposalAndHoldsAtCap() public {
        vm.prank(company);
        uint256 id = fb.createBounty(resolver, arbiter, SPEC, 25 * USDC, PER_FAILURE, 0, deadline, GRACE, WINDOW);
        _propose(id, alice, FP1);
        _propose(id, alice, FP2);

        vm.prank(resolver);
        vm.expectRevert(FailureBounty.CapExceeded.selector);
        fb.propose(id, alice, FP3, RESULT, false);
        assertEq(_available(id), 5 * USDC);
    }

    function test_CapHit_oneBountyCannotSpendAnother() public {
        vm.prank(company);
        uint256 small = fb.createBounty(resolver, arbiter, SPEC, PER_FAILURE, PER_FAILURE, 0, deadline, GRACE, WINDOW);
        _create();
        _propose(small, alice, FP1);
        vm.prank(resolver);
        vm.expectRevert(FailureBounty.CapExceeded.selector);
        fb.propose(small, alice, FP2, RESULT, false);
    }

    // Refund timing

    function test_EarlyRefund_blockedBeforeDeadlineAndDuringGrace() public {
        uint256 id = _create();
        vm.startPrank(company);
        vm.expectRevert(FailureBounty.RefundNotOpen.selector);
        fb.refund(id);

        vm.warp(deadline);
        vm.expectRevert(FailureBounty.RefundNotOpen.selector);
        fb.refund(id);

        vm.warp(uint256(deadline) + GRACE - 1);
        vm.expectRevert(FailureBounty.RefundNotOpen.selector);
        fb.refund(id);

        vm.warp(uint256(deadline) + GRACE);
        uint256 before = usdc.balanceOf(company);
        fb.refund(id);
        vm.stopPrank();
        assertEq(usdc.balanceOf(company), before + CAP);
    }

    function test_Refund_onlyCompany() public {
        uint256 id = _create();
        vm.warp(uint256(deadline) + GRACE);
        vm.prank(stranger);
        vm.expectRevert(FailureBounty.NotCompany.selector);
        fb.refund(id);
    }

    function test_Refund_secondCallHasNothing() public {
        uint256 id = _create();
        vm.warp(uint256(deadline) + GRACE);
        vm.startPrank(company);
        fb.refund(id);
        vm.expectRevert(FailureBounty.NothingToRefund.selector);
        fb.refund(id);
        vm.stopPrank();
    }

    // Refund race

    function test_RefundRace_lastSecondProposalKeepsItsMoney() public {
        uint256 id = _create();
        vm.warp(deadline);
        _propose(id, alice, FP1);

        vm.warp(uint256(deadline) + GRACE);
        uint256 before = usdc.balanceOf(company);
        vm.prank(company);
        fb.refund(id);
        assertEq(usdc.balanceOf(company), before + CAP - PER_FAILURE);
        assertEq(usdc.balanceOf(address(fb)), PER_FAILURE);

        fb.finalize(id, FP1);
        vm.prank(alice);
        fb.claim(id, FP1);
        assertEq(usdc.balanceOf(alice), PER_FAILURE);
        assertEq(usdc.balanceOf(address(fb)), 0);
    }

    function test_RefundRace_finalizedUnclaimedSurvivesRefund() public {
        uint256 id = _create();
        _propose(id, alice, FP1);
        vm.warp(block.timestamp + WINDOW);
        fb.finalize(id, FP1);

        vm.warp(uint256(deadline) + GRACE + 365 days);
        vm.prank(company);
        fb.refund(id);
        vm.prank(company);
        vm.expectRevert(FailureBounty.NothingToRefund.selector);
        fb.refund(id);

        vm.prank(alice);
        fb.claim(id, FP1);
        assertEq(usdc.balanceOf(alice), PER_FAILURE);
    }

    function test_RefundRace_noProposalAfterDeadline() public {
        uint256 id = _create();
        vm.warp(uint256(deadline) + 1);
        vm.prank(resolver);
        vm.expectRevert(FailureBounty.PastDeadline.selector);
        fb.propose(id, alice, FP1, RESULT, false);
    }

    function test_RefundRace_disputeWindowAlwaysEndsBeforeRefund() public {
        vm.prank(company);
        vm.expectRevert(FailureBounty.BadTimes.selector);
        fb.createBounty(resolver, arbiter, SPEC, CAP, PER_FAILURE, TOP, deadline, WINDOW - 1, WINDOW);
    }

    // Reentrancy

    function _hookBounty(HookToken token, FailureBounty hooked, address payer) internal returns (uint256 id) {
        token.mint(payer, CAP);
        vm.startPrank(payer);
        token.approve(address(hooked), CAP);
        id = hooked.createBounty(resolver, arbiter, SPEC, CAP, PER_FAILURE, 0, deadline, GRACE, WINDOW);
        vm.stopPrank();
    }

    function test_Reentrancy_maliciousTokenCannotDoubleClaim() public {
        HookToken token = new HookToken();
        FailureBounty hooked = new FailureBounty(address(token));
        AttackWallet wallet = new AttackWallet();
        uint256 id = _hookBounty(token, hooked, company);

        vm.startPrank(resolver);
        hooked.propose(id, address(wallet), FP1, RESULT, false);
        hooked.propose(id, address(wallet), FP2, RESULT, false);
        vm.stopPrank();
        vm.warp(block.timestamp + WINDOW);
        hooked.finalize(id, FP1);
        hooked.finalize(id, FP2);

        wallet.arm(
            address(hooked),
            abi.encodeCall(FailureBounty.claim, (id, FP1)),
            abi.encodeWithSignature("failures(uint256,bytes32)", id, FP1)
        );
        wallet.execute(address(hooked), abi.encodeCall(FailureBounty.claim, (id, FP1)));

        assertTrue(wallet.attackRan());
        assertFalse(wallet.attackSucceeded());
        assertEq(bytes4(wallet.attackResult()), FailureBounty.Reentrancy.selector);
        assertEq(token.balanceOf(address(wallet)), PER_FAILURE);

        (,,,,, FailureBounty.Status seen) = abi.decode(
            wallet.probeResult(), (address, uint256, bytes32, uint64, bool, FailureBounty.Status)
        );
        assertEq(uint8(seen), uint8(FailureBounty.Status.Claimed), "state must change before the transfer");
    }

    function test_Reentrancy_crossFunctionClaimOtherFingerprintBlocked() public {
        HookToken token = new HookToken();
        FailureBounty hooked = new FailureBounty(address(token));
        AttackWallet wallet = new AttackWallet();
        uint256 id = _hookBounty(token, hooked, company);

        vm.startPrank(resolver);
        hooked.propose(id, address(wallet), FP1, RESULT, false);
        hooked.propose(id, address(wallet), FP2, RESULT, false);
        vm.stopPrank();
        vm.warp(block.timestamp + WINDOW);
        hooked.finalize(id, FP1);
        hooked.finalize(id, FP2);

        wallet.arm(
            address(hooked),
            abi.encodeCall(FailureBounty.claim, (id, FP2)),
            abi.encodeWithSignature("bountyCount()")
        );
        wallet.execute(address(hooked), abi.encodeCall(FailureBounty.claim, (id, FP1)));
        assertEq(bytes4(wallet.attackResult()), FailureBounty.Reentrancy.selector);
        assertEq(token.balanceOf(address(wallet)), PER_FAILURE);

        wallet.execute(address(hooked), abi.encodeCall(FailureBounty.claim, (id, FP2)));
        assertEq(token.balanceOf(address(wallet)), 2 * PER_FAILURE);
    }

    function test_Reentrancy_maliciousTokenCannotDoubleRefund() public {
        HookToken token = new HookToken();
        FailureBounty hooked = new FailureBounty(address(token));
        AttackWallet wallet = new AttackWallet();
        uint256 id = _hookBounty(token, hooked, address(wallet));
        // Second bounty holds the money a double refund would try to steal.
        _hookBounty(token, hooked, company);

        vm.warp(uint256(deadline) + GRACE);
        wallet.arm(
            address(hooked),
            abi.encodeCall(FailureBounty.refund, (id)),
            abi.encodeWithSignature("bounties(uint256)", id)
        );
        wallet.execute(address(hooked), abi.encodeCall(FailureBounty.refund, (id)));

        assertEq(bytes4(wallet.attackResult()), FailureBounty.Reentrancy.selector);
        assertEq(token.balanceOf(address(wallet)), CAP);
        assertEq(token.balanceOf(address(hooked)), CAP);
    }

    // Blocklisted winner

    function test_Blocklist_winnerCannotBlockOthersOrRefund() public {
        uint256 id = _create();
        _propose(id, alice, FP1);
        _propose(id, bob, FP2);
        vm.warp(block.timestamp + WINDOW);
        fb.finalize(id, FP1);
        fb.finalize(id, FP2);

        usdc.setBlocked(alice, true);
        vm.prank(alice);
        vm.expectRevert(FailureBounty.TokenTransferFailed.selector);
        fb.claim(id, FP1);
        assertEq(uint8(_status(id, FP1)), uint8(FailureBounty.Status.Finalized), "failed claim keeps the payout");

        vm.prank(bob);
        fb.claim(id, FP2);
        assertEq(usdc.balanceOf(bob), PER_FAILURE);

        vm.warp(uint256(deadline) + GRACE);
        uint256 before = usdc.balanceOf(company);
        vm.prank(company);
        fb.refund(id);
        assertEq(usdc.balanceOf(company), before + CAP - 2 * PER_FAILURE);

        usdc.setBlocked(alice, false);
        vm.prank(alice);
        fb.claim(id, FP1);
        assertEq(usdc.balanceOf(alice), PER_FAILURE);
    }

    // Decimals guard

    function test_Decimals_18Rejected() public {
        MockUSDC wrong = new MockUSDC(18);
        vm.expectRevert(abi.encodeWithSelector(FailureBounty.BadDecimals.selector, uint256(18)));
        new FailureBounty(address(wrong));
    }

    function test_Decimals_6Accepted() public view {
        assertEq(fb.token(), address(usdc));
        assertEq(fb.TOKEN_DECIMALS(), 6);
    }

    function test_Decimals_missingFunctionRejected() public {
        NoDecimalsToken wrong = new NoDecimalsToken();
        vm.expectRevert(FailureBounty.BadToken.selector);
        new FailureBounty(address(wrong));
    }

    function test_Decimals_noCodeRejected() public {
        vm.expectRevert(FailureBounty.BadToken.selector);
        new FailureBounty(stranger);
    }

    // Access control

    function test_NonResolver_rejected() public {
        uint256 id = _create();
        address[3] memory callers = [company, arbiter, stranger];
        for (uint256 i; i < callers.length; i++) {
            vm.prank(callers[i]);
            vm.expectRevert(FailureBounty.NotResolver.selector);
            fb.propose(id, alice, FP1, RESULT, false);
        }
    }

    function test_NonArbiter_rejected() public {
        uint256 id = _create();
        _propose(id, alice, FP1);
        address[3] memory callers = [company, resolver, stranger];
        for (uint256 i; i < callers.length; i++) {
            vm.prank(callers[i]);
            vm.expectRevert(FailureBounty.NotArbiter.selector);
            fb.reject(id, FP1, bytes32(0));
        }
    }

    function test_NonSubmitter_cannotClaim() public {
        uint256 id = _create();
        _propose(id, alice, FP1);
        vm.warp(block.timestamp + WINDOW);
        fb.finalize(id, FP1);
        vm.prank(stranger);
        vm.expectRevert(FailureBounty.NotSubmitter.selector);
        fb.claim(id, FP1);
    }

    function test_Roles_mustBeSeparate() public {
        vm.startPrank(company);
        vm.expectRevert(FailureBounty.RolesNotSeparate.selector);
        fb.createBounty(resolver, resolver, SPEC, CAP, PER_FAILURE, TOP, deadline, GRACE, WINDOW);
        vm.expectRevert(FailureBounty.RolesNotSeparate.selector);
        fb.createBounty(company, arbiter, SPEC, CAP, PER_FAILURE, TOP, deadline, GRACE, WINDOW);
        vm.expectRevert(FailureBounty.RolesNotSeparate.selector);
        fb.createBounty(resolver, company, SPEC, CAP, PER_FAILURE, TOP, deadline, GRACE, WINDOW);
        vm.stopPrank();
    }

    function test_UnknownBounty_rejected() public {
        vm.prank(resolver);
        vm.expectRevert(FailureBounty.UnknownBounty.selector);
        fb.propose(99, alice, FP1, RESULT, false);
    }

    // Create input checks

    function test_Create_rejectsBadInputs() public {
        vm.startPrank(company);
        vm.expectRevert(FailureBounty.BadHash.selector);
        fb.createBounty(resolver, arbiter, bytes32(0), CAP, PER_FAILURE, TOP, deadline, GRACE, WINDOW);
        vm.expectRevert(FailureBounty.BadAmounts.selector);
        fb.createBounty(resolver, arbiter, SPEC, CAP, 0, TOP, deadline, GRACE, WINDOW);
        vm.expectRevert(FailureBounty.BadAmounts.selector);
        fb.createBounty(resolver, arbiter, SPEC, CAP, CAP + 1, 0, deadline, GRACE, WINDOW);
        vm.expectRevert(FailureBounty.BadAmounts.selector);
        fb.createBounty(resolver, arbiter, SPEC, CAP, PER_FAILURE, PER_FAILURE - 1, deadline, GRACE, WINDOW);
        vm.expectRevert(FailureBounty.BadAmounts.selector);
        fb.createBounty(resolver, arbiter, SPEC, CAP, PER_FAILURE, CAP + 1, deadline, GRACE, WINDOW);
        vm.expectRevert(FailureBounty.BadTimes.selector);
        fb.createBounty(resolver, arbiter, SPEC, CAP, PER_FAILURE, TOP, uint64(block.timestamp), GRACE, WINDOW);
        vm.expectRevert(FailureBounty.BadTimes.selector);
        fb.createBounty(resolver, arbiter, SPEC, CAP, PER_FAILURE, TOP, deadline, GRACE, 59);
        vm.stopPrank();
    }

    function test_Propose_rejectsBadInputs() public {
        uint256 id = _create();
        vm.startPrank(resolver);
        vm.expectRevert(FailureBounty.BadAddress.selector);
        fb.propose(id, address(0), FP1, RESULT, false);
        vm.expectRevert(FailureBounty.BadAddress.selector);
        fb.propose(id, address(fb), FP1, RESULT, false);
        vm.expectRevert(FailureBounty.BadHash.selector);
        fb.propose(id, alice, bytes32(0), RESULT, false);
        vm.expectRevert(FailureBounty.BadHash.selector);
        fb.propose(id, alice, FP1, bytes32(0), false);
        vm.stopPrank();
    }

    // Safe ERC-20 handling

    function test_Token_noReturnValueWorks() public {
        NoReturnToken token = new NoReturnToken();
        FailureBounty other = new FailureBounty(address(token));
        token.mint(company, CAP);
        vm.startPrank(company);
        token.approve(address(other), CAP);
        uint256 id = other.createBounty(resolver, arbiter, SPEC, CAP, PER_FAILURE, 0, deadline, GRACE, WINDOW);
        vm.stopPrank();
        vm.prank(resolver);
        other.propose(id, alice, FP1, RESULT, false);
        vm.warp(block.timestamp + WINDOW);
        other.finalize(id, FP1);
        vm.prank(alice);
        other.claim(id, FP1);
        assertEq(token.balanceOf(alice), PER_FAILURE);
    }

    function test_Token_falseReturnRevertsAndKeepsPayout() public {
        FalseReturnToken token = new FalseReturnToken();
        FailureBounty other = new FailureBounty(address(token));
        token.mint(company, CAP);
        vm.startPrank(company);
        token.approve(address(other), CAP);
        uint256 id = other.createBounty(resolver, arbiter, SPEC, CAP, PER_FAILURE, 0, deadline, GRACE, WINDOW);
        vm.stopPrank();
        vm.prank(resolver);
        other.propose(id, alice, FP1, RESULT, false);
        vm.warp(block.timestamp + WINDOW);
        other.finalize(id, FP1);

        token.setFailing(true);
        vm.prank(alice);
        vm.expectRevert(FailureBounty.TokenTransferFailed.selector);
        other.claim(id, FP1);

        token.setFailing(false);
        vm.prank(alice);
        other.claim(id, FP1);
        assertEq(token.balanceOf(alice), PER_FAILURE);
    }

    function test_Token_feeOnTransferFundingRejected() public {
        FeeToken token = new FeeToken();
        FailureBounty other = new FailureBounty(address(token));
        token.mint(company, CAP);
        vm.startPrank(company);
        token.approve(address(other), CAP);
        vm.expectRevert(FailureBounty.WrongAmountReceived.selector);
        other.createBounty(resolver, arbiter, SPEC, CAP, PER_FAILURE, 0, deadline, GRACE, WINDOW);
        vm.stopPrank();
    }

    // No native value

    function test_NativeValue_rejectedEverywhere() public {
        uint256 id = _create();
        vm.deal(address(this), 1 ether);

        (bool plain,) = address(fb).call{value: 1}("");
        assertFalse(plain);

        bytes[6] memory calls = [
            abi.encodeCall(
                FailureBounty.createBounty, (resolver, arbiter, SPEC, CAP, PER_FAILURE, TOP, deadline, GRACE, WINDOW)
            ),
            abi.encodeCall(FailureBounty.propose, (id, alice, FP1, RESULT, false)),
            abi.encodeCall(FailureBounty.reject, (id, FP1, bytes32(0))),
            abi.encodeCall(FailureBounty.finalize, (id, FP1)),
            abi.encodeCall(FailureBounty.claim, (id, FP1)),
            abi.encodeCall(FailureBounty.refund, (id))
        ];
        for (uint256 i; i < calls.length; i++) {
            (bool ok,) = address(fb).call{value: 1}(calls[i]);
            assertFalse(ok);
        }
        assertEq(address(fb).balance, 0);
    }

    // Fuzz

    function testFuzz_CapNeverExceeded(uint96 cap, uint96 perFailure, uint8 attempts) public {
        cap = uint96(bound(cap, 1, 1_000_000 * USDC));
        perFailure = uint96(bound(perFailure, 1, cap));
        usdc.mint(company, cap);
        vm.prank(company);
        uint256 id = fb.createBounty(resolver, arbiter, SPEC, cap, perFailure, 0, deadline, GRACE, WINDOW);

        uint256 accepted;
        for (uint256 i; i < attempts; i++) {
            vm.prank(resolver);
            try fb.propose(id, alice, keccak256(abi.encode(i)), RESULT, false) {
                accepted++;
            } catch {
                break;
            }
        }
        assertLe(accepted * perFailure, cap);
        assertEq(_available(id), cap - accepted * perFailure);
    }
}
