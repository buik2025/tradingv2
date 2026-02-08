"""Base agent class for Trading System v2.0"""

from abc import ABC, abstractmethod
from typing import Any, Optional
from datetime import datetime
from loguru import logger

from ..core.kite_client import KiteClient
from ..config.settings import Settings


class BaseAgent(ABC):
    """
    Abstract base class for all trading agents.
    Provides common functionality and interface contract.
    """
    
    def __init__(
        self,
        kite: KiteClient,
        config: Settings,
        name: Optional[str] = None
    ):
        self.kite = kite
        self.config = config
        self.name = name or self.__class__.__name__
        self.logger = logger.bind(agent=self.name)
        self._last_run: Optional[datetime] = None
        self._run_count: int = 0
        self._error_count: int = 0
    
    @abstractmethod
    def process(self, *args, **kwargs) -> Any:
        """
        Main processing method. Must be implemented by subclasses.
        
        Returns:
            Agent-specific output (RegimePacket, TradeProposal, etc.)
        """
        pass
    
    def pre_process(self) -> bool:
        """
        Pre-processing hook. Called before process().
        Override to add validation or setup logic.
        
        Returns:
            True if processing should continue, False to skip
        """
        return True
    
    def post_process(self, result: Any) -> Any:
        """
        Post-processing hook. Called after process().
        Override to add logging, metrics, or transformation.
        
        Args:
            result: Output from process()
            
        Returns:
            Potentially modified result
        """
        return result
    
    def run(self, *args, **kwargs) -> Any:
        """
        Execute the agent with pre/post processing hooks.
        Handles errors and metrics.
        """
        self._run_count += 1
        self._last_run = datetime.now()
        
        try:
            if not self.pre_process():
                self.logger.debug("Pre-process returned False, skipping")
                return None
            
            result = self.process(*args, **kwargs)
            result = self.post_process(result)
            
            self.logger.debug(f"Run #{self._run_count} completed successfully")
            return result
            
        except Exception as e:
            self._error_count += 1
            self.logger.error(f"Error in run #{self._run_count}: {e}")
            raise
    
    def get_stats(self) -> dict:
        """Get agent statistics."""
        return {
            "name": self.name,
            "run_count": self._run_count,
            "error_count": self._error_count,
            "last_run": self._last_run.isoformat() if self._last_run else None,
            "error_rate": self._error_count / self._run_count if self._run_count > 0 else 0
        }
    
    def reset_stats(self) -> None:
        """Reset agent statistics."""
        self._run_count = 0
        self._error_count = 0
        self._last_run = None
