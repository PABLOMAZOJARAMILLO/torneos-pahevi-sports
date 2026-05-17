from urllib.parse import quote

from django.conf import settings
from storages.backends.s3 import S3Storage


class SupabaseMediaStorage(S3Storage):
    def url(self, name, parameters=None, expire=None, http_method=None):
        public_base = getattr(settings, "SUPABASE_PUBLIC_MEDIA_URL", "").rstrip("/")

        if public_base:
            clean_name = quote(str(name).lstrip("/"), safe="/")
            return f"{public_base}/{clean_name}"

        return super().url(name, parameters=parameters, expire=expire, http_method=http_method)
