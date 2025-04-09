import logging
import secrets
from typing import List, Optional, Dict, Any, Set
from pathlib import Path

from pydantic import Field, SecretStr, AnyHttpUrl, EmailStr, field_validator, ValidationInfo, HttpUrl
from pydantic_settings import BaseSettings, SettingsConfigDict

# Определяем базовую директорию относительно этого файла
BASE_DIR = Path(__file__).resolve().parent.parent
SERVICE_COST=1
class Settings(BaseSettings):
    """ Основные настройки приложения, загружаемые из .env """
    # --- Telegram ---
    telegram_bot_token: SecretStr = Field(..., validation_alias='TELEGRAM_BOT_TOKEN')

    # --- Webhook ---
    webhook_domain: str = Field(..., validation_alias='WEBHOOK_DOMAIN')
    webhook_server_port: int = Field(8443, validation_alias='WEB_SERVER_PORT')
    webhook_server_listen_host: str = Field("0.0.0.0", validation_alias='WEB_SERVER_LISTEN_HOST')
    telegram_webhook_secret: SecretStr = Field(default_factory=lambda: secrets.token_urlsafe(32), validation_alias='TELEGRAM_WEBHOOK_SECRET')
    yookassa_webhook_path: str = Field("/webhook/yookassa", validation_alias='YOOKASSA_WEBHOOK_PATH')
    base_webhook_url: Optional[str] = None # Вычисляется ниже
    telegram_webhook_path: Optional[str] = None # Вычисляется ниже

    # --- OpenAI ---
    openai_api_key: SecretStr = Field(..., validation_alias='OPENAI_API_KEY')
    openai_model: str = Field("gpt-4o-mini-2024-07-18", validation_alias='OPENAI_MODEL')
    openai_timeout: int = Field(120, validation_alias='OPENAI_TIMEOUT')

    # --- YooKassa ---
    yookassa_shop_id: Optional[str] = Field(None, validation_alias='YOOKASSA_SHOP_ID')
    yookassa_secret_key: Optional[SecretStr] = Field(None, validation_alias='YOOKASSA_SECRET_KEY')

    # --- Администраторы ---
    admin_ids: List[int] = Field(default_factory=list, validation_alias='ADMIN_IDS')

    # --- База данных ---
    database_url: str = Field("sqlite+aiosqlite:///astro_bot.db", validation_alias='DATABASE_URL')
    sync_database_url: Optional[str] = None # Вычисляется ниже

    # --- Контакты и Ссылки ---
    refund_contact_email: EmailStr = Field("admin@example.com", validation_alias='REFUND_CONTACT_EMAIL')
    legal_notice_url_terms: HttpUrl = Field("https://example.com/terms", validation_alias='LEGAL_NOTICE_URL_TERMS')
    legal_notice_url_privacy: HttpUrl = Field("https://example.com/privacy", validation_alias='LEGAL_NOTICE_URL_PRIVACY')

    # --- Пути (относительно BASE_DIR) ---
    static_dir: Path = Field(BASE_DIR / "static")
    pdf_dir: Path = Field(BASE_DIR / "static" / "pdf")
    temp_dir: Path = Field(BASE_DIR / "temp")
    log_dir: Path = Field(BASE_DIR / "logs")
    prompt_dir: Path = Field(BASE_DIR / "prompts")

    # --- Настройки Услуг ---
    service_cost: int = Field(1, validation_alias='SERVICE_COST')
    first_service_free: bool = Field(True, validation_alias='FIRST_SERVICE_FREE')

    # --- Настройки Логирования ---
    log_level: str = Field("INFO", validation_alias='LOG_LEVEL')
    log_to_db: bool = Field(True, validation_alias='LOG_TO_DB')
    log_format: str = Field(
        '%(asctime)s - %(name)s - %(levelname)s - [%(funcName)s:%(lineno)d] - (%(user_id)s) - %(message)s',
        validation_alias='LOG_FORMAT'
    )
    log_file: Optional[Path] = None # Вычисляется ниже

    # --- Мониторинг ---
    sentry_dsn: Optional[str] = Field(None, validation_alias='SENTRY_DSN')

    # --- Безопасность (IP ЮKassa) ---
    yookassa_ips: Set[str] = Field(default={
        "185.71.76.0/27", "185.71.77.0/27", "77.75.153.0/25",
        "77.75.154.128/25", "2a02:5180:0:1509::/64", "2a02:5180:0:2655::/64",
        "2a02:5180:0:1536::/64", "2a02:5180:0:2669::/64",
    })

    # --- Throttling ---
    throttling_rate_limit: float = Field(0.7, validation_alias='THROTTLING_RATE_LIMIT')
    throttling_rate_period: float = Field(1.0, validation_alias='THROTTLING_RATE_PERIOD')

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / '.env',
        env_file_encoding='utf-8',
        extra='ignore',
        case_sensitive=False
    )

    # --- Валидаторы и вычисляемые поля ---
    @field_validator('admin_ids', mode='before')
    @classmethod
    def assemble_admin_ids(cls, v: Any) -> List[int]:
        if isinstance(v, str):
            try: return [int(admin_id.strip()) for admin_id in v.split(',') if admin_id.strip()]
            except ValueError: raise ValueError(f"Неверный формат ADMIN_IDS: '{v}'.")
        return v if isinstance(v, list) else []

    @field_validator('log_level', mode='before')
    @classmethod
    def assemble_log_level(cls, v: str) -> str:
        level = v.strip().upper()
        if level not in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]: raise ValueError(f"Неверный уровень логирования: {v}")
        return level

    @field_validator('yookassa_webhook_path', mode='before')
    @classmethod
    def assemble_yookassa_path(cls, v: str) -> str:
        path = v.strip()
        if not path.startswith('/'): raise ValueError(f"YOOKASSA_WEBHOOK_PATH должен начинаться с '/': {path}")
        return path

    def model_post_init(self, __context: Any) -> None:
        if self.webhook_domain:
            self.base_webhook_url = f"https://{self.webhook_domain}"
            self.telegram_webhook_path = f"/webhook/telegram/{self.telegram_webhook_secret.get_secret_value()}"
        self.sync_database_url = self.database_url.replace("sqlite+aiosqlite", "sqlite")
        self.log_file = self.log_dir / "bot.log"
        for path in [self.static_dir, self.pdf_dir, self.temp_dir, self.log_dir, self.prompt_dir]:
            try: path.mkdir(parents=True, exist_ok=True)
            except OSError as e: logging.error(f"Ошибка создания директории {path}: {e}")


