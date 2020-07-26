# netns IP addresses
bitcoind_ip = "169.254.1.12"
clightning_ip = "169.254.1.13"
lnd_ip = "169.254.1.14"
liquidd_ip = "169.254.1.15"
electrs_ip = "169.254.1.16"
sparkwallet_ip = "169.254.1.17"
lightningcharge_ip = "169.254.1.18"
nanopos_ip = "169.254.1.19"
recurringdonations_ip = "169.254.1.20"
nginx_ip = "169.254.1.21"

### Tests

assert_running("setup-secrets")
# Unused secrets should be inaccessible
succeed('[[ $(stat -c "%U:%G %a" /secrets/dummy) = "root:root 440" ]]')

assert_running("bitcoind")
machine.wait_until_succeeds("bitcoin-cli getnetworkinfo")
assert_matches("su operator -c 'bitcoin-cli getnetworkinfo' | jq", '"version"')

assert_running("electrs")
machine.wait_until_succeeds(
    "ip netns exec nb-electrs nc -z localhost 4224"
)  # prometeus metrics provider
# Check RPC connection to bitcoind
machine.wait_until_succeeds(log_has_string("electrs", "NetworkInfo"))
assert_running("nginx")
# Stop electrs from spamming the test log with 'wait for bitcoind sync' messages
succeed("systemctl stop electrs")

assert_running("liquidd")
machine.wait_until_succeeds("elements-cli getnetworkinfo")
assert_matches("su operator -c 'elements-cli getnetworkinfo' | jq", '"version"')
succeed("su operator -c 'liquidswap-cli --help'")

assert_running("clightning")
assert_matches("su operator -c 'lightning-cli getinfo' | jq", '"id"')

assert_running("spark-wallet")
spark_auth = re.search("login=(.*)", succeed("cat /secrets/spark-wallet-login"))[1]
machine.wait_until_succeeds("ip netns exec nb-spark-wallet nc -z %s 9737" % sparkwallet_ip)
assert_matches(
    f"ip netns exec nb-spark-wallet curl -s {spark_auth}@%s:9737" % sparkwallet_ip, "Spark"
)

assert_running("lightning-charge")
charge_auth = re.search("API_TOKEN=(.*)", succeed("cat /secrets/lightning-charge-env"))[1]
machine.wait_until_succeeds("ip netns exec nb-nanopos nc -z %s 9112" % lightningcharge_ip)
assert_matches(
    f"ip netns exec nb-nanopos curl -s api-token:{charge_auth}@%s:9112/info | jq"
    % lightningcharge_ip,
    '"id"',
)

assert_running("nanopos")
machine.wait_until_succeeds("ip netns exec nb-lightning-charge nc -z %s 9116" % nanopos_ip)
assert_matches("ip netns exec nb-lightning-charge curl %s:9116" % nanopos_ip, "tshirt")

assert_running("onion-chef")

# FIXME: use 'wait_for_unit' because 'create-web-index' always fails during startup due
# to incomplete unit dependencies.
# 'create-web-index' implicitly tests 'nodeinfo'.
machine.wait_for_unit("create-web-index")
machine.wait_until_succeeds("ip netns exec nb-nginx nc -z localhost 80")
assert_matches("ip netns exec nb-nginx curl localhost", "nix-bitcoin")
assert_matches("ip netns exec nb-nginx curl -L localhost/store", "tshirt")

machine.wait_until_succeeds(log_has_string("bitcoind-import-banlist", "Importing node banlist"))
assert_no_failure("bitcoind-import-banlist")

### Security tests

ping_bitcoind = "ip netns exec nb-bitcoind ping -c 1 -w 1"
ping_nanopos = "ip netns exec nb-nanopos ping -c 1 -w 1"

# Positive ping tests (non-exhaustive)
machine.succeed(
    "%s %s &&" % (ping_bitcoind, bitcoind_ip)
    + "%s %s &&" % (ping_bitcoind, clightning_ip)
    + "%s %s &&" % (ping_bitcoind, liquidd_ip)
    + "%s %s &&" % (ping_nanopos, lightningcharge_ip)
    + "%s %s &&" % (ping_nanopos, nanopos_ip)
    + "%s %s" % (ping_nanopos, nginx_ip)
)

# Negative ping tests (non-exhaustive)
machine.fail(
    "%s %s ||" % (ping_bitcoind, sparkwallet_ip)
    + "%s %s ||" % (ping_bitcoind, lightningcharge_ip)
    + "%s %s ||" % (ping_bitcoind, nanopos_ip)
    + "%s %s ||" % (ping_bitcoind, recurringdonations_ip)
    + "%s %s ||" % (ping_bitcoind, nginx_ip)
    + "%s %s ||" % (ping_nanopos, bitcoind_ip)
    + "%s %s ||" % (ping_nanopos, clightning_ip)
    + "%s %s ||" % (ping_nanopos, lnd_ip)
    + "%s %s ||" % (ping_nanopos, liquidd_ip)
    + "%s %s ||" % (ping_nanopos, electrs_ip)
    + "%s %s ||" % (ping_nanopos, sparkwallet_ip)
    + "%s %s" % (ping_nanopos, recurringdonations_ip)
)

# test that netns-exec can't be run for unauthorized namespace
machine.fail("netns-exec nb-electrs ip a")

# test that netns-exec drops capabilities
assert_matches_exactly(
    "su operator -c 'netns-exec nb-bitcoind capsh --print | grep Current '", "Current: =\n"
)

# test that netns-exec can not be executed by users that are not operator
machine.fail("sudo -u clightning netns-exec nb-bitcoind ip a")

### Additional tests

# Current time in µs
pre_restart = succeed("date +%s.%6N").rstrip()

# Sanity-check system by restarting all services
succeed("systemctl restart bitcoind clightning spark-wallet lightning-charge nanopos liquidd")

# Now that the bitcoind restart triggered a banlist import restart, check that
# re-importing already banned addresses works
machine.wait_until_succeeds(
    log_has_string(f"bitcoind-import-banlist --since=@{pre_restart}", "Importing node banlist")
)
assert_no_failure("bitcoind-import-banlist")

### Test lnd

succeed("systemctl stop nanopos lightning-charge spark-wallet clightning")
succeed("systemctl start lnd")
assert_matches("su operator -c 'lncli getinfo' | jq", '"version"')
assert_no_failure("lnd")

### Test loopd

succeed("systemctl start lightning-loop")
assert_matches("su operator -c 'loop --version'", "version")
assert_no_failure("lightning-loop")
