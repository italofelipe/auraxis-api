import os


def _read_bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _is_secret_weak(secret: str) -> bool:
    normalized = secret.strip().lower()
    return normalized in {"", "dev", "super-secret-key", "changeme"} or len(secret) < 32


def _runtime_environment_name() -> str:
    for env_name in ("AURAXIS_ENV", "APP_ENV", "FLASK_ENV"):
        raw = os.getenv(env_name)
        if raw is not None and raw.strip():
            return raw.strip().lower()
    return ""


def validate_security_configuration() -> None:
    enforce = _read_bool_env("SECURITY_ENFORCE_STRONG_SECRETS", True)

    is_debug = _read_bool_env("FLASK_DEBUG", False)
    is_testing = _read_bool_env("FLASK_TESTING", False)
    runtime_environment = _runtime_environment_name()
    secure_runtime = not is_debug and not is_testing

    if not enforce:
        if secure_runtime:
            raise RuntimeError(
                "Invalid runtime configuration: SECURITY_ENFORCE_STRONG_SECRETS "
                "must be true when FLASK_DEBUG=false and FLASK_TESTING=false."
            )
        return

    if runtime_environment in {"prod", "production"} and is_debug:
        raise RuntimeError(
            "Invalid runtime configuration: FLASK_DEBUG must be false in production."
        )

    if is_testing:
        return

    if is_debug:
        return

    secret_key = os.getenv("SECRET_KEY", "dev")
    jwt_secret_key = os.getenv("JWT_SECRET_KEY", "super-secret-key")
    weak = []
    if _is_secret_weak(secret_key):
        weak.append("SECRET_KEY")
    if _is_secret_weak(jwt_secret_key):
        weak.append("JWT_SECRET_KEY")

    if weak:
        raise RuntimeError(
            "Weak/invalid secrets for production runtime: "
            + ", ".join(weak)
            + ". Configure strong values in environment variables."
        )


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev")
    # JWT config
    JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "super-secret-key")
    # Access token continues to be delivered via Authorization header.
    # Refresh token is delivered via httpOnly cookie (SEC-GAP-01 — split-token
    # pattern). Legacy clients can still read the refresh token from the response
    # body during the transition period.
    JWT_TOKEN_LOCATION = ["headers", "cookies"]
    JWT_HEADER_TYPE = "Bearer"
    JWT_COOKIE_DOMAIN = os.getenv("JWT_COOKIE_DOMAIN") or None
    JWT_REFRESH_COOKIE_NAME = "auraxis_refresh"
    JWT_REFRESH_COOKIE_PATH = "/auth/refresh"
    # Secure flag is enabled in non-dev/test runtimes. HTTPS is required for
    # Secure cookies to be sent, so we disable it locally to avoid silently
    # dropping the cookie on http://localhost during development.
    JWT_COOKIE_SECURE = _read_bool_env(
        "JWT_COOKIE_SECURE",
        not _read_bool_env("FLASK_DEBUG", False)
        and not _read_bool_env("FLASK_TESTING", False),
    )
    JWT_COOKIE_SAMESITE = os.getenv("JWT_COOKIE_SAMESITE", "Lax")
    # SEC-AUD-03 — Double-submit CSRF token for the refresh cookie.
    # Gated behind AURAXIS_CSRF_ENFORCE so web/app clients can migrate first:
    # while OFF, the CSRF cookie is NOT set and refresh works without the header
    # (backward-compatible). Once all clients read the CSRF cookie and forward
    # it as X-CSRF-TOKEN on /auth/refresh, flip the flag in prod to enforce.
    JWT_COOKIE_CSRF_PROTECT = _read_bool_env("AURAXIS_CSRF_ENFORCE", False)
    JWT_CSRF_CHECK_FORM = False
    JWT_ACCESS_CSRF_HEADER_NAME = "X-CSRF-TOKEN"
    JWT_REFRESH_CSRF_HEADER_NAME = "X-CSRF-TOKEN"
    JWT_ACCESS_CSRF_COOKIE_NAME = "auraxis_csrf_access"
    JWT_REFRESH_CSRF_COOKIE_NAME = "auraxis_csrf_refresh"
    JWT_ACCESS_CSRF_COOKIE_PATH = os.getenv("JWT_ACCESS_CSRF_COOKIE_PATH", "/")
    JWT_REFRESH_CSRF_COOKIE_PATH = os.getenv("JWT_REFRESH_CSRF_COOKIE_PATH", "/")
    JWT_CSRF_IN_COOKIES = True
    # SEC-1 — close dual-mode: when True, login/refresh responses stop echoing
    # refresh_token in the JSON body; clients must rely on the httpOnly cookie.
    # Keep False until legacy clients have migrated. Header X-Refresh-Cookie-Only
    # lets individual requests opt in without flipping the global switch.
    AURAXIS_REFRESH_COOKIE_ONLY = _read_bool_env("AURAXIS_REFRESH_COOKIE_ONLY", False)
    AURAXIS_PREMIUM_OVERRIDE_USER_IDS = os.getenv(
        "AURAXIS_PREMIUM_OVERRIDE_USER_IDS", ""
    )

    # Email verification grace period — after N days without confirmation,
    # mutations are soft-blocked (reads continue). See:
    # - app/models/user.py — User.email_verification_required_now
    # - app/decorators/require_email_verified.py — endpoint decorator
    EMAIL_VERIFICATION_GRACE_PERIOD_DAYS = int(
        os.getenv("EMAIL_VERIFICATION_GRACE_PERIOD_DAYS", "14")
    )
    EMAIL_VERIFICATION_ENFORCE = _read_bool_env("EMAIL_VERIFICATION_ENFORCE", True)
    # URL base do frontend para o link de confirmação de email. Consumido por
    # email_confirmation_service. Quando vazio, o serviço faz fallback para
    # a URL canônica de prod com warning de log (PR #1335).
    EMAIL_CONFIRMATION_FRONTEND_URL = os.getenv("EMAIL_CONFIRMATION_FRONTEND_URL", "")

    DEBUG = _read_bool_env("FLASK_DEBUG", False)

    # Database config
    _DATABASE_URL = os.getenv("DATABASE_URL")
    SQLALCHEMY_DATABASE_URI = _DATABASE_URL or (
        f"postgresql://{os.getenv('DB_USER')}:{os.getenv('DB_PASS')}@"
        f"{os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}/{os.getenv('DB_NAME')}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    # Connection pool tuned for t2.micro (1 vCPU, 1 GB RAM).
    # pool_size=5 keeps 5 persistent connections; max_overflow=2 allows 2 extra
    # on burst traffic; pool_recycle=300 prevents stale connections after 5 min
    # of idle time; pool_pre_ping validates each connection before handing it out.
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_size": 5,
        "max_overflow": 2,
        "pool_timeout": 20,
        "pool_recycle": 300,
        "pool_pre_ping": True,
    }

    # Brapi config
    BRAPI_KEY = os.getenv("BRAPI_KEY")

    # Web Push (VAPID). Both keys are base64url-encoded (raw EC point for the
    # public/applicationServerKey, raw 32-byte private value for the private
    # key). When unset, web-push dispatch is a no-op so the app runs normally.
    # Generate with: py_vapid / `npx web-push generate-vapid-keys`.
    VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY", "")
    VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY", "")
    VAPID_SUBJECT = os.getenv("VAPID_SUBJECT", "mailto:suporte@auraxis.com.br")

    # Cloudflare Turnstile CAPTCHA
    # Set CLOUDFLARE_TURNSTILE_SECRET_KEY in the environment to enable verification.
    # When the key is empty the service falls back to allow-all (dev/test mode).
    # Set CLOUDFLARE_TURNSTILE_ENABLED=false to explicitly disable (not recommended
    # in production environments).
    CLOUDFLARE_TURNSTILE_SECRET_KEY = os.getenv("CLOUDFLARE_TURNSTILE_SECRET_KEY", "")
    CLOUDFLARE_TURNSTILE_ENABLED = _read_bool_env("CLOUDFLARE_TURNSTILE_ENABLED", True)


class DevelopmentConfig(Config):
    DEBUG = True
