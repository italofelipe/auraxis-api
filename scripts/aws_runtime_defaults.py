#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import dataclass

DEFAULT_PROFILE = "auraxis-admin"
DEFAULT_REGION = "us-east-1"

DEFAULT_PROD_INSTANCE_ID = "i-0057e3b52162f78f8"
DEFAULT_DEV_INSTANCE_ID = "i-0bddcfc8ea56c2ba3"

DEFAULT_PROD_DOMAIN = "api.auraxis.com.br"
DEFAULT_DEV_DOMAIN = "dev.api.auraxis.com.br"

DEFAULT_PROD_SSM_PATH = "/auraxis/prod"
DEFAULT_DEV_SSM_PATH = "/auraxis/dev"

DEFAULT_PROD_SCHEME = "https"
DEFAULT_DEV_SCHEME = "http"

DEFAULT_REPO_PATH = "/opt/auraxis"
DEFAULT_LEGACY_REPO_PATH = "/opt/flask_expenses"
DEFAULT_PUBLIC_REPO_URL = "https://github.com/italofelipe/auraxis-api.git"


@dataclass(frozen=True)
class EnvironmentDefaults:
    env_name: str
    instance_id: str
    domain: str
    ssm_path: str
    public_scheme: str


PROD_DEFAULTS = EnvironmentDefaults(
    env_name="prod",
    instance_id=DEFAULT_PROD_INSTANCE_ID,
    domain=DEFAULT_PROD_DOMAIN,
    ssm_path=DEFAULT_PROD_SSM_PATH,
    public_scheme=DEFAULT_PROD_SCHEME,
)

DEV_DEFAULTS = EnvironmentDefaults(
    env_name="dev",
    instance_id=DEFAULT_DEV_INSTANCE_ID,
    domain=DEFAULT_DEV_DOMAIN,
    ssm_path=DEFAULT_DEV_SSM_PATH,
    public_scheme=DEFAULT_DEV_SCHEME,
)


def get_environment_defaults(env_name: str) -> EnvironmentDefaults:
    if env_name == "prod":
        return PROD_DEFAULTS
    if env_name == "dev":
        return DEV_DEFAULTS
    raise ValueError(f"Unsupported environment: {env_name}")
