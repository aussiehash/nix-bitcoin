{ config, lib, pkgs, ... }:

with lib;
let
  cfg = config.services.electrs;
  inherit (config) nix-bitcoin-services;
  secretsDir = config.nix-bitcoin.secretsDir;
in {
  options.services.electrs = {
    enable = mkEnableOption "electrs";
    dataDir = mkOption {
      type = types.path;
      default = "/var/lib/electrs";
      description = "The data directory for electrs.";
    };
    user = mkOption {
      type = types.str;
      default = "electrs";
      description = "The user as which to run electrs.";
    };
    group = mkOption {
      type = types.str;
      default = cfg.user;
      description = "The group as which to run electrs.";
    };
    high-memory = mkOption {
      type = types.bool;
      default = false;
      description = ''
        If enabled, the electrs service will sync faster on high-memory systems (≥ 8GB).
      '';
    };
    address = mkOption {
      type = types.str;
      default = "127.0.0.1";
      description = "RPC listening address.";
    };
    port = mkOption {
      type = types.port;
      default = 50001;
      description = "RPC port.";
    };
    daemonrpc = mkOption {
      type = types.str;
      default = "127.0.0.1:8332";
      description = ''
        Bitcoin daemon JSONRPC 'addr:port' to connect
      '';
    };
    extraArgs = mkOption {
      type = types.separatedString " ";
      default = "";
      description = "Extra command line arguments passed to electrs.";
    };
    enforceTor = nix-bitcoin-services.enforceTor;
  };

  config = mkIf cfg.enable {
    assertions = [
      { assertion = config.services.bitcoind.prune == 0;
        message = "electrs does not support bitcoind pruning.";
      }
    ];

    environment.systemPackages = [ pkgs.nix-bitcoin.electrs ];

    systemd.tmpfiles.rules = [
      "d '${cfg.dataDir}' 0770 ${cfg.user} ${cfg.group} - -"
    ];

    systemd.services.electrs = {
      description = "Electrs Electrum Server";
      wantedBy = [ "multi-user.target" ];
      requires = [ "bitcoind.service" ];
      after = [ "bitcoind.service" ];
      preStart = ''
        echo "cookie = \"${config.services.bitcoind.rpcuser}:$(cat ${secretsDir}/bitcoin-rpcpassword)\"" \
          > electrs.toml
        '';
      serviceConfig = nix-bitcoin-services.defaultHardening // {
        RuntimeDirectory = "electrs";
        RuntimeDirectoryMode = "700";
        WorkingDirectory = "/run/electrs";
        ExecStart = ''
          ${pkgs.nix-bitcoin.electrs}/bin/electrs -vvv \
          ${if cfg.high-memory then
              traceIf (!config.services.bitcoind.dataDirReadableByGroup) ''
                Warning: For optimal electrs syncing performance, enable services.bitcoind.dataDirReadableByGroup.
                Note that this disables wallet support in bitcoind.
              '' ""
            else
              "--jsonrpc-import --index-batch-size=10"
          } \
          --db-dir '${cfg.dataDir}' --daemon-dir '${config.services.bitcoind.dataDir}' \
          --electrum-rpc-addr=${toString cfg.address}:${toString cfg.port} \
          --daemon-rpc-addr=${toString cfg.daemonrpc} ${cfg.extraArgs}
        '';
        User = cfg.user;
        Group = cfg.group;
        Restart = "on-failure";
        RestartSec = "10s";
        ReadWritePaths = "${cfg.dataDir} ${if cfg.high-memory then "${config.services.bitcoind.dataDir}" else ""}";
      } // (if cfg.enforceTor
          then nix-bitcoin-services.allowTor
          else nix-bitcoin-services.allowAnyIP
        );
    };

    users.users.${cfg.user} = {
      description = "electrs User";
      group = cfg.group;
      extraGroups = [ "bitcoinrpc" ] ++ optionals cfg.high-memory [ "bitcoin" ];
    };
    users.groups.${cfg.group} = {};
  };
}
