import json
import logging
import os
from typing import Any, Dict, List, Optional, Mapping
from urllib.parse import urljoin

import keycloak
import requests
import rich
from pydantic import BaseModel, EmailStr, Extra

from _nebari.stages.kubernetes_ingress import CertificateEnum
from nebari import schema

logger = logging.getLogger(__name__)


class GroupRepresentation(BaseModel):
    id: Optional[str] = None
    name: Optional[str] = "Developer"
    path: Optional[str] = "/developer"
    subGroups: Optional[List["GroupRepresentation"]] = None


class UserConfigRepresentation(BaseModel):
    id: Optional[str] = None
    username: EmailStr
    enabled: bool
    emailVerified: Optional[bool]
    firstName: Optional[str]
    lastName: Optional[str]
    email: EmailStr
    groups: Optional[List[GroupRepresentation]] = [GroupRepresentation().path]
    attributes: Optional[Mapping[str, Any]] = None

    class Config:
        allow_population_by_field_name = True
        extra = Extra.allow


class CreateUserRepresentation(UserConfigRepresentation):
    credentials: List[Dict[str, Any]] = None

    class Config:
        extra = Extra.allow

    def dict(self, **kwargs):
        d = super().dict(**kwargs)
        # Filter out any keys that are not part of the model's fields
        return {k: v for k, v in d.items() if k in self.__fields_set__}


# TODO: Refactor this to enable caching of the authentication token


def do_keycloak(config: schema.Main, *args):
    # suppress insecure warnings
    import urllib3

    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    keycloak_admin = get_keycloak_admin_from_config(config)

    if args[0] == "adduser":
        if len(args) < 2:
            raise ValueError(
                "keycloak command 'adduser' requires `username [password]`"
            )

        username = args[1]
        password = args[2] if len(args) >= 3 else None
        create_user(keycloak_admin, username, password, domain=config.domain)
    elif args[0] == "listusers":
        list_users(keycloak_admin)
    elif args[0] == "listgroups":
        list_groups(keycloak_admin)
    else:
        raise ValueError(f"unknown keycloak command {args[0]}")


def create_group(
    keycloak_admin: keycloak.KeycloakAdmin,
    name: str,
    path: str = None,
    subGroups: List[GroupRepresentation] = None,
):
    payload = GroupRepresentation(name=name, path=path, subGroups=subGroups)
    group = keycloak_admin.create_group(payload.dict(), skip_exists=True)
    rich.print(f"Created group=[green]{name}[/green]")
    return group


def create_user(
    keycloak_admin: keycloak.KeycloakAdmin,
    username: str,
    password: str = None,
    groups=None,
    email=None,
    domain=None,
    enabled=True,
):
    payload = CreateUserRepresentation(
        username=username,
        groups=groups,
        email=email or f"{username}@{domain or 'example.com'}",
        enabled=enabled,
    )
    if password:
        payload.credentials = [
            {"type": "password", "value": password, "temporary": False}
        ]
    else:
        rich.print(
            f"Creating user=[green]{username}[/green] without password (none supplied)"
        )
    user = keycloak_admin.create_user(payload.dict())
    rich.print(f"Created user=[green]{username}[/green]")
    return user


def list_users(keycloak_admin: keycloak.KeycloakAdmin):
    num_users = keycloak_admin.users_count()
    print(f"{num_users} Keycloak Users")

    user_format = "{username:32} | {email:32} | {groups}"
    print(user_format.format(username="username", email="email", groups="groups"))
    print("-" * 120)

    for user in keycloak_admin.get_users():
        _user = UserConfigRepresentation(**user)
        _user.groups = [_["name"] for _ in keycloak_admin.get_user_groups(_user.id)]
        print(
            user_format.format(
                username=_user.username, email=_user.email, groups=_user.groups
            )
        )


def list_groups(keycloak_admin: keycloak.KeycloakAdmin):
    num_groups = keycloak_admin.groups_count().get("count")
    print(f"{num_groups} Keycloak Groups")

    group_format = "{name:32} | {path:32} | {subGroups}"
    print(group_format.format(name="name", path="path", subGroups="subGroups"))
    print("-" * 120)

    for group in keycloak_admin.get_groups():
        _group = GroupRepresentation(**group)
        print(
            group_format.format(
                name=_group.name, path=_group.path, subGroups=_group.subGroups
            )
        )


