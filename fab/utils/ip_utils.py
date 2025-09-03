"""
IP utilities for FAB.

Provides functions for working with IP addresses including
local/private network detection.
"""

import ipaddress
from typing import List


def is_local_ip(ip_address: str) -> bool:
    """
    Check if IP address belongs to local/private networks.
    
    Args:
        ip_address: IP address string to check
        
    Returns:
        bool: True if IP is local/private, False otherwise
    """
    try:
        ip = ipaddress.ip_address(ip_address)
        
        # Define local/private IP ranges
        local_ranges = [
            ipaddress.ip_network('127.0.0.0/8'),      # Loopback
            ipaddress.ip_network('10.0.0.0/8'),       # Private Class A
            ipaddress.ip_network('172.16.0.0/12'),    # Private Class B
            ipaddress.ip_network('192.168.0.0/16'),   # Private Class C
            ipaddress.ip_network('169.254.0.0/16'),   # Link-local
            ipaddress.ip_network('192.0.2.0/24'),     # TEST-NET-1
            ipaddress.ip_network('198.51.100.0/24'),  # TEST-NET-2
            ipaddress.ip_network('203.0.113.0/24'),   # TEST-NET-3
        ]
        
        # Check if IP belongs to any local range
        for local_range in local_ranges:
            if ip in local_range:
                return True
                
        return False
        
    except (ipaddress.AddressValueError, ValueError):
        # Invalid IP address format
        return False


def get_local_ip_ranges() -> List[str]:
    """
    Get list of local/private IP ranges.
    
    Returns:
        List[str]: List of CIDR notation ranges
    """
    return [
        '127.0.0.0/8',      # Loopback
        '10.0.0.0/8',       # Private Class A
        '172.16.0.0/12',    # Private Class B
        '192.168.0.0/16',   # Private Class C
        '169.254.0.0/16',   # Link-local
        '192.0.2.0/24',     # TEST-NET-1
        '198.51.100.0/24',  # TEST-NET-2
        '203.0.113.0/24',   # TEST-NET-3
    ]
