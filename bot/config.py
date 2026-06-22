from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    bot_token: str = ""
    database_url: str = ""
    admin_tg_ids: str = ""

    redis_url: str = "redis://redis:6379/0"

    # YandexGPT (Foundation Models) — translates voice transcripts RU→EN,
    # grounded in the weed_species dictionary so colloquial/ASR-garbled weed
    # names map to the correct Latin name. Empty = translation disabled.
    yc_api_key: str = ""
    yc_folder_id: str = ""
    yc_translate_model: str = "yandexgpt"  # 'yandexgpt' (pro) or 'yandexgpt-lite'

    # Telegram API base override. Empty = use api.telegram.org directly.
    # Set to a Cloudflare-Worker relay URL (e.g. https://xxx.workers.dev) to
    # route around Roskomnadzor's IP-blocking of Telegram from RU networks.
    # The relay must mirror Telegram's /bot<token>/<method> + /file/... paths.
    telegram_api_base: str = ""

    # CVAT Cloud — used by labeling/export.py to auto-create labeling tasks.
    cvat_host: str = "https://app.cvat.ai"
    cvat_api_token: str = ""  # generated under Settings → Personal access tokens
    cvat_project_name: str = "weeds-diseases-stress"

    # SMTP for email login codes (sender = noreply@flagleaf.ru via Yandex Mail
    # for Domain). Empty smtp_host = email login disabled (Telegram /weblogin still works).
    smtp_host: str = ""
    smtp_port: int = 465          # Yandex: 465 SSL
    smtp_user: str = ""           # full mailbox, e.g. noreply@flagleaf.ru
    smtp_password: str = ""       # app-password from Yandex 360
    smtp_from: str = ""           # defaults to smtp_user if empty

    # Web Push (VAPID). Public key is served to the browser; private key is secret
    # (Lockbox). Empty private key = push disabled.
    vapid_public_key: str = ""
    vapid_private_key: str = ""
    vapid_subject: str = "mailto:flagleaf@flagleaf.ru"

    # Collective photo goal shown in /stats + the app ("команда собрала N из M").
    team_photo_goal: int = 1000

    s3_endpoint: str = ""
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_bucket: str = "newgrain-data-prod"
    s3_region: str = "ru-central1"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    @property
    def admin_ids(self) -> set[int]:
        return {int(x) for x in self.admin_tg_ids.replace(" ", "").split(",") if x}


settings = Settings()
