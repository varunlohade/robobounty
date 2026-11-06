"""LOCAL ONLY. Starts anvil, the sponsor mock and the resolver, deploys the real contract with the real Deploy script, and prints the web process env as JSON.

Fresh random wallets with test balances on this one anvil only. The bytecode at the Arc USDC address is MockUSDC, not Arc's USDC. Standard anvil runs a standard EVM, not Arc's.
"""
import argparse
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPONSORS = HERE.parent
POLICY = SPONSORS.parent
ROOT = POLICY.parent
CONTRACTS = ROOT / "contracts"
PYTHON = str(POLICY / ".venv" / "bin" / "python")
sys.path.insert(0, str(SPONSORS))
import arc_spec
import sponsor_status as status

ROLES = ("company", "resolver", "arbiter", "tester")
PASSWORD = "local-mock-password-not-a-secret"


def wait_port(url, tries=60):
    for _ in range(tries):
        try:
            urllib.request.urlopen(urllib.request.Request(url, data=b'{"jsonrpc":"2.0","id":1,"method":"eth_chainId","params":[]}', headers={"Content-Type": "application/json"}), timeout=1).read()
            return
        except OSError:
            time.sleep(0.2)
    raise SystemExit(f"nothing answered at {url}")


def cast(*args):
    return subprocess.run(["cast", *args], capture_output=True, text=True, check=True, timeout=60).stdout.strip()


