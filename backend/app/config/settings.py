"""Configuration settings loader for Trading System v2.0"""

from pydantic_settings import BaseSettings
from pydantic import Field
from typing import Optional
from pathlib import Path


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    # API Credentials
    kite_api_key: str = Field(..., description="KiteConnect API key")
    kite_api_secret: str = Field(..., description="KiteConnect API secret")
    kite_access_token: str = Field("", description="KiteConnect access token")
    
    # Telegram (optional)
    telegram_bot_token: Optional[str] = Field(None, description="Telegram bot token")
    telegram_chat_id: Optional[str] = Field(None, description="Telegram chat ID")
    
    # Trading Mode
    trading_mode: str = Field("paper", description="Trading mode: paper or live")
    
    # Instrument Tokens
    nifty_token: int = Field(256265, description="NIFTY 50 instrument token")
    banknifty_token: int = Field(260105, description="Bank NIFTY instrument token")
    india_vix_token: int = Field(264969, description="India VIX instrument token")
    
    # Regime Thresholds
    adx_range_bound: int = Field(12, description="ADX threshold for range-bound")
    adx_trend: int = Field(22, description="ADX threshold for trend")
    iv_low: int = Field(35, description="IV percentile low threshold")
    iv_high: int = Field(75, description="IV percentile high threshold")
    correlation_threshold: float = Field(0.4, description="Correlation threshold")
    
    # Risk Limits
    max_margin_pct: float = Field(0.40, description="Max margin utilization")
    max_loss_per_trade: float = Field(0.01, description="Max loss per trade")
    max_daily_loss: float = Field(0.03, description="Max daily loss")
    max_weekly_loss: float = Field(0.05, description="Max weekly loss")
    max_positions: int = Field(3, description="Max concurrent positions")
    
    # Greeks Limits
    max_delta: int = Field(30, description="Max portfolio delta")
    max_gamma: float = Field(0.3, description="Max portfolio gamma")
    max_vega: int = Field(400, description="Max portfolio vega")
    
    # Paths
    data_dir: Path = Field(Path("data"), description="Data directory")
    logs_dir: Path = Field(Path("logs"), description="Logs directory")
    state_dir: Path = Field(Path("state"), description="State directory")
    models_dir: Path = Field(Path("data/models"), description="ML models directory")
    
    # Database
    db_path: Path = Field(Path("data/trading.db"), description="SQLite database path")
    
    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore"
    }
    
    def ensure_directories(self) -> None:
        """Create required directories if they don't exist."""
        for dir_path in [self.data_dir, self.logs_dir, self.state_dir, self.models_dir]:
            dir_path.mkdir(parents=True, exist_ok=True)
