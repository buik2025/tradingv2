"""
Event Calendar Service - Manages trading blackout events.

Provides:
- NSE/MCX holiday calendar
- RBI policy dates
- Major earnings dates
- Global macro events (Fed, US CPI, etc.)
- Event blackout checking for Sentinel
"""

from datetime import datetime, date, timedelta
from typing import List, Dict, Optional, Tuple
from enum import Enum
from pathlib import Path
import json
from loguru import logger

from ...database.models import EventRecord, get_session


class EventType(str, Enum):
    """Types of market events."""
    HOLIDAY = "HOLIDAY"           # Market closed
    RBI = "RBI"                   # RBI policy decision
    BUDGET = "BUDGET"             # Union Budget
    FED = "FED"                   # US Fed meeting
    EARNINGS = "EARNINGS"         # Major stock earnings
    EXPIRY = "EXPIRY"             # F&O expiry
    MACRO = "MACRO"               # Other macro events (CPI, GDP, etc.)
    OTHER = "OTHER"


class EventImpact(str, Enum):
    """Impact level of events."""
    HIGH = "HIGH"       # Full blackout - no new positions
    MEDIUM = "MEDIUM"   # Reduced sizing, hedged only
    LOW = "LOW"         # Caution, normal trading allowed


class EventCalendar:
    """
    Manages event calendar for trading blackouts.
    
    Usage:
        calendar = EventCalendar()
        calendar.load_events()
        
        # Check if trading is blocked
        is_blocked, event_name, days = calendar.check_blackout()
        if is_blocked:
            print(f"Trading blocked due to: {event_name}")
    """
    
    # Default blackout windows (days before/after event)
    BLACKOUT_WINDOWS = {
        EventType.HOLIDAY: (0, 0),      # Just the day
        EventType.RBI: (1, 1),          # T-1 to T+1
        EventType.BUDGET: (2, 1),       # T-2 to T+1
        EventType.FED: (1, 1),          # T-1 to T+1
        EventType.EARNINGS: (1, 0),     # T-1 to T
        EventType.EXPIRY: (0, 0),       # Just expiry day (caution)
        EventType.MACRO: (1, 0),        # T-1 to T
        EventType.OTHER: (1, 1),        # Default
    }
    
    def __init__(self, data_dir: Optional[Path] = None):
        """Initialize event calendar.
        
        Args:
            data_dir: Directory for event data files
        """
        if data_dir:
            self.data_dir = data_dir
        else:
            # Use absolute path relative to this file's location
            self.data_dir = Path(__file__).parent.parent.parent.parent / "data"
        self._events: List[Dict] = []
        self._loaded = False
    
    def load_events(self, force_reload: bool = False) -> int:
        """
        Load events from database and JSON file.
        
        Args:
            force_reload: Force reload even if already loaded
            
        Returns:
            Number of events loaded
        """
        if self._loaded and not force_reload:
            return len(self._events)
        
        self._events = []
        
        # Load from database
        db_count = self._load_from_database()
        
        # Load from JSON file (for static events like holidays)
        json_count = self._load_from_json()
        
        # Add hardcoded 2026 events if no data found
        if len(self._events) == 0:
            self._add_default_2026_events()
        
        self._loaded = True
        logger.info(f"Loaded {len(self._events)} events (DB: {db_count}, JSON: {json_count})")
        
        return len(self._events)
    
    def _load_from_database(self) -> int:
        """Load events from database."""
        count = 0
        try:
            session = get_session()
            records = session.query(EventRecord).filter(
                EventRecord.is_active == True,
                EventRecord.event_date >= date.today() - timedelta(days=7)
            ).all()
            
            for record in records:
                self._events.append({
                    "id": record.id,
                    "name": record.event_name,
                    "type": record.event_type or EventType.OTHER.value,
                    "date": record.event_date,
                    "blackout_start": record.blackout_start,
                    "blackout_end": record.blackout_end,
                    "impact": record.impact or EventImpact.HIGH.value,
                    "description": record.description,
                    "source": "database"
                })
                count += 1
            
            session.close()
        except Exception as e:
            logger.warning(f"Failed to load events from database: {e}")
        
        return count
    
    def _load_from_json(self) -> int:
        """Load events from JSON file."""
        count = 0
        json_path = self.data_dir / "events_calendar.json"
        
        if not json_path.exists():
            logger.debug(f"No events JSON file at {json_path}")
            return 0
        
        try:
            with open(json_path, "r") as f:
                data = json.load(f)
            
            for event in data.get("events", []):
                event_date = datetime.strptime(event["date"], "%Y-%m-%d").date()
                
                # Skip past events (more than 7 days ago)
                if event_date < date.today() - timedelta(days=7):
                    continue
                
                self._events.append({
                    "name": event["name"],
                    "type": event.get("type", EventType.OTHER.value),
                    "date": event_date,
                    "blackout_start": self._parse_date(event.get("blackout_start")),
                    "blackout_end": self._parse_date(event.get("blackout_end")),
                    "impact": event.get("impact", EventImpact.HIGH.value),
                    "description": event.get("description"),
                    "source": "json"
                })
                count += 1
                
        except Exception as e:
            logger.warning(f"Failed to load events from JSON: {e}")
        
        return count
    
    def _parse_date(self, date_str: Optional[str]) -> Optional[date]:
        """Parse date string to date object."""
        if not date_str:
            return None
        try:
            return datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            return None
    
    def _add_default_2026_events(self) -> None:
        """Add default 2026 events for Indian markets."""
        logger.info("Adding default 2026 events")
        
        # NSE Holidays 2026 (approximate - should be updated from NSE)
        holidays_2026 = [
            ("2026-01-26", "Republic Day"),
            ("2026-03-10", "Maha Shivaratri"),
            ("2026-03-17", "Holi"),
            ("2026-04-02", "Ram Navami"),
            ("2026-04-06", "Mahavir Jayanti"),
            ("2026-04-10", "Good Friday"),
            ("2026-04-14", "Dr. Ambedkar Jayanti"),
            ("2026-05-01", "Maharashtra Day"),
            ("2026-05-25", "Buddha Purnima"),
            ("2026-07-07", "Muharram"),
            ("2026-08-15", "Independence Day"),
            ("2026-08-26", "Janmashtami"),
            ("2026-10-02", "Gandhi Jayanti"),
            ("2026-10-20", "Dussehra"),
            ("2026-10-21", "Dussehra Holiday"),
            ("2026-11-09", "Diwali (Laxmi Puja)"),
            ("2026-11-10", "Diwali Balipratipada"),
            ("2026-11-30", "Guru Nanak Jayanti"),
            ("2026-12-25", "Christmas"),
        ]
        
        for date_str, name in holidays_2026:
            self._events.append({
                "name": name,
                "type": EventType.HOLIDAY.value,
                "date": datetime.strptime(date_str, "%Y-%m-%d").date(),
                "impact": EventImpact.HIGH.value,
                "source": "default"
            })
        
        # RBI Policy Dates 2026 (bi-monthly)
        rbi_dates_2026 = [
            ("2026-02-06", "RBI MPC February 2026"),
            ("2026-04-08", "RBI MPC April 2026"),
            ("2026-06-05", "RBI MPC June 2026"),
            ("2026-08-07", "RBI MPC August 2026"),
            ("2026-10-02", "RBI MPC October 2026"),
            ("2026-12-04", "RBI MPC December 2026"),
        ]
        
        for date_str, name in rbi_dates_2026:
            event_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            self._events.append({
                "name": name,
                "type": EventType.RBI.value,
                "date": event_date,
                "blackout_start": event_date - timedelta(days=1),
                "blackout_end": event_date + timedelta(days=1),
                "impact": EventImpact.HIGH.value,
                "source": "default"
            })
        
        # US Fed FOMC Dates 2026 (approximate)
        fed_dates_2026 = [
            ("2026-01-28", "FOMC January 2026"),
            ("2026-03-18", "FOMC March 2026"),
            ("2026-05-06", "FOMC May 2026"),
            ("2026-06-17", "FOMC June 2026"),
            ("2026-07-29", "FOMC July 2026"),
            ("2026-09-16", "FOMC September 2026"),
            ("2026-11-04", "FOMC November 2026"),
            ("2026-12-16", "FOMC December 2026"),
        ]
        
        for date_str, name in fed_dates_2026:
            event_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            self._events.append({
                "name": name,
                "type": EventType.FED.value,
                "date": event_date,
                "blackout_start": event_date - timedelta(days=1),
                "blackout_end": event_date + timedelta(days=1),
                "impact": EventImpact.MEDIUM.value,
                "source": "default"
            })
        
        # Union Budget 2026
        self._events.append({
            "name": "Union Budget 2026",
            "type": EventType.BUDGET.value,
            "date": date(2026, 2, 1),
            "blackout_start": date(2026, 1, 30),
            "blackout_end": date(2026, 2, 2),
            "impact": EventImpact.HIGH.value,
            "source": "default"
        })
    
    def check_blackout(
        self,
        check_date: Optional[date] = None,
        blackout_days: int = 2
    ) -> Tuple[bool, Optional[str], Optional[int]]:
        """
        Check if trading is blocked due to an event.
        
        Args:
            check_date: Date to check (default: today)
            blackout_days: Default blackout window if not specified
            
        Returns:
            Tuple of (is_blocked, event_name, days_until_event)
        """
        if not self._loaded:
            self.load_events()
        
        check_date = check_date or date.today()
        
        for event in self._events:
            event_date = event["date"]
            if isinstance(event_date, str):
                event_date = datetime.strptime(event_date, "%Y-%m-%d").date()
            
            # Calculate blackout window
            blackout_start = event.get("blackout_start")
            blackout_end = event.get("blackout_end")
            
            if not blackout_start:
                event_type = EventType(event.get("type", EventType.OTHER.value))
                before, after = self.BLACKOUT_WINDOWS.get(event_type, (1, 1))
                blackout_start = event_date - timedelta(days=before)
                blackout_end = event_date + timedelta(days=after)
            
            # Check if check_date falls within blackout
            if blackout_start <= check_date <= blackout_end:
                days_until = (event_date - check_date).days
                return True, event["name"], days_until
        
        return False, None, None
    
    def get_upcoming_events(
        self,
        days_ahead: int = 14,
        event_types: Optional[List[EventType]] = None
    ) -> List[Dict]:
        """
        Get upcoming events within specified days.
        
        Args:
            days_ahead: Number of days to look ahead
            event_types: Filter by event types (None = all)
            
        Returns:
            List of upcoming events
        """
        if not self._loaded:
            self.load_events()
        
        today = date.today()
        cutoff = today + timedelta(days=days_ahead)
        
        upcoming = []
        for event in self._events:
            event_date = event["date"]
            if isinstance(event_date, str):
                event_date = datetime.strptime(event_date, "%Y-%m-%d").date()
            
            if today <= event_date <= cutoff:
                if event_types is None or EventType(event.get("type")) in event_types:
                    upcoming.append({
                        **event,
                        "days_until": (event_date - today).days
                    })
        
        # Sort by date
        upcoming.sort(key=lambda x: x["date"])
        return upcoming
    
    def add_event(
        self,
        name: str,
        event_date: date,
        event_type: EventType = EventType.OTHER,
        impact: EventImpact = EventImpact.HIGH,
        description: Optional[str] = None,
        persist: bool = True
    ) -> None:
        """
        Add an event to the calendar.
        
        Args:
            name: Event name
            event_date: Date of event
            event_type: Type of event
            impact: Impact level
            description: Optional description
            persist: Save to database
        """
        # Calculate blackout window
        before, after = self.BLACKOUT_WINDOWS.get(event_type, (1, 1))
        
        event = {
            "name": name,
            "type": event_type.value,
            "date": event_date,
            "blackout_start": event_date - timedelta(days=before),
            "blackout_end": event_date + timedelta(days=after),
            "impact": impact.value,
            "description": description,
            "source": "manual"
        }
        
        self._events.append(event)
        
        if persist:
            self._save_to_database(event)
        
        logger.info(f"Added event: {name} on {event_date}")
    
    def _save_to_database(self, event: Dict) -> None:
        """Save event to database."""
        try:
            session = get_session()
            record = EventRecord(
                event_name=event["name"],
                event_type=event["type"],
                event_date=event["date"],
                blackout_start=event.get("blackout_start"),
                blackout_end=event.get("blackout_end"),
                impact=event.get("impact"),
                description=event.get("description"),
                is_active=True
            )
            session.add(record)
            session.commit()
            session.close()
        except Exception as e:
            logger.error(f"Failed to save event to database: {e}")
    
    def is_trading_day(self, check_date: Optional[date] = None) -> bool:
        """
        Check if given date is a trading day (not a holiday).
        
        Args:
            check_date: Date to check (default: today)
            
        Returns:
            True if trading day, False if holiday
        """
        if not self._loaded:
            self.load_events()
        
        check_date = check_date or date.today()
        
        # Check weekends
        if check_date.weekday() >= 5:  # Saturday = 5, Sunday = 6
            return False
        
        # Check holidays
        for event in self._events:
            if event.get("type") == EventType.HOLIDAY.value:
                event_date = event["date"]
                if isinstance(event_date, str):
                    event_date = datetime.strptime(event_date, "%Y-%m-%d").date()
                if event_date == check_date:
                    return False
        
        return True
    
    def get_next_trading_day(self, from_date: Optional[date] = None) -> date:
        """
        Get next trading day from given date.
        
        Args:
            from_date: Starting date (default: today)
            
        Returns:
            Next trading day
        """
        check_date = (from_date or date.today()) + timedelta(days=1)
        
        while not self.is_trading_day(check_date):
            check_date += timedelta(days=1)
            if check_date > date.today() + timedelta(days=30):
                break  # Safety limit
        
        return check_date


# Singleton instance
_calendar_instance: Optional[EventCalendar] = None


def get_event_calendar() -> EventCalendar:
    """Get singleton event calendar instance."""
    global _calendar_instance
    if _calendar_instance is None:
        _calendar_instance = EventCalendar()
        _calendar_instance.load_events()
    return _calendar_instance
