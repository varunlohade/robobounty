// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

/// @title FailureBounty
/// @notice Holds a company's USDC-style bounty and pays one fixed amount per new robot failure.
/// A resolver proposes, an arbiter can reject during a dispute window, anyone can finalize after it,
/// and the winner pulls the money. No function accepts native value.
contract FailureBounty {
    enum Status {
        None,
        Pending,
        Rejected,
        Finalized,
        Claimed
    }

    struct Bounty {
        address company;
        address resolver;
        address arbiter;
        bytes32 specHash;
        uint256 perFailure;
        uint256 topPrize;
        /// Money not tied to any proposal. The only balance a refund can touch.
        uint256 available;
        uint64 deadline;
        uint64 refundOpensAt;
        uint64 disputeWindow;
        bool topPrizeTaken;
    }

    struct Failure {
        address submitter;
        uint256 amount;
        bytes32 resultHash;
        uint64 disputeEndsAt;
        bool isTopPrize;
        Status status;
    }

    uint8 public constant TOKEN_DECIMALS = 6;
    uint64 public constant MIN_DISPUTE_WINDOW = 60;

    address public immutable token;

    uint256 public bountyCount;
    mapping(uint256 bountyId => Bounty) public bounties;
    mapping(uint256 bountyId => mapping(bytes32 fingerprint => Failure)) public failures;

    uint256 private _lock = 1;

    event BountyCreated(
        uint256 indexed bountyId,
        address indexed company,
        address resolver,
        address arbiter,
        bytes32 specHash,
        uint256 cap,
        uint256 perFailure,
        uint256 topPrize,
        uint64 deadline,
        uint64 refundOpensAt,
        uint64 disputeWindow
    );
    event FailureProposed(
        uint256 indexed bountyId,
        bytes32 indexed fingerprint,
        address indexed submitter,
        bytes32 resultHash,
        uint256 amount,
        bool isTopPrize,
        uint64 disputeEndsAt
    );
    event FailureRejected(uint256 indexed bountyId, bytes32 indexed fingerprint, bytes32 reasonHash);
    event FailureFinalized(uint256 indexed bountyId, bytes32 indexed fingerprint);
    event FailureClaimed(uint256 indexed bountyId, bytes32 indexed fingerprint, address indexed submitter, uint256 amount);
    event Refunded(uint256 indexed bountyId, address indexed company, uint256 amount);

    error Reentrancy();
    error BadToken();
    error BadDecimals(uint256 actual);
    error TokenTransferFailed();
    error WrongAmountReceived();
    error BadAddress();
    error RolesNotSeparate();
    error BadAmounts();
    error BadTimes();
    error BadHash();
    error UnknownBounty();
    error NotResolver();
    error NotArbiter();
    error NotSubmitter();
    error NotCompany();
    error PastDeadline();
    error DuplicateFingerprint();
    error TopPrizeUnavailable();
    error CapExceeded();
    error WrongStatus();
    error DisputeWindowOpen();
    error DisputeWindowClosed();
    error RefundNotOpen();
    error NothingToRefund();

    modifier nonReentrant() {
        if (_lock != 1) revert Reentrancy();
        _lock = 2;
        _;
        _lock = 1;
    }

    constructor(address token_) {
        if (token_.code.length == 0) revert BadToken();
        (bool ok, bytes memory data) = token_.staticcall(abi.encodeWithSignature("decimals()"));
        if (!ok || data.length != 32) revert BadToken();
        uint256 decimals = abi.decode(data, (uint256));
        if (decimals != TOKEN_DECIMALS) revert BadDecimals(decimals);
        token = token_;
    }

    /// @notice Moves `cap` from the caller into a new bounty. The caller must approve first.
    /// @param grace Seconds after the deadline before a refund opens. Must cover the dispute window.
    function createBounty(
        address resolver,
        address arbiter,
        bytes32 specHash,
        uint256 cap,
        uint256 perFailure,
        uint256 topPrize,
        uint64 deadline,
        uint64 grace,
        uint64 disputeWindow
    ) external nonReentrant returns (uint256 bountyId) {
        if (resolver == address(0) || arbiter == address(0)) revert BadAddress();
        if (resolver == arbiter || resolver == msg.sender || arbiter == msg.sender) revert RolesNotSeparate();
        if (specHash == bytes32(0)) revert BadHash();
        if (perFailure == 0 || perFailure > cap) revert BadAmounts();
        if (topPrize != 0 && (topPrize < perFailure || topPrize > cap)) revert BadAmounts();
        if (deadline <= block.timestamp || disputeWindow < MIN_DISPUTE_WINDOW || grace < disputeWindow) {
            revert BadTimes();
        }

        bountyId = ++bountyCount;
        uint64 refundOpensAt = deadline + grace;
        bounties[bountyId] = Bounty({
            company: msg.sender,
            resolver: resolver,
            arbiter: arbiter,
            specHash: specHash,
            perFailure: perFailure,
            topPrize: topPrize,
            available: cap,
            deadline: deadline,
            refundOpensAt: refundOpensAt,
            disputeWindow: disputeWindow,
            topPrizeTaken: false
        });
        emit BountyCreated(
            bountyId, msg.sender, resolver, arbiter, specHash, cap, perFailure, topPrize, deadline, refundOpensAt, disputeWindow
        );

        uint256 balanceBefore = _balance();
        _callToken(abi.encodeWithSignature("transferFrom(address,address,uint256)", msg.sender, address(this), cap));
        if (_balance() != balanceBefore + cap) revert WrongAmountReceived();
    }

    /// @notice Resolver reserves a payout for a new failure. A rejected fingerprint can be proposed again.
    /// @param isTopPrize Pays the top prize in place of the per-failure amount. One live top prize per bounty.
    function propose(uint256 bountyId, address submitter, bytes32 fingerprint, bytes32 resultHash, bool isTopPrize)
        external
        nonReentrant
    {
        Bounty storage b = _bounty(bountyId);
        if (msg.sender != b.resolver) revert NotResolver();
        if (block.timestamp > b.deadline) revert PastDeadline();
        if (submitter == address(0) || submitter == address(this)) revert BadAddress();
        if (fingerprint == bytes32(0) || resultHash == bytes32(0)) revert BadHash();

        Failure storage f = failures[bountyId][fingerprint];
        if (f.status != Status.None && f.status != Status.Rejected) revert DuplicateFingerprint();

        uint256 amount = b.perFailure;
        if (isTopPrize) {
            if (b.topPrize == 0 || b.topPrizeTaken) revert TopPrizeUnavailable();
            b.topPrizeTaken = true;
            amount = b.topPrize;
        }
        if (amount > b.available) revert CapExceeded();
        b.available -= amount;

        uint64 disputeEndsAt = uint64(block.timestamp) + b.disputeWindow;
        failures[bountyId][fingerprint] = Failure({
            submitter: submitter,
            amount: amount,
            resultHash: resultHash,
            disputeEndsAt: disputeEndsAt,
            isTopPrize: isTopPrize,
            status: Status.Pending
        });
        emit FailureProposed(bountyId, fingerprint, submitter, resultHash, amount, isTopPrize, disputeEndsAt);
    }

    /// @notice Arbiter cancels a pending failure during the dispute window and frees its money.
    function reject(uint256 bountyId, bytes32 fingerprint, bytes32 reasonHash) external nonReentrant {
        Bounty storage b = _bounty(bountyId);
        if (msg.sender != b.arbiter) revert NotArbiter();
        Failure storage f = failures[bountyId][fingerprint];
        if (f.status != Status.Pending) revert WrongStatus();
        if (block.timestamp >= f.disputeEndsAt) revert DisputeWindowClosed();

        f.status = Status.Rejected;
        b.available += f.amount;
        if (f.isTopPrize) b.topPrizeTaken = false;
        emit FailureRejected(bountyId, fingerprint, reasonHash);
    }

    /// @notice Anyone can finalize once the window ends, so no single role can hold a winner's money.
    function finalize(uint256 bountyId, bytes32 fingerprint) external nonReentrant {
        Failure storage f = failures[bountyId][fingerprint];
        if (f.status != Status.Pending) revert WrongStatus();
        if (block.timestamp < f.disputeEndsAt) revert DisputeWindowOpen();

        f.status = Status.Finalized;
        emit FailureFinalized(bountyId, fingerprint);
    }

    /// @notice The named submitter pulls a finalized payout. One failing winner cannot block others.
    function claim(uint256 bountyId, bytes32 fingerprint) external nonReentrant {
        Failure storage f = failures[bountyId][fingerprint];
        if (f.status != Status.Finalized) revert WrongStatus();
        if (msg.sender != f.submitter) revert NotSubmitter();

        f.status = Status.Claimed;
        uint256 amount = f.amount;
        emit FailureClaimed(bountyId, fingerprint, msg.sender, amount);

        _callToken(abi.encodeWithSignature("transfer(address,uint256)", msg.sender, amount));
    }

    /// @notice Company takes back only money not tied to a proposal, after deadline plus grace.
    /// Money freed by a later rejection can be refunded by calling again.
    function refund(uint256 bountyId) external nonReentrant {
        Bounty storage b = _bounty(bountyId);
        if (msg.sender != b.company) revert NotCompany();
        if (block.timestamp < b.refundOpensAt) revert RefundNotOpen();
        uint256 amount = b.available;
        if (amount == 0) revert NothingToRefund();

        b.available = 0;
        emit Refunded(bountyId, msg.sender, amount);

        _callToken(abi.encodeWithSignature("transfer(address,uint256)", msg.sender, amount));
    }

    function _bounty(uint256 bountyId) private view returns (Bounty storage b) {
        b = bounties[bountyId];
        if (b.company == address(0)) revert UnknownBounty();
    }

    function _balance() private view returns (uint256) {
        (bool ok, bytes memory data) = token.staticcall(abi.encodeWithSignature("balanceOf(address)", address(this)));
        if (!ok || data.length != 32) revert TokenTransferFailed();
        return abi.decode(data, (uint256));
    }

    /// @dev Accepts tokens that return true or nothing. Rejects a revert or a false return.
    function _callToken(bytes memory callData) private {
        (bool ok, bytes memory data) = token.call(callData);
        if (!ok || (data.length != 0 && (data.length != 32 || !abi.decode(data, (bool))))) {
            revert TokenTransferFailed();
        }
    }
}
