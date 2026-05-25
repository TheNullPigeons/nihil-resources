# windows/pivot

Tunneling and pivoting binaries to drop on compromised Windows hosts.

- `chisel_amd64.gz` - TCP tunnel / SOCKS5 proxy (fetch via catalog, extract before use)
- `ligolo-ng/` - ligolo-ng agent binaries for Windows (dropped on the foothold)
- `ligolo-ng-proxy/` - ligolo-ng proxy for Windows (cross-op: attacker machine running Windows)

Fetch binaries via catalog: `python3 scripts/update.py`
