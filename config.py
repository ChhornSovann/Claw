# config.py
"""
Configuration module for Claw Bot
Centralizes all environment variables and settings
"""

import os
from dataclasses import dataclass


@dataclass
class Config:
    """
    Bot configuration with environment variables.
    All settings are loaded from environment with sensible defaults.
    """
    # Required
    BOT_TOKEN: str = os.getenv('TELEGRAM_BOT_TOKEN', '8394145104:AAH8UELqFVYT-TWCrxJwRGkmfi80vDkiuTc')
    
    # Webhook settings (for production deployment)
    WEBHOOK_URL: str = os.getenv('WEBHOOK_URL', '')  # e.g., https://yourapp.railway.app
    PORT: int = int(os.getenv('PORT', 8080))
    WEBHOOK_SECRET: str = os.getenv('WEBHOOK_SECRET', '')  # Optional: for webhook security
    
    # Database
    DATABASE_PATH: str = os.getenv('DATABASE_PATH', 'claw_bot.db')
    
    # API Keys (optional - features work without them)
    OPENWEATHER_API_KEY: str = os.getenv('OPENWEATHER_API_KEY', '849ed4230b8ae4e130129670b7229760')
    NEWS_API_KEY: str = os.getenv('NEWS_API_KEY', '1f748104cfc64f53a666a2f1c3354502')
    
    @property
    def is_webhook_mode(self) -> bool:
        """Check if webhook mode is configured"""
        return bool(self.WEBHOOK_URL)
    
    def validate(self) -> None:
        """Validate required configuration"""
        if not self.BOT_TOKEN:
            raise ValueError("TELEGRAM_BOT_TOKEN environment variable is required!")