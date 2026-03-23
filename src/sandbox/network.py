from __future__ import annotations

import logging

from src.config import settings

logger = logging.getLogger(__name__)

IPTABLES_RULES_TEMPLATE = """
# Allow DNS
iptables -A OUTPUT -p udp --dport 53 -j ACCEPT
iptables -A OUTPUT -p tcp --dport 53 -j ACCEPT

# Allow whitelisted hosts
{whitelist_rules}

# Allow established connections
iptables -A OUTPUT -m state --state ESTABLISHED,RELATED -j ACCEPT

# Block everything else outbound
iptables -A OUTPUT -j DROP
"""


def generate_firewall_script() -> str:
    """Generate iptables rules that whitelist only package registries."""
    rules: list[str] = []
    for host in settings.sandbox_network_whitelist:
        rules.append(f"iptables -A OUTPUT -d {host} -j ACCEPT")

    return IPTABLES_RULES_TEMPLATE.format(
        whitelist_rules="\n".join(rules),
    )
