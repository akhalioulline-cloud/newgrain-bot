from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    bot_token: str = ""
    database_url: str = ""
    admin_tg_ids: str = ""

    redis_url: str = "redis://redis:6379/0"

    # Local faster-whisper model size for voice-note transcription.
    # "small" = good Russian accuracy (~0.5 GB); "base" is lighter/faster.
    whisper_model: str = "small"

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
