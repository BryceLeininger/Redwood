"""Create a localhost TLS certificate for the Outlook add-in panel."""
from __future__ import annotations

import argparse
import ipaddress
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


def create_certificate(cert_path: Path, key_path: Path, days: int = 365) -> None:
    cert_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.parent.mkdir(parents=True, exist_ok=True)

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    subject = issuer = x509.Name(
        [
            x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
            x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, "CA"),
            x509.NameAttribute(NameOID.LOCALITY_NAME, "Localhost"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "AgentFactory"),
            x509.NameAttribute(NameOID.COMMON_NAME, "localhost"),
        ]
    )

    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=days))
        .add_extension(
            x509.SubjectAlternativeName(
                [
                    x509.DNSName("localhost"),
                    x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
                ]
            ),
            critical=False,
        )
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(private_key=key, algorithm=hashes.SHA256())
    )

    key_path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))


def trust_certificate(cert_path: Path) -> None:
    command = ["certutil", "-user", "-addstore", "Root", str(cert_path)]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or "unknown error"
        raise RuntimeError(f"Failed to trust certificate: {message}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Create localhost TLS certificate for Outlook agent panel.")
    parser.add_argument("--cert-path", default="outlook_addin/certs/localhost.crt")
    parser.add_argument("--key-path", default="outlook_addin/certs/localhost.key")
    parser.add_argument("--days", type=int, default=365, help="Validity period in days.")
    parser.add_argument("--trust", action="store_true", help="Trust cert in current user root store.")
    args = parser.parse_args()

    cert_path = Path(args.cert_path)
    key_path = Path(args.key_path)
    create_certificate(cert_path, key_path, days=max(1, args.days))

    if args.trust:
        trust_certificate(cert_path)

    print(f"Certificate: {cert_path}")
    print(f"Private Key: {key_path}")
    if args.trust:
        print("Certificate trusted in current user root store.")


if __name__ == "__main__":
    main()
