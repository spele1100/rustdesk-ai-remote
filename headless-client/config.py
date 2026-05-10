"""Configuration for the headless RustDesk client."""

import os
import json

# Defaults
DEFAULT_SERVER_HOST = "localhost"
DEFAULT_SERVER_PORT = 21116
DEFAULT_RELAY_PORT = 21117
DEFAULT_API_PORT = 8080
DEFAULT_PREFERRED_CODEC = "VP9"


class Config:
    def __init__(self, **kwargs):
        self.server_host = kwargs.get("server_host", os.getenv("RUSTDESK_SERVER_HOST", DEFAULT_SERVER_HOST))
        self.server_port = int(kwargs.get("server_port", os.getenv("RUSTDESK_SERVER_PORT", DEFAULT_SERVER_PORT)))
        self.relay_port = int(kwargs.get("relay_port", os.getenv("RUSTDESK_RELAY_PORT", DEFAULT_RELAY_PORT)))
        self.target_id = kwargs.get("target_id", os.getenv("RUSTDESK_TARGET_ID", ""))
        self.password = kwargs.get("password", os.getenv("RUSTDESK_PASSWORD", ""))
        self.preferred_codec = kwargs.get("preferred_codec", os.getenv("RUSTDESK_CODEC", DEFAULT_PREFERRED_CODEC))
        self.api_port = int(kwargs.get("api_port", os.getenv("RUSTDESK_API_PORT", DEFAULT_API_PORT)))
        self.api_host = kwargs.get("api_host", os.getenv("RUSTDESK_API_HOST", "0.0.0.0"))
        self.my_name = kwargs.get("my_name", "headless-client")
        self.version = "1.3.6"

    @classmethod
    def from_file(cls, path):
        with open(path) as f:
            data = json.load(f)
        return cls(**data)

    def to_dict(self):
        return {
            "server_host": self.server_host,
            "server_port": self.server_port,
            "relay_port": self.relay_port,
            "target_id": self.target_id,
            "preferred_codec": self.preferred_codec,
            "api_port": self.api_port,
            "api_host": self.api_host,
            "my_name": self.my_name,
            "version": self.version,
        }
