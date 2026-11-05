// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

/// USDC-style token with a blocklist: a blocked sender or receiver reverts, as on Arc and Circle USDC.
contract MockUSDC {
    uint8 public decimals = 6;
    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;
    mapping(address => bool) public blocked;

    constructor(uint8 decimals_) {
        decimals = decimals_;
    }

    function mint(address to, uint256 amount) external {
        balanceOf[to] += amount;
    }

    function setBlocked(address who, bool value) external {
        blocked[who] = value;
    }

    function approve(address spender, uint256 amount) external returns (bool) {
        allowance[msg.sender][spender] = amount;
        return true;
    }

    function transfer(address to, uint256 amount) public virtual returns (bool) {
        _move(msg.sender, to, amount);
        return true;
    }

    function transferFrom(address from, address to, uint256 amount) public virtual returns (bool) {
        allowance[from][msg.sender] -= amount;
        _move(from, to, amount);
        return true;
    }

    function _move(address from, address to, uint256 amount) internal {
        require(!blocked[from] && !blocked[to], "blocklisted");
        balanceOf[from] -= amount;
        balanceOf[to] += amount;
    }
}

interface ITransferHook {
    function onTokenReceived() external;
}

/// Malicious token: calls the receiver during a transfer, so the receiver can re-enter the bounty.
contract HookToken is MockUSDC(6) {
    function transfer(address to, uint256 amount) public override returns (bool) {
        _move(msg.sender, to, amount);
        if (to.code.length != 0) ITransferHook(to).onTokenReceived();
        return true;
    }
}

/// Wallet that re-enters with a chosen call when it receives tokens.
contract AttackWallet is ITransferHook {
    address public target;
    bytes public attackCall;
    bytes public probeCall;
    bool public attackRan;
    bool public attackSucceeded;
    bytes public attackResult;
    bytes public probeResult;

    function arm(address target_, bytes calldata attackCall_, bytes calldata probeCall_) external {
        target = target_;
        attackCall = attackCall_;
        probeCall = probeCall_;
    }

    function execute(address to, bytes calldata data) external returns (bytes memory) {
        (bool ok, bytes memory result) = to.call(data);
        if (!ok) {
            assembly {
                revert(add(result, 32), mload(result))
            }
        }
        return result;
    }

    function onTokenReceived() external {
        if (attackRan || target == address(0)) return;
        attackRan = true;
        (, probeResult) = target.staticcall(probeCall);
        (attackSucceeded, attackResult) = target.call(attackCall);
    }
}

/// USDT style: transfer and transferFrom return nothing.
contract NoReturnToken {
    uint8 public constant decimals = 6;
    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;

    function mint(address to, uint256 amount) external {
        balanceOf[to] += amount;
    }

    function approve(address spender, uint256 amount) external {
        allowance[msg.sender][spender] = amount;
    }

    function transfer(address to, uint256 amount) external {
        balanceOf[msg.sender] -= amount;
        balanceOf[to] += amount;
    }

    function transferFrom(address from, address to, uint256 amount) external {
        allowance[from][msg.sender] -= amount;
        balanceOf[from] -= amount;
        balanceOf[to] += amount;
    }
}

/// Reports failure by returning false once switched on, without moving funds.
contract FalseReturnToken is MockUSDC(6) {
    bool public failing;

    function setFailing(bool value) external {
        failing = value;
    }

    function transfer(address to, uint256 amount) public override returns (bool) {
        if (failing) return false;
        return super.transfer(to, amount);
    }
}

/// Takes a 1% fee on transferFrom, so the contract receives less than the cap.
contract FeeToken is MockUSDC(6) {
    function transferFrom(address from, address to, uint256 amount) public override returns (bool) {
        allowance[from][msg.sender] -= amount;
        uint256 fee = amount / 100;
        _move(from, address(0xFEE), fee);
        _move(from, to, amount - fee);
        return true;
    }
}

/// Has no decimals() function at all.
contract NoDecimalsToken {
    function balanceOf(address) external pure returns (uint256) {
        return 0;
    }
}
