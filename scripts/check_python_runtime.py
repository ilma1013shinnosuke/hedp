import ssl
import sys


def main() -> int:
    errors = []
    if sys.version_info < (3, 11):
        errors.append("Python 3.11以上が必要です")
    if "LibreSSL" in ssl.OPENSSL_VERSION:
        errors.append("LibreSSL版Pythonは使用できません")
    elif ssl.OPENSSL_VERSION_INFO < (1, 1, 1):
        errors.append("OpenSSL 1.1.1以上が必要です")
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 2
    print(f"Python {sys.version.split()[0]} / {ssl.OPENSSL_VERSION}: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
