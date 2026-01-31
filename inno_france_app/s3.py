from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import boto3

from .settings import AppSettings


@dataclass
class S3UploadResult:
    key: str
    url: Optional[str]


class S3Client:
    def __init__(self, settings: AppSettings) -> None:
        self.enabled = all(
            [
                settings.s3_endpoint,
                settings.s3_bucket,
                settings.s3_access_key,
                settings.s3_secret_key,
            ]
        )
        self.bucket = settings.s3_bucket
        self.prefix = settings.s3_prefix.strip("/") if settings.s3_prefix else ""
        self.endpoint = settings.s3_endpoint
        if not self.enabled:
            self.client = None
            return
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
        )

    def upload_file(self, local_path: str, key: str) -> Optional[S3UploadResult]:
        if not self.enabled or not self.client:
            return None
        final_key = f"{self.prefix}/{key}" if self.prefix else key
        self.client.upload_file(local_path, self.bucket, final_key)
        url = None
        if self.endpoint:
            endpoint = self.endpoint.rstrip("/")
            url = f"{endpoint}/{self.bucket}/{final_key}"
        return S3UploadResult(key=final_key, url=url)

