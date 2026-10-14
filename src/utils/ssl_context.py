"""
Centralized TLS / SSL Context Provider
Enforces strict TLS certificate validation using Mozilla's CA bundle via certifi.
Eliminates all disabled SSL verification (ssl=False / unverified contexts) across production paths.
"""

import ssl
import certifi


def get_verified_ssl_context() -> ssl.SSLContext:
    """
    Return an SSLContext enforcing strict certificate verification against certifi's CA bundle.
    Guarantees production security without relying on expired or broken OS certificate trust stores.
    """
    ctx = ssl.create_default_context(cafile=certifi.where())
    ctx.check_hostname = True
    ctx.verify_mode = ssl.CERT_REQUIRED
    return ctx