class Stack:
    """Use as a context manager. Fields: env_web, env_resolver, env_tester, keystores, addresses, rpc."""

    def __init__(self, anvil_port=8745, mock_port=8746, world=True, window=60, cap=1000, per_failure=100, start_resolver=True, require_world=True):
        self.anvil_port, self.mock_port, self.world, self.window, self.cap, self.per_failure, self.start_resolver, self.require_world = anvil_port, mock_port, world, window, cap, per_failure, start_resolver, require_world
        self.procs, self.rpc = [], f"http://127.0.0.1:{anvil_port}"
        self.temp = tempfile.TemporaryDirectory(prefix="crashlab-mock-")
        self.dir = Path(self.temp.name)

    def __enter__(self):
        self.procs.append(subprocess.Popen(["anvil", "--port", str(self.anvil_port), "--silent", "--block-time", "1"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        wait_port(self.rpc)
        self.procs.append(subprocess.Popen([PYTHON, str(HERE / "mock_sponsors.py"), "--port", str(self.mock_port)]))
        password = self.dir / "password"
        password.write_text(PASSWORD)
        self.password = str(password)
        self.keystores, self.addresses = {}, {}
        for role in ROLES:
            folder = self.dir / role
            folder.mkdir()
            made = json.loads(subprocess.run(["cast", "wallet", "new", str(folder), "--unsafe-password", PASSWORD, "--json"], capture_output=True, text=True, check=True).stdout)
            row = made["data"][0] if isinstance(made, dict) else made[0]
            self.keystores[role], self.addresses[role] = row["path"], row["address"]
            cast("rpc", "anvil_setBalance", row["address"], hex(10**20), "--rpc-url", self.rpc)
        self.install_usdc()
        self.spec = self.dir / "spec"
        self.spec_hash = arc_spec.build(self.spec, schema_limits=True)["spec_hash"]
        self.deploy()
        return self.finish_env()

    def install_usdc(self):
        code = json.loads(subprocess.run(["forge", "inspect", "test/Mocks.sol:MockUSDC", "deployedBytecode", "--json"], cwd=CONTRACTS, capture_output=True, text=True, check=True).stdout or '""')
        code = code["data"] if isinstance(code, dict) and "data" in code else code
        code = code if isinstance(code, str) else code.get("object")
        cast("rpc", "anvil_setCode", status.ARC_USDC, code, "--rpc-url", self.rpc)
        cast("rpc", "anvil_setStorageAt", status.ARC_USDC, "0x0", "0x" + "6".zfill(64), "--rpc-url", self.rpc)  # decimals sits in slot 0
        self.usdc_send("mint(address,uint256)", self.addresses["company"], str(self.cap * 10 * 10**6))

    def usdc_send(self, signature, *args):
        subprocess.run(["cast", "send", status.ARC_USDC, signature, *args, "--rpc-url", self.rpc, "--keystore", self.keystores["company"], "--password-file", self.password, "--json"], capture_output=True, check=True, timeout=60)

    def deploy(self):
        env = {**os.environ, "ARC_USDC_ADDRESS": status.ARC_USDC, "ARC_COMPANY_ADDRESS": self.addresses["company"], "ARC_RESOLVER_ADDRESS": self.addresses["resolver"], "ARC_ARBITER_ADDRESS": self.addresses["arbiter"],
               "ARC_TESTER_ADDRESS": self.addresses["tester"], "ARC_SPEC_HASH": self.spec_hash, "ARC_CAP_BASE_UNITS": str(self.cap * 10**6), "ARC_PER_FAILURE_BASE_UNITS": str(self.per_failure * 10**6),
               "ARC_TOP_PRIZE_BASE_UNITS": "0", "ARC_DEADLINE_SECONDS": "86400", "ARC_GRACE_SECONDS": "3600", "ARC_DISPUTE_WINDOW_SECONDS": str(self.window)}
        done = subprocess.run(["forge", "script", "script/Deploy.s.sol:Deploy", "--rpc-url", self.rpc, "--broadcast", "--keystore", self.keystores["company"], "--password-file", self.password, "--sender", self.addresses["company"]],
                              cwd=CONTRACTS, env=env, capture_output=True, text=True, timeout=240)
        if done.returncode != 0:
            raise SystemExit("deploy failed:\n" + done.stdout[-3000:] + done.stderr[-2000:])
        self.deploy_output = done.stdout
        run = json.loads((CONTRACTS / "broadcast" / "Deploy.s.sol" / "31337" / "run-latest.json").read_text())
        self.bounty = next(t["contractAddress"] for t in run["transactions"] if t["contractName"] == "FailureBounty")

    def finish_env(self):
        base = {k: v for k, v in os.environ.items() if k not in status.SECRET_VARS}
        arc = {"ARC_RPC_URL": self.rpc, "ARC_BOUNTY_ADDRESS": self.bounty, "ARC_BOUNTY_ID": "1", "ARC_USDC_ADDRESS": status.ARC_USDC, "ARC_TESTER_ADDRESS": self.addresses["tester"],
               "ARC_SPEC_DIR": str(self.spec), "ARC_RESOLVER_DIR": str(self.dir / "resolver"), "WORLD_DB": str(self.dir / "world.sqlite")}
        world = {"WORLD_APP_ID": "app_staging_mock", "WORLD_RP_ID": "rp_mock", "WORLD_RP_SIGNING_KEY": "0x" + "ab" * 32, "WORLD_ENVIRONMENT": "staging",
                 "WORLD_VERIFY_URL": f"http://127.0.0.1:{self.mock_port}/api/v4/verify/{{rp_id}}", "WORLD_HUMAN_CAP": "3"} if self.world else {}
        zg = {"CRASHLAB_LLM": "0g", "ZG_API_KEY": "mock-zg-key-not-a-secret", "ZG_MODEL": "mock-good", "ZG_ROUTER_URL": f"http://127.0.0.1:{self.mock_port}/v1",
              "ZG_SDK_MODULE": str(HERE / "mock_zg_sdk.mjs"), "ZG_ETHERS_MODULE": str(HERE / "mock_ethers.mjs")}
        self.env_web = {**base, **arc, **world}
        self.env_web_full = {**self.env_web, **zg}  # for the app check: all three switched on against mocks
        self.env_resolver = {**base, **arc, "ARC_RESOLVER_KEYSTORE": self.keystores["resolver"], "ARC_RESOLVER_PASSWORD_FILE": self.password, "ARC_REQUIRE_WORLD_ID": "1" if self.require_world else "0"}
        self.env_tester = {**base, **arc, "ARC_TESTER_KEYSTORE": self.keystores["tester"], "ARC_TESTER_PASSWORD_FILE": self.password}
        if self.start_resolver:
            self.resolver_log = open(self.dir / "resolver.log", "w")
            self.procs.append(subprocess.Popen([PYTHON, str(SPONSORS / "resolver.py"), "serve"], env=self.env_resolver, stdout=self.resolver_log, stderr=subprocess.STDOUT))
        return self

    def __exit__(self, *_):
        for p in reversed(self.procs):
            p.terminate()
        for p in self.procs:
            p.wait(timeout=10)
        self.temp.cleanup()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--anvil-port", type=int, default=8745)
    ap.add_argument("--mock-port", type=int, default=8746)
    ap.add_argument("--window", type=int, default=60)
    a = ap.parse_args()
    with Stack(a.anvil_port, a.mock_port, window=a.window) as stack:
        print(json.dumps({"web": stack.env_web_full, "tester": stack.env_tester, "addresses": stack.addresses, "bounty": stack.bounty}), flush=True)

        def stop(*_):  # a second SIGTERM must not interrupt the cleanup
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            sys.exit(0)
        signal.signal(signal.SIGTERM, stop)
        signal.pause()


if __name__ == "__main__":
    main()