def get_keycloak_admin_from_config(config: schema.Main):
    keycloak_server_url = os.environ.get(
        "KEYCLOAK_SERVER_URL", f"https://{config.domain}/auth/"
    )

    keycloak_username = os.environ.get("KEYCLOAK_ADMIN_USERNAME", "root")
    keycloak_password = os.environ.get(
        "KEYCLOAK_ADMIN_PASSWORD", config.security.keycloak.initial_root_password
    )

    should_verify_tls = config.certificate.type != CertificateEnum.selfsigned

    try:
        keycloak_admin = keycloak.KeycloakAdmin(
            server_url=keycloak_server_url,
            username=keycloak_username,
            password=keycloak_password,
            realm_name=os.environ.get("KEYCLOAK_REALM", "nebari"),
            user_realm_name="master",
            auto_refresh_token=("get", "put", "post", "delete"),
            verify=should_verify_tls,
        )
    except (
        keycloak.exceptions.KeycloakConnectionError,
        keycloak.exceptions.KeycloakAuthenticationError,
    ) as e:
        raise ValueError(f"Failed to connect to Keycloak server: {e}")

    return keycloak_admin


def keycloak_rest_api_call(config: schema.Main = None, request: str = None):
    """Communicate directly with the Keycloak REST API by passing it a request"""
    keycloak_server_url = os.environ.get(
        "KEYCLOAK_SERVER_URL", f"https://{config.domain}/auth/"
    )

    keycloak_admin_username = os.environ.get("KEYCLOAK_ADMIN_USERNAME", "root")
    keycloak_admin_password = os.environ.get(
        "KEYCLOAK_ADMIN_PASSWORD",
        config.security.keycloak.initial_root_password,
    )

    try:
        # Get `token` to interact with Keycloak Admin
        url = urljoin(
            keycloak_server_url, "realms/master/protocol/openid-connect/token"
        )
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
        }
        data = {
            "username": keycloak_admin_username,
            "password": keycloak_admin_password,
            "grant_type": "password",
            "client_id": "admin-cli",
        }

        response = requests.post(
            url=url,
            headers=headers,
            data=data,
            verify=False,
        )

        if response.status_code == 200:
            token = json.loads(response.content.decode())["access_token"]
        else:
            raise ValueError(
                f"Unable to retrieve Keycloak API token. Status code: {response.status_code}"
            )

        # Send request to Keycloak REST API
        method, endpoint = request.split()
        url = urljoin(
            urljoin(keycloak_server_url, "admin/realms/"), endpoint.lstrip("/")
        )
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
        }

        response = requests.request(
            method=method, url=url, headers=headers, verify=False
        )

        if response.status_code == 200:
            content = json.loads(response.content.decode())
            return content
        else:
            raise ValueError(
                f"Unable to communicate with Keycloak API. Status code: {response.status_code}"
            )

    except requests.exceptions.RequestException as e:
        raise e


# TODO: Replace this for the python-keycloak library api calls


def export_keycloak_users(config: schema.Main, realm: str):
    request = f"GET /{realm}/users"

    users = keycloak_rest_api_call(config, request=request)

    return {
        "realm": realm,
        "users": users,
    }


def export_keycloak_users_and_groups(
    config: schema.Main, realm: str, group_membership: bool = False
):
    request = f"GET /{realm}/users"

    users = keycloak_rest_api_call(config, request=request)

    if group_membership:
        # Ask for confirmation before proceeding if the number of users is large
        if len(users) > 10:
            if not rich.prompt.Confirm.ask(
                f"Exporting group membership for {len(users)} users. Continue? (This operation may take a while) [y/N]"
            ):
                return
        for user in users:
            user_id = user["id"]
            request = f"GET /{realm}/users/{user_id}/groups"
            user_groups = keycloak_rest_api_call(config, request=request)
            user["groups"] = user_groups

    request = f"GET /{realm}/groups"

    groups = keycloak_rest_api_call(config, request=request)

    return {
        "realm": realm,
        "users": users,
        "groups": groups,
    }


def import_keycloak_user_and_groups(
    config: schema.Main,
    realm: str,
    users: List[Dict[str, Any]],
    groups: List[Dict[str, Any]],
):
    # for group in groups:
    #     request = f"POST /{realm}/groups"
    #     keycloak_rest_api_call(config, request=request)

    #     group_id = group["id"]
    #     request = f"PUT /{realm}/groups/{group_id}"
    #     keycloak_rest_api_call(config, request=request)

    #     for user in group["users"]:
    #         request = f"POST /{realm}/groups/{group_id}/users/{user['id']}"
    #         keycloak_rest_api_call(config, request=request)
    # for user in users:
    #     request = f"POST /{realm}/users"
    #     keycloak_rest_api_call(config, request=request)

    #     user_id = user["id"]
    #     request = f"PUT /{realm}/users/{user_id}"
    #     keycloak_rest_api_call(config, request=request)

    #     for group in user["groups"]:
    #         request = f"POST /{realm}/users/{user_id}/groups/{group['id']}"
    #         keycloak_rest_api_call(config, request=request)

    return True