try:
    settings = Settings()
    # Логируем после настройки logging в bot.py
except Exception as e:
     print(f"CRITICAL: Ошибка загрузки настроек: {e}")
     raise ValueError(f"Ошибка конфигурации: {e}")

# --- Константы для удобства ---
SERVICE_NATAL_CHART = "natal_chart"
SERVICE_FORECAST = "forecast"
SERVICE_COMPATIBILITY = "compatibility"
SERVICE_DREAM = "dream"
SERVICE_SIGNS = "signs"
SERVICE_PALMISTRY = "palmistry"

PAID_SERVICES = {
    SERVICE_NATAL_CHART: "Персональная натальная карта",
    SERVICE_FORECAST: "Персональный прогноз на год",
    SERVICE_COMPATIBILITY: "Проверка совместимости",
    SERVICE_DREAM: "Толкование сна",
    SERVICE_SIGNS: "Значение приметы",
    SERVICE_PALMISTRY: "Хиромантия по фото рук",
}

PAYMENT_OPTIONS = {
    "buy_1": {"price": 9900, "credits": 1, "description": "1 услуга (99 ₽)"},
    "buy_3": {"price": 27900, "credits": 3, "description": "3 услуги (93 ₽/шт)"},
    "buy_5": {"price": 44900, "credits": 5, "description": "5 услуг (90 ₽/шт)"},
    "buy_10": {"price": 84900, "credits": 10, "description": "10 услуг (85 ₽/шт)"},
    "buy_20": {"price": 149900, "credits": 20, "description": "20 услуг (75 ₽/шт)"},
}

# Дисклеймеры (можно вынести в отдельный файл или оставить здесь)
ACCEPT_TERMS_PROMPT = "Пожалуйста, ознакомьтесь с условиями и примите их для продолжения."
PALMISTRY_DISCLAIMER = "Помните, что анализ ладони с помощью ИИ носит общий и развлекательный характер и не является профессиональной хиромантией."
ASTROLOGY_DISCLAIMER = "Астрологические интерпретации, сгенерированные ИИ, носят информационно-развлекательный характер и не заменяют консультацию профессионального астролога."
GEOCODING_DISCLAIMER = "Координаты определяются автоматически по названию города. Для большей точности используйте ближайший крупный город или проверьте данные." # Вернули дисклеймер для Geopy
PAYMENT_THANK_YOU = "Спасибо за покупку! Ваши кредиты ({credits}) были успешно зачислены."
PAYMENT_ERROR = "Произошла ошибка во время обработки платежа. Пожалуйста, попробуйте позже или свяжитесь с поддержкой."
PAYMENT_PENDING = "Ваш платеж находится в обработке. Кредиты будут зачислены после подтверждения оплаты ЮKassa."

# Формируем текст LEGAL_NOTICE здесь, используя URL из settings
LEGAL_NOTICE = (
    f"Нажимая 'Принять', вы подтверждаете, что ознакомились и согласны с "
    f"<a href='{settings.legal_notice_url_terms}'>Пользовательским соглашением</a> и "
    f"<a href='{settings.legal_notice_url_privacy}'>Политикой конфиденциальности</a>. "
    "Вы также понимаете, что предоставляемые ботом услуги носят "
    "информационно-развлекательный характер."
)