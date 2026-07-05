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
    # The agronomist assistant runs on the newest generation (5.1, via the `rc` tag —
    # `yandexgpt`/`yandexgpt/latest` still resolve to 5.0 / 09.02.2025). Kept separate
    # from yc_translate_model so parsing/translation stay on the stable build. Flip back
    # to "yandexgpt" here (or via env) if rc ever misbehaves.
    yc_chat_model: str = "yandexgpt/rc"
    # Model for the crop+target extraction fallback (runs only when the deterministic
    # lexicon misses — i.e. the HARD cases: diseases, pests, uncommon weeds, padalitsa).
    # Tested lite here and it mis-classified padalitsa рапса as злаков (should be двудольн),
    # while pro got it right — and those nuanced cases are exactly the ones that reach this
    # fallback. The lexicon already removes the double-call on common questions, so the rare
    # fallback stays on the capable (pro) model: correctness > ~0.5 s here.
    yc_extract_model: str = "yandexgpt"

    # Flagleaf proactive participation. "shadow" = evaluate unsummoned messages + LOG the would-be
    # reply, post NOTHING (data-gathering to decide if it should speak). "off" = don't evaluate.
    # "live" = actually post (NOT enabled until shadow data justifies it).
    flagleaf_proactive: str = "shadow"

    # EPPO Global Database API — neutral pest/disease/weed reference (RU/Latin names,
    # hosts, quarantine status). Token from data.eppo.int. NB: the legacy API was retired
    # (May 2026); the current one is base `https://api.eppo.int/gd/v2` with auth via the
    # HTTP header `X-Api-Key` (not a query param). name2codes resolves LATIN names only.
    eppo_api_token: str = ""

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
